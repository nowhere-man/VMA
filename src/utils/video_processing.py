"""
视频处理公共工具模块

提供分辨率计算、滤镜构建等公共函数，供编码和打分阶段使用。
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class VideoProcessingConfig:
    """视频处理配置"""

    shortest_size: Optional[int] = None  # 最短边尺寸
    target_fps: Optional[float] = None  # 目标帧率
    upscale_to_source: bool = True  # 是否上采样到源分辨率
    scale_algorithm: str = "bicubic"  # 缩放算法


def calculate_target_resolution(
    src_width: int,
    src_height: int,
    shortest_size: Optional[int],
) -> Tuple[int, int]:
    """
    根据最短边计算目标分辨率（保持宽高比）

    Args:
        src_width: 源视频宽度
        src_height: 源视频高度
        shortest_size: 最短边尺寸（可选）

    Returns:
        (target_width, target_height) 目标分辨率，确保为偶数
    """
    if not shortest_size:
        return src_width, src_height

    # 确定短边
    shortest_len = min(src_width, src_height)

    # 计算缩放比例
    scale_ratio = shortest_size / shortest_len

    # 计算目标分辨率（确保为偶数）
    target_width = int((src_width * scale_ratio) / 2) * 2
    target_height = int((src_height * scale_ratio) / 2) * 2

    return target_width, target_height


def build_vf_filter(
    src_width: int,
    src_height: int,
    src_fps: float,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
    target_fps: Optional[float] = None,
    scale_algorithm: str = "bicubic",
) -> Optional[str]:
    """
    构建 -vf 滤镜字符串

    Args:
        src_width: 源视频宽度
        src_height: 源视频高度
        src_fps: 源视频帧率
        target_width: 目标宽度（可选）
        target_height: 目标高度（可选）
        target_fps: 目标帧率（可选）
        scale_algorithm: 缩放算法，默认 bicubic

    Returns:
        滤镜字符串，如 "fps=30,scale=1280:720:flags=bicubic"
        如果不需要任何转换，返回 None
    """
    filters = []

    # 帧率转换
    if target_fps and abs(target_fps - src_fps) > 0.01:
        filters.append(f"fps={target_fps}")

    # 分辨率转换
    out_width = target_width if target_width else src_width
    out_height = target_height if target_height else src_height

    if out_width != src_width or out_height != src_height:
        filters.append(f"scale={out_width}:{out_height}:flags={scale_algorithm}")

    if not filters:
        return None

    return ",".join(filters)


def build_encode_vf_filter(
    src_width: int,
    src_height: int,
    src_fps: float,
    shortest_size: Optional[int] = None,
    target_fps: Optional[float] = None,
    scale_algorithm: str = "bicubic",
) -> Tuple[Optional[str], int, int, float]:
    """
    构建编码阶段的 -vf 滤镜字符串

    Args:
        src_width: 源视频宽度
        src_height: 源视频高度
        src_fps: 源视频帧率
        shortest_size: 最短边尺寸（可选）
        target_fps: 目标帧率（可选）
        scale_algorithm: 缩放算法，默认 bicubic

    Returns:
        (vf_filter, out_width, out_height, out_fps)
        - vf_filter: 滤镜字符串，如果不需要转换则为 None
        - out_width: 输出宽度
        - out_height: 输出高度
        - out_fps: 输出帧率
    """
    # 计算目标分辨率
    out_width, out_height = calculate_target_resolution(src_width, src_height, shortest_size)

    # 确定输出帧率
    out_fps = target_fps if target_fps else src_fps

    # 构建滤镜
    vf_filter = build_vf_filter(
        src_width=src_width,
        src_height=src_height,
        src_fps=src_fps,
        target_width=out_width,
        target_height=out_height,
        target_fps=out_fps,
        scale_algorithm=scale_algorithm,
    )

    return vf_filter, out_width, out_height, out_fps


def build_scoring_vf_filter(
    src_width: int,
    src_height: int,
    src_fps: float,
    enc_width: int,
    enc_height: int,
    enc_fps: float,
    upscale_to_source: bool = True,
    scale_algorithm: str = "bicubic",
) -> Tuple[Optional[str], Optional[str], int, int, float]:
    """
    构建打分阶段的 -vf 滤镜字符串

    Args:
        src_width: 源视频宽度
        src_height: 源视频高度
        src_fps: 源视频帧率
        enc_width: 编码后视频宽度
        enc_height: 编码后视频高度
        enc_fps: 编码后视频帧率
        upscale_to_source: Metrics策略，True=码流上采样到源分辨率
        scale_algorithm: 缩放算法，默认 bicubic

    Returns:
        (ref_vf_filter, enc_vf_filter, score_width, score_height, score_fps)
        - ref_vf_filter: 源视频滤镜字符串
        - enc_vf_filter: 编码视频滤镜字符串
        - score_width: 打分分辨率宽度
        - score_height: 打分分辨率高度
        - score_fps: 打分帧率
    """
    # 打分帧率 = 编码后帧率（源视频需要下采样到编码后帧率）
    score_fps = enc_fps

    if upscale_to_source:
        # 码流上采样到源分辨率
        score_width = src_width
        score_height = src_height

        # 源视频：只需要帧率转换
        ref_vf_filter = build_vf_filter(
            src_width=src_width,
            src_height=src_height,
            src_fps=src_fps,
            target_fps=score_fps,
            scale_algorithm=scale_algorithm,
        )

        # 编码视频：需要分辨率上采样
        enc_vf_filter = build_vf_filter(
            src_width=enc_width,
            src_height=enc_height,
            src_fps=enc_fps,
            target_width=score_width,
            target_height=score_height,
            scale_algorithm=scale_algorithm,
        )
    else:
        # 源视频下采样到码流分辨率
        score_width = enc_width
        score_height = enc_height

        # 源视频：需要帧率转换 + 分辨率下采样
        ref_vf_filter = build_vf_filter(
            src_width=src_width,
            src_height=src_height,
            src_fps=src_fps,
            target_width=score_width,
            target_height=score_height,
            target_fps=score_fps,
            scale_algorithm=scale_algorithm,
        )

        # 编码视频：不需要转换
        enc_vf_filter = None

    return ref_vf_filter, enc_vf_filter, score_width, score_height, score_fps
