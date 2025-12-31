"""
Stream Analysis 后台处理器

处理 Stream Analysis 任务的执行、指标计算和报告生成
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nanoid import generate

from src.config import settings
from src.models import Job, JobMode, JobStatus
from src.services.ffmpeg import ffmpeg_service
from src.utils.metrics import parse_psnr_log, parse_ssim_log, parse_vmaf_log
from src.utils.encoding import parse_yuv_name

logger = logging.getLogger(__name__)


def _now_tz():
    return datetime.now().astimezone()


def _is_yuv(path: Path) -> bool:
    return path.suffix.lower() == ".yuv"


def _frame_size_bytes_yuv420p(width: int, height: int) -> int:
    return (width * height * 3) // 2


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


def _make_command_callbacks(job, job_storage):
    from src.models import CommandLog, CommandStatus

    def add_command_log(command_type: str, command: str, source_file: str = None) -> str:
        command_id = generate(size=8)
        log = CommandLog(
            command_id=command_id,
            command_type=command_type,
            command=command,
            status=CommandStatus.PENDING,
            source_file=source_file,
        )
        job.metadata.command_logs.append(log)
        job_storage.update_job(job)
        return command_id

    def update_command_status(command_id: str, status: str, error: str = None):
        for cmd_log in job.metadata.command_logs:
            if cmd_log.command_id == command_id:
                cmd_log.status = CommandStatus(status)
                now = _now_tz()
                if status == "running":
                    cmd_log.started_at = now
                elif status in ("completed", "failed"):
                    cmd_log.completed_at = now
                if error:
                    cmd_log.error_message = error
                break
        job_storage.update_job(job)

    return add_command_log, update_command_status


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
    通用码流分析逻辑（供 Stream Analysis 任务使用）

    使用管道方式计算指标，不保存临时 YUV 文件。

    Args:
        reference_path: 参考视频路径
        encoded_paths: 已编码视频路径列表
        analysis_dir: 输出目录（会生成日志及 stream_analysis.json）
        raw_width/raw_height/raw_fps: 参考为 YUV 时必填
        raw_pix_fmt: 参考 YUV 像素格式
        upscale_to_source: Metrics策略，True=码流上采样到源分辨率，False=源视频下采样到码流分辨率
        target_fps: 模板指定的目标帧率（优先使用）
        add_command_callback/update_status_callback: 可选的命令日志回调

    Returns:
        Tuple[report_data, summary]: 完整报告数据（含逐帧）和轻量摘要
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
                "fps": enc_fps,
                "psnr": psnr_data,
                "ssim": ssim_data,
                "vmaf": vmaf_data,
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

    analysis_dir = job.job_dir / "analysis"
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

    # 修改 JSON 文件名：report_data.json → stream_analysis.json
    summary["data_file"] = str((analysis_dir / "stream_analysis.json").relative_to(job.job_dir))
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


class StreamAnalysisRunner:
    """Stream Analysis 任务处理器"""

    def __init__(self) -> None:
        """初始化任务处理器"""
        self.processing = False
        self.current_job: Optional[str] = None
        self.supported_modes = {JobMode.BITSTREAM_ANALYSIS}

    async def process_job(self, job_id: str) -> None:
        """
        处理单个任务

        Args:
            job_id: 任务 ID
        """
        from .storage import job_storage

        job = job_storage.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        # 仅处理该处理器支持的模式
        if job.metadata.mode not in self.supported_modes:
            logger.info(f"Skipping job {job_id} (unsupported mode: {job.metadata.mode})")
            return

        try:
            # 更新状态为处理中
            job.metadata.status = JobStatus.PROCESSING
            job.metadata.updated_at = _now_tz()
            job_storage.update_job(job)

            logger.info(f"Processing job {job_id} (mode: {job.metadata.mode})")

            # 处理 Stream Analysis 任务
            if job.metadata.mode == JobMode.BITSTREAM_ANALYSIS:
                await self._process_stream_analysis(job)

            # 更新状态为已完成
            job.metadata.status = JobStatus.COMPLETED
            job.metadata.completed_at = _now_tz()
            job.metadata.updated_at = _now_tz()
            job_storage.update_job(job)

            logger.info(f"Job {job_id} completed successfully")

        except Exception as e:
            # 更新状态为失败
            job.metadata.status = JobStatus.FAILED
            job.metadata.error_message = str(e)
            job.metadata.updated_at = _now_tz()
            job_storage.update_job(job)

            logger.error(f"Job {job_id} failed: {str(e)}")

    async def _process_stream_analysis(self, job: Job) -> None:
        """处理 Stream Analysis 任务（Ref + 多个 Encoded）"""
        from .storage import job_storage

        add_command_log, update_command_status = _make_command_callbacks(job, job_storage)

        report_data, summary = await analyze_bitstream_job(
            job,
            add_command_callback=add_command_log,
            update_status_callback=update_command_status,
        )

        # 写入报告数据文件（供 Streamlit 使用）
        report_rel_path = summary.get("data_file")
        if not report_rel_path:
            raise RuntimeError("Stream analysis missing data_file")

        report_path = job.job_dir / report_rel_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False)

        job.metadata.execution_result = summary
        job_storage.update_job(job)

    async def start_background_processor(self) -> None:
        """启动后台处理器（轮询待处理任务）"""
        from .storage import job_storage

        self.processing = True
        logger.info("Background Stream Analysis processor started")

        while self.processing:
            try:
                # 查找待处理的任务
                pending_jobs = job_storage.list_jobs(status=JobStatus.PENDING, limit=20)
                job_to_process = next(
                    (j for j in pending_jobs if j.metadata.mode in self.supported_modes),
                    None,
                )

                if job_to_process:
                    self.current_job = job_to_process.job_id
                    await self.process_job(job_to_process.job_id)
                    self.current_job = None
                else:
                    # 没有待处理任务，等待一会儿
                    await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error in background processor: {str(e)}")
                await asyncio.sleep(5)

    def stop_background_processor(self) -> None:
        """停止后台处理器"""
        self.processing = False
        logger.info("Background Stream Analysis processor stopped")


# 全局单例
stream_analysis_runner = StreamAnalysisRunner()
