"""
码流分析服务

Ref + 多个 Encoded 的质量指标与码率分析：
- 所有打分输入统一转换为 yuv420p rawvideo
- PSNR/SSIM 输出每帧 y/u/v/avg
- VMAF 同时计算 vmaf 与 vmaf_neg（v0.6.1 / v0.6.1neg）
- 码率分析输出平均码率、每帧大小与帧类型
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from pathlib import Path
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

from src.config import settings
from src.models import Job
from src.services.ffmpeg import ffmpeg_service

logger = logging.getLogger(__name__)


def _is_yuv(path: Path) -> bool:
    return path.suffix.lower() == ".yuv"


def _frame_size_bytes_yuv420p(width: int, height: int) -> int:
    return (width * height * 3) // 2


def _count_yuv420p_frames(path: Path, width: int, height: int) -> int:
    frame_size = _frame_size_bytes_yuv420p(width, height)
    if frame_size <= 0:
        raise ValueError("Invalid frame size for yuv420p")
    size = path.stat().st_size
    if size % frame_size != 0:
        raise ValueError(f"YUV 文件大小与分辨率不匹配: {path.name} (size={size}, frame={frame_size})")
    return size // frame_size


def _parse_psnr_stats(log_path: Path) -> Dict[str, Any]:
    """
    PSNR stats_file 行格式示例：
    n:1 mse_avg:0.52 mse_y:0.48 mse_u:0.58 mse_v:0.52 psnr_avg:50.99 psnr_y:51.31 psnr_u:50.48 psnr_v:50.97
    """
    frames_avg: List[float] = []
    frames_y: List[float] = []
    frames_u: List[float] = []
    frames_v: List[float] = []

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "psnr_avg" not in line:
                continue
            parts = line.strip().split()
            values: Dict[str, float] = {}
            for part in parts:
                if ":" not in part:
                    continue
                key, val = part.split(":", 1)
                if key.startswith("psnr_"):
                    try:
                        values[key] = float(val)
                    except ValueError:
                        continue
            if "psnr_avg" in values:
                frames_avg.append(values.get("psnr_avg", 0.0))
                frames_y.append(values.get("psnr_y", 0.0))
                frames_u.append(values.get("psnr_u", 0.0))
                frames_v.append(values.get("psnr_v", 0.0))

    if not frames_avg:
        raise ValueError(f"No PSNR data found in {log_path.name}")

    def _mean(values: List[float]) -> float:
        return sum(values) / len(values)

    return {
        "summary": {
            "psnr_avg": _mean(frames_avg),
            "psnr_y": _mean(frames_y),
            "psnr_u": _mean(frames_u),
            "psnr_v": _mean(frames_v),
        },
        "frames": {
            "psnr_avg": frames_avg,
            "psnr_y": frames_y,
            "psnr_u": frames_u,
            "psnr_v": frames_v,
        },
    }


def _parse_ssim_stats(log_path: Path) -> Dict[str, Any]:
    """
    SSIM stats_file 行格式示例：
    n:1 Y:0.9876 U:0.9901 V:0.9888 All:0.9885 (15.234)
    """
    frames_all: List[float] = []
    frames_y: List[float] = []
    frames_u: List[float] = []
    frames_v: List[float] = []

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "All:" not in line:
                continue
            parts = line.strip().split()
            values: Dict[str, float] = {}
            for part in parts:
                if ":" not in part:
                    continue
                key, val = part.split(":", 1)
                key_norm = key.strip()
                if key_norm in ("Y", "U", "V", "All"):
                    try:
                        values[key_norm] = float(val)
                    except ValueError:
                        continue
            if "All" in values:
                frames_all.append(values.get("All", 0.0))
                frames_y.append(values.get("Y", 0.0))
                frames_u.append(values.get("U", 0.0))
                frames_v.append(values.get("V", 0.0))

    if not frames_all:
        raise ValueError(f"No SSIM data found in {log_path.name}")

    def _mean(values: List[float]) -> float:
        return sum(values) / len(values)

    return {
        "summary": {
            "ssim_avg": _mean(frames_all),
            "ssim_y": _mean(frames_y),
            "ssim_u": _mean(frames_u),
            "ssim_v": _mean(frames_v),
        },
        "frames": {
            "ssim_avg": frames_all,
            "ssim_y": frames_y,
            "ssim_u": frames_u,
            "ssim_v": frames_v,
        },
    }


def _parse_vmaf_csv(log_path: Path) -> Dict[str, Any]:
    def _to_float(val: Any) -> Optional[float]:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _mean(values: List[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def _harmonic_mean(values: List[float]) -> float:
        positives = [v for v in values if v and v > 0]
        return len(positives) / sum(1.0 / v for v in positives) if positives else 0.0

    def _build_feature_summary(series: Dict[str, List[Optional[float]]]) -> Dict[str, Dict[str, float]]:
        summary: Dict[str, Dict[str, float]] = {}
        for key, vals in series.items():
            nums = [v for v in vals if isinstance(v, (int, float))]
            if not nums:
                continue
            entry: Dict[str, float] = {"mean": _mean(nums)}
            harmonic = _harmonic_mean(nums)
            if harmonic:
                entry["harmonic_mean"] = harmonic
            summary[key] = entry
        return summary

    def _parse_json(text: str) -> Dict[str, Any]:
        data = json.loads(text)
        frames = data.get("frames", []) or []

        metric_keys = set()
        for frame in frames:
            metrics = frame.get("metrics", {}) or {}
            metric_keys.update(metrics.keys())

        metric_keys_sorted = sorted(metric_keys)
        frame_series: Dict[str, List[Optional[float]]] = {k: [] for k in metric_keys_sorted}

        for frame in frames:
            metrics = frame.get("metrics", {}) or {}
            for key in metric_keys_sorted:
                frame_series[key].append(_to_float(metrics.get(key)))

        frame_series = {k: v for k, v in frame_series.items() if any(val is not None for val in v)}

        pooled = data.get("pooled_metrics", {}) or {}
        vmaf_pooled = pooled.get("vmaf", {}) or {}
        vmaf_neg_pooled = pooled.get("vmaf_neg", {}) or {}

        feature_summary: Dict[str, Dict[str, float]] = {}
        for key, stats in pooled.items():
            if not isinstance(stats, dict):
                continue
            entry: Dict[str, float] = {}
            mean_val = _to_float(stats.get("mean"))
            harmonic_val = _to_float(stats.get("harmonic_mean"))
            if mean_val is not None:
                entry["mean"] = mean_val
            if harmonic_val is not None:
                entry["harmonic_mean"] = harmonic_val
            if entry:
                feature_summary[key] = entry

        result: Dict[str, Any] = {
            "summary": {
                "vmaf_mean": _to_float(vmaf_pooled.get("mean")) if vmaf_pooled else None,
                "vmaf_harmonic_mean": _to_float(vmaf_pooled.get("harmonic_mean")) if vmaf_pooled else None,
                "vmaf_neg_mean": _to_float(vmaf_neg_pooled.get("mean")) if vmaf_neg_pooled else None,
            },
            "frames": {
                **frame_series,
            },
        }

        if feature_summary:
            result["feature_summary"] = feature_summary

        return result

    def _parse_csv(text: str) -> Dict[str, Any]:
        reader = csv.DictReader(StringIO(text))
        fieldnames = reader.fieldnames or []
        metric_keys = [fn for fn in fieldnames if fn and fn.lower() not in {"frame", "index", "frame_num"}]

        frame_series: Dict[str, List[Optional[float]]] = {k: [] for k in metric_keys}
        for row in reader:
            for key in metric_keys:
                frame_series[key].append(_to_float(row.get(key)))

        frame_series = {k: v for k, v in frame_series.items() if any(val is not None for val in v)}

        vmaf_vals = [v for v in frame_series.get("vmaf", []) if v is not None]
        vmaf_neg_vals = [v for v in frame_series.get("vmaf_neg", []) if v is not None]

        result: Dict[str, Any] = {
            "summary": {
                "vmaf_mean": _mean(vmaf_vals) if vmaf_vals else None,
                "vmaf_harmonic_mean": _harmonic_mean(vmaf_vals) if vmaf_vals else None,
                "vmaf_neg_mean": _mean(vmaf_neg_vals) if vmaf_neg_vals else None,
            },
            "frames": frame_series,
        }

        feature_summary = _build_feature_summary(frame_series)
        if feature_summary:
            result["feature_summary"] = feature_summary

        return result

    text = log_path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        raise ValueError(f"VMAF log is empty: {log_path.name}")

    if text.lstrip().startswith("{"):
        return _parse_json(text)
    return _parse_csv(text)


async def _run_subprocess(cmd: List[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=settings.ffmpeg_timeout)
    except asyncio.TimeoutError:
        process.kill()
        raise RuntimeError("Command timed out")

    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="ignore"))


async def _infer_input_format(path: Path) -> Optional[str]:
    if path.stat().st_size == 0:
        raise RuntimeError(f"文件为空: {path.name}")

    suffix = path.suffix.lower()
    if suffix in {".h264", ".264"}:
        return "h264"
    if suffix in {".h265", ".265", ".hevc"}:
        return "hevc"

    # Container/auto probe
    try:
        info = await ffmpeg_service.get_video_info(path)
        if info.get("width") and info.get("height"):
            return None
    except Exception:
        pass

    for fmt, codec in (("h264", "h264"), ("hevc", "hevc")):
        try:
            info = await ffmpeg_service.get_video_info(path, input_format=fmt)
            codec_name = info.get("codec_name")
            if info.get("width") and info.get("height") and codec_name == codec:
                return fmt
        except Exception:
            continue

    raise RuntimeError(f"无法识别码流格式（仅支持 h264/h265 或容器格式）: {path.name}")


async def build_bitstream_report(
    reference_path: Path,
    encoded_paths: List[Path],
    analysis_dir: Path,
    raw_width: Optional[int] = None,
    raw_height: Optional[int] = None,
    raw_fps: Optional[float] = None,
    raw_pix_fmt: str = "yuv420p",
    add_command_callback=None,
    update_status_callback=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    通用码流分析逻辑（可供模板任务与码流分析任务复用）

    Args:
        reference_path: 参考视频路径
        encoded_paths: 已编码视频路径列表
        analysis_dir: 输出目录（会生成 yuv、日志及 report_data.json）
        raw_width/raw_height/raw_fps: 参考为 YUV 时必填
        raw_pix_fmt: 参考 YUV 像素格式
        add_command_callback/update_status_callback: 可选的命令日志回调
    """
    analysis_dir.mkdir(parents=True, exist_ok=True)

    if not reference_path.exists():
        raise FileNotFoundError("参考视频不存在")

    if not encoded_paths:
        raise ValueError("未提供任何编码视频")

    # 1) 准备参考 yuv420p
    ref_tmp_created = False
    if _is_yuv(reference_path):
        if raw_width is None or raw_height is None or raw_fps is None:
            raise ValueError("参考视频为 .yuv，必须提供 width/height/fps")
        ref_width, ref_height, ref_fps = raw_width, raw_height, float(raw_fps)
        ref_yuv = reference_path
    else:
        ref_fmt = await _infer_input_format(reference_path)
        ref_info = await ffmpeg_service.get_video_info(reference_path, input_format=ref_fmt)
        ref_width = int(ref_info.get("width") or 0)
        ref_height = int(ref_info.get("height") or 0)
        ref_fps_val = ref_info.get("fps")
        if not ref_width or not ref_height:
            raise ValueError("无法解析参考视频分辨率")
        if not isinstance(ref_fps_val, (int, float)) or ref_fps_val <= 0:
            raise ValueError("无法解析参考视频帧率（如为裸码流且未携带 VUI，请改用 yuv 输入并填写 fps）")
        ref_fps = float(ref_fps_val)
        ref_yuv = analysis_dir / "ref_yuv420p.yuv"
        await ffmpeg_service.decode_to_yuv420p(
            reference_path,
            ref_yuv,
            input_format=ref_fmt,
            add_command_callback=add_command_callback,
            update_status_callback=update_status_callback,
            command_type="ref_to_yuv",
            source_file=str(reference_path),
        )
        ref_tmp_created = True

    ref_frames_total = _count_yuv420p_frames(ref_yuv, ref_width, ref_height)

    # 命令日志包装
    async def _run_logged(cmd: List[str], cmd_type: str):
        cmd_id = None
        if add_command_callback:
            cmd_id = add_command_callback(cmd_type, " ".join(cmd), str(reference_path))
        if update_status_callback and cmd_id:
            update_status_callback(cmd_id, "running")
        try:
            await _run_subprocess(cmd)
            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "completed")
        except Exception as exc:
            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "failed", str(exc))
            raise

    # 2) 对每个 Encoded：转换到 yuv420p（必要时上采样），并计算指标与码率
    encoded_reports: List[Dict[str, Any]] = []
    encoded_summaries: List[Dict[str, Any]] = []

    for idx, enc_input in enumerate(encoded_paths):
        if not enc_input.exists():
            raise FileNotFoundError(f"编码视频不存在: {enc_input.name}")

        enc_label = enc_input.name
        enc_is_yuv = _is_yuv(enc_input)

        # 2.1 输入格式与基本信息
        enc_fmt: Optional[str] = None
        enc_codec: Optional[str] = None
        enc_width: Optional[int] = None
        enc_height: Optional[int] = None
        enc_fps: Optional[float] = None

        if enc_is_yuv:
            if raw_width is None or raw_height is None or raw_fps is None:
                raise ValueError("检测到 .yuv Encoded，必须提供 width/height/fps")
            enc_width, enc_height, enc_fps = raw_width, raw_height, float(raw_fps)
        else:
            enc_fmt = await _infer_input_format(enc_input)
            info = await ffmpeg_service.get_video_info(enc_input, input_format=enc_fmt)
            enc_codec = info.get("codec_name")
            enc_width = int(info.get("width") or 0) if info.get("width") else None
            enc_height = int(info.get("height") or 0) if info.get("height") else None
            fps_val = info.get("fps")
            enc_fps = float(fps_val) if isinstance(fps_val, (int, float)) and fps_val > 0 else None

        # 2.2 帧率一致性校验（可获取的情况下）——如不一致则沿用参考帧率继续处理
        if enc_fps is not None and abs(enc_fps - ref_fps) > 0.01:
            logger.warning(f"帧率不一致: Ref={ref_fps}, Encoded({enc_label})={enc_fps}，继续按参考帧率处理")
            enc_fps = ref_fps

        # 2.3 转换为 yuv420p（必要时缩放到 Ref 分辨率）
        enc_yuv = analysis_dir / f"encoded_{idx+1}_yuv420p.yuv"

        scaled = False
        if enc_is_yuv:
            scaled = bool(enc_width != ref_width or enc_height != ref_height)
            if scaled:
                await ffmpeg_service.decode_to_yuv420p(
                    enc_input,
                    enc_yuv,
                    input_width=enc_width,
                    input_height=enc_height,
                    input_fps=ref_fps,
                    input_pix_fmt=raw_pix_fmt,
                    scale_width=ref_width,
                    scale_height=ref_height,
                    add_command_callback=add_command_callback,
                    update_status_callback=update_status_callback,
                    command_type="scale_yuv_to_ref",
                    source_file=str(enc_input),
                )
            else:
                enc_yuv = enc_input
        else:
            scaled = bool(enc_width and enc_height and (enc_width != ref_width or enc_height != ref_height))
            await ffmpeg_service.decode_to_yuv420p(
                enc_input,
                enc_yuv,
                input_format=enc_fmt,
                scale_width=ref_width,
                scale_height=ref_height,
                add_command_callback=add_command_callback,
                update_status_callback=update_status_callback,
                command_type="bitstream_to_yuv",
                source_file=str(enc_input),
            )

        enc_frames = _count_yuv420p_frames(enc_yuv, ref_width, ref_height)
        frames_used = min(ref_frames_total, enc_frames)
        frame_mismatch = enc_frames != ref_frames_total

        # 2.4 计算 PSNR / SSIM / VMAF(vmaf + vmaf_neg)
        psnr_log = analysis_dir / f"encoded_{idx+1}_psnr.log"
        ssim_log = analysis_dir / f"encoded_{idx+1}_ssim.log"
        vmaf_csv = analysis_dir / f"encoded_{idx+1}_vmaf.csv"

        # 注意：ffmpeg 滤镜的第一个输入为待测(distorted)，第二个为参考(reference)
        raw_ref_args = [
            ffmpeg_service.ffmpeg_path,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-s",
            f"{ref_width}x{ref_height}",
            "-r",
            str(ref_fps),
            "-i",
            str(enc_yuv),  # distorted
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-s",
            f"{ref_width}x{ref_height}",
            "-r",
            str(ref_fps),
            "-i",
            str(ref_yuv),  # reference
        ]

        limit_args = ["-frames:v", str(frames_used)] if frame_mismatch else []

        await _run_logged(
            raw_ref_args
            + [
                "-filter_complex",
                f"psnr=stats_file={psnr_log}",
            ]
            + limit_args
            + [
                "-f",
                "null",
                "-",
            ],
            "psnr",
        )
        await _run_logged(
            raw_ref_args
            + [
                "-filter_complex",
                f"ssim=stats_file={ssim_log}",
            ]
            + limit_args
            + [
                "-f",
                "null",
                "-",
            ],
            "ssim",
        )

        model_value = (
            "version=vmaf_v0.6.1\\:name=vmaf|version=vmaf_v0.6.1neg\\:name=vmaf_neg"
        )
        vmaf_filter = (
            f"libvmaf='model={model_value}':n_threads=8:log_fmt=csv:log_path={vmaf_csv}"
        )
        await _run_logged(
            raw_ref_args
            + [
                "-filter_complex",
                vmaf_filter,
            ]
            + limit_args
            + [
                "-f",
                "null",
                "-",
            ],
            "vmaf",
        )

        psnr_data = _parse_psnr_stats(psnr_log)
        ssim_data = _parse_ssim_stats(ssim_log)
        vmaf_data = _parse_vmaf_csv(vmaf_csv)
        # 清理中间文件
        try:
            # if psnr_log.exists():
            #     psnr_log.unlink()
            # if ssim_log.exists():
            #     ssim_log.unlink()
            # if vmaf_csv.exists():
            #     vmaf_csv.unlink()
            # 清理转换后的 yuv（仅当非原始输入或缩放过时）
            if enc_yuv.exists() and enc_yuv != enc_input:
                enc_yuv.unlink()
        except Exception:
            logger.warning("清理中间文件失败", exc_info=True)

        # 2.5 码率/帧结构（Encoded 原始文件）
        frame_types: List[str] = []
        frame_sizes: List[int] = []
        frame_timestamps: List[float] = []

        if enc_is_yuv:
            frame_size = _frame_size_bytes_yuv420p(enc_width or ref_width, enc_height or ref_height)
            frame_types = ["RAW"] * frames_used
            frame_sizes = [frame_size] * frames_used
            frame_timestamps = [i / ref_fps for i in range(frames_used)]
        else:
            frames_info = await ffmpeg_service.probe_video_frames(enc_input, input_format=enc_fmt)
            for i, fr in enumerate(frames_info):
                frame_types.append((fr.get("pict_type") or "UNK"))
                frame_sizes.append(int(fr.get("pkt_size") or 0))
                ts = fr.get("timestamp")
                frame_timestamps.append(float(ts) if ts is not None else (i / ref_fps))

            if len(frame_sizes) > frames_used:
                frame_types = frame_types[:frames_used]
                frame_sizes = frame_sizes[:frames_used]
                frame_timestamps = frame_timestamps[:frames_used]
            elif len(frame_sizes) < frames_used:
                frames_used = len(frame_sizes)

        duration_seconds = frames_used / ref_fps
        avg_bitrate_bps = int((sum(frame_sizes) * 8) / duration_seconds) if duration_seconds > 0 else 0

        encoded_reports.append(
            {
                "label": enc_label,
                "input_format": enc_fmt or "auto",
                "codec": enc_codec,
                "scaled_to_reference": scaled,
                "frames_total": enc_frames,
                "frames_used": frames_used,
                "frames_mismatch": frame_mismatch,
                "metrics": {
                    "psnr": psnr_data,
                    "ssim": ssim_data,
                    "vmaf": vmaf_data,
                },
                "bitrate": {
                    "avg_bitrate_bps": avg_bitrate_bps,
                    "frame_types": frame_types,
                    "frame_sizes": frame_sizes,
                    "frame_timestamps": frame_timestamps,
                },
            }
        )

        encoded_summaries.append(
            {
                "label": enc_label,
                "scaled_to_reference": scaled,
                "avg_bitrate_bps": avg_bitrate_bps,
                "psnr": psnr_data["summary"],
                "ssim": ssim_data["summary"],
                "vmaf": vmaf_data["summary"],
                "bitrate": {
                    "frame_types": frame_types,
                    "frame_sizes": frame_sizes,
                    "frame_timestamps": [round(t, 2) for t in frame_timestamps],
                },
            }
        )

    frames_used_overall = min(
        (item.get("frames_used", ref_frames_total) for item in encoded_reports),
        default=ref_frames_total,
    )

    report_data: Dict[str, Any] = {
        "kind": "bitstream_analysis",
        "reference": {
            "label": reference_path.name,
            "width": ref_width,
            "height": ref_height,
            "fps": ref_fps,
            "frames": ref_frames_total,
            "frames_total": ref_frames_total,
            "frames_used": frames_used_overall,
        },
        "encoded": encoded_reports,
    }

    summary: Dict[str, Any] = {
        "type": "bitstream_analysis",
        "reference": report_data["reference"],
        "encoded": encoded_summaries,
    }

    # 清理参考临时 yuv（仅对非原始 yuv 输入）
    try:
        if ref_tmp_created and ref_yuv.exists():
            ref_yuv.unlink()
    except Exception:
        logger.warning("清理参考 yuv 失败", exc_info=True)

    return report_data, summary


async def analyze_bitstream_job(
    job: Job,
    add_command_callback=None,
    update_status_callback=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    执行码流分析，返回：
    - report_data: 用于 Streamlit 展示的完整数据（包含逐帧）
    - summary: 写入 metadata.execution_result 的轻量摘要（不包含逐帧）
    """
    ref_input = job.get_reference_path()
    if not ref_input or not ref_input.exists():
        raise FileNotFoundError("参考视频不存在")

    analysis_dir = job.job_dir / "bitstream_analysis"
    encoded_inputs = [job.job_dir / v.filename for v in job.metadata.encoded_videos]
    if not encoded_inputs:
        raise ValueError("未提供任何编码视频")

    raw_w = job.metadata.rawvideo_width
    raw_h = job.metadata.rawvideo_height
    raw_fps = job.metadata.rawvideo_fps
    raw_pix_fmt = job.metadata.rawvideo_pix_fmt or "yuv420p"

    report_data, summary = await build_bitstream_report(
        reference_path=ref_input,
        encoded_paths=encoded_inputs,
        analysis_dir=analysis_dir,
        raw_width=raw_w,
        raw_height=raw_h,
        raw_fps=raw_fps,
        raw_pix_fmt=raw_pix_fmt,
        add_command_callback=add_command_callback,
        update_status_callback=update_status_callback,
    )

    summary["report_data_file"] = str((analysis_dir / "report_data.json").relative_to(job.job_dir))
    report_data["job_id"] = job.job_id

    # 清理上传的源文件（仅删除任务目录内的副本，保留外部路径）
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except Exception:
            logger.warning(f"删除文件失败: {path}", exc_info=True)

    job_root = job.job_dir.resolve()
    to_remove: list[Path] = []

    ref_path = job.get_reference_path()
    if ref_path and ref_path.exists():
        try:
            if ref_path.resolve().is_relative_to(job_root):
                to_remove.append(ref_path)
        except Exception:
            pass

    for vid in job.metadata.encoded_videos or []:
        p = Path(vid.filename)
        if not p.is_absolute():
            p = job.job_dir / p
        if p.exists():
            try:
                if p.resolve().is_relative_to(job_root):
                    to_remove.append(p)
            except Exception:
                pass

    for item in to_remove:
        _safe_unlink(item)

    return report_data, summary
