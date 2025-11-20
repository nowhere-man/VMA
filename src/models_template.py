"""
转码模板数据模型定义

定义转码模板相关的数据结构：EncodingTemplate、EncoderType 等
"""
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EncoderType(str, Enum):
    """编码器类型枚举"""

    FFMPEG = "ffmpeg"  # FFmpeg 编码器
    X264 = "x264"  # x264 编码器
    X265 = "x265"  # x265 编码器
    VVENC = "vvenc"  # VVenC (VVC) 编码器


class SequenceType(str, Enum):
    """序列类型枚举"""

    MEDIA = "media"  # 容器格式（mp4, flv等）
    YUV420P = "yuv420p"  # YUV 420P 原始格式


class SourcePathType(str, Enum):
    """源路径类型枚举"""

    SINGLE_FILE = "single_file"  # 单文件
    MULTIPLE_FILES = "multiple_files"  # 多文件（逗号分隔）
    DIRECTORY = "directory"  # 目录


class OutputType(str, Enum):
    """输出类型枚举"""

    SAME_AS_SOURCE = "same_as_source"  # 同源视频类型
    RAW_STREAM = "raw_stream"  # 原始流（h264/h265/h266等）


class EncodingTemplateMetadata(BaseModel):
    """转码模板元数据（持久化到 JSON）"""

    template_id: str = Field(..., description="模板 ID (nanoid 12字符)")

    # 第一大类：基本信息
    name: str = Field(..., min_length=1, max_length=100, description="模板名称")
    description: Optional[str] = Field(None, max_length=500, description="模板描述")

    # 第二大类：测试序列配置
    sequence_type: SequenceType = Field(..., description="序列类型（Media或YUV 420P）")
    width: Optional[int] = Field(None, gt=0, description="视频宽度（YUV类型必填）")
    height: Optional[int] = Field(None, gt=0, description="视频高度（YUV类型必填）")
    fps: Optional[float] = Field(None, gt=0, description="帧率（YUV类型必填）")
    source_path_type: SourcePathType = Field(..., description="源路径类型（单文件/多文件/目录）")
    source_path: str = Field(..., min_length=1, description="源视频路径")

    # 第三大类：编码配置
    encoder_type: EncoderType = Field(..., description="编码器类型（ffmpeg/x264/x265/vvenc）")
    encoder_path: Optional[str] = Field(None, description="编码器可执行文件路径（可选）")
    encoder_params: str = Field(..., max_length=2000, description="编码参数（直接传给编码器）")

    # 第四大类：输出配置
    output_type: OutputType = Field(..., description="输出类型（同源视频类型/Raw Stream）")
    output_dir: str = Field(..., min_length=1, description="输出目录（保存转码输出的码流）")
    metrics_report_dir: str = Field(..., min_length=1, description="报告目录（保存Streamlit生成的报告）")

    # 第五大类：质量指标配置
    skip_metrics: bool = Field(default=False, description="是否跳过质量指标计算")
    metrics_types: list[str] = Field(
        default_factory=list, description="要计算的指标类型（psnr/ssim/vmaf）"
    )

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")

    @field_validator("metrics_types")
    @classmethod
    def validate_metrics_types(cls, v: list[str]) -> list[str]:
        """验证指标类型的有效性"""
        valid_types = {"psnr", "ssim", "vmaf"}
        invalid = set(v) - valid_types
        if invalid:
            raise ValueError(
                f"无效的指标类型: {invalid}. 有效值: {valid_types}"
            )
        return v

    @field_validator("source_path", "output_dir", "metrics_report_dir")
    @classmethod
    def validate_path_not_empty(cls, v: str) -> str:
        """验证路径不为空"""
        if not v.strip():
            raise ValueError("路径不能为空或仅包含空白字符")
        return v.strip()

    @field_validator("encoder_path")
    @classmethod
    def normalize_paths(cls, v: Optional[str]) -> Optional[str]:
        """归一化路径，允许为空"""
        if v is None:
            return None
        value = v.strip()
        return value or None

    def model_post_init(self, __context) -> None:
        """模型初始化后验证"""
        # YUV类型必须提供宽、高、fps
        if self.sequence_type == SequenceType.YUV420P:
            if not self.width:
                raise ValueError("YUV 420P类型必须指定视频宽度（width）")
            if not self.height:
                raise ValueError("YUV 420P类型必须指定视频高度（height）")
            if not self.fps:
                raise ValueError("YUV 420P类型必须指定帧率（fps）")

        # 同源视频类型只能在Media类型时使用
        if self.output_type == OutputType.SAME_AS_SOURCE:
            if self.sequence_type != SequenceType.MEDIA:
                raise ValueError("输出类型为'同源视频类型'时，序列类型必须为Media")

        # 如果不跳过质量指标，必须指定至少一个指标类型
        if not self.skip_metrics and not self.metrics_types:
            raise ValueError("启用质量指标计算时必须至少选择一个指标类型（PSNR/SSIM/VMAF）")

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
        }
    )


class EncodingTemplate(BaseModel):
    """转码模板对象（内存中使用，包含文件路径）"""

    metadata: EncodingTemplateMetadata = Field(..., description="模板元数据")
    template_dir: Path = Field(..., description="模板目录路径")

    @property
    def template_id(self) -> str:
        """模板 ID"""
        return self.metadata.template_id

    @property
    def name(self) -> str:
        """模板名称"""
        return self.metadata.name

    def get_metadata_path(self) -> Path:
        """获取元数据文件路径"""
        return self.template_dir / "template.json"

    def validate_paths(self) -> dict[str, bool]:
        """
        验证配置的路径是否有效

        Returns:
            包含各路径验证结果的字典
        """
        results = {
            "source_exists": Path(self.metadata.source_path).exists(),
            "output_dir_writable": self._check_dir_writable(
                self.metadata.output_dir
            ),
            "metrics_dir_writable": self._check_dir_writable(
                self.metadata.metrics_report_dir
            ),
        }
        return results

    def _check_dir_writable(self, dir_path: str) -> bool:
        """检查目录是否可写"""
        path = Path(dir_path)
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                return True
            except Exception:
                return False
        return path.is_dir() and bool(path.stat().st_mode & 0o200)

    model_config = ConfigDict(arbitrary_types_allowed=True)
