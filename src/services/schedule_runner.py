"""
Schedule 执行服务

负责执行 Schedule，包括构建编码器、加载模板、创建任务
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from nanoid import generate

from src.config import settings
from src.models.job import JobMetadata, JobMode, JobStatus
from src.models.schedule import (
    ScheduleExecution,
    ScheduleMetadata,
    ScheduleRepeat,
    ScheduleStatus,
)
from src.models.template import EncoderType, EncodingTemplate, TemplateType
from src.services.builder import get_encoder_builder
from src.services.metrics_analysis_runner import metrics_analysis_runner
from src.services.metrics_comparison_runner import template_runner as metrics_comparison_runner
from src.services.storage import job_storage
from src.services.template_storage import template_storage
from src.services.schedule_storage import schedule_storage

logger = logging.getLogger(__name__)


class ScheduleRunner:
    """Schedule 执行器"""

    def __init__(self):
        """初始化执行器"""
        self.workspace_root = Path(settings.schedules_root_dir) / "workspace"

    async def execute(self, schedule: ScheduleMetadata) -> ScheduleExecution:
        """
        执行 Schedule

        Args:
            schedule: Schedule 元数据

        Returns:
            ScheduleExecution: 执行记录
        """
        execution_id = generate(size=12)
        start_time = datetime.utcnow()

        logger.info(f"Executing schedule: {schedule.schedule_id} (execution: {execution_id})")

        build_status = "skipped"
        build_log_path = None
        job_id = None
        error_message = None

        try:
            # 1. 构建编码器
            build_success, build_log, encoder_path = await self._build_encoder(
                schedule=schedule,
                execution_id=execution_id,
            )

            # 保存构建日志
            if build_log:
                log_filename = f"build_{execution_id}.log"
                schedule_storage.save_build_log(
                    schedule.schedule_id,
                    log_filename,
                    build_log,
                )
                build_log_path = f"logs/{log_filename}"

            if not build_success:
                build_status = "failed"
                error_message = "Encoder build failed"
                logger.error(f"Schedule {schedule.schedule_id} failed: {error_message}")
            else:
                build_status = "success"

                # 2. 加载模板并覆盖 encoder_path
                template = await self._load_template_with_encoder(
                    schedule=schedule,
                    encoder_path=encoder_path,
                )

                # 3. 创建任务
                job = await self._create_job(
                    schedule=schedule,
                    template=template,
                )

                job_id = job.job_id

                # 4. 执行任务
                await self._run_job(job, template)

                logger.info(f"Schedule {schedule.schedule_id} completed successfully")

        except Exception as e:
            error_message = str(e)
            logger.exception(f"Schedule {schedule.schedule_id} failed with exception")

        # 创建执行记录
        execution = ScheduleExecution(
            execution_id=execution_id,
            schedule_id=schedule.schedule_id,
            executed_at=start_time,
            job_id=job_id or "",
            build_status=build_status,
            build_log_path=build_log_path,
            error_message=error_message,
        )

        # 保存执行记录
        schedule_storage.add_execution(schedule.schedule_id, execution)

        # 更新 Schedule 状态
        schedule.last_execution = start_time
        schedule.last_execution_status = "success" if not error_message else "failed"
        schedule.last_execution_job_id = job_id

        # 计算下次执行时间
        if schedule.repeat != ScheduleRepeat.NONE and schedule.status == ScheduleStatus.ACTIVE:
            schedule.next_execution = self._calculate_next_execution(
                start_time,
                schedule.repeat,
            )
        else:
            schedule.next_execution = None

        schedule_storage.update_schedule(schedule.schedule_id, schedule)

        return execution

    async def _build_encoder(
        self,
        schedule: ScheduleMetadata,
        execution_id: str,
    ) -> tuple[bool, str, Optional[Path]]:
        """
        构建编码器

        Args:
            schedule: Schedule 元数据
            execution_id: 执行 ID

        Returns:
            Tuple[bool, str, Optional[Path]]: (是否成功, 日志, 二进制路径)
        """
        logger.info(f"Building encoder: {schedule.encoder_type}")

        builder = get_encoder_builder(self.workspace_root)

        success, log, encoder_path = await builder.build(
            config=schedule.encoder_config,
        )

        if success:
            logger.info(f"Encoder built successfully: {encoder_path}")
        else:
            logger.error(f"Encoder build failed")

        return success, log, encoder_path

    async def _load_template_with_encoder(
        self,
        schedule: ScheduleMetadata,
        encoder_path: Path,
    ) -> EncodingTemplate:
        """
        加载模板并覆盖 encoder_path

        Args:
            schedule: Schedule 元数据
            encoder_path: 编码器二进制路径

        Returns:
            EncodingTemplate: 更新后的模板对象
        """
        logger.info(f"Loading template: {schedule.template_id}")

        # 从存储加载模板
        template = template_storage.get_template(schedule.template_id)
        if not template:
            raise ValueError(f"Template not found: {schedule.template_id}")

        # 覆盖 encoder_path（由于 extra="ignore"，可以动态添加字段）
        # 更新 anchor 侧的 encoder_path
        if hasattr(template.metadata.anchor, "__dict__"):
            template.metadata.anchor.encoder_path = str(encoder_path)
        else:
            # Pydantic model，使用 model_copy 或直接设置
            template.metadata.anchor = template.metadata.anchor.model_copy(
                update={"encoder_path": str(encoder_path)}
            )

        # 如果是 comparison 模式，也需要更新 test 侧
        if template.metadata.test:
            if hasattr(template.metadata.test, "__dict__"):
                template.metadata.test.encoder_path = str(encoder_path)
            else:
                template.metadata.test = template.metadata.test.model_copy(
                    update={"encoder_path": str(encoder_path)}
                )

        # 验证模板类型
        expected_type = TemplateType(schedule.template_type)
        if template.metadata.template_type != expected_type:
            raise ValueError(
                f"Template type mismatch: expected {expected_type}, got {template.metadata.template_type}"
            )

        logger.info(f"Template loaded: {template.metadata.name}")
        logger.info(f"Encoder path set: {encoder_path}")

        return template

    async def _create_job(
        self,
        schedule: ScheduleMetadata,
        template: EncodingTemplate,
    ) -> object:
        """
        创建任务

        Args:
            schedule: Schedule 元数据
            template: 模板对象

        Returns:
            Job: 创建的任务对象
        """
        logger.info(f"Creating job for template: {schedule.template_id}")

        # 确定任务模式
        template_type = TemplateType(schedule.template_type)
        if template_type == TemplateType.METRICS_COMPARISON:
            job_mode = JobMode.METRICS_COMPARISON
        elif template_type == TemplateType.METRICS_ANALYSIS:
            job_mode = JobMode.METRICS_ANALYSIS
        else:
            raise ValueError(f"Unsupported template type: {template_type}")

        # 创建任务元数据
        metadata = JobMetadata(
            job_id=job_storage.generate_job_id(),
            status=JobStatus.PENDING,
            mode=job_mode,
            template_id=schedule.template_id,
            template_name=schedule.template_name,
        )

        # 创建任务
        job = job_storage.create_job(metadata)

        logger.info(f"Job created: {job.job_id}")

        return job

    async def _run_job(
        self,
        job: object,
        template: EncodingTemplate,
    ) -> None:
        """
        运行任务

        Args:
            job: 任务对象
            template: 模板对象
        """
        logger.info(f"Running job: {job.job_id}")

        # 更新任务状态
        job.metadata.status = JobStatus.PROCESSING
        job_storage.update_job(job)

        try:
            # 根据模板类型选择执行器
            template_type = template.metadata.template_type

            if template_type == TemplateType.METRICS_COMPARISON:
                logger.info("Running metrics comparison")
                result = await metrics_comparison_runner.execute(template, job=job)
            elif template_type == TemplateType.METRICS_ANALYSIS:
                logger.info("Running metrics analysis")
                result = await metrics_analysis_runner.execute(template, job=job)
            else:
                raise ValueError(f"Unsupported template type: {template_type}")

            # 更新任务状态
            job.metadata.status = JobStatus.COMPLETED
            job.metadata.execution_result = result
            job.metadata.completed_at = datetime.utcnow()
            job_storage.update_job(job)

            logger.info(f"Job completed: {job.job_id}")

        except Exception as e:
            error_message = str(e)
            logger.exception(f"Job failed: {job.job_id}")

            # 更新任务状态
            job.metadata.status = JobStatus.FAILED
            job.metadata.error_message = error_message
            job.metadata.completed_at = datetime.utcnow()
            job_storage.update_job(job)

            raise

    def _calculate_next_execution(
        self,
        base_time: datetime,
        repeat: ScheduleRepeat,
    ) -> Optional[datetime]:
        """
        计算下次执行时间

        Args:
            base_time: 基准时间
            repeat: 重复周期

        Returns:
            下次执行时间
        """
        from datetime import timedelta

        if repeat == ScheduleRepeat.DAILY:
            return base_time + timedelta(days=1)
        elif repeat == ScheduleRepeat.WEEKLY:
            return base_time + timedelta(weeks=1)
        elif repeat == ScheduleRepeat.MONTHLY:
            # 简单处理：加 30 天
            return base_time + timedelta(days=30)
        else:
            return None


# 全局单例
schedule_runner = ScheduleRunner()
