"""
APScheduler 调度器服务

负责管理和执行定时任务
"""
import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from src.models.schedule import ScheduleMetadata, ScheduleRepeat, ScheduleStatus
from src.services.schedule_runner import schedule_runner
from src.services.schedule_storage import schedule_storage

logger = logging.getLogger(__name__)


class SchedulerService:
    """APScheduler 调度器服务"""

    def __init__(self):
        """初始化调度器"""
        # 配置 JobStore 和 Executor
        jobstores = {
            "default": MemoryJobStore(),
        }
        executors = {
            "default": AsyncIOExecutor(),
        }
        job_defaults = {
            "coalesce": True,  # 合并错过的任务
            "max_instances": 1,  # 同一任务最多同时运行 1 个实例
            "misfire_grace_time": 3600,  # 错过任务的宽限时间（秒）
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

        self._running = False

    async def start(self) -> None:
        """启动调度器并加载所有 Schedules"""
        if self._running:
            logger.warning("Scheduler is already running")
            return

        self.scheduler.start()
        self._running = True
        logger.info("Scheduler started")

        # 加载所有 Schedules
        await self.load_schedules()

    def shutdown(self, wait: bool = True) -> None:
        """
        关闭调度器

        Args:
            wait: 是否等待正在执行的任务完成
        """
        if not self._running:
            logger.warning("Scheduler is not running")
            return

        self.scheduler.shutdown(wait=wait)
        self._running = False
        logger.info("Scheduler shutdown")

    def add_schedule(self, schedule: ScheduleMetadata) -> None:
        """
        添加 Schedule 到调度器

        Args:
            schedule: Schedule 元数据
        """
        if schedule.status != ScheduleStatus.ACTIVE:
            logger.info(f"Schedule {schedule.schedule_id} is not active, skipping")
            return

        # 创建触发器
        trigger = self._create_trigger(schedule)

        # 添加任务
        self.scheduler.add_job(
            func=self._execute_schedule,
            trigger=trigger,
            id=schedule.schedule_id,
            args=[schedule.schedule_id],
            name=schedule.name,
            replace_existing=True,
        )

        logger.info(f"Schedule added: {schedule.schedule_id} (next_run: {schedule.next_execution})")

    def remove_schedule(self, schedule_id: str) -> None:
        """
        从调度器移除 Schedule

        Args:
            schedule_id: Schedule ID
        """
        try:
            self.scheduler.remove_job(schedule_id)
            logger.info(f"Schedule removed: {schedule_id}")
        except Exception as e:
            logger.warning(f"Failed to remove schedule {schedule_id}: {e}")

    def update_schedule(self, schedule: ScheduleMetadata) -> None:
        """
        更新调度器中的 Schedule

        Args:
            schedule: Schedule 元数据
        """
        # 移除旧的
        self.remove_schedule(schedule.schedule_id)

        # 添加新的
        self.add_schedule(schedule)

    def pause_schedule(self, schedule_id: str) -> None:
        """
        暂停 Schedule

        Args:
            schedule_id: Schedule ID
        """
        try:
            self.scheduler.pause_job(schedule_id)
            logger.info(f"Schedule paused: {schedule_id}")
        except Exception as e:
            logger.warning(f"Failed to pause schedule {schedule_id}: {e}")

    def resume_schedule(self, schedule_id: str) -> None:
        """
        恢复 Schedule

        Args:
            schedule_id: Schedule ID
        """
        try:
            self.scheduler.resume_job(schedule_id)
            logger.info(f"Schedule resumed: {schedule_id}")
        except Exception as e:
            logger.warning(f"Failed to resume schedule {schedule_id}: {e}")

    async def load_schedules(self) -> None:
        """从存储加载所有 Schedules"""
        schedules = schedule_storage.list_schedules()

        logger.info(f"Loading {len(schedules)} schedules")

        for schedule in schedules:
            if schedule.status == ScheduleStatus.ACTIVE:
                # 检查是否需要立即执行
                if schedule.next_execution and schedule.next_execution <= datetime.utcnow():
                    logger.info(f"Schedule {schedule.schedule_id} is due, executing now")
                    await self._execute_schedule(schedule.schedule_id)
                else:
                    self.add_schedule(schedule)

    async def _execute_schedule(self, schedule_id: str) -> None:
        """
        执行 Schedule（调度器回调）

        Args:
            schedule_id: Schedule ID
        """
        logger.info(f"Executing schedule: {schedule_id}")

        try:
            # 从存储加载最新的 Schedule
            schedule = schedule_storage.get_schedule(schedule_id)
            if not schedule:
                logger.error(f"Schedule not found: {schedule_id}")
                return

            # 检查状态
            if schedule.status != ScheduleStatus.ACTIVE:
                logger.info(f"Schedule {schedule_id} is not active, skipping")
                return

            # 执行 Schedule
            execution = await schedule_runner.execute(schedule)

            logger.info(
                f"Schedule {schedule_id} execution completed: "
                f"job_id={execution.job_id}, status={execution.build_status}"
            )

            # 重新加载 Schedule（可能已更新）
            updated_schedule = schedule_storage.get_schedule(schedule_id)
            if updated_schedule and updated_schedule.status == ScheduleStatus.ACTIVE:
                # 更新调度器中的任务
                self.update_schedule(updated_schedule)

        except Exception as e:
            logger.exception(f"Failed to execute schedule {schedule_id}: {e}")

    def _create_trigger(self, schedule: ScheduleMetadata):
        """
        创建触发器

        Args:
            schedule: Schedule 元数据

        Returns:
            Trigger 对象
        """
        if schedule.repeat == ScheduleRepeat.NONE:
            # 单次执行
            return DateTrigger(run_date=schedule.start_time, timezone="UTC")

        # 定时执行（使用 CronTrigger）
        # 注意：APScheduler 3.x 的 CronTrigger 使用 cron 表达式
        # 这里我们简化处理，只支持每天的固定时间
        hour = schedule.start_time.hour
        minute = schedule.start_time.minute

        if schedule.repeat == ScheduleRepeat.DAILY:
            # 每天执行
            return CronTrigger(
                hour=hour,
                minute=minute,
                timezone="UTC",
            )
        elif schedule.repeat == ScheduleRepeat.WEEKLY:
            # 每周执行（在相同的星期几）
            day_of_week = schedule.start_time.weekday()
            return CronTrigger(
                day_of_week=day_of_week,
                hour=hour,
                minute=minute,
                timezone="UTC",
            )
        elif schedule.repeat == ScheduleRepeat.MONTHLY:
            # 每月执行（在相同的日期）
            day = schedule.start_time.day
            return CronTrigger(
                day=day,
                hour=hour,
                minute=minute,
                timezone="UTC",
            )
        else:
            # 默认单次执行
            return DateTrigger(run_date=schedule.start_time, timezone="UTC")

    def get_next_run_time(self, schedule_id: str) -> Optional[datetime]:
        """
        获取 Schedule 的下次执行时间

        Args:
            schedule_id: Schedule ID

        Returns:
            下次执行时间，如果不存在则返回 None
        """
        try:
            job = self.scheduler.get_job(schedule_id)
            return job.next_run_time if job else None
        except Exception:
            return None

    def list_scheduled_jobs(self) -> list[dict]:
        """
        列出所有已调度的任务

        Returns:
            任务信息列表
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time,
            })
        return jobs


# 全局单例
scheduler_service = SchedulerService()
