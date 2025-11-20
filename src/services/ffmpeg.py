"""
FFmpeg 服务

提供视频处理和质量指标计算功能
"""
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

    async def get_video_info(self, video_path: Path) -> Dict[str, any]:
        """
        获取视频文件信息

        Args:
            video_path: 视频文件路径

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
            str(video_path),
        ]

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
            }

        except Exception as e:
            raise RuntimeError(f"Failed to get video info: {str(e)}")

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
            vmaf_filter = f"libvmaf=log_path={output_json}:log_fmt=json"

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
        """解析 VMAF JSON 文件"""
        try:
            with open(json_path, "r") as f:
                data = json.load(f)

            # VMAF JSON 结构: {"pooled_metrics": {"vmaf": {"mean": 95.5, "harmonic_mean": 94.2}}}
            pooled = data.get("pooled_metrics", {}).get("vmaf", {})

            return {
                "vmaf_mean": float(pooled.get("mean", 0.0)),
                "vmaf_harmonic_mean": float(pooled.get("harmonic_mean", 0.0)),
            }

        except Exception as e:
            raise RuntimeError(f"Failed to parse VMAF JSON: {str(e)}")


# Helper function for subprocess with timeout
async def _wait_for_process(
    process: asyncio.subprocess.Process, timeout: int
) -> Tuple[bytes, bytes]:
    """等待子进程完成，带超时"""
    return await asyncio.wait_for(process.communicate(), timeout=timeout)


# 全局单例
ffmpeg_service = FFmpegService()
