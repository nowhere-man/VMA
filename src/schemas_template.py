"""
转码模板 API Schema 定义

定义转码模板相关的请求和响应模型
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.models_template import EncoderType, SequenceType, SourcePathType, OutputType


class CreateTemplateRequest(BaseModel):
    """创建模板请求"""

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
    encoder_path: Optional[str] = Field(None, max_length=500, description="编码器可执行文件路径（可选）")
    encoder_params: str = Field(..., max_length=2000, description="编码参数（直接传给编码器）")

    # 第四大类：输出配置
    output_type: OutputType = Field(..., description="输出类型（同源视频类型/Raw Stream）")
    output_dir: str = Field(..., min_length=1, description="输出目录（保存转码输出的码流）")
    metrics_report_dir: str = Field(..., min_length=1, description="报告目录")

    # 第五大类：质量指标配置
    skip_metrics: bool = Field(default=False, description="是否跳过质量指标计算")
    metrics_types: list[str] = Field(
        default_factory=list, description="要计算的指标类型（psnr/ssim/vmaf）"
    )


class UpdateTemplateRequest(BaseModel):
    """更新模板请求"""

    # 第一大类：基本信息
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="模板名称")
    description: Optional[str] = Field(None, max_length=500, description="模板描述")

    # 第二大类：测试序列配置
    sequence_type: Optional[SequenceType] = Field(None, description="序列类型（Media或YUV 420P）")
    width: Optional[int] = Field(None, gt=0, description="视频宽度（YUV类型必填）")
    height: Optional[int] = Field(None, gt=0, description="视频高度（YUV类型必填）")
    fps: Optional[float] = Field(None, gt=0, description="帧率（YUV类型必填）")
    source_path_type: Optional[SourcePathType] = Field(None, description="源路径类型（单文件/多文件/目录）")
    source_path: Optional[str] = Field(None, min_length=1, description="源视频路径")

    # 第三大类：编码配置
    encoder_type: Optional[EncoderType] = Field(None, description="编码器类型（ffmpeg/x264/x265/vvenc）")
    encoder_path: Optional[str] = Field(None, max_length=500, description="编码器可执行文件路径（可选）")
    encoder_params: Optional[str] = Field(None, max_length=2000, description="编码参数（直接传给编码器）")

    # 第四大类：输出配置
    output_type: Optional[OutputType] = Field(None, description="输出类型（同源视频类型/Raw Stream）")
    output_dir: Optional[str] = Field(None, min_length=1, description="输出目录（保存转码输出的码流）")
    metrics_report_dir: Optional[str] = Field(None, min_length=1, description="报告目录")

    # 第五大类：质量指标配置
    skip_metrics: Optional[bool] = Field(None, description="是否跳过质量指标计算")
    metrics_types: Optional[list[str]] = Field(None, description="要计算的指标类型（psnr/ssim/vmaf）")


class TemplateResponse(BaseModel):
    """模板响应"""

    template_id: str = Field(..., description="模板 ID")

    # 第一大类：基本信息
    name: str = Field(..., description="模板名称")
    description: Optional[str] = Field(None, description="模板描述")

    # 第二大类：测试序列配置
    sequence_type: SequenceType = Field(..., description="序列类型（Media或YUV 420P）")
    width: Optional[int] = Field(None, description="视频宽度（YUV类型必填）")
    height: Optional[int] = Field(None, description="视频高度（YUV类型必填）")
    fps: Optional[float] = Field(None, description="帧率（YUV类型必填）")
    source_path_type: SourcePathType = Field(..., description="源路径类型（单文件/多文件/目录）")
    source_path: str = Field(..., description="源视频路径")

    # 第三大类：编码配置
    encoder_type: EncoderType = Field(..., description="编码器类型（ffmpeg/x264/x265/vvenc）")
    encoder_path: Optional[str] = Field(None, description="编码器可执行文件路径（可选）")
    encoder_params: str = Field(..., description="编码参数（直接传给编码器）")

    # 第四大类：输出配置
    output_type: OutputType = Field(..., description="输出类型（同源视频类型/Raw Stream）")
    output_dir: str = Field(..., description="输出目录（保存转码输出的码流）")
    metrics_report_dir: str = Field(..., description="报告目录")

    # 第五大类：质量指标配置
    skip_metrics: bool = Field(..., description="是否跳过质量指标计算")
    metrics_types: list[str] = Field(..., description="要计算的指标类型（psnr/ssim/vmaf）")

    # 时间戳
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class TemplateExecutionFileResult(BaseModel):
    """单个文件的执行结果"""

    source_file: str = Field(..., description="源文件路径")
    output_file: str = Field(..., description="输出文件路径")
    encoder_type: EncoderType = Field(..., description="编码器类型")
    elapsed_seconds: float = Field(..., description="耗时（秒）")
    cpu_time_seconds: Optional[float] = Field(
        None, description="CPU 时间（秒）"
    )
    cpu_percent: Optional[float] = Field(
        None, description="平均 CPU 利用率百分比"
    )
    average_fps: Optional[float] = Field(
        None, description="平均转码帧率（fps）"
    )
    output_info: Optional[Dict[str, Any]] = Field(
        None, description="输出视频信息"
    )
    output_size_bytes: Optional[int] = Field(
        None, description="输出文件大小（字节）"
    )
    metrics: Optional[Dict[str, Any]] = Field(
        None, description="质量指标结果"
    )


class TemplateExecutionSummary(BaseModel):
    """模板执行概要"""

    template_id: str = Field(..., description="模板 ID")
    template_name: str = Field(..., description="模板名称")
    total_files: int = Field(..., description="总文件数")
    successful: int = Field(..., description="成功数")
    failed: int = Field(..., description="失败数")
    results: List[TemplateExecutionFileResult] = Field(
        ..., description="逐文件执行结果"
    )
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="错误信息")
    average_speed_fps: Optional[float] = Field(
        None, description="平均转码帧率"
    )
    average_cpu_percent: Optional[float] = Field(
        None, description="平均 CPU 利用率"
    )
    average_bitrate: Optional[float] = Field(
        None, description="平均码率（bps）"
    )


class TemplateComparisonStat(BaseModel):
    """对比统计值"""

    template_a: Optional[float] = Field(None, description="模板 A 数值")
    template_b: Optional[float] = Field(None, description="模板 B 数值")
    delta: Optional[float] = Field(None, description="B - A 的差值")
    delta_percent: Optional[float] = Field(None, description="相对差值 (%)")


class TemplateComparisonMetrics(BaseModel):
    """对比结果指标"""

    speed_fps: TemplateComparisonStat
    cpu_percent: TemplateComparisonStat
    bitrate: TemplateComparisonStat
    quality_metrics: Dict[str, TemplateComparisonStat]
    bd_rate: Dict[str, Optional[float]]


class TemplateComparisonRequest(BaseModel):
    """模板对比请求"""

    template_a: str = Field(..., description="模板 A ID")
    template_b: str = Field(..., description="模板 B ID")


class TemplateComparisonResponse(BaseModel):
    """模板对比响应"""

    template_a: TemplateExecutionSummary
    template_b: TemplateExecutionSummary
    comparisons: TemplateComparisonMetrics


class TemplateListItem(BaseModel):
    """模板列表项"""

    template_id: str = Field(..., description="模板 ID")
    name: str = Field(..., description="模板名称")
    description: Optional[str] = Field(None, description="模板描述")
    sequence_type: SequenceType = Field(..., description="序列类型")
    encoder_type: EncoderType = Field(..., description="编码器类型")
    created_at: datetime = Field(..., description="创建时间")


class CreateTemplateResponse(BaseModel):
    """创建模板响应"""

    template_id: str = Field(..., description="模板 ID")
    name: str = Field(..., description="模板名称")
    created_at: datetime = Field(..., description="创建时间")


class ValidateTemplateResponse(BaseModel):
    """验证模板路径响应"""

    template_id: str = Field(..., description="模板 ID")
    source_exists: bool = Field(..., description="源路径是否存在")
    output_dir_writable: bool = Field(..., description="输出目录是否可写")
    metrics_dir_writable: bool = Field(..., description="报告目录是否可写")
    all_valid: bool = Field(..., description="所有路径是否都有效")
