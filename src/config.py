"""
配置管理模块

从 config.yml 加载配置
"""
import yaml
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ValidationError

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.yml"


class Settings(BaseModel):
    # 服务器配置
    host: str
    fastapi_port: int
    streamlit_port: int

    # 报告存储
    reports_root_dir: Path

    # 任务存储
    jobs_root_dir: Path
    # 模板存储（持久化模板）
    templates_root_dir: Path

    # FFmpeg 配置
    ffmpeg_path: Optional[str] = None  # FFmpeg 目录路径，如 /usr/local/ffmpeg/bin
    ffmpeg_timeout: int

    # 日志配置
    log_level: str

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


def load_settings() -> Settings:
    if not CONFIG_FILE.is_file():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    try:
        return Settings(**data)
    except ValidationError as exc:
        raise ValueError(f"Invalid config.yml: {exc}") from exc


# 全局配置实例
settings = load_settings()
