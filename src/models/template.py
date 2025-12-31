"""
模板数据模型（Anchor / Test）
"""
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EncoderType(str, Enum):
    FFMPEG = "ffmpeg"
    X264 = "x264"
    X265 = "x265"
    VVENC = "vvenc"


class TemplateType(str, Enum):
    METRICS_COMPARISON = "metrics_comparison"  # Anchor vs Test
    METRICS_ANALYSIS = "metrics_analysis"  # 单侧 Metrics 分析模板


class RateControl(str, Enum):
    CRF = "crf"
    ABR = "abr"


class TemplateSideConfig(BaseModel):
    """Anchor / Test 侧配置"""

    skip_encode: bool = Field(default=False, description="跳过转码")
    source_dir: str = Field(..., description="源视频目录（仅扫一级）")
    encoder_type: Optional[EncoderType] = Field(None, description="编码器类型")
    encoder_params: Optional[str] = Field(None, description="编码器参数")
    rate_control: Optional[RateControl] = Field(None, description="码控模式")
    bitrate_points: List[float] = Field(default_factory=list, description="码率点列表（支持浮点）")
    bitstream_dir: str = Field(..., description="码流目录（平铺）")

    # 视频处理配置
    shortest_size: Optional[int] = Field(None, description="短边尺寸（可选，默认使用源视频分辨率）")
    target_fps: Optional[float] = Field(None, description="目标帧率（可选，默认使用源视频帧率）")
    upscale_to_source: bool = Field(default=True, description="Metrics策略：True=码流上采样到源分辨率，False=源视频下采样到码流分辨率")
    concurrency: int = Field(default=1, description="并发数量")

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def validate_fields(self) -> "TemplateSideConfig":
        ctx = getattr(self, "__pydantic_context__", {}) or {}
        skip_path_check = ctx.get("skip_path_check")
        if not self.source_dir.strip():
            raise ValueError("source_dir 不能为空")
        if not skip_path_check and not Path(self.source_dir).is_dir():
            raise ValueError(f"源视频目录不存在: {self.source_dir}")
        if not self.bitstream_dir.strip():
            raise ValueError("bitstream_dir 不能为空")

        if not self.skip_encode:
            if not self.encoder_type:
                raise ValueError("未跳过转码时必须指定 encoder_type")
            if not self.encoder_params or not self.encoder_params.strip():
                raise ValueError("未跳过转码时必须提供 encoder_params")
            if not self.rate_control:
                raise ValueError("未跳过转码时必须选择码控方式")
            if not self.bitrate_points:
                raise ValueError("未跳过转码时必须提供码率点")
        return self


class EncodingTemplateMetadata(BaseModel):
    """模板元数据（持久化）"""

    template_id: str = Field(..., description="模板 ID")
    name: str = Field(..., description="模板名称")
    description: Optional[str] = Field(None, description="模板描述")

    template_type: TemplateType = Field(default=TemplateType.METRICS_COMPARISON, description="模板类型")

    anchor: TemplateSideConfig
    test: Optional[TemplateSideConfig] = None

    anchor_computed: bool = Field(default=False, description="Anchor 是否已计算完成")
    anchor_fingerprint: Optional[str] = Field(None, description="Anchor 配置指纹，用于变更检测")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        extra="ignore",
        json_encoders={datetime: lambda v: v.isoformat()},
    )

    @model_validator(mode="after")
    def validate_by_type(self) -> "EncodingTemplateMetadata":
        if self.template_type == TemplateType.METRICS_COMPARISON:
            if self.test is None:
                raise ValueError("Comparison 模板需要 Test 配置")
        else:
            # Metrics 分析模板不需要 test，也不需要 anchor_computed
            self.test = None
            self.anchor_computed = False
            self.anchor_fingerprint = None
        return self


class EncodingTemplate(BaseModel):
    """模板对象（包含所在目录）"""

    metadata: EncodingTemplateMetadata
    template_dir: Path

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def template_id(self) -> str:
        return self.metadata.template_id

    @property
    def name(self) -> str:
        return self.metadata.name

    def get_metadata_path(self) -> Path:
        return self.template_dir / "template.json"
