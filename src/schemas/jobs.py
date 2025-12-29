"""
任务相关 API schemas
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from src.models.job import CommandLog, JobMode, JobStatus, MetricsResult


class CreateJobResponse(BaseModel):
    """创建任务响应"""

    job_id: str = Field(..., description="任务 ID")
    status: JobStatus = Field(..., description="任务状态")
    mode: JobMode = Field(..., description="任务模式")
    created_at: datetime = Field(..., description="创建时间")


class JobDetailResponse(BaseModel):
    """任务详情响应"""

    job_id: str = Field(..., description="任务 ID")
    status: JobStatus = Field(..., description="任务状态")
    mode: JobMode = Field(..., description="任务模式")

    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")

    # 模板信息
    template_name: Optional[str] = Field(None, description="模板名称")

    # 视频信息
    reference_filename: Optional[str] = Field(None, description="参考视频文件名")
    distorted_filename: Optional[str] = Field(None, description="待测视频文件名")

    # 指标结果
    metrics: Optional[MetricsResult] = Field(None, description="质量指标结果")

    # 命令执行记录
    command_logs: List[CommandLog] = Field(default_factory=list, description="命令执行记录")

    # 错误信息
    error_message: Optional[str] = Field(None, description="错误信息")


class JobListItem(BaseModel):
    """任务列表项"""

    job_id: str = Field(..., description="任务 ID")
    status: JobStatus = Field(..., description="任务状态")
    mode: JobMode = Field(..., description="任务模式")
    created_at: datetime = Field(..., description="创建时间")


JobListResponse = List[JobListItem]


class MetricsResponse(BaseModel):
    """指标报告响应"""

    job_id: str = Field(..., description="任务 ID")
    status: JobStatus = Field(..., description="任务状态")
    metrics: Optional[MetricsResult] = Field(None, description="质量指标结果")


class ErrorResponse(BaseModel):
    """错误响应"""

    detail: str = Field(..., description="错误详情")
