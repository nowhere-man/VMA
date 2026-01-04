"""
Schedule 存储服务

负责 Schedule 和执行记录的持久化存储
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from nanoid import generate

from src.config import settings
from src.models.schedule import (
    ScheduleMetadata,
    ScheduleExecution,
    ScheduleStatus,
)

logger = logging.getLogger(__name__)


class ScheduleStorage:
    """Schedule 存储服务"""

    def __init__(self):
        self.root_dir = Path(settings.schedules_root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def generate_schedule_id(self) -> str:
        """生成 Schedule ID（12 字符）"""
        return generate(size=12)

    def _get_schedule_dir(self, schedule_id: str) -> Path:
        """获取 Schedule 目录"""
        schedule_dir = self.root_dir / schedule_id
        schedule_dir.mkdir(parents=True, exist_ok=True)
        return schedule_dir

    def _get_schedule_path(self, schedule_id: str) -> Path:
        """获取 schedule.yml 路径"""
        return self._get_schedule_dir(schedule_id) / "schedule.yml"

    def _get_executions_path(self, schedule_id: str) -> Path:
        """获取 executions.yml 路径"""
        return self._get_schedule_dir(schedule_id) / "executions.yml"

    def create_schedule(self, schedule: ScheduleMetadata) -> None:
        """创建 Schedule"""
        schedule_dir = self._get_schedule_dir(schedule.schedule_id)

        # 创建子目录
        (schedule_dir / "workspace").mkdir(exist_ok=True)
        (schedule_dir / "logs").mkdir(exist_ok=True)

        # 保存 schedule.yml
        schedule_path = self._get_schedule_path(schedule.schedule_id)
        with open(schedule_path, "w", encoding="utf-8") as f:
            import yaml
            yaml.dump(
                schedule.model_dump(mode="json"),
                f,
                allow_unicode=True,
                default_flow_style=False,
            )

        logger.info(f"Schedule created: {schedule.schedule_id}")

    def get_schedule(self, schedule_id: str) -> Optional[ScheduleMetadata]:
        """获取 Schedule"""
        schedule_path = self._get_schedule_path(schedule_id)
        if not schedule_path.exists():
            return None

        try:
            import yaml
            with open(schedule_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return ScheduleMetadata(**data)
        except Exception as e:
            logger.error(f"Failed to load schedule {schedule_id}: {e}")
            return None

    def list_schedules(self) -> List[ScheduleMetadata]:
        """列出所有 Schedules"""
        schedules = []
        for schedule_dir in self.root_dir.iterdir():
            if not schedule_dir.is_dir():
                continue
            schedule = self.get_schedule(schedule_dir.name)
            if schedule:
                schedules.append(schedule)
        # 按创建时间倒序
        schedules.sort(key=lambda s: s.created_at, reverse=True)
        return schedules

    def update_schedule(self, schedule_id: str, schedule: ScheduleMetadata) -> None:
        """更新 Schedule"""
        schedule.updated_at = datetime.utcnow()
        schedule_path = self._get_schedule_path(schedule_id)
        with open(schedule_path, "w", encoding="utf-8") as f:
            import yaml
            yaml.dump(
                schedule.model_dump(mode="json"),
                f,
                allow_unicode=True,
                default_flow_style=False,
            )
        logger.info(f"Schedule updated: {schedule_id}")

    def delete_schedule(self, schedule_id: str) -> None:
        """删除 Schedule"""
        schedule_dir = self._get_schedule_dir(schedule_id)
        import shutil
        if schedule_dir.exists():
            shutil.rmtree(schedule_dir)
            logger.info(f"Schedule deleted: {schedule_id}")

    def add_execution(self, schedule_id: str, execution: ScheduleExecution) -> None:
        """添加执行记录"""
        executions_path = self._get_executions_path(schedule_id)

        # 加载现有执行记录
        executions = self.list_executions(schedule_id, limit=1000)

        # 添加新记录
        executions.append(execution)

        # 只保留最近 100 条
        executions = executions[-100:]

        # 保存
        with open(executions_path, "w", encoding="utf-8") as f:
            import yaml
            yaml.dump(
                [e.model_dump(mode="json") for e in executions],
                f,
                allow_unicode=True,
                default_flow_style=False,
            )

    def list_executions(self, schedule_id: str, limit: int = 100) -> List[ScheduleExecution]:
        """获取执行历史"""
        executions_path = self._get_executions_path(schedule_id)
        if not executions_path.exists():
            return []

        try:
            import yaml
            with open(executions_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            executions = [ScheduleExecution(**item) for item in data]
            # 按执行时间倒序，取前 N 条
            executions.sort(key=lambda e: e.executed_at, reverse=True)
            return executions[:limit]
        except Exception as e:
            logger.error(f"Failed to load executions for {schedule_id}: {e}")
            return []

    def save_build_log(self, schedule_id: str, log_filename: str, content: str) -> None:
        """保存构建日志"""
        log_path = self._get_schedule_dir(schedule_id) / "logs" / log_filename
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Build log saved: {log_path}")

    def get_build_log(self, schedule_id: str, log_filename: str) -> Optional[str]:
        """获取构建日志内容"""
        log_path = self._get_schedule_dir(schedule_id) / "logs" / log_filename
        if not log_path.exists():
            return None
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read log {log_filename}: {e}")
            return None


# 全局单例
schedule_storage = ScheduleStorage()
