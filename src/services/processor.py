"""
后台任务处理器

处理视频质量指标计算任务
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nanoid import generate

from src.models import Job, JobMode, JobStatus, MetricsResult

logger = logging.getLogger(__name__)


def _now_tz():
    return datetime.now().astimezone()


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


class TaskProcessor:
    """后台任务处理器"""

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
        # Import here to avoid circular dependency
        from .ffmpeg import ffmpeg_service
        from .storage import job_storage

        job = job_storage.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        # 仅处理该处理器支持的模式（模板/对比任务由其他后台机制处理）
        if job.metadata.mode not in self.supported_modes:
            logger.info(f"Skipping job {job_id} (unsupported mode: {job.metadata.mode})")
            return

        try:
            # 更新状态为处理中
            job.metadata.status = JobStatus.PROCESSING
            job.metadata.updated_at = _now_tz()
            job_storage.update_job(job)

            logger.info(f"Processing job {job_id} (mode: {job.metadata.mode})")

            # 根据模式处理
            if job.metadata.mode == JobMode.BITSTREAM_ANALYSIS:
                await self._process_bitstream_analysis(job)

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

    async def _process_bitstream_analysis(self, job: Job) -> None:
        """
        处理码流分析任务（Ref + 多个 Encoded）
        """
        from .storage import job_storage
        from .bitstream_analysis import analyze_bitstream_job

        add_command_log, update_command_status = _make_command_callbacks(job, job_storage)

        report_data, summary = await analyze_bitstream_job(
            job,
            add_command_callback=add_command_log,
            update_status_callback=update_command_status,
        )

        # 写入报告数据文件（供 Streamlit 使用）
        report_rel_path = summary.get("report_data_file")
        if not report_rel_path:
            raise RuntimeError("Bitstream analysis missing report_data_file")

        report_path = job.job_dir / report_rel_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        job.metadata.execution_result = summary
        job_storage.update_job(job)

    async def _calculate_metrics(
        self,
        job: Job,
        reference_path: Path,
        distorted_path: Path,
        add_command_callback=None,
        update_status_callback=None,
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
                reference_path,
                distorted_path,
                psnr_log,
                add_command_callback=add_command_callback,
                update_status_callback=update_status_callback,
                command_type="psnr",
                source_file=str(distorted_path),
            )
            ssim_task = ffmpeg_service.calculate_ssim(
                reference_path,
                distorted_path,
                ssim_log,
                add_command_callback=add_command_callback,
                update_status_callback=update_status_callback,
                command_type="ssim",
                source_file=str(distorted_path),
            )
            vmaf_task = ffmpeg_service.calculate_vmaf(
                reference_path,
                distorted_path,
                vmaf_json,
                add_command_callback=add_command_callback,
                update_status_callback=update_status_callback,
                command_type="vmaf",
                source_file=str(distorted_path),
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
        logger.info("Background task processor stopped")


# 全局单例
task_processor = TaskProcessor()
