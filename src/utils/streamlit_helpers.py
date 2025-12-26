"""
Streamlit 页面公共工具模块

提供任务列表加载、报告读取等公共函数
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import plotly.graph_objects as go
import streamlit as st

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.config import settings


def jobs_root_dir() -> Path:
    """获取任务根目录"""
    root = settings.jobs_root_dir
    if root.is_absolute():
        return root
    return (project_root / root).resolve()


def list_jobs(
    report_subpath: str,
    limit: int = 50,
    check_status: bool = False,
) -> List[Dict[str, Any]]:
    """
    列出包含指定报告文件的任务

    Args:
        report_subpath: 报告文件相对于任务目录的路径，如 "metrics_analysis/report_data.json"
        limit: 返回的最大任务数
        check_status: 是否检查任务状态（仅返回已完成的任务）

    Returns:
        任务列表，按修改时间倒序排列
    """
    root = jobs_root_dir()
    if not root.exists():
        return []

    items: List[Dict[str, Any]] = []
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        report_path = job_dir / report_subpath
        if not report_path.exists():
            continue

        item: Dict[str, Any] = {
            "job_id": job_dir.name,
            "mtime": report_path.stat().st_mtime,
            "report_path": report_path,
        }

        # 读取报告数据以提取元信息
        try:
            report_data = json.loads(report_path.read_text(encoding="utf-8"))
            item["report_data"] = report_data
        except Exception:
            item["report_data"] = {}

        if check_status:
            meta_path = job_dir / "metadata.json"
            status_ok = True
            try:
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    status_ok = meta.get("status") == "COMPLETED"
            except Exception:
                status_ok = True
            item["status_ok"] = status_ok

        items.append(item)

    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def get_query_param(param_name: str) -> Optional[str]:
    """
    获取 URL 查询参数

    Args:
        param_name: 参数名

    Returns:
        参数值，如果不存在则返回 None
    """
    value = st.query_params.get(param_name)
    if value:
        if isinstance(value, list):
            value = value[0] if value else None
        return str(value) if value else None
    return None


def load_json_report(job_id: str, report_subpath: str) -> Dict[str, Any]:
    """
    加载任务的 JSON 报告文件

    Args:
        job_id: 任务 ID
        report_subpath: 报告文件相对于任务目录的路径

    Returns:
        报告数据字典

    Raises:
        FileNotFoundError: 报告文件不存在
    """
    report_path = jobs_root_dir() / job_id / report_subpath
    if not report_path.exists():
        raise FileNotFoundError(f"未找到报告数据文件: {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def parse_rate_point(label: str) -> tuple[Optional[str], Optional[float]]:
    """
    解析码率点位标签

    从文件名或标签中提取码率控制模式和值
    格式: name_rc_value 或 name_rc_value.ext

    Args:
        label: 标签字符串

    Returns:
        (rc_mode, value) 元组
    """
    if not label:
        return None, None
    # 去掉文件扩展名
    label_no_ext = label.rsplit(".", 1)[0] if "." in label else label
    parts = label_no_ext.rsplit("_", 2)
    if len(parts) < 3:
        return None, None
    rc = parts[-2]
    try:
        val = float(parts[-1])
    except (ValueError, TypeError):
        return rc, None
    return rc, val


# ========== CPU 图表相关 ==========

def aggregate_cpu_samples(samples: List[float], interval_ms: int) -> Tuple[List[float], List[float]]:
    """
    聚合 CPU 采样数据

    Args:
        samples: CPU 采样数据列表（原始采样间隔为 100ms）
        interval_ms: 聚合间隔（毫秒）

    Returns:
        (x_values, y_values) 元组，x 为时间（秒），y 为 CPU 占用率
    """
    if not samples:
        return [], []
    # 原始采样间隔为100ms
    step = interval_ms // 100
    if step <= 1:
        # 不聚合
        x = [i * 0.1 for i in range(len(samples))]
        return x, samples
    # 聚合
    agg_samples = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i+step]
        if chunk:
            agg_samples.append(sum(chunk) / len(chunk))
    x = [i * (interval_ms / 1000) for i in range(len(agg_samples))]
    return x, agg_samples


def create_cpu_chart(
    base_samples: List[float],
    exp_samples: List[float],
    agg_interval: int,
    title: str,
    base_label: str = "Baseline",
    exp_label: str = "Test",
    base_color: str = "#2563eb",
    exp_color: str = "#dc2626",
) -> go.Figure:
    """
    创建 CPU 占用率对比图表

    Args:
        base_samples: 基准组 CPU 采样数据
        exp_samples: 实验组 CPU 采样数据
        agg_interval: 聚合间隔（毫秒）
        title: 图表标题
        base_label: 基准组标签
        exp_label: 实验组标签
        base_color: 基准组颜色
        exp_color: 实验组颜色

    Returns:
        Plotly Figure 对象
    """
    base_x, base_y = aggregate_cpu_samples(base_samples, agg_interval)
    exp_x, exp_y = aggregate_cpu_samples(exp_samples, agg_interval)

    fig = go.Figure()

    # 基准组折线
    if base_y:
        fig.add_trace(go.Scatter(
            x=base_x, y=base_y,
            mode="lines",
            name=base_label,
            line=dict(color=base_color, width=2),
        ))
        # 标记最大值
        max_idx = base_y.index(max(base_y))
        fig.add_trace(go.Scatter(
            x=[base_x[max_idx]], y=[base_y[max_idx]],
            mode="markers+text",
            name=f"{base_label} Max",
            marker=dict(color=base_color, size=12, symbol="star"),
            text=[f"Max: {base_y[max_idx]:.1f}%"],
            textposition="top center",
            showlegend=False,
        ))

    # 实验组折线
    if exp_y:
        fig.add_trace(go.Scatter(
            x=exp_x, y=exp_y,
            mode="lines",
            name=exp_label,
            line=dict(color=exp_color, width=2),
        ))
        # 标记最大值
        max_idx = exp_y.index(max(exp_y))
        fig.add_trace(go.Scatter(
            x=[exp_x[max_idx]], y=[exp_y[max_idx]],
            mode="markers+text",
            name=f"{exp_label} Max",
            marker=dict(color=exp_color, size=12, symbol="star"),
            text=[f"Max: {exp_y[max_idx]:.1f}%"],
            textposition="top center",
            showlegend=False,
        ))

    fig.update_layout(
        title=title,
        xaxis_title="Time (s)",
        yaxis_title="CPU (%)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )

    return fig
