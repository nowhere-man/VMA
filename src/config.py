"""
配置管理模块

从环境变量加载应用配置
环境变量使用 VMA_ 前缀，例如 VMA_PORT=8080
"""
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8080

    # 任务存储
    jobs_root_dir: Path = Path("./jobs")
    # 模板存储（持久化模板）
    templates_root_dir: Path = Path("./templates")

    # FFmpeg 配置
    ffmpeg_path: Optional[str] = None  # FFmpeg 目录路径，如 /usr/local/ffmpeg/bin
    ffmpeg_timeout: int = 600

    # 日志配置
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="VMA_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    def get_ffmpeg_bin(self) -> str:
        """获取 ffmpeg 可执行文件路径"""
        if self.ffmpeg_path:
            return str(Path(self.ffmpeg_path) / "ffmpeg")
        return "ffmpeg"

    def get_ffprobe_bin(self) -> str:
        """获取 ffprobe 可执行文件路径"""
        if self.ffmpeg_path:
            return str(Path(self.ffmpeg_path) / "ffprobe")
        return "ffprobe"


# 全局配置实例
settings = Settings()
