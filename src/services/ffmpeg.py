"""
FFmpeg 服务

提供视频处理和质量指标计算功能
"""
import asyncio
import csv
import json
import subprocess
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import settings


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

        cmd.extend([
            "-lavfi",
            f"psnr=stats_file={output_log}",
            "-f",
            "null",
            "-",
        ])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await _wait_for_process(process, settings.ffmpeg_timeout)

            if process.returncode != 0:
                raise RuntimeError(f"PSNR calculation failed: {stderr.decode()}")

            # 解析 PSNR 日志
            return await self._parse_psnr_log(output_log)

        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError("PSNR calculation timed out")
        except Exception as e:
            raise RuntimeError(f"Failed to calculate PSNR: {str(e)}")

    async def calculate_ssim(
        self,
        reference_path: Path,
        distorted_path: Path,
        output_log: Path,
        ref_width: int = None,
        ref_height: int = None,
        ref_fps: float = None,
        ref_pix_fmt: str = "yuv420p",
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

        cmd.extend([
            "-lavfi",
            f"ssim=stats_file={output_log}",
            "-f",
            "null",
            "-",
        ])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await _wait_for_process(process, settings.ffmpeg_timeout)

            if process.returncode != 0:
                raise RuntimeError(f"SSIM calculation failed: {stderr.decode()}")

            # 解析 SSIM 日志
            return await self._parse_ssim_log(output_log)

        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError("SSIM calculation timed out")
        except Exception as e:
            raise RuntimeError(f"Failed to calculate SSIM: {str(e)}")

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

        # 构建VMAF滤镜参数
        # 如果提供了model_path且存在，使用指定的模型文件
        # 否则使用FFmpeg内置模型
        if model_path and model_path.exists():
            vmaf_filter = f"libvmaf=model_path={model_path}:log_path={output_json}:log_fmt=json"
        else:
            # 使用FFmpeg内置模型
            vmaf_filter = f"libvmaf=log_path={output_json}:log_fmt=csv"

        cmd.extend([
            "-lavfi",
            vmaf_filter,
            "-f",
            "null",
            "-",
        ])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await _wait_for_process(process, settings.ffmpeg_timeout)

            if process.returncode != 0:
                raise RuntimeError(f"VMAF calculation failed: {stderr.decode()}")

            # 解析 VMAF JSON
            return await self._parse_vmaf_json(output_json)

        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError("VMAF calculation timed out")
        except Exception as e:
            raise RuntimeError(f"Failed to calculate VMAF: {str(e)}")

    async def encode_video(
        self,
        input_path: Path,
        output_path: Path,
        preset: str = "medium",
        crf: int = 23,
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

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await _wait_for_process(process, settings.ffmpeg_timeout)

            if process.returncode != 0:
                raise RuntimeError(f"Encoding failed: {stderr.decode()}")

        except asyncio.TimeoutError:
            process.kill()
            raise RuntimeError("Encoding timed out")
        except Exception as e:
            raise RuntimeError(f"Failed to encode video: {str(e)}")

    async def _parse_psnr_log(self, log_path: Path) -> Dict[str, float]:
        """解析 PSNR 日志文件"""
        # PSNR 日志格式: n:1 mse_avg:0.52 mse_y:0.48 mse_u:0.58 mse_v:0.52 psnr_avg:50.99 psnr_y:51.31 psnr_u:50.48 psnr_v:50.97
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()

            # 计算平均值
            psnr_y_sum, psnr_u_sum, psnr_v_sum, psnr_avg_sum = 0.0, 0.0, 0.0, 0.0
            count = 0

            for line in lines:
                if "psnr_avg" in line:
                    parts = line.strip().split()
                    for part in parts:
                        if part.startswith("psnr_avg:"):
                            psnr_avg_sum += float(part.split(":")[1])
                        elif part.startswith("psnr_y:"):
                            psnr_y_sum += float(part.split(":")[1])
                        elif part.startswith("psnr_u:"):
                            psnr_u_sum += float(part.split(":")[1])
                        elif part.startswith("psnr_v:"):
                            psnr_v_sum += float(part.split(":")[1])
                    count += 1

            if count == 0:
                raise ValueError("No PSNR data found in log")

            return {
                "psnr_avg": psnr_avg_sum / count,
                "psnr_y": psnr_y_sum / count,
                "psnr_u": psnr_u_sum / count,
                "psnr_v": psnr_v_sum / count,
            }

        except Exception as e:
            raise RuntimeError(f"Failed to parse PSNR log: {str(e)}")

    async def _parse_ssim_log(self, log_path: Path) -> Dict[str, float]:
        """解析 SSIM 日志文件"""
        # SSIM 日志格式类似 PSNR
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()

            ssim_y_sum, ssim_u_sum, ssim_v_sum, ssim_avg_sum = 0.0, 0.0, 0.0, 0.0
            count = 0

            for line in lines:
                if "All:" in line:
                    parts = line.strip().split()
                    for part in parts:
                        if part.startswith("All:"):
                            ssim_avg_sum += float(part.split(":")[1])
                        elif part.startswith("Y:"):
                            ssim_y_sum += float(part.split(":")[1])
                        elif part.startswith("U:"):
                            ssim_u_sum += float(part.split(":")[1])
                        elif part.startswith("V:"):
                            ssim_v_sum += float(part.split(":")[1])
                    count += 1

            if count == 0:
                raise ValueError("No SSIM data found in log")

            return {
                "ssim_avg": ssim_avg_sum / count,
                "ssim_y": ssim_y_sum / count,
                "ssim_u": ssim_u_sum / count,
                "ssim_v": ssim_v_sum / count,
            }

        except Exception as e:
            raise RuntimeError(f"Failed to parse SSIM log: {str(e)}")

    async def _parse_vmaf_json(self, json_path: Path) -> Dict[str, float]:
        """解析 VMAF 日志文件（支持 json 或 csv 日志格式）"""

        def _safe_float(val: Any) -> Optional[float]:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        def _mean(values: List[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        def _harmonic_mean(values: List[float]) -> float:
            positives = [v for v in values if v and v > 0]
            return len(positives) / sum(1.0 / v for v in positives) if positives else 0.0

        def _parse_csv(text: str) -> Dict[str, float]:
            reader = csv.DictReader(StringIO(text))
            vmaf_vals: List[float] = []
            vmaf_neg_vals: List[float] = []
            for row in reader:
                vmaf_val = _safe_float(row.get("vmaf"))
                if vmaf_val is not None:
                    vmaf_vals.append(vmaf_val)
                vmaf_neg_val = _safe_float(row.get("vmaf_neg"))
                if vmaf_neg_val is not None:
                    vmaf_neg_vals.append(vmaf_neg_val)

            return {
                "vmaf_mean": _mean(vmaf_vals),
                "vmaf_harmonic_mean": _harmonic_mean(vmaf_vals),
                "vmaf_neg_mean": _mean(vmaf_neg_vals),
            }

        try:
            text = json_path.read_text()
            stripped = text.lstrip()
            if stripped.startswith("{"):
                data = json.loads(text)
                pooled = data.get("pooled_metrics", {}).get("vmaf", {}) or {}
                vmaf_neg_pooled = data.get("pooled_metrics", {}).get("vmaf_neg", {}) or {}
                return {
                    "vmaf_mean": float(pooled.get("mean", 0.0)),
                    "vmaf_harmonic_mean": float(pooled.get("harmonic_mean", 0.0)),
                    "vmaf_neg_mean": float(vmaf_neg_pooled.get("mean", 0.0)),
                }

            # CSV 日志
            return _parse_csv(text)

        except Exception as e:
            raise RuntimeError(f"Failed to parse VMAF log: {str(e)}")


# Helper function for subprocess with timeout
async def _wait_for_process(
    process: asyncio.subprocess.Process, timeout: int
) -> Tuple[bytes, bytes]:
    """等待子进程完成，带超时"""
    return await asyncio.wait_for(process.communicate(), timeout=timeout)


# 全局单例
ffmpeg_service = FFmpegService()
