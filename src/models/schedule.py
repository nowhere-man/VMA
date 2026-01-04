"""
Schedule 数据模型

用于定时执行模板任务，自动编译编码器
"""
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


class ScheduleRepeat(str, Enum):
    """重复周期"""
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduleStatus(str, Enum):
    """Schedule 状态"""
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class EncoderConfig(BaseModel):
    """编码器配置"""
    repo: str = Field(..., description="Git 仓库地址")
    branch: str = Field(..., description="分支名")
    build_script: str = Field(..., description="构建脚本")
    binary_path: str = Field(..., description="构建后的二进制路径（相对于仓库根目录）")

    model_config = ConfigDict(extra="ignore")


class ScheduleMetadata(BaseModel):
    """Schedule 元数据（持久化）"""
    schedule_id: str = Field(..., description="Schedule ID")
    name: str = Field(..., description="Schedule 名称")
    description: Optional[str] = Field(None, description="Schedule 描述")

    # 编码器配置
    encoder_type: str = Field(..., description="编码器类型 (ffmpeg/x264/x265/vvenc)")
    encoder_config: EncoderConfig = Field(..., description="编码器配置")

    # 模板配置
    template_id: str = Field(..., description="模板 ID")
    template_type: str = Field(..., description="模板类型 (metrics_analysis/metrics_comparison)")
    template_name: str = Field(..., description="模板名称")

    # 调度配置
    start_time: datetime = Field(..., description="首次执行时间")
    repeat: ScheduleRepeat = Field(default=ScheduleRepeat.NONE, description="重复周期")

    # 状态
    status: ScheduleStatus = Field(default=ScheduleStatus.ACTIVE, description="状态")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")

    # 最近的执行信息
    last_execution: Optional[datetime] = Field(None, description="最近执行时间")
    last_execution_status: Optional[str] = Field(None, description="最近执行状态 (success/failed)")
    last_execution_job_id: Optional[str] = Field(None, description="最近执行的任务 ID")
    next_execution: Optional[datetime] = Field(None, description="下次执行时间")

    model_config = ConfigDict(
        extra="ignore",
        json_encoders={datetime: lambda v: v.isoformat()},
    )


class ScheduleExecution(BaseModel):
    """单次执行记录"""
    execution_id: str = Field(..., description="执行 ID")
    schedule_id: str = Field(..., description="Schedule ID")
    executed_at: datetime = Field(..., description="执行时间")
    job_id: str = Field(..., description="生成的任务 ID")
    build_status: str = Field(..., description="构建状态 (success/failed/skipped)")
    build_log_path: Optional[str] = Field(None, description="构建日志路径（相对于 schedule 目录）")
    error_message: Optional[str] = Field(None, description="错误信息")

    model_config = ConfigDict(
        extra="ignore",
        json_encoders={datetime: lambda v: v.isoformat()},
    )
