"""
基于模板的转码服务

使用转码模板执行视频编码任务
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

import psutil

from src.models_template import EncodingTemplate, EncoderType, SequenceType, OutputType, SourcePathType

logger = logging.getLogger(__name__)


class TemplateEncoderService:
    """基于模板的转码服务"""

    def __init__(self):
        """初始化转码服务"""
        self.encoder_paths = {
            EncoderType.FFMPEG: "ffmpeg",
            EncoderType.X264: "x264",
            EncoderType.X265: "x265",
            EncoderType.VVENC: "vvenc",
        }

    async def encode_with_template(
        self, template: EncodingTemplate, source_files: Optional[List[Path]] = None,
        add_command_callback=None, update_status_callback=None
    ) -> dict:
        """
        使用模板执行转码任务

        Args:
            template: 转码模板
            source_files: 可选的源文件列表，如果不提供则使用模板中的 source_path
            add_command_callback: 添加命令日志的回调函数
            update_status_callback: 更新命令状态的回调函数

        Returns:
            包含执行结果信息的字典
        """
        # 获取源文件列表
        if source_files is None:
            source_files = self.resolve_source_files(template)

        if not source_files:
            raise ValueError(f"未找到源文件: {template.metadata.source_path}")

        logger.info(
            f"使用模板 {template.name} 转码 {len(source_files)} 个文件"
        )

        # 准备报告目录（如果需要计算质量指标）
        if not template.metadata.skip_metrics:
            metrics_dir = Path(template.metadata.metrics_report_dir)
            metrics_dir.mkdir(parents=True, exist_ok=True)

        # 准备输出目录
        output_dir = Path(template.metadata.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 执行转码任务
        results = []
        failed = []

        # 串行执行（简化处理，如需并行可后续扩展）
        for source_file in source_files:
            try:
                result = await self._encode_single_file(
                    template, source_file,
                    add_command_callback, update_status_callback
                )
                results.append(result)
            except Exception as e:
                logger.error(f"转码失败 {source_file}: {str(e)}")
                failed.append({"file": str(source_file), "error": str(e)})

        # 计算统计信息
        def _mean(values: List[Optional[float]]) -> Optional[float]:
            valid = [v for v in values if isinstance(v, (int, float))]
            if not valid:
                return None
            return sum(valid) / len(valid)

        average_speed = _mean([res.get("average_fps") for res in results])
        average_cpu = _mean([res.get("cpu_percent") for res in results])
        average_bitrate = _mean(
            [
                (res.get("output_info") or {}).get("bitrate")
                for res in results
            ]
        )

        return {
            "template_id": template.template_id,
            "template_name": template.name,
            "total_files": len(source_files),
            "successful": len(results),
            "failed": len(failed),
            "results": results,
            "errors": failed,
            "average_speed_fps": average_speed,
            "average_cpu_percent": average_cpu,
            "average_bitrate": average_bitrate,
        }

    async def _encode_single_file(
        self, template: EncodingTemplate, source_file: Path,
        add_command_callback=None, update_status_callback=None
    ) -> dict:
        """
        转码单个文件

        Args:
            template: 转码模板
            source_file: 源文件路径
            add_command_callback: 添加命令日志的回调函数
            update_status_callback: 更新命令状态的回调函数

        Returns:
            包含转码结果的字典
        """
        # 构建输出文件路径和扩展名
        output_dir = Path(template.metadata.output_dir)

        # 根据输出类型确定扩展名
        if template.metadata.output_type == OutputType.SAME_AS_SOURCE:
            # 同源视频类型
            output_extension = source_file.suffix.lstrip('.')
        else:
            # Raw Stream 类型，根据编码器类型确定扩展名
            if template.metadata.encoder_type == EncoderType.X264:
                output_extension = "h264"
            elif template.metadata.encoder_type == EncoderType.X265:
                output_extension = "h265"
            elif template.metadata.encoder_type == EncoderType.VVENC:
                output_extension = "h266"
            elif template.metadata.encoder_type == EncoderType.FFMPEG:
                # FFmpeg 默认使用 h264
                output_extension = "h264"
            else:
                output_extension = "bin"

        output_file = output_dir / f"{source_file.stem}_encode.{output_extension}"

        # 获取编码器命令
        encoder_cmd = self._build_encoder_command(
            template, source_file, output_file
        )

        logger.info(f"转码: {source_file} -> {output_file}")
        logger.debug(f"命令: {' '.join(encoder_cmd)}")

        # 记录编码命令
        encode_cmd_id = None
        if add_command_callback:
            encode_cmd_id = add_command_callback(
                "encode", " ".join(encoder_cmd), str(source_file)
            )

        start_time = time.perf_counter()
        cpu_time_seconds = None
        cpu_percent = None
        process_handle = None

        # 更新命令状态为运行中
        if update_status_callback and encode_cmd_id:
            update_status_callback(encode_cmd_id, "running")

        # 执行转码
        process = await asyncio.create_subprocess_exec(
            *encoder_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            process_handle = psutil.Process(process.pid)
        except (psutil.NoSuchProcess, psutil.Error):
            process_handle = None

        stdout, stderr = await process.communicate()

        elapsed = time.perf_counter() - start_time

        if process_handle:
            try:
                cpu_times = process_handle.cpu_times()
                cpu_time_seconds = (cpu_times.user or 0.0) + (cpu_times.system or 0.0)
                cpu_denominator = elapsed * max(1, psutil.cpu_count() or os.cpu_count() or 1)
                if cpu_denominator > 0:
                    cpu_percent = min(100.0, (cpu_time_seconds / cpu_denominator) * 100.0)
            except (psutil.NoSuchProcess, psutil.Error):
                cpu_time_seconds = None
                cpu_percent = None

        if process.returncode != 0:
            error_msg = stderr.decode()
            if update_status_callback and encode_cmd_id:
                update_status_callback(encode_cmd_id, "failed", error_msg)
            raise RuntimeError(f"转码失败: {error_msg}")

        # 更新编码命令状态为完成
        if update_status_callback and encode_cmd_id:
            update_status_callback(encode_cmd_id, "completed")

        from .ffmpeg import ffmpeg_service

        output_info = None
        average_fps = None
        try:
            output_info = await ffmpeg_service.get_video_info(output_file)
            if output_info:
                duration = output_info.get("duration") or 0.0
                fps = output_info.get("fps") or 0.0
                if duration > 0 and fps > 0 and elapsed > 0:
                    total_frames = fps * duration
                    average_fps = total_frames / elapsed
        except Exception as exc:
            logger.warning(f"读取输出视频信息失败: {exc}")
            output_info = None

        result = {
            "source_file": str(source_file),
            "output_file": str(output_file),
            "encoder_type": template.metadata.encoder_type,
            "elapsed_seconds": elapsed,
            "cpu_time_seconds": cpu_time_seconds,
            "cpu_percent": cpu_percent,
            "average_fps": average_fps,
            "output_info": output_info,
        }

        # 如果不跳过质量指标计算
        if not template.metadata.skip_metrics:
            metrics = await self._calculate_metrics(
                template, source_file, output_file,
                add_command_callback, update_status_callback
            )
            result["metrics"] = metrics

        try:
            result["output_size_bytes"] = output_file.stat().st_size
        except OSError:
            result["output_size_bytes"] = None

        return result

    def _build_encoder_command(
        self, template: EncodingTemplate, source_file: Path, output_file: Path
    ) -> List[str]:
        """
        构建编码器命令

        Args:
            template: 转码模板
            source_file: 源文件路径
            output_file: 输出文件路径

        Returns:
            编码器命令列表
        """
        encoder_type = template.metadata.encoder_type
        encoder_path = template.metadata.encoder_path or self.encoder_paths.get(encoder_type)

        if not encoder_path:
            raise ValueError(f"未配置编码器可执行文件，且无法推断 {encoder_type} 的默认路径")

        if encoder_type == EncoderType.FFMPEG:
            # FFmpeg 命令格式
            cmd = [encoder_path]

            # 如果是 YUV 输入，需要指定像素格式、分辨率和帧率
            if template.metadata.sequence_type == SequenceType.YUV420P:
                cmd.extend([
                    "-f", "rawvideo",
                    "-pix_fmt", "yuv420p",
                    "-s", f"{template.metadata.width}x{template.metadata.height}",
                    "-r", str(template.metadata.fps),
                ])

            cmd.extend(["-i", str(source_file)])

            # 添加用户自定义参数
            if template.metadata.encoder_params:
                cmd.extend(template.metadata.encoder_params.split())

            # 自动覆盖输出文件
            cmd.extend(["-y", str(output_file)])

        elif encoder_type in [EncoderType.X264, EncoderType.X265]:
            # x264/x265 命令格式
            cmd = [encoder_path]

            # 如果是 YUV 输入，需要指定输入格式
            if template.metadata.sequence_type == SequenceType.YUV420P:
                cmd.extend([
                    "--input-res", f"{template.metadata.width}x{template.metadata.height}",
                    "--fps", str(template.metadata.fps),
                ])

            # 添加用户参数
            if template.metadata.encoder_params:
                cmd.extend(template.metadata.encoder_params.split())

            cmd.extend(["-o", str(output_file), str(source_file)])

        elif encoder_type == EncoderType.VVENC:
            # vvenc 命令格式
            cmd = [encoder_path, "-i", str(source_file)]

            # 如果是 YUV 输入，需要指定分辨率和帧率
            if template.metadata.sequence_type == SequenceType.YUV420P:
                cmd.extend([
                    "--size", f"{template.metadata.width}x{template.metadata.height}",
                    "--framerate", str(template.metadata.fps),
                ])

            cmd.extend(["-o", str(output_file)])

            # 添加用户参数
            if template.metadata.encoder_params:
                cmd.extend(template.metadata.encoder_params.split())

        else:
            raise ValueError(f"不支持的编码器类型: {encoder_type}")

        return cmd

    async def _calculate_metrics(
        self, template: EncodingTemplate, reference: Path, distorted: Path,
        add_command_callback=None, update_status_callback=None
    ) -> dict:
        """
        计算质量指标

        Args:
            template: 转码模板
            reference: 参考视频
            distorted: 待测视频
            add_command_callback: 添加命令日志的回调函数
            update_status_callback: 更新命令状态的回调函数

        Returns:
            包含质量指标的字典
        """
        from .ffmpeg import ffmpeg_service

        metrics = {}
        metrics_dir = Path(template.metadata.metrics_report_dir)

        # 准备YUV参数（如果是YUV格式）
        yuv_params = {}
        yuv_cmd_params = ""
        if template.metadata.sequence_type == SequenceType.YUV420P:
            yuv_params = {
                "ref_width": template.metadata.width,
                "ref_height": template.metadata.height,
                "ref_fps": template.metadata.fps,
                "ref_pix_fmt": "yuv420p",
            }
            yuv_cmd_params = f"-f rawvideo -pix_fmt yuv420p -s {template.metadata.width}x{template.metadata.height} -r {template.metadata.fps}"

        try:
            # 根据配置计算不同的指标
            if "psnr" in template.metadata.metrics_types:
                psnr_log = metrics_dir / f"{distorted.stem}_psnr.log"

                # 构建命令用于记录
                psnr_cmd = f"ffmpeg -i {distorted} {yuv_cmd_params} -i {reference} -lavfi psnr=stats_file={psnr_log} -f null -"
                psnr_cmd_id = None
                if add_command_callback:
                    psnr_cmd_id = add_command_callback("psnr", psnr_cmd, str(reference))

                if update_status_callback and psnr_cmd_id:
                    update_status_callback(psnr_cmd_id, "running")

                try:
                    psnr_result = await ffmpeg_service.calculate_psnr(
                        reference, distorted, psnr_log, **yuv_params
                    )
                    metrics["psnr"] = psnr_result
                    if update_status_callback and psnr_cmd_id:
                        update_status_callback(psnr_cmd_id, "completed")
                except Exception as e:
                    if update_status_callback and psnr_cmd_id:
                        update_status_callback(psnr_cmd_id, "failed", str(e))
                    raise

            if "ssim" in template.metadata.metrics_types:
                ssim_log = metrics_dir / f"{distorted.stem}_ssim.log"

                # 构建命令用于记录
                ssim_cmd = f"ffmpeg -i {distorted} {yuv_cmd_params} -i {reference} -lavfi ssim=stats_file={ssim_log} -f null -"
                ssim_cmd_id = None
                if add_command_callback:
                    ssim_cmd_id = add_command_callback("ssim", ssim_cmd, str(reference))

                if update_status_callback and ssim_cmd_id:
                    update_status_callback(ssim_cmd_id, "running")

                try:
                    ssim_result = await ffmpeg_service.calculate_ssim(
                        reference, distorted, ssim_log, **yuv_params
                    )
                    metrics["ssim"] = ssim_result
                    if update_status_callback and ssim_cmd_id:
                        update_status_callback(ssim_cmd_id, "completed")
                except Exception as e:
                    if update_status_callback and ssim_cmd_id:
                        update_status_callback(ssim_cmd_id, "failed", str(e))
                    raise

            if "vmaf" in template.metadata.metrics_types:
                vmaf_json = metrics_dir / f"{distorted.stem}_vmaf.json"

                # 构建命令用于记录
                vmaf_cmd = f"ffmpeg -i {distorted} {yuv_cmd_params} -i {reference} -lavfi libvmaf=log_path={vmaf_json}:log_fmt=json -f null -"
                vmaf_cmd_id = None
                if add_command_callback:
                    vmaf_cmd_id = add_command_callback("vmaf", vmaf_cmd, str(reference))

                if update_status_callback and vmaf_cmd_id:
                    update_status_callback(vmaf_cmd_id, "running")

                try:
                    vmaf_result = await ffmpeg_service.calculate_vmaf(
                        reference, distorted, vmaf_json, **yuv_params
                    )
                    metrics["vmaf"] = vmaf_result
                    if update_status_callback and vmaf_cmd_id:
                        update_status_callback(vmaf_cmd_id, "completed")
                except Exception as e:
                    if update_status_callback and vmaf_cmd_id:
                        update_status_callback(vmaf_cmd_id, "failed", str(e))
                    raise

        except Exception as e:
            logger.error(f"计算指标失败: {str(e)}")
            metrics["error"] = str(e)

        return metrics

    def _resolve_source_files(self, source_path: str) -> List[Path]:
        """
        解析源文件路径
        
        支持三种模式：
        1. 单个文件路径: /path/to/video.mp4
        2. 多个文件路径（逗号分隔）: /path/to/video1.mp4,/path/to/video2.mp4
        3. 目录路径: /path/to/videos/

        Args:
            source_path: 源路径

        Returns:
            源文件列表
        """
        # 检查是否包含逗号（多个文件）
        if ',' in source_path:
            files = []
            for file_path in source_path.split(','):
                file_path = file_path.strip()
                if file_path:
                    path = Path(file_path)
                    if path.is_file():
                        files.append(path)
                    else:
                        logger.warning(f"文件不存在: {file_path}")
            return sorted(files)
        
        path = Path(source_path.strip())

        # 如果是文件
        if path.is_file():
            return [path]

        # 如果是目录
        if path.is_dir():
            # 查找所有视频文件
            video_extensions = [".mp4", ".mkv", ".avi", ".mov", ".flv", ".yuv"]
            files = []
            for ext in video_extensions:
                files.extend(path.glob(f"*{ext}"))
            return sorted(files)

        # 如果包含通配符
        if "*" in source_path or "?" in source_path:
            parent = Path(source_path).parent
            pattern = Path(source_path).name
            return sorted(parent.glob(pattern))

        return []

    def resolve_source_files(self, template: EncodingTemplate) -> List[Path]:
        """获取模板配置对应的源文件列表"""

        return self._resolve_source_files(template.metadata.source_path)


# 全局单例
template_encoder_service = TemplateEncoderService()
