"""
配置管理模块

从环境变量加载应用配置
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

    # FFmpeg 配置
    ffmpeg_timeout: int = 600
    vmaf_model_path: Optional[Path] = Path("/usr/share/model/vmaf_v0.6.1.json")

    # 清理配置
    retention_days: int = 7

    # 日志配置
    log_level: str = "INFO"
    log_format: str = "json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# 全局配置实例
settings = Settings()
