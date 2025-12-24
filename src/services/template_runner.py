"""
模板执行与指标计算（Baseline / Experimental）

尽量复用现有码流分析逻辑，允许破坏式实现。
"""
import asyncio
import json
import platform
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil
import numpy as np
import scipy.interpolate

from src.models import CommandLog, CommandStatus
from src.models_template import EncoderType, EncodingTemplate, TemplateSideConfig
from src.services import job_storage
from src.services.bitstream_analysis import build_bitstream_report
from src.services.ffmpeg import ffmpeg_service


def _now():
    return datetime.now().astimezone()


@dataclass
class SourceInfo:
    path: Path
    is_yuv: bool
    width: int
    height: int
    fps: float
    pix_fmt: str = "yuv420p"


def _list_sources(source_dir: Path) -> List[Path]:
    return sorted([p for p in source_dir.iterdir() if p.is_file()])


def _parse_yuv_name(path: Path) -> Tuple[int, int, float]:
    stem = path.stem
    import re

    m = re.search(r"_([0-9]+)x([0-9]+)_([0-9]+(?:\.[0-9]+)?)$", stem)
    if not m:
        raise ValueError(f"YUV 文件名不符合格式: {path.name}")
    return int(m.group(1)), int(m.group(2)), float(m.group(3))


async def _probe_media(path: Path) -> Tuple[int, int, float]:
    info = await ffmpeg_service.get_video_info(path)
    w = info.get("width")
    h = info.get("height")
    fps = info.get("fps")
    if not (w and h and fps):
        raise ValueError(f"无法解析分辨率/FPS: {path}")
    return int(w), int(h), float(fps)


async def _collect_sources(source_dir: str) -> List[SourceInfo]:
    base = Path(source_dir)
    if not base.is_dir():
        raise ValueError(f"源目录不存在: {source_dir}")
    files = _list_sources(base)
    if not files:
        raise ValueError(f"源目录为空: {source_dir}")

    results: List[SourceInfo] = []
    for p in files:
        if p.suffix.lower() == ".yuv":
            w, h, fps = _parse_yuv_name(p)
            results.append(SourceInfo(path=p, is_yuv=True, width=w, height=h, fps=fps))
        else:
            w, h, fps = await _probe_media(p)
            results.append(SourceInfo(path=p, is_yuv=False, width=w, height=h, fps=fps))
    return results


def _encoder_extension(enc: EncoderType) -> str:
    if enc == EncoderType.X264:
        return ".h264"
    if enc == EncoderType.X265:
        return ".h265"
    if enc == EncoderType.VVENC:
        return ".h266"
    return ".h264"


def _is_container_file(path: Path) -> bool:
    return path.suffix.lower() in {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".flv",
        ".ts",
        ".webm",
        ".mpg",
        ".mpeg",
        ".m4v",
    }


def _build_output_stem(src: Path, rate_control: str, val: float) -> str:
    rc = (rate_control or "rc").lower()
    val_str = str(val).rstrip("0").rstrip(".") if isinstance(val, float) else str(val)
    return f"{src.stem}_{rc}_{val_str}"


def _output_extension(enc: EncoderType, src: SourceInfo, is_container: bool) -> str:
    if enc == EncoderType.FFMPEG:
        if is_container:
            return src.path.suffix or ".mp4"
        return _encoder_extension(enc)
    return _encoder_extension(enc)


def _strip_rc_tokens(enc: EncoderType, params: str) -> List[str]:
    tokens = shlex.split(params) if params else []
    cleaned: List[str] = []
    skip_next = False
    ffmpeg_flags = {"-crf", "-b:v"}
    encoder_flags = {"--crf", "--bitrate"}
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if enc == EncoderType.FFMPEG and tok in ffmpeg_flags:
            skip_next = True
            continue
        if enc != EncoderType.FFMPEG and tok in encoder_flags:
            skip_next = True
            continue
        cleaned.append(tok)
    return cleaned


def _start_command(job, command_type: str, command: List[str], source_file: Optional[str]) -> Optional[CommandLog]:
    if not job:
        return None
    log = CommandLog(
        command_id=f"{len(job.metadata.command_logs)+1}",
        command_type=command_type,
        command=" ".join(command),
        status=CommandStatus.RUNNING,
        source_file=str(source_file) if source_file else None,
        started_at=_now(),
    )
    job.metadata.command_logs.append(log)
    try:
        job_storage.update_job(job)
    except Exception:
        pass
    return log


def _finish_command(job, log: Optional[CommandLog], status: CommandStatus, error: Optional[str] = None) -> None:
    if not job or not log:
        return
    log.status = status
    log.completed_at = _now()
    if error:
        log.error_message = error
    try:
        job_storage.update_job(job)
    except Exception:
        pass


def _fingerprint(side: TemplateSideConfig) -> str:
    payload = {
        "skip_encode": side.skip_encode,
        "source_dir": side.source_dir,
        "encoder_type": side.encoder_type,
        "encoder_params": side.encoder_params,
        "rate_control": side.rate_control,
        "bitrate_points": side.bitrate_points,
        "bitstream_dir": side.bitstream_dir,
    }
    return json.dumps(payload, sort_keys=True)


def _build_encode_cmd(
    enc: EncoderType,
    params: str,
    rc: str,
    val: float,
    src: SourceInfo,
    output: Path,
) -> List[str]:
    val_str = str(val)
    if enc == EncoderType.FFMPEG:
        cmd = [ffmpeg_service.ffmpeg_path, "-y"]
        if src.is_yuv:
            cmd += [
                "-f",
                "rawvideo",
                "-pix_fmt",
                src.pix_fmt,
                "-s",
                f"{src.width}x{src.height}",
                "-r",
                str(src.fps),
            ]
        cmd += ["-i", str(src.path)]
        cmd += _strip_rc_tokens(enc, params)
        if rc.lower() == "crf":
            cmd += ["-crf", val_str]
        else:
            cmd += ["-b:v", f"{val_str}k"]
        if src.is_yuv or src.path.suffix.lower() in {".h264", ".264"}:
            cmd += ["-c:v", "libx264"]
        elif src.path.suffix.lower() in {".h265", ".265", ".hevc"}:
            cmd += ["-c:v", "libx265"]
        cmd += [str(output)]
        return cmd

    base = [enc.value]
    if src.is_yuv:
        if enc in {EncoderType.X264, EncoderType.X265}:
            base += ["--input-res", f"{src.width}x{src.height}", "--fps", str(src.fps)]
        elif enc == EncoderType.VVENC:
            base += ["--size", f"{src.width}x{src.height}", "--framerate", str(src.fps)]
    base += _strip_rc_tokens(enc, params)
    if rc.lower() == "crf":
        base += ["--crf", val_str]
    else:
        base += ["--bitrate", val_str]
    base += ["-o", str(output), str(src.path)]
    return base


def _bd_metrics(rate1: List[float], metric1: List[float], rate2: List[float], metric2: List[float], piecewise: int = 0) -> Optional[float]:
    if len(rate1) < 4 or len(rate2) < 4:
        return None
    lR1 = np.log(rate1)
    lR2 = np.log(rate2)
    m1 = np.array(metric1)
    m2 = np.array(metric2)
    try:
        p1 = np.polyfit(lR1, m1, 3)
        p2 = np.polyfit(lR2, m2, 3)
    except Exception:
        return None
    min_int = max(min(lR1), min(lR2))
    max_int = min(max(lR1), max(lR2))
    if max_int <= min_int:
        return None
    if piecewise == 0:
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)
        int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
        int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
    else:
        lin = np.linspace(min_int, max_int, num=100, retstep=True)
        interval = lin[1]
        samples = lin[0]
        v1 = scipy.interpolate.pchip_interpolate(np.sort(lR1), m1[np.argsort(lR1)], samples)
        v2 = scipy.interpolate.pchip_interpolate(np.sort(lR2), m2[np.argsort(lR2)], samples)
        int1 = np.trapz(v1, dx=interval)
        int2 = np.trapz(v2, dx=interval)
    avg_diff = (int2 - int1) / (max_int - min_int)
    return avg_diff


def _bd_rate(rate1: List[float], metric1: List[float], rate2: List[float], metric2: List[float], piecewise: int = 0) -> Optional[float]:
    if len(rate1) < 4 or len(rate2) < 4:
        return None
    lR1 = np.log(rate1)
    lR2 = np.log(rate2)
    try:
        p1 = np.polyfit(metric1, lR1, 3)
        p2 = np.polyfit(metric2, lR2, 3)
    except Exception:
        return None
    min_int = max(min(metric1), min(metric2))
    max_int = min(max(metric1), max(metric2))
    if max_int <= min_int:
        return None
    if piecewise == 0:
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)
        int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
        int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
    else:
        lin = np.linspace(min_int, max_int, num=100, retstep=True)
        interval = lin[1]
        samples = lin[0]
        v1 = scipy.interpolate.pchip_interpolate(np.sort(metric1), lR1[np.argsort(metric1)], samples)
        v2 = scipy.interpolate.pchip_interpolate(np.sort(metric2), lR2[np.argsort(metric2)], samples)
        int1 = np.trapz(v1, dx=interval)
        int2 = np.trapz(v2, dx=interval)
    avg_exp_diff = (int2 - int1) / (max_int - min_int)
    return (np.exp(avg_exp_diff) - 1) * 100


def _env_info() -> Dict[str, str]:
    info = {}
    try:
        info["os"] = platform.platform()
        cpu = platform.processor() or platform.uname().processor
        info["cpu"] = cpu or ""
        info["phys_cores"] = str(psutil.cpu_count(logical=False) or "")
        info["log_cores"] = str(psutil.cpu_count(logical=True) or "")
        info["numa_nodes"] = ""
        info["cpu_percent_start"] = str(psutil.cpu_percent(interval=0.1))
        vm = psutil.virtual_memory()
        info["mem_total"] = str(vm.total)
        info["mem_available"] = str(vm.available)
    except Exception:
        pass
    return info


async def _encode_side(
    side: TemplateSideConfig,
    sources: List[SourceInfo],
    recompute: bool,
    job=None,
) -> Dict[str, List[Path]]:
    outputs: Dict[str, List[Path]] = {}
    side_dir = Path(side.bitstream_dir)
    side_dir.mkdir(parents=True, exist_ok=True)

    for src in sources:
        file_outputs: List[Path] = []
        for val in side.bitrate_points or []:
            if side.skip_encode:
                stem = _build_output_stem(src.path, side.rate_control.value if side.rate_control else "rc", val)
                matches = list(side_dir.glob(f"{stem}.*"))
                if matches:
                    file_outputs.append(matches[0])
                    continue
                raise FileNotFoundError(f"缺少码流: {stem}")
            stem = _build_output_stem(src.path, side.rate_control.value if side.rate_control else "rc", val)
            ext = _output_extension(side.encoder_type, src, is_container=not src.is_yuv and _is_container_file(src.path))
            out_path = side_dir / f"{stem}{ext}"
            if not recompute and out_path.exists():
                file_outputs.append(out_path)
                continue

            cmd = _build_encode_cmd(side.encoder_type, side.encoder_params or "", side.rate_control.value, val, src, out_path)
            log = _start_command(job, "encode", cmd, src.path)
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                _finish_command(job, log, CommandStatus.FAILED, error=stderr.decode(errors="ignore"))
                raise RuntimeError(f"编码失败 {out_path.name}: {stderr.decode(errors='ignore')}")
            _finish_command(job, log, CommandStatus.COMPLETED)
            file_outputs.append(out_path)
        outputs[src.path.stem] = file_outputs
    return outputs


def _extract_bitrate_point(path: Path) -> Optional[float]:
    stem = path.stem
    parts = stem.split("_")
    if len(parts) < 3:
        return None
    try:
        return float(parts[-1])
    except Exception:
        return None


async def run_template(
    template: EncodingTemplate,
    job=None,
) -> Dict[str, Any]:
    def _add_cmd(cmd_type: str, command: str, source_file: Optional[str] = None) -> Optional[str]:
        if not job:
            return None
        log = CommandLog(
            command_id=f"{len(job.metadata.command_logs)+1}",
            command_type=cmd_type,
            command=command,
            status=CommandStatus.PENDING,
            source_file=source_file,
        )
        job.metadata.command_logs.append(log)
        try:
            job_storage.update_job(job)
        except Exception:
            pass
        return log.command_id

    def _update_cmd(cmd_id: str, status: str, error: Optional[str] = None) -> None:
        if not job or not cmd_id:
            return
        for log in job.metadata.command_logs:
            if log.command_id == cmd_id:
                log.status = CommandStatus(status)
                now = _now()
                if status == "running":
                    log.started_at = now
                elif status in {"completed", "failed"}:
                    log.completed_at = now
                if error:
                    log.error_message = error
                break
        try:
            job_storage.update_job(job)
        except Exception:
            pass
    # 校验码控/点位一致性
    if template.metadata.baseline.rate_control != template.metadata.experimental.rate_control:
        raise ValueError("Baseline 与 Experimental 的码控方式不一致")
    if template.metadata.baseline.encoder_type and template.metadata.experimental.encoder_type:
        if template.metadata.baseline.encoder_type != template.metadata.experimental.encoder_type:
            raise ValueError("Baseline 与 Experimental 的编码器类型不一致")
    if sorted(template.metadata.baseline.bitrate_points or []) != sorted(template.metadata.experimental.bitrate_points or []):
        raise ValueError("Baseline 与 Experimental 的码率点位不一致")
    # 收集源并按 stem 对齐
    baseline_sources = await _collect_sources(template.metadata.baseline.source_dir)
    exp_sources = await _collect_sources(template.metadata.experimental.source_dir)
    base_map = {p.path.stem: p for p in baseline_sources}
    exp_map = {p.path.stem: p for p in exp_sources}
    if set(base_map.keys()) != set(exp_map.keys()):
        missing_a = set(base_map.keys()) - set(exp_map.keys())
        missing_b = set(exp_map.keys()) - set(base_map.keys())
        raise ValueError(f"源文件不匹配: baseline 多 {missing_a}，experimental 多 {missing_b}")
    ordered_sources = [base_map[k] for k in sorted(base_map.keys())]

    # Baseline 编码/校验
    def _has_files(p: Path) -> bool:
        return any(p.glob("*")) if p.exists() else False

    baseline_needed = (not template.metadata.baseline_computed) or (not _has_files(Path(template.metadata.baseline.bitstream_dir)))
    baseline_outputs = await _encode_side(
        template.metadata.baseline,
        ordered_sources,
        recompute=baseline_needed,
        job=job,
    )
    template.metadata.baseline_computed = True
    template.metadata.baseline_fingerprint = _fingerprint(template.metadata.baseline)

    # Experimental 编码/校验
    exp_outputs = await _encode_side(
        template.metadata.experimental,
        [exp_map[s.path.stem] for s in ordered_sources],
        recompute=True,
        job=job,
    )

    # 计算指标
    analysis_root = Path(job.job_dir) / "analysis" if job else Path(template.template_dir) / "analysis"
    analysis_root.mkdir(parents=True, exist_ok=True)

    report_entries = []
    bd_metrics = []

    for src in ordered_sources:
        key = src.path.stem
        baseline_paths = baseline_outputs.get(key, [])
        exp_paths = exp_outputs.get(key, [])

        if not baseline_paths or not exp_paths:
            raise ValueError(f"缺少码流: {src.path.name}")

        analysis_dir = analysis_root / src.path.stem
        analysis_dir.mkdir(parents=True, exist_ok=True)

        base_report, base_summary = await build_bitstream_report(
            reference_path=src.path,
            encoded_paths=baseline_paths,
            analysis_dir=analysis_dir / "baseline",
            raw_width=src.width if src.is_yuv else None,
            raw_height=src.height if src.is_yuv else None,
            raw_fps=src.fps if src.is_yuv else None,
            raw_pix_fmt=src.pix_fmt,
            add_command_callback=_add_cmd,
            update_status_callback=_update_cmd,
        )
        exp_report, exp_summary = await build_bitstream_report(
            reference_path=src.path,
            encoded_paths=exp_paths,
            analysis_dir=analysis_dir / "experimental",
            raw_width=src.width if src.is_yuv else None,
            raw_height=src.height if src.is_yuv else None,
            raw_fps=src.fps if src.is_yuv else None,
            raw_pix_fmt=src.pix_fmt,
            add_command_callback=_add_cmd,
            update_status_callback=_update_cmd,
        )

        # 生成 BD 曲线
        def _collect(series, key):
            pts = []
            for item in series:
                bitrate = item.get("avg_bitrate_bps")
                metric = ((item.get("metrics") or {}).get(key) or {}).get("summary") or {}
                val = metric.get(key.replace("vmaf_neg", "vmaf_neg_mean", 1)) or metric.get(f"{key}_avg") or metric.get("vmaf_neg_mean")
                if isinstance(val, (int, float)) and isinstance(bitrate, (int, float)) and bitrate > 0:
                    pts.append((float(val), float(bitrate)))
            return pts

        # encoded summaries are in report["encoded"]
        base_enc = base_report.get("encoded") or []
        exp_enc = exp_report.get("encoded") or []

        def _pair_curves(key):
            pts_a = _collect(base_enc, key)
            pts_b = _collect(exp_enc, key)
            if len(pts_a) < 4 or len(pts_b) < 4:
                return None
            m1, r1 = zip(*sorted(pts_a, key=lambda x: x[0]))
            m2, r2 = zip(*sorted(pts_b, key=lambda x: x[0]))
            return _bd_rate(list(r1), list(m1), list(r2), list(m2))

        def _pair_metrics(key):
            pts_a = []
            pts_b = []
            for series, target in ((base_enc, pts_a), (exp_enc, pts_b)):
                for item in series:
                    bitrate = item.get("avg_bitrate_bps")
                    metric = ((item.get("metrics") or {}).get(key) or {}).get("summary") or {}
                    val = metric.get(key.replace("vmaf_neg", "vmaf_neg_mean", 1)) or metric.get(f"{key}_avg") or metric.get("vmaf_neg_mean")
                    if isinstance(val, (int, float)) and isinstance(bitrate, (int, float)) and bitrate > 0:
                        target.append((float(bitrate), float(val)))
            if len(pts_a) < 4 or len(pts_b) < 4:
                return None
            r1, m1 = zip(*sorted(pts_a, key=lambda x: x[0]))
            r2, m2 = zip(*sorted(pts_b, key=lambda x: x[0]))
            return _bd_metrics(list(r1), list(m1), list(r2), list(m2))

        bd_metrics.append(
            {
                "source": src.path.name,
                "bd_rate_psnr": _pair_curves("psnr"),
                "bd_rate_ssim": _pair_curves("ssim"),
                "bd_rate_vmaf": _pair_curves("vmaf"),
                "bd_rate_vmaf_neg": _pair_curves("vmaf_neg"),
                "bd_psnr": _pair_metrics("psnr"),
                "bd_ssim": _pair_metrics("ssim"),
                "bd_vmaf": _pair_metrics("vmaf"),
                "bd_vmaf_neg": _pair_metrics("vmaf_neg"),
            }
        )

        report_entries.append(
            {
                "source": src.path.name,
                "baseline": base_summary,
                "experimental": exp_summary,
            }
        )

    env = _env_info()
    result: Dict[str, Any] = {
        "kind": "template_metrics",
        "template_id": template.template_id,
        "template_name": template.metadata.name,
        "rate_control": template.metadata.baseline.rate_control.value if template.metadata.baseline.rate_control else None,
        "bitrate_points": template.metadata.baseline.bitrate_points,
        "baseline": {
            "source_dir": template.metadata.baseline.source_dir,
            "bitstream_dir": template.metadata.baseline.bitstream_dir,
            "encoder_type": template.metadata.baseline.encoder_type.value if template.metadata.baseline.encoder_type else None,
            "encoder_params": template.metadata.baseline.encoder_params,
        },
        "experimental": {
            "source_dir": template.metadata.experimental.source_dir,
            "bitstream_dir": template.metadata.experimental.bitstream_dir,
            "encoder_type": template.metadata.experimental.encoder_type.value if template.metadata.experimental.encoder_type else None,
            "encoder_params": template.metadata.experimental.encoder_params,
        },
        "baseline_computed": template.metadata.baseline_computed,
        "baseline_fingerprint": _fingerprint(template.metadata.baseline),
        "entries": report_entries,
        "bd_metrics": bd_metrics,
        "environment": env,
    }

    if job:
        report_dir = Path(job.job_dir) / "metrics_analysis"
    else:
        report_dir = template.template_dir / "metrics_analysis"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report_data.json"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        if job:
            result["report_data_file"] = str(report_path.relative_to(job.job_dir))
        else:
            result["report_data_file"] = str(report_path)
    except Exception:
        pass

    return result


# 全局实例
class TemplateRunner:
    async def execute(self, template: EncodingTemplate, job=None):
        return await run_template(template, job=job)


template_runner = TemplateRunner()
