"""
质量指标解析器

解析FFmpeg生成的PSNR、SSIM、VMAF质量指标文件
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional


class MetricsParser:
    """质量指标解析器"""

    @staticmethod
    def parse_psnr_log(log_path: Path) -> Optional[Dict[str, float]]:
        """
        解析PSNR日志文件

        Args:
            log_path: PSNR日志文件路径

        Returns:
            包含PSNR指标的字典，如果解析失败则返回None
        """
        if not log_path.exists():
            return None

        try:
            with open(log_path, "r") as f:
                content = f.read()

            # 查找平均PSNR值
            # FFmpeg PSNR输出格式示例: [Parsed_psnr_0 @ ...] PSNR y:45.123 u:48.456 v:47.789 average:45.678 min:42.1 max:48.9
            match = re.search(
                r"PSNR\s+y:([\d.]+)\s+u:([\d.]+)\s+v:([\d.]+)\s+average:([\d.]+)",
                content,
                re.IGNORECASE,
            )

            if match:
                return {
                    "psnr_y": float(match.group(1)),
                    "psnr_u": float(match.group(2)),
                    "psnr_v": float(match.group(3)),
                    "psnr_avg": float(match.group(4)),
                }

            return None

        except Exception as e:
            print(f"解析PSNR日志失败 {log_path}: {str(e)}")
            return None

    @staticmethod
    def parse_ssim_log(log_path: Path) -> Optional[Dict[str, float]]:
        """
        解析SSIM日志文件

        Args:
            log_path: SSIM日志文件路径

        Returns:
            包含SSIM指标的字典，如果解析失败则返回None
        """
        if not log_path.exists():
            return None

        try:
            with open(log_path, "r") as f:
                content = f.read()

            # FFmpeg SSIM输出格式示例: [Parsed_ssim_0 @ ...] SSIM Y:0.9876 U:0.9901 V:0.9888 All:0.9885 (15.234)
            match = re.search(
                r"SSIM\s+Y:([\d.]+)\s+U:([\d.]+)\s+V:([\d.]+)\s+All:([\d.]+)",
                content,
                re.IGNORECASE,
            )

            if match:
                return {
                    "ssim_y": float(match.group(1)),
                    "ssim_u": float(match.group(2)),
                    "ssim_v": float(match.group(3)),
                    "ssim_avg": float(match.group(4)),
                }

            return None

        except Exception as e:
            print(f"解析SSIM日志失败 {log_path}: {str(e)}")
            return None

    @staticmethod
    def parse_vmaf_json(json_path: Path) -> Optional[Dict[str, float]]:
        """
        解析VMAF JSON文件

        Args:
            json_path: VMAF JSON文件路径

        Returns:
            包含VMAF指标的字典，如果解析失败则返回None
        """
        if not json_path.exists():
            return None

        try:
            with open(json_path, "r") as f:
                data = json.load(f)

            # VMAF JSON结构: {"pooled_metrics": {"vmaf": {"mean": 95.5, "harmonic_mean": 94.2}}}
            pooled = data.get("pooled_metrics", {})
            vmaf_data = pooled.get("vmaf", {})

            if vmaf_data:
                result = {
                    "vmaf_mean": vmaf_data.get("mean"),
                    "vmaf_harmonic_mean": vmaf_data.get("harmonic_mean"),
                }

                # 移除None值
                return {k: v for k, v in result.items() if v is not None}

            return None

        except Exception as e:
            print(f"解析VMAF JSON失败 {json_path}: {str(e)}")
            return None

    @staticmethod
    def calculate_bdrate(
        rate_quality_pairs_a: List[tuple], rate_quality_pairs_b: List[tuple]
    ) -> Optional[float]:
        """
        计算BD-rate（Bjontegaard Delta Rate）

        使用简化的分段线性插值方法

        Args:
            rate_quality_pairs_a: 第一组(bitrate, quality)对
            rate_quality_pairs_b: 第二组(bitrate, quality)对

        Returns:
            BD-rate百分比，如果无法计算则返回None
        """
        if len(rate_quality_pairs_a) < 2 or len(rate_quality_pairs_b) < 2:
            return None

        try:
            # 简化的BD-rate计算
            # 这里使用平均码率差异的近似方法
            # 实际的BD-rate计算需要更复杂的曲线拟合

            # 按质量排序
            pairs_a = sorted(rate_quality_pairs_a, key=lambda x: x[1])
            pairs_b = sorted(rate_quality_pairs_b, key=lambda x: x[1])

            # 找到质量重叠区间
            min_quality = max(pairs_a[0][1], pairs_b[0][1])
            max_quality = min(pairs_a[-1][1], pairs_b[-1][1])

            if min_quality >= max_quality:
                return None

            # 在重叠区间内采样并计算平均码率差异
            num_samples = 10
            quality_step = (max_quality - min_quality) / num_samples
            rate_diffs = []

            for i in range(num_samples + 1):
                q = min_quality + i * quality_step

                # 线性插值找到对应的码率
                rate_a = MetricsParser._interpolate_rate(pairs_a, q)
                rate_b = MetricsParser._interpolate_rate(pairs_b, q)

                if rate_a and rate_b and rate_a > 0:
                    rate_diff = (rate_b - rate_a) / rate_a * 100
                    rate_diffs.append(rate_diff)

            if not rate_diffs:
                return None

            # 返回平均BD-rate
            return sum(rate_diffs) / len(rate_diffs)

        except Exception as e:
            print(f"计算BD-rate失败: {str(e)}")
            return None

    @staticmethod
    def _interpolate_rate(
        pairs: List[tuple], target_quality: float
    ) -> Optional[float]:
        """线性插值找到目标质量对应的码率"""
        if not pairs or len(pairs) < 2:
            return None

        # 如果目标质量超出范围，返回None
        if target_quality < pairs[0][1] or target_quality > pairs[-1][1]:
            return None

        # 查找插值区间
        for i in range(len(pairs) - 1):
            q1, r1 = pairs[i][1], pairs[i][0]
            q2, r2 = pairs[i + 1][1], pairs[i + 1][0]

            if q1 <= target_quality <= q2:
                # 线性插值
                if q2 == q1:
                    return r1
                t = (target_quality - q1) / (q2 - q1)
                return r1 + t * (r2 - r1)

        return None


# 全局单例
metrics_parser = MetricsParser()
