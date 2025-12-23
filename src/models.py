"""
数据模型定义

定义核心数据结构：Job、MetricsResult、JobMetadata
"""
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    """任务状态枚举"""

    PENDING = "pending"  # 等待处理
    PROCESSING = "processing"  # 正在处理
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


class JobMode(str, Enum):
    """任务模式枚举"""

    SINGLE_FILE = "single_file"  # 单文件模式：系统执行预设转码
    DUAL_FILE = "dual_file"  # 双文件模式：用户提供参考和待测视频
    BITSTREAM_ANALYSIS = "bitstream_analysis"  # 码流分析：参考 + 多个编码文件
    COMPARISON = "comparison"  # 对比模式：对比两个模板的执行结果
    TEMPLATE = "template"  # 模板模式：使用模板执行转码


class CommandStatus(str, Enum):
    """命令执行状态"""

    PENDING = "pending"  # 等待执行
    RUNNING = "running"  # 正在执行
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


class CommandLog(BaseModel):
    """命令执行记录"""

    command_id: str = Field(..., description="命令ID")
    command_type: str = Field(..., description="命令类型(encode/psnr/ssim/vmaf/ffmpeg预处理等)")
    command: str = Field(..., description="完整命令行")
    status: CommandStatus = Field(default=CommandStatus.PENDING, description="执行状态")
    source_file: Optional[str] = Field(None, description="源文件")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    error_message: Optional[str] = Field(None, description="错误信息")


class MetricsResult(BaseModel):
    """视频质量指标结果"""

    # 总体平均值
    psnr_avg: Optional[float] = Field(None, description="平均 PSNR (dB)")
    psnr_y: Optional[float] = Field(None, description="Y 分量 PSNR (dB)")
    psnr_u: Optional[float] = Field(None, description="U 分量 PSNR (dB)")
    psnr_v: Optional[float] = Field(None, description="V 分量 PSNR (dB)")

    ssim_avg: Optional[float] = Field(None, description="平均 SSIM")
    ssim_y: Optional[float] = Field(None, description="Y 分量 SSIM")
    ssim_u: Optional[float] = Field(None, description="U 分量 SSIM")
    ssim_v: Optional[float] = Field(None, description="V 分量 SSIM")

    vmaf_mean: Optional[float] = Field(None, description="VMAF 平均分")
    vmaf_harmonic_mean: Optional[float] = Field(None, description="VMAF 调和平均分")

    # 帧级数据文件路径（相对于任务目录）
    frame_metrics_file: Optional[str] = Field(None, description="帧级指标 JSON 文件路径")


class VideoInfo(BaseModel):
    """视频文件信息"""

    filename: str = Field(..., description="文件名")
    size_bytes: int = Field(..., description="文件大小（字节）")
    duration: Optional[float] = Field(None, description="视频时长（秒）")
    width: Optional[int] = Field(None, description="视频宽度")
    height: Optional[int] = Field(None, description="视频高度")
    fps: Optional[float] = Field(None, description="帧率")
    bitrate: Optional[int] = Field(None, description="比特率 (bps)")


class JobMetadata(BaseModel):
    """任务元数据（持久化到 JSON）"""

    job_id: str = Field(..., description="任务 ID (nanoid 12字符)")
    status: JobStatus = Field(default=JobStatus.PENDING, description="任务状态")
    mode: JobMode = Field(..., description="任务模式")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="更新时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")

    # 原始视频信息
    reference_video: Optional[VideoInfo] = Field(None, description="参考视频信息")
    distorted_video: Optional[VideoInfo] = Field(None, description="待测视频信息")
    encoded_videos: List[VideoInfo] = Field(default_factory=list, description="编码视频信息列表（码流分析）")

    # RawVideo (YUV) 参数（码流分析）
    rawvideo_width: Optional[int] = Field(None, description="YUV 宽度（仅 rawvideo）")
    rawvideo_height: Optional[int] = Field(None, description="YUV 高度（仅 rawvideo）")
    rawvideo_fps: Optional[float] = Field(None, description="YUV 帧率（仅 rawvideo）")
    rawvideo_pix_fmt: str = Field(default="yuv420p", description="YUV 像素格式（默认 yuv420p）")

    # 转码参数（单文件模式）
    preset: Optional[str] = Field(None, description="转码预设")

    # 模板信息
    template_id: Optional[str] = Field(None, description="模板 ID")
    template_name: Optional[str] = Field(None, description="模板名称")

    # 对比任务参数（对比模式）
    template_a_id: Optional[str] = Field(None, description="模板 A ID（对比模式）")
    template_b_id: Optional[str] = Field(None, description="模板 B ID（对比模式）")
    comparison_result: Optional[dict] = Field(None, description="对比结果数据（对比模式）")

    # 执行结果（模板执行模式）
    execution_result: Optional[dict] = Field(None, description="执行结果数据（模板执行模式）")

    # 命令执行记录
    command_logs: List[CommandLog] = Field(default_factory=list, description="命令执行记录")

    # 指标结果
    metrics: Optional[MetricsResult] = Field(None, description="质量指标结果")

    # 错误信息
    error_message: Optional[str] = Field(None, description="错误信息")

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
        }
    )


class Job(BaseModel):
    """任务对象（内存中使用，包含文件路径）"""

    metadata: JobMetadata = Field(..., description="任务元数据")
    job_dir: Path = Field(..., description="任务目录路径")

    @property
    def job_id(self) -> str:
        """任务 ID"""
        return self.metadata.job_id

    @property
    def status(self) -> JobStatus:
        """任务状态"""
        return self.metadata.status

    def get_reference_path(self) -> Optional[Path]:
        """获取参考视频文件路径"""
        if self.metadata.reference_video:
            ref = Path(self.metadata.reference_video.filename)
            return ref if ref.is_absolute() else (self.job_dir / ref)
        return None

    def get_distorted_path(self) -> Optional[Path]:
        """获取待测视频文件路径"""
        if self.metadata.distorted_video:
            dist = Path(self.metadata.distorted_video.filename)
            return dist if dist.is_absolute() else (self.job_dir / dist)
        return None

    def get_metadata_path(self) -> Path:
        """获取元数据文件路径"""
        return self.job_dir / "metadata.json"

    model_config = ConfigDict(arbitrary_types_allowed=True)
