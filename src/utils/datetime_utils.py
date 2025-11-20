"""
日期时间工具函数

提供时间格式化、计算等功能
"""
from datetime import datetime, timedelta
from typing import Optional


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化日期时间

    Args:
        dt: datetime 对象
        format_str: 格式字符串

    Returns:
        格式化的日期时间字符串
    """
    return dt.strftime(format_str)


def format_datetime_iso(dt: datetime) -> str:
    """
    格式化为 ISO 8601 格式

    Args:
        dt: datetime 对象

    Returns:
        ISO 格式字符串
    """
    return dt.isoformat()


def parse_datetime_iso(iso_str: str) -> Optional[datetime]:
    """
    解析 ISO 8601 格式的日期时间字符串

    Args:
        iso_str: ISO 格式字符串

    Returns:
        datetime 对象，解析失败返回 None
    """
    try:
        return datetime.fromisoformat(iso_str)
    except Exception:
        return None


def get_datetime_diff_human(dt1: datetime, dt2: Optional[datetime] = None) -> str:
    """
    获取两个时间点的差异（人类可读格式）

    Args:
        dt1: 第一个时间点
        dt2: 第二个时间点（默认为当前时间）

    Returns:
        格式化的时间差字符串（如 "2小时前"）
    """
    if dt2 is None:
        dt2 = datetime.utcnow()

    diff = dt2 - dt1

    if diff < timedelta(seconds=60):
        return f"{int(diff.total_seconds())}秒前"
    elif diff < timedelta(hours=1):
        return f"{int(diff.total_seconds() / 60)}分钟前"
    elif diff < timedelta(days=1):
        return f"{int(diff.total_seconds() / 3600)}小时前"
    elif diff < timedelta(days=30):
        return f"{diff.days}天前"
    elif diff < timedelta(days=365):
        return f"{int(diff.days / 30)}个月前"
    else:
        return f"{int(diff.days / 365)}年前"


def is_expired(dt: datetime, retention_days: int) -> bool:
    """
    检查日期时间是否已过期

    Args:
        dt: 要检查的日期时间
        retention_days: 保留天数

    Returns:
        是否已过期
    """
    expiry_date = dt + timedelta(days=retention_days)
    return datetime.utcnow() > expiry_date


def format_duration(seconds: float) -> str:
    """
    格式化时长（秒）为人类可读格式

    Args:
        seconds: 秒数

    Returns:
        格式化的时长字符串（如 "1:23:45"）
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"
