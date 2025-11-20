"""
文件操作工具函数

提供视频文件信息提取、文件保存等通用功能
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.models import VideoInfo


def save_uploaded_file(file_content: bytes, destination: Path) -> None:
    """
    保存上传的文件

    Args:
        file_content: 文件内容（字节）
        destination: 目标文件路径
    """
    destination.parent.mkdir(parents=True, exist_ok=True)

    with open(destination, "wb") as f:
        f.write(file_content)


def get_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
    """
    计算文件哈希值

    Args:
        file_path: 文件路径
        algorithm: 哈希算法（默认 sha256）

    Returns:
        十六进制哈希字符串
    """
    hash_obj = hashlib.new(algorithm)

    with open(file_path, "rb") as f:
        # 分块读取以处理大文件
        for chunk in iter(lambda: f.read(8192), b""):
            hash_obj.update(chunk)

    return hash_obj.hexdigest()


def extract_video_info(file_path: Path) -> VideoInfo:
    """
    提取视频文件基本信息

    Args:
        file_path: 视频文件路径

    Returns:
        VideoInfo: 视频信息对象

    Note:
        此版本返回基本信息（文件名和大小）
        完整的视频元数据提取（duration, fps 等）将在 US1 中通过 FFmpeg 实现
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_stat = file_path.stat()

    return VideoInfo(
        filename=file_path.name,
        size_bytes=file_stat.st_size,
        # 以下字段将在后续通过 FFmpeg 填充
        duration=None,
        width=None,
        height=None,
        fps=None,
        bitrate=None,
    )


def save_json(data: Dict[str, Any], file_path: Path) -> None:
    """
    保存 JSON 数据到文件

    Args:
        data: 要保存的字典数据
        file_path: 目标文件路径
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    从文件加载 JSON 数据

    Args:
        file_path: JSON 文件路径

    Returns:
        字典数据，如果文件不存在或无效则返回 None
    """
    if not file_path.exists():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_file_size_human(size_bytes: int) -> str:
    """
    将字节大小转换为人类可读格式

    Args:
        size_bytes: 字节大小

    Returns:
        格式化的大小字符串（如 "1.5 MB"）
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"
