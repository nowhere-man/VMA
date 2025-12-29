"""
Metrics 分析模板 API schemas
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from src.models.template import EncoderType, RateControl, TemplateSideConfig


class MetricsTemplatePayload(BaseModel):
    skip_encode: bool = Field(default=False, description="跳过转码")
    source_dir: str = Field(..., description="源视频目录")
    encoder_type: Optional[EncoderType] = Field(None, description="编码器类型")
    encoder_params: Optional[str] = Field(None, description="编码器参数")
    rate_control: Optional[RateControl] = Field(None, description="码控方式")
    bitrate_points: List[float] = Field(default_factory=list, description="码率点列表")
    bitstream_dir: str = Field(..., description="码流目录")


class CreateMetricsTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    config: MetricsTemplatePayload


class UpdateMetricsTemplateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    config: Optional[MetricsTemplatePayload] = None


class MetricsTemplateResponse(BaseModel):
    template_id: str
    name: str
    description: Optional[str]
    config: dict  # 返回 dict，避免前端编辑时路径校验
    created_at: datetime
    updated_at: datetime
    template_type: str = Field(default="metrics_analysis")


class MetricsTemplateListItem(BaseModel):
    template_id: str
    name: str
    description: Optional[str]
    created_at: datetime
    source_dir: str
    bitstream_dir: str
    template_type: str = Field(default="metrics_analysis")


class ValidateMetricsTemplateResponse(BaseModel):
    template_id: str
    source_exists: bool
    output_dir_writable: bool
    all_valid: bool
