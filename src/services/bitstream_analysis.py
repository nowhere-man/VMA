"""
码流分析服务

Ref + 多个 Encoded 的质量指标与码率分析：
- 使用管道方式计算指标（不保存临时 YUV 文件）
- PSNR/SSIM 输出每帧 y/u/v/avg
- VMAF 同时计算 vmaf 与 vmaf_neg（v0.6.1 / v0.6.1neg）
- 码率分析输出平均码率、每帧大小与帧类型
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import settings
from src.models import Job
from src.services.ffmpeg import ffmpeg_service
from src.utils.metrics import parse_psnr_log, parse_ssim_log, parse_vmaf_log
from src.utils.encoding import parse_yuv_name

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
    upscale_to_source: bool = True,
    target_fps: Optional[float] = None,
    add_command_callback=None,
    update_status_callback=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    通用码流分析逻辑（可供模板任务与码流分析任务复用）

    使用管道方式计算指标，不保存临时 YUV 文件。

    Args:
        reference_path: 参考视频路径
        encoded_paths: 已编码视频路径列表
        analysis_dir: 输出目录（会生成日志及 report_data.json）
        raw_width/raw_height/raw_fps: 参考为 YUV 时必填
        raw_pix_fmt: 参考 YUV 像素格式
        upscale_to_source: Metrics策略，True=码流上采样到源分辨率，False=源视频下采样到码流分辨率
        target_fps: 模板指定的目标帧率（优先使用）
        add_command_callback/update_status_callback: 可选的命令日志回调
    """
    analysis_dir.mkdir(parents=True, exist_ok=True)

    if not reference_path.exists():
        raise FileNotFoundError("参考视频不存在")

    if not encoded_paths:
        raise ValueError("未提供任何编码视频")

    # 1) 获取参考视频信息
    ref_is_yuv = _is_yuv(reference_path)
    ref_input_format: Optional[str] = None

    if ref_is_yuv:
        if raw_width is None or raw_height is None or raw_fps is None:
            try:
                ref_width, ref_height, ref_fps = parse_yuv_name(reference_path)
            except ValueError as exc:
                raise ValueError("参考视频为 .yuv，文件名需包含 _WxH_FPS，例如 video_1920x1080_30.yuv") from exc
        else:
            ref_width, ref_height, ref_fps = raw_width, raw_height, float(raw_fps)
    else:
        ref_input_format = await _infer_input_format(reference_path)
        ref_info = await ffmpeg_service.get_video_info(reference_path, input_format=ref_input_format)
        ref_width = int(ref_info.get("width") or 0)
        ref_height = int(ref_info.get("height") or 0)
        ref_fps_val = ref_info.get("fps")
        if not ref_width or not ref_height:
            raise ValueError("无法解析参考视频分辨率")
        if not isinstance(ref_fps_val, (int, float)) or ref_fps_val <= 0:
            raise ValueError("无法解析参考视频帧率（如为裸码流且未携带 VUI，请改用 yuv 输入并填写 fps）")
        ref_fps = float(ref_fps_val)

    # 2) 对每个 Encoded：使用管道方式计算指标
    encoded_reports: List[Dict[str, Any]] = []
    encoded_summaries: List[Dict[str, Any]] = []

    for idx, enc_input in enumerate(encoded_paths):
        if not enc_input.exists():
            raise FileNotFoundError(f"编码视频不存在: {enc_input.name}")

        enc_label = enc_input.name
        enc_is_yuv = _is_yuv(enc_input)

        # 2.1 输入格式与基本信息
        enc_input_format: Optional[str] = None
        enc_codec: Optional[str] = None
        enc_width: int
        enc_height: int
        enc_fps: float

        if enc_is_yuv:
            if raw_width is not None and raw_height is not None and raw_fps is not None:
                enc_width, enc_height, enc_fps = raw_width, raw_height, float(raw_fps)
            else:
                try:
                    enc_width, enc_height, enc_fps = parse_yuv_name(enc_input)
                except ValueError as exc:
                    raise ValueError(
                        f"检测到 .yuv，文件名需包含 _WxH_FPS，例如 video_1920x1080_30.yuv: {enc_input.name}"
                    ) from exc
        else:
            enc_input_format = await _infer_input_format(enc_input)
            info = await ffmpeg_service.get_video_info(enc_input, input_format=enc_input_format)
            enc_codec = info.get("codec_name")
            enc_width = int(info.get("width") or 0)
            enc_height = int(info.get("height") or 0)
            fps_val = info.get("fps")
            if not enc_width or not enc_height:
                raise ValueError(f"无法解析编码视频分辨率: {enc_input.name}")
            enc_fps = float(fps_val) if isinstance(fps_val, (int, float)) and fps_val > 0 else ref_fps

        # 2.2 使用管道方式计算指标
        enc_analysis_dir = analysis_dir / f"encoded_{idx+1}"
        enc_analysis_dir.mkdir(parents=True, exist_ok=True)

        metrics_result = await ffmpeg_service.calculate_metrics_pipeline(
            reference_path=reference_path,
            encoded_path=enc_input,
            analysis_dir=enc_analysis_dir,
            src_width=ref_width,
            src_height=ref_height,
            src_fps=ref_fps,
            enc_width=enc_width,
            enc_height=enc_height,
            enc_fps=enc_fps,
            upscale_to_source=upscale_to_source,
            ref_input_format=ref_input_format,
            enc_input_format=enc_input_format,
            ref_is_yuv=ref_is_yuv,
            enc_is_yuv=enc_is_yuv,
            ref_pix_fmt=raw_pix_fmt,
            enc_pix_fmt=raw_pix_fmt,
            target_fps=target_fps,
            add_command_callback=add_command_callback,
            update_status_callback=update_status_callback,
        )

        psnr_data = metrics_result.get("psnr", {})
        ssim_data = metrics_result.get("ssim", {})
        vmaf_data = metrics_result.get("vmaf", {})

        # 2.3 码率/帧结构
        frame_types: List[str] = []
        frame_sizes: List[int] = []
        frame_timestamps: List[float] = []
        frames_used: int = 0

        if enc_is_yuv:
            # YUV 文件：计算帧数
            frame_size = _frame_size_bytes_yuv420p(enc_width, enc_height)
            enc_frames = enc_input.stat().st_size // frame_size if frame_size > 0 else 0
            frames_used = enc_frames
            frame_types = ["RAW"] * frames_used
            frame_sizes = [frame_size] * frames_used
            frame_timestamps = [i / enc_fps for i in range(frames_used)]
        else:
            frames_info = await ffmpeg_service.probe_video_frames(enc_input, input_format=enc_input_format)
            for i, fr in enumerate(frames_info):
                frame_types.append((fr.get("pict_type") or "UNK"))
                frame_sizes.append(int(fr.get("pkt_size") or 0))
                ts = fr.get("timestamp")
                frame_timestamps.append(float(ts) if ts is not None else (i / enc_fps))
            frames_used = len(frame_sizes)

        duration_seconds = frames_used / enc_fps if enc_fps > 0 else 0
        avg_bitrate_bps = int((sum(frame_sizes) * 8) / duration_seconds) if duration_seconds > 0 else 0

        # 判断是否进行了缩放
        scaled = (enc_width != ref_width or enc_height != ref_height)

        encoded_reports.append(
            {
                "label": enc_label,
                "format": enc_codec or "Unknown",
                "width": enc_width,
                "height": enc_height,
                "fps": enc_fps,
                "input_format": enc_input_format or "auto",
                "codec": enc_codec,
                "scaled_to_reference": scaled and upscale_to_source,
                "frames_total": frames_used,
                "frames_used": frames_used,
                "frames_mismatch": False,
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
                "scaled_to_reference": scaled and upscale_to_source,
                "avg_bitrate_bps": avg_bitrate_bps,
                "psnr": psnr_data.get("summary", {}),
                "ssim": ssim_data.get("summary", {}),
                "vmaf": vmaf_data.get("summary", {}),
                "bitrate": {
                    "frame_types": frame_types,
                    "frame_sizes": frame_sizes,
                    "frame_timestamps": [round(t, 2) for t in frame_timestamps],
                },
            }
        )

    frames_used_overall = min(
        (item.get("frames_used", 0) for item in encoded_reports),
        default=0,
    )

    report_data: Dict[str, Any] = {
        "kind": "bitstream_analysis",
        "reference": {
            "label": reference_path.name,
            "width": ref_width,
            "height": ref_height,
            "fps": ref_fps,
            "frames": frames_used_overall,
            "frames_total": frames_used_overall,
            "frames_used": frames_used_overall,
        },
        "encoded": encoded_reports,
    }

    summary: Dict[str, Any] = {
        "type": "bitstream_analysis",
        "reference": report_data["reference"],
        "encoded": encoded_summaries,
    }

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
        upscale_to_source=job.metadata.upscale_to_source,
        target_fps=None,
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
