"""
Schedule API schemas
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from src.models.schedule import ScheduleRepeat, ScheduleStatus


class EncoderConfigPayload(BaseModel):
    """编码器配置（创建/更新时使用）"""
    repo: str = Field(..., description="Git 仓库地址")
    branch: str = Field(..., description="分支名")
    build_script: str = Field(..., description="构建脚本")
    binary_path: str = Field(..., description="构建后的二进制路径（相对于仓库根目录）")


class CreateScheduleRequest(BaseModel):
    """创建 Schedule 请求"""
    name: str = Field(..., min_length=1, max_length=100, description="Schedule 名称")
    description: Optional[str] = Field(None, max_length=500, description="Schedule 描述")
    encoder_type: str = Field(..., description="编码器类型 (ffmpeg/x264/x265/vvenc)")
    encoder_config: EncoderConfigPayload = Field(..., description="编码器配置")
    template_id: str = Field(..., description="模板 ID")
    start_time: datetime = Field(..., description="首次执行时间")
    repeat: ScheduleRepeat = Field(default=ScheduleRepeat.NONE, description="重复周期")


class UpdateScheduleRequest(BaseModel):
    """更新 Schedule 请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Schedule 名称")
    description: Optional[str] = Field(None, max_length=500, description="Schedule 描述")
    template_id: Optional[str] = Field(None, description="模板 ID")
    start_time: Optional[datetime] = Field(None, description="首次执行时间")
    repeat: Optional[ScheduleRepeat] = Field(None, description="重复周期")
    status: Optional[ScheduleStatus] = Field(None, description="状态")


class ScheduleListItem(BaseModel):
    """Schedule 列表项"""
    schedule_id: str
    name: str
    description: Optional[str]
    encoder_type: str
    template_id: str
    template_type: str
    template_name: str
    status: ScheduleStatus
    start_time: datetime
    repeat: ScheduleRepeat
    created_at: datetime
    updated_at: datetime
    last_execution: Optional[datetime]
    last_execution_status: Optional[str]
    next_execution: Optional[datetime]


class ScheduleDetailResponse(BaseModel):
    """Schedule 详情响应"""
    schedule_id: str
    name: str
    description: Optional[str]
    encoder_type: str
    encoder_config: dict
    template_id: str
    template_type: str
    template_name: str
    start_time: datetime
    repeat: ScheduleRepeat
    status: ScheduleStatus
    created_at: datetime
    updated_at: datetime
    last_execution: Optional[datetime]
    last_execution_status: Optional[str]
    last_execution_job_id: Optional[str]
    next_execution: Optional[datetime]


class CreateScheduleResponse(BaseModel):
    """创建 Schedule 响应"""
    schedule_id: str
    status: str = Field(default="created")


class ExecutionListItem(BaseModel):
    """执行历史列表项"""
    execution_id: str
    schedule_id: str
    executed_at: datetime
    job_id: str
    build_status: str
    build_log_path: Optional[str]
    error_message: Optional[str]


class ExecutionDetailResponse(BaseModel):
    """执行详情响应"""
    execution_id: str
    schedule_id: str
    executed_at: datetime
    job_id: str
    build_status: str
    build_log_path: Optional[str]
    error_message: Optional[str]
