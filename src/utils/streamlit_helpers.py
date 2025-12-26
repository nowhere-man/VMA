"""
Streamlit 页面公共工具模块

提供任务列表加载、报告读取等公共函数
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
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
    base_color: str = "#636efa",
    exp_color: str = "#f0553b",
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


def create_fps_chart(
    df_perf: "pd.DataFrame",
    base_label: str = "Baseline",
    exp_label: str = "Test",
    base_color: str = "#636efa",
    exp_color: str = "#f0553b",
) -> go.Figure:
    """
    创建 FPS 对比图表

    Args:
        df_perf: 性能数据 DataFrame，包含 Video, Side, Point, FPS 列
        base_label: 基准组标签
        exp_label: 实验组标签
        base_color: 基准组颜色
        exp_color: 实验组颜色

    Returns:
        Plotly Figure 对象
    """
    # 按 Video 和 Point 排序
    df_sorted = df_perf.sort_values(by=["Video", "Point"])

    # 创建 x 轴标签：Video_Point
    df_sorted["x_label"] = df_sorted["Video"].astype(str) + "_" + df_sorted["Point"].astype(str)

    # 分离 baseline 和 test 数据
    base_data = df_sorted[df_sorted["Side"] == base_label]
    exp_data = df_sorted[df_sorted["Side"] == exp_label]

    fig = go.Figure()

    # Baseline 折线
    if not base_data.empty:
        fig.add_trace(go.Scatter(
            x=base_data["x_label"],
            y=base_data["FPS"],
            mode="lines+markers",
            name=base_label,
            line=dict(color=base_color, width=2),
            marker=dict(size=8),
        ))

    # Test 折线
    if not exp_data.empty:
        fig.add_trace(go.Scatter(
            x=exp_data["x_label"],
            y=exp_data["FPS"],
            mode="lines+markers",
            name=exp_label,
            line=dict(color=exp_color, width=2),
            marker=dict(size=8),
        ))

    fig.update_layout(
        title="FPS 对比",
        xaxis_title="Video_Point",
        yaxis_title="FPS",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        xaxis=dict(tickangle=-45),
    )

    return fig


def color_positive_green(val):
    """
    正值显示绿色，负值显示红色（用于 FPS 等越大越好的指标）

    Args:
        val: 数值

    Returns:
        CSS 样式字符串
    """
    if pd.isna(val) or not isinstance(val, (int, float)):
        return ""
    if val > 0:
        return "color: green"
    elif val < 0:
        return "color: red"
    return ""


def color_positive_red(val):
    """
    正值显示红色，负值显示绿色（用于 CPU、Bitrate 等越小越好的指标）

    Args:
        val: 数值

    Returns:
        CSS 样式字符串
    """
    if pd.isna(val) or not isinstance(val, (int, float)):
        return ""
    if val > 0:
        return "color: red"
    elif val < 0:
        return "color: green"
    return ""


def format_env_info(env: Dict[str, Any]) -> str:
    """
    格式化环境信息为 Markdown 列表

    Args:
        env: 环境信息字典

    Returns:
        格式化后的 Markdown 字符串
    """
    if not env:
        return "未采集到环境信息。"

    lines = []

    # 系统信息
    lines.append("**系统信息**")
    os_name = env.get('os', 'N/A')
    hostname = env.get('hostname', 'N/A')
    linux_distro = env.get('linux_distro', '')

    lines.append(f"- **操作系统**: {os_name}")
    lines.append(f"- **主机名**: {hostname}")
    if os_name == "Linux" and linux_distro:
        lines.append(f"- **发行版**: {linux_distro}")

    lines.append("")  # 空行

    # CPU 信息
    lines.append("**CPU 信息**")
    cpu_model = env.get('cpu_model', env.get('cpu', 'N/A'))
    cpu_arch = env.get('cpu_arch', 'N/A')
    phys_cores = env.get('cpu_phys_cores', env.get('phys_cores', 'N/A'))
    log_cores = env.get('cpu_log_cores', env.get('log_cores', 'N/A'))
    cpu_freq = env.get('cpu_freq_mhz', 'N/A')
    numa_nodes = env.get('numa_nodes', 'N/A')
    cpu_percent = env.get('cpu_percent_before', env.get('cpu_percent_start', 'N/A'))

    lines.append(f"- **CPU 型号**: {cpu_model}")
    lines.append(f"- **CPU 架构**: {cpu_arch}")
    lines.append(f"- **核心/线程**: {phys_cores}C/{log_cores}T")
    lines.append(f"- **CPU 主频**: {cpu_freq} MHz")
    lines.append(f"- **NUMA Nodes**: {numa_nodes}")
    lines.append(f"- **CPU 占用率**: {cpu_percent}%")

    lines.append("")  # 空行

    # 内存信息
    lines.append("**内存信息**")
    # 兼容新旧格式
    mem_total_gb = env.get('mem_total_gb')
    mem_used_gb = env.get('mem_used_gb')
    mem_available_gb = env.get('mem_available_gb')
    mem_percent = env.get('mem_percent_used')

    # 如果是旧格式（MB），转换为 GB
    if mem_total_gb is None and env.get('mem_total_mb'):
        try:
            mem_total_gb = round(env.get('mem_total_mb') / 1024, 2)
        except (ValueError, TypeError):
            pass
    if mem_available_gb is None and env.get('mem_available_mb'):
        try:
            mem_available_gb = round(env.get('mem_available_mb') / 1024, 2)
        except (ValueError, TypeError):
            pass
    if mem_used_gb is None and mem_total_gb and mem_available_gb:
        mem_used_gb = round(mem_total_gb - mem_available_gb, 2)

    # 计算可用率
    mem_avail_percent = None
    if mem_percent is not None:
        mem_avail_percent = round(100 - mem_percent, 1)
    elif mem_total_gb and mem_available_gb:
        mem_avail_percent = round((mem_available_gb / mem_total_gb) * 100, 1)

    lines.append(f"- **总内存**: {mem_total_gb if mem_total_gb else 'N/A'} GB")
    lines.append(f"- **已使用**: {mem_used_gb if mem_used_gb else 'N/A'} GB")
    lines.append(f"- **可用内存**: {mem_available_gb if mem_available_gb else 'N/A'} GB")
    lines.append(f"- **可用率**: {mem_avail_percent if mem_avail_percent is not None else 'N/A'}%")

    lines.append("")  # 空行

    # 其他信息
    lines.append("**其他信息**")
    exec_time = env.get('execution_time', 'N/A')
    lines.append(f"- **运行时间**: {exec_time}")

    return "\n".join(lines)
