"""
共享 schema 定义
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from src.models.template import EncoderType, RateControl


class SideConfigPayload(BaseModel):
    skip_encode: bool = Field(default=False, description="跳过转码")
    source_dir: str = Field(..., description="源视频目录")
    encoder_type: Optional[EncoderType] = Field(None, description="编码器类型")
    encoder_path: Optional[str] = Field(None, description="编码器路径")
    encoder_params: Optional[str] = Field(None, description="编码器参数")
    rate_control: Optional[RateControl] = Field(None, description="码控方式")
    bitrate_points: List[float] = Field(default_factory=list, description="码率点列表")
    bitstream_dir: str = Field(..., description="码流目录")
    shortest_size: Optional[int] = Field(None, description="短边尺寸")
    target_fps: Optional[float] = Field(None, description="目标帧率")
    upscale_to_source: bool = Field(default=True, description="Metrics策略")
    concurrency: int = Field(default=1, description="并发数量")
