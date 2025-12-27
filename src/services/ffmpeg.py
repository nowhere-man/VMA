"""
FFmpeg 服务

提供视频处理和质量指标计算功能
"""
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.config import settings
from src.utils.metrics import parse_psnr_summary, parse_ssim_summary, parse_vmaf_summary


async def _wait_for_process(process, timeout: int) -> Tuple[bytes, bytes]:
    """等待进程完成，带超时"""
    return await asyncio.wait_for(process.communicate(), timeout=timeout)


async def _run_metric_cmd(
    cmd: List[str],
    metric_name: str,
    parse_func: Callable,
    output_path: Path,
    add_command_callback,
    update_status_callback,
    command_type: str,
    source_file: str,
) -> Dict[str, Any]:
    """
    执行指标计算命令的公共逻辑

    Args:
        cmd: 完整的命令列表
        metric_name: 指标名称（用于错误消息）
        parse_func: 解析结果的函数
        output_path: 输出文件路径
        add_command_callback: 添加命令回调
        update_status_callback: 更新状态回调
        command_type: 命令类型
        source_file: 源文件路径

    Returns:
        解析后的指标结果
    """
    cmd_id = None
    if add_command_callback:
        cmd_id = add_command_callback(command_type, " ".join(cmd), source_file)
    if update_status_callback and cmd_id:
        update_status_callback(cmd_id, "running")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await _wait_for_process(process, settings.ffmpeg_timeout)

        if process.returncode != 0:
            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "failed", stderr.decode())
            raise RuntimeError(f"{metric_name} calculation failed: {stderr.decode()}")

        result = parse_func(output_path)
        if update_status_callback and cmd_id:
            update_status_callback(cmd_id, "completed")
        return result

    except asyncio.TimeoutError:
        process.kill()
        if update_status_callback and cmd_id:
            update_status_callback(cmd_id, "failed", f"{metric_name} calculation timed out")
        raise RuntimeError(f"{metric_name} calculation timed out")
    except Exception as e:
        if update_status_callback and cmd_id:
            update_status_callback(cmd_id, "failed", str(e))
        raise RuntimeError(f"Failed to calculate {metric_name}: {str(e)}")


class FFmpegService:
    """FFmpeg 视频处理服务"""

    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        """
        初始化 FFmpeg 服务

        Args:
            ffmpeg_path: ffmpeg 可执行文件路径
            ffprobe_path: ffprobe 可执行文件路径
        """
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def _build_metric_cmd(
        self,
        reference_path: Path,
        distorted_path: Path,
        filter_testr: str,
        ref_width: int = None,
        ref_height: int = None,
        ref_fps: float = None,
        ref_pix_fmt: str = "yuv420p",
    ) -> List[str]:
        """
        构建指标计算命令的公共部分

        Args:
            reference_path: 参考视频路径
            distorted_path: 待测视频路径
            filter_testr: 滤镜表达式（如 "psnr=stats_file=xxx"）
            ref_width: 参考视频宽度（YUV格式必需）
            ref_height: 参考视频高度（YUV格式必需）
            ref_fps: 参考视频帧率（YUV格式必需）
            ref_pix_fmt: 参考视频像素格式

        Returns:
            命令列表
        """
        cmd = [self.ffmpeg_path]

        # 添加distorted视频输入
        cmd.extend(["-i", str(distorted_path)])

        # 如果是YUV格式，需要为reference视频指定参数
        if ref_width and ref_height:
            cmd.extend([
                "-f", "rawvideo",
                "-pix_fmt", ref_pix_fmt,
                "-s", f"{ref_width}x{ref_height}",
            ])
            if ref_fps:
                cmd.extend(["-r", str(ref_fps)])

        # 添加reference视频输入
        cmd.extend(["-i", str(reference_path)])

        # 添加滤镜和输出
        cmd.extend([
            "-lavfi",
            filter_testr,
            "-f",
            "null",
            "-",
        ])

        return cmd

    async def get_video_info(
        self, video_path: Path, input_format: Optional[str] = None
    ) -> Dict[str, any]:
        """
        获取视频文件信息

        Args:
            video_path: 视频文件路径
            input_format: 可选输入格式（如 h264/hevc/rawvideo 等）

        Returns:
            包含 duration, width, height, fps, bitrate 的字典
        """
        cmd = [
            self.ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
        ]
        if input_format:
            cmd.extend(["-f", input_format])
        cmd.append(str(video_path))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"ffprobe failed: {stderr.decode()}")

            info = json.loads(stdout.decode())

            # 查找视频流
            video_stream = None
            for stream in info.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            if not video_stream:
                raise ValueError("No video stream found")

            # 提取视频信息
            format_info = info.get("format", {})

            # 计算帧率
            fps = None
            if "r_frame_rate" in video_stream:
                num, den = map(int, video_stream["r_frame_rate"].split("/"))
                if den != 0:
                    fps = num / den

            return {
                "duration": float(format_info.get("duration", 0)),
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "fps": fps,
                "bitrate": int(format_info.get("bit_rate", 0)),
                "codec_name": video_stream.get("codec_name"),
                "nb_frames": (
                    int(video_stream.get("nb_frames"))
                    if str(video_stream.get("nb_frames", "")).isdigit()
                    else None
                ),
            }

        except Exception as e:
            raise RuntimeError(f"Failed to get video info: {str(e)}")

    async def decode_to_yuv420p(
        self,
        input_path: Path,
        output_path: Path,
        input_format: Optional[str] = None,
        input_width: Optional[int] = None,
        input_height: Optional[int] = None,
        input_fps: Optional[float] = None,
        input_pix_fmt: str = "yuv420p",
        scale_width: Optional[int] = None,
        scale_height: Optional[int] = None,
        add_command_callback=None,
        update_status_callback=None,
        command_type: str = "ffmpeg_decode",
        source_file: Optional[str] = None,
    ) -> None:
        """
        将输入视频解码为 yuv420p rawvideo。

        - 当 input_width/input_height 提供时，输入按 rawvideo 处理（通常用于 .yuv）。
        - 当 input_format 提供时，强制指定输入格式（通常用于裸码流 h264/hevc 等）。
        - 当 scale_width/scale_height 提供时，对输出进行缩放（用于与参考视频对齐分辨率）。
        - add_command_callback/update_status_callback 可选，用于在任务日志中记录 ffmpeg 命令
        """
        cmd: List[str] = [self.ffmpeg_path, "-y"]

        # 输入
        if input_width is not None and input_height is not None:
            cmd.extend(["-f", "rawvideo", "-pix_fmt", input_pix_fmt, "-s", f"{input_width}x{input_height}"])
            if input_fps is not None:
                cmd.extend(["-r", str(input_fps)])
            cmd.extend(["-i", str(input_path)])
        else:
            if input_format:
                cmd.extend(["-f", input_format])
            cmd.extend(["-i", str(input_path)])

        # 输出滤镜
        vf_parts: List[str] = []
        if scale_width is not None and scale_height is not None:
            vf_parts.append(f"scale={scale_width}:{scale_height}")
        vf_parts.append("format=yuv420p")

        cmd.extend(["-an", "-sn", "-vf", ",".join(vf_parts)])
        cmd.extend(["-f", "rawvideo", "-pix_fmt", "yuv420p", str(output_path)])

        cmd_id = None
        if add_command_callback:
            cmd_id = add_command_callback(
                command_type or "ffmpeg_decode",
                " ".join(cmd),
                source_file or str(input_path),
            )
        if update_status_callback and cmd_id:
            update_status_callback(cmd_id, "running")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await _wait_for_process(process, settings.ffmpeg_timeout)
            if process.returncode != 0:
                error_msg = stderr.decode()
                raise RuntimeError(f"Decode to yuv failed: {error_msg}")
            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "completed")
        except asyncio.TimeoutError:
            process.kill()
            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "failed", "Decode to yuv timed out")
            raise RuntimeError("Decode to yuv timed out")
        except Exception as e:
            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "failed", str(e))
            raise RuntimeError(f"Failed to decode to yuv: {str(e)}")

    async def probe_video_frames(
        self, video_path: Path, input_format: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        使用 ffprobe 提取每一帧的基础信息（帧类型、包大小、时间戳）。

        Returns:
            List[dict]: 每帧包含 index, pict_type, pkt_size, timestamp
        """
        cmd: List[str] = [
            self.ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=pict_type,pkt_size,best_effort_timestamp_time,pkt_pts_time",
        ]
        if input_format:
            cmd.extend(["-f", input_format])
        cmd.append(str(video_path))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await _wait_for_process(process, settings.ffmpeg_timeout)
            if process.returncode != 0:
                raise RuntimeError(f"ffprobe failed: {stderr.decode()}")

            payload = json.loads(stdout.decode())
            frames = payload.get("frames", []) or []
            results: List[Dict[str, Any]] = []

            for idx, frame in enumerate(frames):
                pkt_size = frame.get("pkt_size")
                try:
                    size_val = int(pkt_size) if pkt_size is not None else 0
                except (TypeError, ValueError):
                    size_val = 0

                ts_val = frame.get("best_effort_timestamp_time")
                if ts_val is None:
                    ts_val = frame.get("pkt_pts_time")

                timestamp: Optional[float]
                try:
                    timestamp = float(ts_val) if ts_val is not None else None
                except (TypeError, ValueError):
                    timestamp = None

                results.append(
                    {
                        "index": idx,
                        "pict_type": frame.get("pict_type") or None,
                        "pkt_size": size_val,
                        "timestamp": timestamp,
                    }
                )

            return results
        except Exception as e:
            raise RuntimeError(f"Failed to probe frames: {str(e)}")

    async def calculate_psnr(
        self,
        reference_path: Path,
        distorted_path: Path,
        output_log: Path,
        ref_width: int = None,
        ref_height: int = None,
        ref_fps: float = None,
        ref_pix_fmt: str = "yuv420p",
        add_command_callback=None,
        update_status_callback=None,
        command_type: str = "psnr",
        source_file: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        计算 PSNR 指标

        Args:
            reference_path: 参考视频路径
            distorted_path: 待测视频路径
            output_log: PSNR 日志输出路径
            ref_width: 参考视频宽度（YUV格式必需）
            ref_height: 参考视频高度（YUV格式必需）
            ref_fps: 参考视频帧率（YUV格式必需）
            ref_pix_fmt: 参考视频像素格式

        Returns:
            包含 psnr_avg, psnr_y, psnr_u, psnr_v 的字典
        """
        cmd = self._build_metric_cmd(
            reference_path, distorted_path,
            f"psnr=stats_file={output_log}",
            ref_width, ref_height, ref_fps, ref_pix_fmt,
        )
        return await _run_metric_cmd(
            cmd, "PSNR", parse_psnr_summary, output_log,
            add_command_callback, update_status_callback,
            command_type, source_file or str(distorted_path),
        )

    async def calculate_ssim(
        self,
        reference_path: Path,
        distorted_path: Path,
        output_log: Path,
        ref_width: int = None,
        ref_height: int = None,
        ref_fps: float = None,
        ref_pix_fmt: str = "yuv420p",
        add_command_callback=None,
        update_status_callback=None,
        command_type: str = "ssim",
        source_file: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        计算 SSIM 指标

        Args:
            reference_path: 参考视频路径
            distorted_path: 待测视频路径
            output_log: SSIM 日志输出路径
            ref_width: 参考视频宽度（YUV格式必需）
            ref_height: 参考视频高度（YUV格式必需）
            ref_fps: 参考视频帧率（YUV格式必需）
            ref_pix_fmt: 参考视频像素格式

        Returns:
            包含 ssim_avg, ssim_y, ssim_u, ssim_v 的字典
        """
        cmd = self._build_metric_cmd(
            reference_path, distorted_path,
            f"ssim=stats_file={output_log}",
            ref_width, ref_height, ref_fps, ref_pix_fmt,
        )
        return await _run_metric_cmd(
            cmd, "SSIM", parse_ssim_summary, output_log,
            add_command_callback, update_status_callback,
            command_type, source_file or str(distorted_path),
        )

    async def calculate_vmaf(
        self,
        reference_path: Path,
        distorted_path: Path,
        output_json: Path,
        model_path: Optional[Path] = None,
        ref_width: int = None,
        ref_height: int = None,
        ref_fps: float = None,
        ref_pix_fmt: str = "yuv420p",
        add_command_callback=None,
        update_status_callback=None,
        command_type: str = "vmaf",
        source_file: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        计算 VMAF 指标

        Args:
            reference_path: 参考视频路径
            distorted_path: 待测视频路径
            output_json: VMAF JSON 输出路径
            model_path: VMAF 模型文件路径（可选，不提供则使用FFmpeg内置模型）
            ref_width: 参考视频宽度（YUV格式必需）
            ref_height: 参考视频高度（YUV格式必需）
            ref_fps: 参考视频帧率（YUV格式必需）
            ref_pix_fmt: 参考视频像素格式

        Returns:
            包含 vmaf_mean, vmaf_harmonic_mean 的字典
        """
        # 构建VMAF滤镜参数
        if model_path and model_path.exists():
            vmaf_filter = f"libvmaf=model_path={model_path}:log_path={output_json}:log_fmt=json"
        else:
            vmaf_filter = f"libvmaf=log_path={output_json}:log_fmt=csv"

        cmd = self._build_metric_cmd(
            reference_path, distorted_path,
            vmaf_filter,
            ref_width, ref_height, ref_fps, ref_pix_fmt,
        )
        return await _run_metric_cmd(
            cmd, "VMAF", parse_vmaf_summary, output_json,
            add_command_callback, update_status_callback,
            command_type, source_file or str(distorted_path),
        )

    async def encode_video(
        self,
        input_path: Path,
        output_path: Path,
        preset: str = "medium",
        crf: int = 23,
        add_command_callback=None,
        update_status_callback=None,
        command_type: str = "encode",
        source_file: Optional[str] = None,
    ) -> None:
        """
        使用固定预设编码视频（单文件模式）

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            preset: 编码预设
            crf: CRF 值
        """
        cmd = [
            self.ffmpeg_path,
            "-i",
            str(input_path),
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-c:a",
            "copy",
            str(output_path),
        ]

        cmd_id = None
        if add_command_callback:
            cmd_id = add_command_callback(command_type, " ".join(cmd), source_file or str(input_path))
        if update_status_callback and cmd_id:
            update_status_callback(cmd_id, "running")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await _wait_for_process(process, settings.ffmpeg_timeout)

            if process.returncode != 0:
                if update_status_callback and cmd_id:
                    update_status_callback(cmd_id, "failed", stderr.decode())
                raise RuntimeError(f"Encoding failed: {stderr.decode()}")

            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "completed")

        except asyncio.TimeoutError:
            process.kill()
            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "failed", "Encoding timed out")
            raise RuntimeError("Encoding timed out")
        except Exception as e:
            if update_status_callback and cmd_id:
                update_status_callback(cmd_id, "failed", str(e))
            raise RuntimeError(f"Failed to encode video: {str(e)}")


# 全局单例
ffmpeg_service = FFmpegService(
    ffmpeg_path=settings.get_ffmpeg_bin(),
    ffprobe_path=settings.get_ffprobe_bin(),
)
