"""
模板工具模块

提供模板配置相关的工具函数。
"""

import json
from typing import Any


def fingerprint(side: Any) -> str:
    """
    生成模板侧配置的指纹（用于检测配置变更）

    Args:
        side: TemplateSideConfig 对象或具有相同属性的对象

    Returns:
        配置的 JSON 字符串指纹
    """
    payload = {
        "skip_encode": side.skip_encode,
        "source_dir": side.source_dir,
        "encoder_type": side.encoder_type,
        "encoder_path": side.encoder_path,
        "encoder_params": side.encoder_params,
        "rate_control": side.rate_control,
        "bitrate_points": side.bitrate_points,
        "bitstream_dir": side.bitstream_dir,
    }
    return json.dumps(payload, sort_keys=True)
