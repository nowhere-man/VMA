"""
模板执行与指标计算（Anchor / Test）

尽量复用现有码流分析逻辑，允许破坏式实现。
"""
import asyncio
import json
import platform
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil
import numpy as np

from src.models import CommandLog, CommandStatus
from src.models.template import EncoderType, EncodingTemplate, TemplateSideConfig
from src.services import job_storage
from src.services.stream_analysis_runner import build_bitstream_report
from src.services.ffmpeg import ffmpeg_service
from src.utils.bd_rate import bd_rate as _bd_rate, bd_metrics as _bd_metrics
from src.utils.encoding import (
    SourceInfo,
    collect_sources as _collect_sources,
    build_output_stem as _build_output_stem,
    output_extension as _output_extension,
    is_container_file as _is_container_file,
    build_encode_cmd as _build_encode_cmd,
    start_command as _start_command,
    finish_command as _finish_command,
    now as _now,
)
from src.utils.template_helpers import fingerprint as _fingerprint
from src.utils.performance import PerformanceData, run_encode_with_perf as _run_encode_with_perf




def _get_cpu_brand() -> str:
    """跨平台获取 CPU 品牌/型号名称"""
    import subprocess

    # macOS: 使用 sysctl
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

    # Linux: 读取 /proc/cpuinfo
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":")[1].strip()
        except Exception:
            pass

    # Windows: 使用 wmic 或注册表
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip() and l.strip() != "Name"]
                if lines:
                    return lines[0]
        except Exception:
            pass

    # 回退到 platform.processor()
    return platform.processor() or "Unknown"


def _env_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        # 执行时间
        from datetime import datetime
        info["execution_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 操作系统
        info["os"] = platform.system()
        info["os_version"] = platform.release()
        info["os_full"] = platform.platform()

        # CPU 信息
        info["cpu_arch"] = platform.machine()  # x86_64, arm64, aarch64 等
        info["cpu_model"] = _get_cpu_brand()   # Apple M2, Intel Xeon 等
        info["cpu_phys_cores"] = psutil.cpu_count(logical=False) or 0
        info["cpu_log_cores"] = psutil.cpu_count(logical=True) or 0
        info["cpu_percent_before"] = round(psutil.cpu_percent(interval=0.1), 1)

        # CPU 主频（MHz）
        try:
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                info["cpu_freq_mhz"] = round(cpu_freq.current, 2)
        except Exception:
            pass

        # NUMA nodes
        try:
            import subprocess
            if platform.system() == "Linux":
                result = subprocess.run(
                    ["lscpu"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if line.startswith("NUMA node(s):"):
                            info["numa_nodes"] = int(line.split(":")[1].strip())
                            break
        except Exception:
            pass

        # 内存信息（转换为 GB）
        vm = psutil.virtual_memory()
        info["mem_total_gb"] = round(vm.total / (1024 ** 3), 2)
        info["mem_used_gb"] = round(vm.used / (1024 ** 3), 2)
        info["mem_available_gb"] = round(vm.available / (1024 ** 3), 2)
        info["mem_percent_used"] = round(vm.percent, 1)

        # Linux 发行版信息
        if platform.system() == "Linux":
            try:
                import subprocess
                result = subprocess.run(
                    ["lsb_release", "-d"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    info["linux_distro"] = result.stdout.split(":", 1)[1].strip() if ":" in result.stdout else result.stdout.strip()
                else:
                    # 尝试读取 /etc/os-release
                    try:
                        with open("/etc/os-release", "r") as f:
                            for line in f:
                                if line.startswith("PRETTY_NAME="):
                                    info["linux_distro"] = line.split("=", 1)[1].strip().strip('"')
                                    break
                    except Exception:
                        pass
            except Exception:
                pass

        # 主机名
        info["hostname"] = platform.node()

    except Exception:
        pass
    return info


async def _encode_side(
    side: TemplateSideConfig,
    sources: List[SourceInfo],
    recompute: bool,
    job=None,
) -> Tuple[Dict[str, Tuple[List[Path], int, int, float]], Dict[str, List[PerformanceData]]]:
    """
    编码一侧（Anchor 或 Test）的所有源文件（支持并发）
    返回: (outputs, performance_data)
        - outputs: {source_stem: (encoded_paths, out_width, out_height, out_fps)}
        - performance_data: {source_stem: [PerformanceData, ...]}
    """
    import asyncio

    side_dir = Path(side.bitstream_dir)
    side_dir.mkdir(parents=True, exist_ok=True)

    concurrency = side.concurrency or 1
    semaphore = asyncio.Semaphore(concurrency)

    async def encode_single_task(
        src: SourceInfo,
        val: float,
        src_idx: int,
        point_idx: int,
    ) -> Tuple[int, int, Path, Optional[PerformanceData]]:
        """单个编码任务"""
        async with semaphore:
            out_width, out_height, out_fps = src.width, src.height, src.fps

            # 检查是否跳过编码
            if side.skip_encode:
                stem = _build_output_stem(src.path, side.rate_control.value if side.rate_control else "rc", val)
                matches = list(side_dir.glob(f"{stem}.*"))
                if matches:
                    return src_idx, point_idx, matches[0], None
                raise FileNotFoundError(f"缺少码流: {stem}")

            # 检查是否复用已有码流
            stem = _build_output_stem(src.path, side.rate_control.value if side.rate_control else "rc", val)
            ext = _output_extension(side.encoder_type, src, is_container=not src.is_yuv and _is_container_file(src.path), params=side.encoder_params or "")
            out_path = side_dir / f"{stem}{ext}"

            if not recompute and out_path.exists():
                return src_idx, point_idx, out_path, None

            # 执行编码
            cmd, out_width, out_height, out_fps = _build_encode_cmd(
                side.encoder_type,
                side.encoder_params or "",
                side.rate_control.value,
                val,
                src,
                out_path,
                shortest_size=side.shortest_size,
                target_fps=side.target_fps,
            )
            log = _start_command(job, "encode", cmd, src.path, job_storage)

            returncode, _, stderr, perf = await _run_encode_with_perf(cmd, side.encoder_type)

            if returncode != 0:
                _finish_command(job, log, CommandStatus.FAILED, job_storage, error=stderr.decode(errors="ignore"))
                raise RuntimeError(f"编码失败 {out_path.name}: {stderr.decode(errors='ignore')}")

            _finish_command(job, log, CommandStatus.COMPLETED, job_storage)
            return src_idx, point_idx, out_path, perf

    # 创建所有编码任务
    tasks = []
    for src_idx, src in enumerate(sources):
        for point_idx, val in enumerate(side.bitrate_points or []):
            tasks.append(encode_single_task(src, val, src_idx, point_idx))

    # 并发执行所有编码任务
    results = await asyncio.gather(*tasks)

    # 重组结果（按原始顺序）
    outputs: Dict[str, Tuple[List[Path], int, int, float]] = {}
    perf_data: Dict[str, List[Optional[PerformanceData]]] = {}

    for src in sources:
        src_results = [r for r in results if r[0] == sources.index(src)]
        file_outputs = []
        file_perfs = []

        # 按码率点顺序排序
        src_results.sort(key=lambda x: x[1])

        for _, point_idx, out_path, perf in src_results:
            file_outputs.append(out_path)
            file_perfs.append(perf)

        # 获取输出尺寸和帧率（从第一个有效结果）
        out_width = src.width
        out_height = src.height
        out_fps = src.fps

        outputs[src.path.stem] = (file_outputs, out_width, out_height, out_fps)
        perf_data[src.path.stem] = file_perfs

    return outputs, perf_data


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
    if template.metadata.anchor.rate_control != template.metadata.test.rate_control:
        raise ValueError("Anchor 与 Test 的码控方式不一致")
    if template.metadata.anchor.encoder_type and template.metadata.test.encoder_type:
        if template.metadata.anchor.encoder_type != template.metadata.test.encoder_type:
            raise ValueError("Anchor 与 Test 的编码器类型不一致")
    if sorted(template.metadata.anchor.bitrate_points or []) != sorted(template.metadata.test.bitrate_points or []):
        raise ValueError("Anchor 与 Test 的码率点位不一致")
    # 收集源并按 stem 对齐
    anchor_sources = await _collect_sources(template.metadata.anchor.source_dir)
    test_sources = await _collect_sources(template.metadata.test.source_dir)
    anchor_map = {p.path.stem: p for p in anchor_sources}
    test_map = {p.path.stem: p for p in test_sources}
    if set(anchor_map.keys()) != set(test_map.keys()):
        missing_a = set(anchor_map.keys()) - set(test_map.keys())
        missing_b = set(test_map.keys()) - set(anchor_map.keys())
        raise ValueError(f"源文件不匹配: Anchor 多 {missing_a}，Test 多 {missing_b}")
    ordered_sources = [anchor_map[k] for k in sorted(anchor_map.keys())]

    # Anchor 编码/校验
    def _has_files(p: Path) -> bool:
        return any(p.glob("*")) if p.exists() else False

    anchor_needed = (not template.metadata.anchor_computed) or (not _has_files(Path(template.metadata.anchor.bitstream_dir)))

    # 收集 Anchor 环境信息（编码前）
    anchor_env = _env_info()

    anchor_outputs, anchor_perfs = await _encode_side(
        template.metadata.anchor,
        ordered_sources,
        recompute=anchor_needed,
        job=job,
    )
    template.metadata.anchor_computed = True
    template.metadata.anchor_fingerprint = _fingerprint(template.metadata.anchor)

    # Test 编码/校验
    # 收集 Test 环境信息（编码前）
    test_env = _env_info()

    test_outputs, test_perfs = await _encode_side(
        template.metadata.test,
        [test_map[s.path.stem] for s in ordered_sources],
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
        anchor_info = anchor_outputs.get(key)
        test_info = test_outputs.get(key)

        if not anchor_info or not test_info:
            raise ValueError(f"缺少码流: {src.path.name}")

        anchor_paths, _anchor_w, _anchor_h, _anchor_fps = anchor_info
        test_paths, _test_w, _test_h, _test_fps = test_info

        if not anchor_paths or not test_paths:
            raise ValueError(f"缺少码流: {src.path.name}")

        analysis_dir = analysis_root / src.path.stem
        analysis_dir.mkdir(parents=True, exist_ok=True)

        anchor_report, anchor_summary = await build_bitstream_report(
            reference_path=src.path,
            encoded_paths=anchor_paths,
            analysis_dir=analysis_dir / "anchor",
            raw_width=src.width if src.is_yuv else None,
            raw_height=src.height if src.is_yuv else None,
            raw_fps=src.fps if src.is_yuv else None,
            raw_pix_fmt=src.pix_fmt,
            upscale_to_source=template.metadata.anchor.upscale_to_source,
            target_fps=template.metadata.anchor.target_fps,
            add_command_callback=_add_cmd,
            update_status_callback=_update_cmd,
        )
        test_report, test_summary = await build_bitstream_report(
            reference_path=src.path,
            encoded_paths=test_paths,
            analysis_dir=analysis_dir / "test",
            raw_width=src.width if src.is_yuv else None,
            raw_height=src.height if src.is_yuv else None,
            raw_fps=src.fps if src.is_yuv else None,
            raw_pix_fmt=src.pix_fmt,
            upscale_to_source=template.metadata.test.upscale_to_source,
            target_fps=template.metadata.test.target_fps,
            add_command_callback=_add_cmd,
            update_status_callback=_update_cmd,
        )

        # 生成 BD 曲线
        def _extract_bitrate(item):
            bitrate = item.get("avg_bitrate_bps") or (item.get("bitrate") or {}).get("avg_bitrate_bps")
            if isinstance(bitrate, (int, float)) and bitrate > 0:
                return float(bitrate)
            return None

        def _extract_metric_value(item, key):
            # vmaf_neg_mean 在 vmaf 结构里，不是单独的 vmaf_neg 结构
            if key == "vmaf_neg":
                metric = (item.get("metrics") or {}).get("vmaf") or {}
                if not metric:
                    metric = item.get("vmaf") or {}
                val = metric.get("vmaf_neg_mean")
            else:
                metric = (item.get("metrics") or {}).get(key) or {}
                if not metric:
                    metric = item.get(key) or {}
                val = metric.get(f"{key}_avg") or metric.get(f"{key}_mean")
            if isinstance(val, (int, float)):
                return float(val)
            return None

        def _collect(series, key):
            pts = []
            for item in series:
                bitrate = _extract_bitrate(item)
                val = _extract_metric_value(item, key)
                if bitrate is not None and val is not None:
                    pts.append((val, bitrate))
            return pts

        # encoded summaries are in report["encoded"]
        anchor_enc = anchor_report.get("encoded") or []
        test_enc = test_report.get("encoded") or []

        def _pair_curves(key):
            pts_a = _collect(anchor_enc, key)
            pts_b = _collect(test_enc, key)
            if len(pts_a) < 4 or len(pts_b) < 4:
                return None
            m1, r1 = zip(*sorted(pts_a, key=lambda x: x[0]))
            m2, r2 = zip(*sorted(pts_b, key=lambda x: x[0]))
            return _bd_rate(list(r1), list(m1), list(r2), list(m2))

        def _pair_metrics(key):
            pts_a = []
            pts_b = []
            for series, target in ((anchor_enc, pts_a), (test_enc, pts_b)):
                for item in series:
                    bitrate = _extract_bitrate(item)
                    val = _extract_metric_value(item, key)
                    if bitrate is not None and val is not None:
                        target.append((bitrate, val))
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

        # 将性能数据添加到 summary 的 encoded 列表中
        anchor_perf_list = anchor_perfs.get(key, [])
        test_perf_list = test_perfs.get(key, [])

        # 为 anchor encoded 添加性能数据
        if anchor_summary and "encoded" in anchor_summary:
            for i, enc_item in enumerate(anchor_summary["encoded"]):
                if i < len(anchor_perf_list):
                    perf_dict = anchor_perf_list[i].to_dict()
                    if perf_dict:  # 只有有数据时才添加
                        enc_item["performance"] = perf_dict

        # 为 test encoded 添加性能数据
        if test_summary and "encoded" in test_summary:
            for i, enc_item in enumerate(test_summary["encoded"]):
                if i < len(test_perf_list):
                    perf_dict = test_perf_list[i].to_dict()
                    if perf_dict:  # 只有有数据时才添加
                        enc_item["performance"] = perf_dict

        report_entries.append(
            {
                "source": src.path.name,
                "anchor": anchor_summary,
                "test": test_summary,
            }
        )

    result: Dict[str, Any] = {
        "kind": "template_metrics",
        "template_id": template.template_id,
        "template_name": template.metadata.name,
        "rate_control": template.metadata.anchor.rate_control.value if template.metadata.anchor.rate_control else None,
        "bitrate_points": template.metadata.anchor.bitrate_points,
        "anchor": {
            "source_dir": template.metadata.anchor.source_dir,
            "bitstream_dir": template.metadata.anchor.bitstream_dir,
            "encoder_type": template.metadata.anchor.encoder_type.value if template.metadata.anchor.encoder_type else None,
            "encoder_params": template.metadata.anchor.encoder_params,
        },
        "test": {
            "source_dir": template.metadata.test.source_dir,
            "bitstream_dir": template.metadata.test.bitstream_dir,
            "encoder_type": template.metadata.test.encoder_type.value if template.metadata.test.encoder_type else None,
            "encoder_params": template.metadata.test.encoder_params,
        },
        "anchor_computed": template.metadata.anchor_computed,
        "anchor_fingerprint": _fingerprint(template.metadata.anchor),
        "entries": report_entries,
        "bd_metrics": bd_metrics,
        "anchor_environment": anchor_env,
        "test_environment": test_env,
    }

    if job:
        report_dir = Path(job.job_dir) / "metrics_analysis"
    else:
        report_dir = template.template_dir / "metrics_analysis"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "metrics_comparison.json"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            # 使用紧凑格式减小文件体积（无缩进，无多余空格）
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        if job:
            result["data_file"] = str(report_path.relative_to(job.job_dir))
        else:
            result["data_file"] = str(report_path)
    except Exception:
        pass

    return result


# 全局实例
class TemplateRunner:
    async def execute(self, template: EncodingTemplate, job=None):
        return await run_template(template, job=job)


template_runner = TemplateRunner()
