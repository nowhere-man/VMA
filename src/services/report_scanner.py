"""
报告扫描服务

扫描并聚合转码模板生成的质量分析报告
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from src.services.template_storage import template_storage
from src.services.metrics_parser import metrics_parser


class ReportScanner:
    """报告扫描服务"""

    def scan_all_reports(self) -> List[Dict]:
        """
        扫描所有模板生成的报告

        Returns:
            报告数据列表
        """
        reports = []
        templates = template_storage.list_templates()

        for template in templates:
            template_reports = self._scan_template_reports(template)
            reports.extend(template_reports)

        # 按时间排序（最新的在前）
        reports.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return reports

    def _scan_template_reports(self, template) -> List[Dict]:
        """扫描单个模板的报告"""
        reports = []
        metadata = template.metadata

        # 获取metrics报告目录
        metrics_dir = Path(metadata.metrics_report_dir)
        if not metrics_dir.exists():
            return reports

        # 扫描所有PSNR、SSIM、VMAF文件
        psnr_files = list(metrics_dir.glob("*_psnr.log"))
        ssim_files = list(metrics_dir.glob("*_ssim.log"))
        vmaf_files = list(metrics_dir.glob("*_vmaf.json"))

        # 按文件名前缀分组
        file_groups = {}

        for psnr_file in psnr_files:
            prefix = psnr_file.stem.replace("_psnr", "")
            if prefix not in file_groups:
                file_groups[prefix] = {}
            file_groups[prefix]["psnr"] = psnr_file

        for ssim_file in ssim_files:
            prefix = ssim_file.stem.replace("_ssim", "")
            if prefix not in file_groups:
                file_groups[prefix] = {}
            file_groups[prefix]["ssim"] = ssim_file

        for vmaf_file in vmaf_files:
            prefix = vmaf_file.stem.replace("_vmaf", "")
            if prefix not in file_groups:
                file_groups[prefix] = {}
            file_groups[prefix]["vmaf"] = vmaf_file

        # 为每组文件创建报告条目
        for prefix, files in file_groups.items():
            report = self._create_report_entry(template, prefix, files)
            if report:
                reports.append(report)

        return reports

    def _create_report_entry(
        self, template, file_prefix: str, metric_files: Dict[str, Path]
    ) -> Optional[Dict]:
        """创建单个报告条目"""
        metrics = {}

        # 解析PSNR
        if "psnr" in metric_files:
            psnr_data = metrics_parser.parse_psnr_log(metric_files["psnr"])
            if psnr_data:
                metrics.update(psnr_data)

        # 解析SSIM
        if "ssim" in metric_files:
            ssim_data = metrics_parser.parse_ssim_log(metric_files["ssim"])
            if ssim_data:
                metrics.update(ssim_data)

        # 解析VMAF
        if "vmaf" in metric_files:
            vmaf_data = metrics_parser.parse_vmaf_json(metric_files["vmaf"])
            if vmaf_data:
                metrics.update(vmaf_data)

        # 如果没有任何指标，跳过
        if not metrics:
            return None

        # 获取最新文件的时间戳
        timestamps = []
        for file_path in metric_files.values():
            if file_path.exists():
                timestamps.append(file_path.stat().st_mtime)

        timestamp = max(timestamps) if timestamps else 0

        metadata = template.metadata

        return {
            "report_id": f"{metadata.template_id}_{file_prefix}",
            "file_name": file_prefix,
            "template_id": metadata.template_id,
            "template_name": metadata.name,
            "template_description": metadata.description,
            "encoder_type": metadata.encoder_type.value if metadata.encoder_type else None,
            "encoder_params": metadata.encoder_params,
            "mode": metadata.mode.value,
            "metrics": metrics,
            "timestamp": timestamp,
            "created_at": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            "metric_files": {
                k: str(v) for k, v in metric_files.items()
            },
        }

    def get_report_by_id(self, report_id: str) -> Optional[Dict]:
        """
        根据report_id获取单个报告

        Args:
            report_id: 报告ID（格式：template_id_file_prefix）

        Returns:
            报告数据字典，如果不存在则返回None
        """
        all_reports = self.scan_all_reports()
        for report in all_reports:
            if report["report_id"] == report_id:
                return report
        return None

    def get_reports_by_template(self, template_id: str) -> List[Dict]:
        """
        获取指定模板的所有报告

        Args:
            template_id: 模板ID

        Returns:
            报告列表
        """
        all_reports = self.scan_all_reports()
        return [r for r in all_reports if r["template_id"] == template_id]

    def get_template_summary(self) -> Dict[str, int]:
        """
        获取模板报告统计

        Returns:
            包含各模板报告数量的字典
        """
        all_reports = self.scan_all_reports()
        summary = {}

        for report in all_reports:
            template_id = report["template_id"]
            summary[template_id] = summary.get(template_id, 0) + 1

        return summary


# 全局单例
report_scanner = ReportScanner()
