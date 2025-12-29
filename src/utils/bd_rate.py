"""
BD-Rate 和 BD-Metrics 计算工具模块

基于 Bjontegaard Delta (BD) 算法计算视频编码质量指标的差异。
BD-Rate: 在相同质量下，码率节省的百分比
BD-Metrics: 在相同码率下，质量指标的差异
"""

from typing import List, Optional, Tuple

import numpy as np
import scipy.interpolate  # type: ignore


def _compute_integrals(
    x1: np.ndarray,
    y1: np.ndarray,
    x2: np.ndarray,
    y2: np.ndarray,
    piecewise: int,
) -> Tuple[Optional[float], Optional[float], float, float]:
    """
    计算两条曲线在公共区间上的积分

    Args:
        x1, y1: 第一条曲线的 x, y 数据
        x2, y2: 第二条曲线的 x, y 数据
        piecewise: 0 使用多项式积分，非0 使用分段插值

    Returns:
        (int1, int2, min_int, max_int) 元组，积分值和积分区间
        如果无法计算返回 (None, None, 0, 0)
    """
    try:
        p1 = np.polyfit(x1, y1, 3)
        p2 = np.polyfit(x2, y2, 3)
    except Exception:
        return None, None, 0, 0

    min_int = max(min(x1), min(x2))
    max_int = min(max(x1), max(x2))

    if max_int <= min_int:
        return None, None, 0, 0

    if piecewise == 0:
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)
        int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
        int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
    else:
        lin = np.linspace(min_int, max_int, num=100, retstep=True)
        interval = lin[1]
        samples = lin[0]
        v1 = scipy.interpolate.pchip_interpolate(
            np.sort(x1), y1[np.argsort(x1)], samples
        )
        v2 = scipy.interpolate.pchip_interpolate(
            np.sort(x2), y2[np.argsort(x2)], samples
        )
        int1 = np.trapz(v1, dx=interval)
        int2 = np.trapz(v2, dx=interval)

    return int1, int2, min_int, max_int


def bd_rate(
    rate1: List[float],
    metric1: List[float],
    rate2: List[float],
    metric2: List[float],
    piecewise: int = 0,
) -> Optional[float]:
    """
    计算 BD-Rate (Bjontegaard Delta Rate)

    在相同质量指标下，计算码率节省的百分比。
    负值表示 rate2 相比 rate1 节省了码率（更好）。

    Args:
        rate1: 参考组的码率列表（至少4个点）
        metric1: 参考组的质量指标列表（如 PSNR, VMAF）
        rate2: 实验组的码率列表（至少4个点）
        metric2: 实验组的质量指标列表
        piecewise: 0 使用多项式积分，非0 使用分段插值

    Returns:
        BD-Rate 百分比，负值表示码率节省；None 表示无法计算
    """
    if len(rate1) < 4 or len(rate2) < 4:
        return None

    lR1 = np.log(rate1)
    lR2 = np.log(rate2)
    m1_arr = np.array(metric1)
    m2_arr = np.array(metric2)

    int1, int2, min_int, max_int = _compute_integrals(m1_arr, lR1, m2_arr, lR2, piecewise)
    if int1 is None or int2 is None:
        return None

    avg_test_diff = (int2 - int1) / (max_int - min_int)
    return (np.exp(avg_test_diff) - 1) * 100


def bd_metrics(
    rate1: List[float],
    metric1: List[float],
    rate2: List[float],
    metric2: List[float],
    piecewise: int = 0,
) -> Optional[float]:
    """
    计算 BD-Metrics (Bjontegaard Delta Metrics)

    在相同码率下，计算质量指标的差异。
    正值表示 metric2 相比 metric1 质量更好。

    Args:
        rate1: 参考组的码率列表（至少4个点）
        metric1: 参考组的质量指标列表（如 PSNR, VMAF）
        rate2: 实验组的码率列表（至少4个点）
        metric2: 实验组的质量指标列表
        piecewise: 0 使用多项式积分，非0 使用分段插值

    Returns:
        BD-Metrics 差值，正值表示质量提升；None 表示无法计算
    """
    if len(rate1) < 4 or len(rate2) < 4:
        return None

    lR1 = np.log(rate1)
    lR2 = np.log(rate2)
    m1 = np.array(metric1)
    m2 = np.array(metric2)

    int1, int2, min_int, max_int = _compute_integrals(lR1, m1, lR2, m2, piecewise)
    if int1 is None or int2 is None:
        return None

    avg_diff = (int2 - int1) / (max_int - min_int)
    return avg_diff
