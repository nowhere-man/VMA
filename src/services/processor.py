"""
后台任务处理器

处理视频质量指标计算任务
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models import Job, JobMode, JobStatus, MetricsResult

logger = logging.getLogger(__name__)


class TaskProcessor:
    """后台任务处理器"""

    def __init__(self) -> None:
        """初始化任务处理器"""
        self.processing = False
        self.current_job: Optional[str] = None

    async def process_job(self, job_id: str) -> None:
        """
        处理单个任务

        Args:
            job_id: 任务 ID
        """
        # Import here to avoid circular dependency
        from .ffmpeg import ffmpeg_service
        from .storage import job_storage

        job = job_storage.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        try:
            # 更新状态为处理中
            job.metadata.status = JobStatus.PROCESSING
            job.metadata.updated_at = datetime.utcnow()
            job_storage.update_job(job)

            logger.info(f"Processing job {job_id} (mode: {job.metadata.mode})")

            # 根据模式处理
            if job.metadata.mode == JobMode.SINGLE_FILE:
                await self._process_single_file(job)
            elif job.metadata.mode == JobMode.DUAL_FILE:
                await self._process_dual_file(job)

            # 更新状态为已完成
            job.metadata.status = JobStatus.COMPLETED
            job.metadata.completed_at = datetime.utcnow()
            job.metadata.updated_at = datetime.utcnow()
            job_storage.update_job(job)

            logger.info(f"Job {job_id} completed successfully")

        except Exception as e:
            # 更新状态为失败
            job.metadata.status = JobStatus.FAILED
            job.metadata.error_message = str(e)
            job.metadata.updated_at = datetime.utcnow()
            job_storage.update_job(job)

            logger.error(f"Job {job_id} failed: {str(e)}")

    async def _process_single_file(self, job: Job) -> None:
        """
        处理单文件模式任务

        Args:
            job: 任务对象
        """
        from .ffmpeg import ffmpeg_service
        from .storage import job_storage

        # 获取原始视频路径
        reference_path = job.get_reference_path()
        if not reference_path or not reference_path.exists():
            raise FileNotFoundError(f"Reference video not found: {reference_path}")

        # 生成编码后的视频路径
        distorted_path = job.job_dir / "encoded_output.mp4"

        # 使用预设编码视频
        preset = job.metadata.preset or "medium"
        logger.info(f"Encoding video with preset: {preset}")

        await ffmpeg_service.encode_video(
            input_path=reference_path,
            output_path=distorted_path,
            preset=preset,
            crf=23,
        )

        # 更新待测视频信息
        video_info = await self._get_video_info(distorted_path)
        from src.models import VideoInfo

        job.metadata.distorted_video = VideoInfo(
            filename=distorted_path.name,
            size_bytes=distorted_path.stat().st_size,
            **video_info,
        )

        # 计算质量指标
        await self._calculate_metrics(job, reference_path, distorted_path)

    async def _process_dual_file(self, job: Job) -> None:
        """
        处理双文件模式任务

        Args:
            job: 任务对象
        """
        # 获取参考视频和待测视频路径
        reference_path = job.get_reference_path()
        distorted_path = job.get_distorted_path()

        if not reference_path or not reference_path.exists():
            raise FileNotFoundError(f"Reference video not found: {reference_path}")

        if not distorted_path or not distorted_path.exists():
            raise FileNotFoundError(f"Distorted video not found: {distorted_path}")

        # 验证视频信息
        ref_info = await self._get_video_info(reference_path)
        dist_info = await self._get_video_info(distorted_path)

        # 检查分辨率是否匹配
        if (
            ref_info["width"] != dist_info["width"]
            or ref_info["height"] != dist_info["height"]
        ):
            logger.warning(
                f"Resolution mismatch: reference {ref_info['width']}x{ref_info['height']} vs "
                f"distorted {dist_info['width']}x{dist_info['height']}"
            )

        # 计算质量指标
        await self._calculate_metrics(job, reference_path, distorted_path)

    async def _calculate_metrics(
        self, job: Job, reference_path: Path, distorted_path: Path
    ) -> None:
        """
        计算质量指标

        Args:
            job: 任务对象
            reference_path: 参考视频路径
            distorted_path: 待测视频路径
        """
        from .ffmpeg import ffmpeg_service
        from .storage import job_storage

        metrics = MetricsResult()

        # 定义输出文件路径
        psnr_log = job.job_dir / "psnr.log"
        ssim_log = job.job_dir / "ssim.log"
        vmaf_json = job.job_dir / "vmaf.json"

        try:
            # 并行计算 PSNR、SSIM、VMAF
            logger.info(f"Calculating metrics for job {job.job_id}")

            psnr_task = ffmpeg_service.calculate_psnr(
                reference_path, distorted_path, psnr_log
            )
            ssim_task = ffmpeg_service.calculate_ssim(
                reference_path, distorted_path, ssim_log
            )
            vmaf_task = ffmpeg_service.calculate_vmaf(
                reference_path, distorted_path, vmaf_json
            )

            # 等待所有指标计算完成
            psnr_result, ssim_result, vmaf_result = await asyncio.gather(
                psnr_task, ssim_task, vmaf_task, return_exceptions=True
            )

            # 处理 PSNR 结果
            if isinstance(psnr_result, dict):
                metrics.psnr_avg = psnr_result.get("psnr_avg")
                metrics.psnr_y = psnr_result.get("psnr_y")
                metrics.psnr_u = psnr_result.get("psnr_u")
                metrics.psnr_v = psnr_result.get("psnr_v")
            else:
                logger.error(f"PSNR calculation failed: {psnr_result}")

            # 处理 SSIM 结果
            if isinstance(ssim_result, dict):
                metrics.ssim_avg = ssim_result.get("ssim_avg")
                metrics.ssim_y = ssim_result.get("ssim_y")
                metrics.ssim_u = ssim_result.get("ssim_u")
                metrics.ssim_v = ssim_result.get("ssim_v")
            else:
                logger.error(f"SSIM calculation failed: {ssim_result}")

            # 处理 VMAF 结果
            if isinstance(vmaf_result, dict):
                metrics.vmaf_mean = vmaf_result.get("vmaf_mean")
                metrics.vmaf_harmonic_mean = vmaf_result.get("vmaf_harmonic_mean")
            else:
                logger.error(f"VMAF calculation failed: {vmaf_result}")

            # 保存指标到任务元数据
            job.metadata.metrics = metrics
            job_storage.update_job(job)

            logger.info(f"Metrics calculated successfully for job {job.job_id}")

        except Exception as e:
            logger.error(f"Failed to calculate metrics: {str(e)}")
            raise

    async def _get_video_info(self, video_path: Path) -> dict:
        """获取视频信息"""
        from .ffmpeg import ffmpeg_service

        return await ffmpeg_service.get_video_info(video_path)

    async def start_background_processor(self) -> None:
        """启动后台处理器（轮询待处理任务）"""
        from .storage import job_storage

        self.processing = True
        logger.info("Background task processor started")

        while self.processing:
            try:
                # 查找待处理的任务
                pending_jobs = job_storage.list_jobs(status=JobStatus.PENDING, limit=1)

                if pending_jobs:
                    job = pending_jobs[0]
                    self.current_job = job.job_id
                    await self.process_job(job.job_id)
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
        logger.info("Background task processor stopped")


# 全局单例
task_processor = TaskProcessor()
