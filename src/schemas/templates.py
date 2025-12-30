"""
模板 API schemas
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from src.models.template import EncoderType, RateControl, TemplateSideConfig


class TemplateSidePayload(BaseModel):
    skip_encode: bool = Field(default=False, description="跳过转码")
    source_dir: str = Field(..., description="源视频目录")
    encoder_type: Optional[EncoderType] = Field(None, description="编码器类型")
    encoder_path: Optional[str] = Field(None, description="编码器路径")
    encoder_params: Optional[str] = Field(None, description="编码器参数")
    rate_control: Optional[RateControl] = Field(None, description="码控方式")
    bitrate_points: List[float] = Field(default_factory=list, description="码率点列表")
    bitstream_dir: str = Field(..., description="码流目录")
    shortest_size: Optional[int] = Field(None, description="最短边尺寸")
    target_fps: Optional[float] = Field(None, description="目标帧率")
    upscale_to_source: bool = Field(default=True, description="Metrics策略")
    concurrency: int = Field(default=1, description="并发数量")


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    anchor: TemplateSidePayload
    test: TemplateSidePayload


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    anchor: Optional[TemplateSidePayload] = None
    test: Optional[TemplateSidePayload] = None


class TemplateResponse(BaseModel):
    template_id: str
    name: str
    description: Optional[str]
    template_type: str
    anchor: dict  # 返回原始 dict，避免前端编辑时因路径校验失败
    test: Optional[dict] = None
    anchor_computed: bool
    anchor_fingerprint: Optional[str]
    created_at: datetime
    updated_at: datetime


class CreateTemplateResponse(BaseModel):
    template_id: str
    status: str = Field(default="created")


class ValidateTemplateResponse(BaseModel):
    template_id: str
    source_exists: bool
    output_dir_writable: bool
    all_valid: bool


class TemplateListItem(BaseModel):
    template_id: str
    name: str
    description: Optional[str]
    created_at: datetime
    template_type: str
    anchor_source_dir: str
    anchor_bitstream_dir: str
    test_source_dir: Optional[str] = None
    test_bitstream_dir: Optional[str] = None
    anchor_computed: bool = False
    anchor_encoder_params: Optional[str] = None
    anchor_bitrate_points: List[float] = Field(default_factory=list)
    test_encoder_params: Optional[str] = None
    test_bitrate_points: List[float] = Field(default_factory=list)
