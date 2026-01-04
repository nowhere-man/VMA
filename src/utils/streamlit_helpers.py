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
        report_subpath: 报告文件相对于任务目录的路径，如 "metrics_analysis/metrics_analysis.json"
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
                    status_ok = meta.get("status") == "completed"
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
    anchor_samples: List[float],
    test_samples: List[float],
    agg_interval: int,
    title: str,
    anchor_label: str = "Anchor",
    test_label: str = "Test",
    anchor_color: str = "#636efa",
    test_color: str = "#f0553b",
) -> go.Figure:
    """
    创建 CPU 占用率对比图表

    Args:
        anchor_samples: 基准组 CPU 采样数据
        test_samples: 实验组 CPU 采样数据
        agg_interval: 聚合间隔（毫秒）
        title: 图表标题
        anchor_label: 基准组标签
        test_label: 实验组标签
        anchor_color: 基准组颜色
        test_color: 实验组颜色

    Returns:
        Plotly Figure 对象
    """
    anchor_x, anchor_y = aggregate_cpu_samples(anchor_samples, agg_interval)
    test_x, test_y = aggregate_cpu_samples(test_samples, agg_interval)

    fig = go.Figure()

    # 基准组折线
    if anchor_y:
        fig.add_trace(go.Scatter(
            x=anchor_x, y=anchor_y,
            mode="lines",
            name=anchor_label,
            line=dict(color=anchor_color, width=2),
        ))
        # 标记最大值
        max_idx = anchor_y.index(max(anchor_y))
        fig.add_trace(go.Scatter(
            x=[anchor_x[max_idx]], y=[anchor_y[max_idx]],
            mode="markers+text",
            name=f"{anchor_label} Max",
            marker=dict(color=anchor_color, size=12, symbol="star"),
            text=[f"Max: {anchor_y[max_idx]:.1f}%"],
            textposition="top center",
            showlegend=False,
        ))

    # 实验组折线
    if test_y:
        fig.add_trace(go.Scatter(
            x=test_x, y=test_y,
            mode="lines",
            name=test_label,
            line=dict(color=test_color, width=2),
        ))
        # 标记最大值
        max_idx = test_y.index(max(test_y))
        fig.add_trace(go.Scatter(
            x=[test_x[max_idx]], y=[test_y[max_idx]],
            mode="markers+text",
            name=f"{test_label} Max",
            marker=dict(color=test_color, size=12, symbol="star"),
            text=[f"Max: {test_y[max_idx]:.1f}%"],
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
    anchor_label: str = "Anchor",
    test_label: str = "Test",
    anchor_color: str = "#636efa",
    test_color: str = "#f0553b",
) -> go.Figure:
    """
    创建 FPS 对比图表

    Args:
        df_perf: 性能数据 DataFrame，包含 Video, Side, Point, FPS 列
        anchor_label: 基准组标签
        test_label: 实验组标签
        anchor_color: 基准组颜色
        test_color: 实验组颜色

    Returns:
        Plotly Figure 对象
    """
    # 按 Video 和 Point 排序
    df_sorted = df_perf.sort_values(by=["Video", "Point"])

    # 创建 x 轴标签：Video_Point
    df_sorted["x_label"] = df_sorted["Video"].astype(str) + "_" + df_sorted["Point"].astype(str)

    # 分离 anchor 和 test 数据
    anchor_data = df_sorted[df_sorted["Side"] == anchor_label]
    test_data = df_sorted[df_sorted["Side"] == test_label]

    fig = go.Figure()

    # Anchor 折线
    if not anchor_data.empty:
        fig.add_trace(go.Scatter(
            x=anchor_data["x_label"],
            y=anchor_data["FPS"],
            mode="lines+markers",
            name=anchor_label,
            line=dict(color=anchor_color, width=2),
            marker=dict(size=8),
        ))

    # Test 折线
    if not test_data.empty:
        fig.add_trace(go.Scatter(
            x=test_data["x_label"],
            y=test_data["FPS"],
            mode="lines+markers",
            name=test_label,
            line=dict(color=test_color, width=2),
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


def _summary_stats(series: "pd.Series") -> Tuple[Any, Any, Any]:
    clean = series.dropna()
    if clean.empty:
        return pd.NA, pd.NA, pd.NA
    return clean.mean(), clean.max(), clean.min()


def _build_sign_styles(
    df: "pd.DataFrame",
    default_rule: Tuple[str, str],
    row_rules: Optional[Dict[str, Tuple[str, str]]] = None,
) -> "pd.DataFrame":
    rules = row_rules or {}
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    for row_label in df.index:
        pos_color, neg_color = rules.get(row_label, default_rule)
        for col in df.columns:
            value = df.at[row_label, col]
            if pd.isna(value) or not isinstance(value, (int, float)):
                styles.at[row_label, col] = "color: #94a3b8;"
            elif value > 0:
                styles.at[row_label, col] = f"color: {pos_color};"
            elif value < 0:
                styles.at[row_label, col] = f"color: {neg_color};"
            else:
                styles.at[row_label, col] = ""
    return styles


def _render_overall_table(
    title: str,
    df: "pd.DataFrame",
    fmt: str,
    suffix: str,
    default_rule: Tuple[str, str],
    row_rules: Optional[Dict[str, Tuple[str, str]]] = None,
    empty_text: Optional[str] = None,
) -> None:
    if df.empty:
        st.info(empty_text or "暂无数据。")
        return

    styles = _build_sign_styles(df, default_rule, row_rules)

    def _format_value(value: Any) -> str:
        if pd.isna(value) or not isinstance(value, (int, float)):
            return "--"
        return f"{format(value, fmt)}{suffix}"

    styler = (
        df.style.apply(lambda _: styles, axis=None)
        .format(_format_value)
        .set_properties(**{"text-align": "right", "font-weight": "600"})
        .set_table_styles([{"selector": "th", "props": [("text-align", "right")]}])
    )

    st.markdown(f"**{title}**")
    st.dataframe(styler, use_container_width=True)


def render_delta_bar_chart_by_point(
    df: "pd.DataFrame",
    point_col: str,
    metric_options: List[str],
    metric_config: Dict[str, Dict[str, str]],
    point_select_label: str,
    metric_select_label: str,
    point_select_key: str,
    metric_select_key: str,
    video_col: str = "Video",
    empty_point_msg: str = "暂无可用的码率点位数据。",
    empty_data_msg: str = "暂无对应点位的 Delta 数据。",
) -> None:
    if df.empty:
        st.info(empty_data_msg)
        return

    point_options = sorted(df[point_col].dropna().unique().tolist())
    if not point_options:
        st.info(empty_point_msg)
        return

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        selected_point = st.selectbox(point_select_label, point_options, key=point_select_key)
    with col_sel2:
        selected_metric = st.selectbox(metric_select_label, metric_options, key=metric_select_key)

    chart_source = df[df[point_col] == selected_point]
    if chart_source.empty:
        st.info(empty_data_msg)
        return

    agg_chart = chart_source.groupby(video_col)[selected_metric].mean().reset_index()
    video_order = chart_source[video_col].dropna().unique().tolist()
    agg_chart[video_col] = pd.Categorical(agg_chart[video_col], categories=video_order, ordered=True)
    agg_chart = agg_chart.sort_values(video_col)

    default_cfg = {"fmt": "{:+.2f}", "pos": "#00cc96", "neg": "#ef553b"}
    cfg = metric_config.get(selected_metric, default_cfg)
    colors = []
    texts = []
    for value in agg_chart[selected_metric]:
        if pd.isna(value) or not isinstance(value, (int, float)):
            colors.append("gray")
            texts.append("")
        elif value > 0:
            colors.append(cfg.get("pos", default_cfg["pos"]))
            texts.append(cfg.get("fmt", default_cfg["fmt"]).format(value))
        elif value < 0:
            colors.append(cfg.get("neg", default_cfg["neg"]))
            texts.append(cfg.get("fmt", default_cfg["fmt"]).format(value))
        else:
            colors.append("gray")
            texts.append(cfg.get("fmt", default_cfg["fmt"]).format(value))

    fig_delta = go.Figure(
        go.Bar(
            x=agg_chart[video_col],
            y=agg_chart[selected_metric],
            marker_color=colors,
            text=texts,
            textposition="outside",
        )
    )
    fig_delta.update_layout(
        xaxis_title=video_col,
        yaxis_title=selected_metric,
    )
    st.plotly_chart(fig_delta, use_container_width=True)


def render_delta_table_expander(
    title: str,
    styled_df: Any,
    column_config: Optional[Dict[str, Any]] = None,
) -> None:
    with st.expander(title, expanded=False):
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
        )


def render_overall_section(
    df_metrics: "pd.DataFrame",
    df_perf: "pd.DataFrame",
    bd_list: List[Dict[str, Any]],
    anchor_label: str = "Anchor",
    test_label: str = "Test",
    show_bd: bool = True,
) -> None:
    """
    渲染 Overall 汇总部分

    Args:
        df_metrics: 指标数据 DataFrame，包含 Video, Side, RC, Point, Bitrate_kbps, PSNR, SSIM, VMAF, VMAF-NEG 列
        df_perf: 性能数据 DataFrame，包含 Video, Side, Point, FPS, CPU Avg(%) 列
        bd_list: BD-Rate/BD-Metrics 数据列表
        anchor_label: 基准组标签
        test_label: 实验组标签
        show_bd: 是否展示 BD-Rate / BD-Metrics 汇总
    """
    if df_metrics.empty:
        st.info("暂无可用的指标数据。")
        return

    # 获取所有点位
    point_list = sorted(df_metrics["Point"].dropna().unique().tolist())

    if not point_list:
        st.info("暂无可用的码率点位数据。")
        return

    # ===== BD-Rate / BD-Metrics =====
    if show_bd:
        if bd_list:
            df_bd = pd.DataFrame(bd_list)
            bd_psnr_avg, bd_psnr_max, bd_psnr_min = _summary_stats(df_bd["bd_rate_psnr"])
            bd_ssim_avg, bd_ssim_max, bd_ssim_min = _summary_stats(df_bd["bd_rate_ssim"])
            bd_vmaf_avg, bd_vmaf_max, bd_vmaf_min = _summary_stats(df_bd["bd_rate_vmaf"])
            bd_vmaf_neg_avg, bd_vmaf_neg_max, bd_vmaf_neg_min = _summary_stats(df_bd["bd_rate_vmaf_neg"])

            bd_rate_df = pd.DataFrame(
                {
                    "平均": [bd_psnr_avg, bd_ssim_avg, bd_vmaf_avg, bd_vmaf_neg_avg],
                    "最大": [bd_psnr_max, bd_ssim_max, bd_vmaf_max, bd_vmaf_neg_max],
                    "最小": [bd_psnr_min, bd_ssim_min, bd_vmaf_min, bd_vmaf_neg_min],
                },
                index=["PSNR", "SSIM", "VMAF", "VMAF-NEG"],
            )

            bd_m_psnr_avg, bd_m_psnr_max, bd_m_psnr_min = _summary_stats(df_bd["bd_psnr"])
            bd_m_ssim_avg, bd_m_ssim_max, bd_m_ssim_min = _summary_stats(df_bd["bd_ssim"])
            bd_m_vmaf_avg, bd_m_vmaf_max, bd_m_vmaf_min = _summary_stats(df_bd["bd_vmaf"])
            bd_m_vmaf_neg_avg, bd_m_vmaf_neg_max, bd_m_vmaf_neg_min = _summary_stats(df_bd["bd_vmaf_neg"])

            bd_metrics_df = pd.DataFrame(
                {
                    "平均": [bd_m_psnr_avg, bd_m_ssim_avg, bd_m_vmaf_avg, bd_m_vmaf_neg_avg],
                    "最大": [bd_m_psnr_max, bd_m_ssim_max, bd_m_vmaf_max, bd_m_vmaf_neg_max],
                    "最小": [bd_m_psnr_min, bd_m_ssim_min, bd_m_vmaf_min, bd_m_vmaf_neg_min],
                },
                index=["PSNR", "SSIM", "VMAF", "VMAF-NEG"],
            )

            bd_rate_col, bd_metrics_col = st.columns(2)
            with bd_rate_col:
                _render_overall_table(
                    "BD-Rate",
                    bd_rate_df,
                    "+.2f",
                    "%",
                    ("red", "green"),
                    empty_text="暂无 BD-Rate 数据。",
                )
            with bd_metrics_col:
                _render_overall_table(
                    "BD-Metrics",
                    bd_metrics_df,
                    "+.4f",
                    "",
                    ("green", "red"),
                    empty_text="暂无 BD-Metrics 数据。",
                )
        else:
            st.info("暂无 BD-Rate / BD-Metrics 数据。")

    point_label_col, point_select_col, point_spacer_col = st.columns([1, 2, 6])
    with point_label_col:
        st.markdown("**码率点位**")
    with point_select_col:
        selected_point = st.selectbox(
            "选择码率点位",
            point_list,
            key="overall_point",
            label_visibility="collapsed",
        )
    point_spacer_col.empty()

    # 筛选选中点位的数据
    point_df = df_metrics[df_metrics["Point"] == selected_point]
    anchor_point = point_df[point_df["Side"] == anchor_label]
    test_point = point_df[point_df["Side"] == test_label]

    # 合并 anchor 和 test
    merged_point = anchor_point.merge(
        test_point,
        on=["Video", "RC", "Point"],
        suffixes=("_anchor", "_test"),
    )

    if merged_point.empty:
        st.warning("选中点位没有可对比的数据。")
        return

    performance_df = pd.DataFrame()

    psnr_diff = merged_point["PSNR_test"] - merged_point["PSNR_anchor"]
    psnr_avg, psnr_max, psnr_min = _summary_stats(psnr_diff)

    ssim_diff = merged_point["SSIM_test"] - merged_point["SSIM_anchor"]
    ssim_avg, ssim_max, ssim_min = _summary_stats(ssim_diff)

    vmaf_diff = merged_point["VMAF_test"] - merged_point["VMAF_anchor"]
    vmaf_avg, vmaf_max, vmaf_min = _summary_stats(vmaf_diff)

    vmaf_neg_diff = merged_point["VMAF-NEG_test"] - merged_point["VMAF-NEG_anchor"]
    vmaf_neg_avg, vmaf_neg_max, vmaf_neg_min = _summary_stats(vmaf_neg_diff)

    metrics_df = pd.DataFrame(
        {
            "平均": [psnr_avg, ssim_avg, vmaf_avg, vmaf_neg_avg],
            "最大": [psnr_max, ssim_max, vmaf_max, vmaf_neg_max],
            "最小": [psnr_min, ssim_min, vmaf_min, vmaf_neg_min],
        },
        index=["PSNR", "SSIM", "VMAF", "VMAF-NEG"],
    )

    if not df_perf.empty:
        perf_point_df = df_perf[df_perf["Point"] == selected_point]
        anchor_perf_point = perf_point_df[perf_point_df["Side"] == anchor_label]
        test_perf_point = perf_point_df[perf_point_df["Side"] == test_label]
        merged_perf_point = anchor_perf_point.merge(
            test_perf_point,
            on=["Video", "Point"],
            suffixes=("_anchor", "_test"),
        )

        if not merged_perf_point.empty:
            cpu_diff_pct_series = ((merged_perf_point["CPU Avg(%)_test"] - merged_perf_point["CPU Avg(%)_anchor"]) / merged_perf_point["CPU Avg(%)_anchor"].replace(0, pd.NA)) * 100
            cpu_avg_pct, cpu_max_pct, cpu_min_pct = _summary_stats(cpu_diff_pct_series)

            fps_diff_pct_series = ((merged_perf_point["FPS_test"] - merged_perf_point["FPS_anchor"]) / merged_perf_point["FPS_anchor"].replace(0, pd.NA)) * 100
            fps_avg_pct, fps_max_pct, fps_min_pct = _summary_stats(fps_diff_pct_series)

            performance_df = pd.DataFrame(
                {
                    "平均": [cpu_avg_pct, fps_avg_pct],
                    "最大": [cpu_max_pct, fps_max_pct],
                    "最小": [cpu_min_pct, fps_min_pct],
                },
                index=["CPU Usage", "FPS"],
            )

    bitrate_diff_pct_series = ((merged_point["Bitrate_kbps_test"] - merged_point["Bitrate_kbps_anchor"]) / merged_point["Bitrate_kbps_anchor"].replace(0, pd.NA)) * 100
    bitrate_avg, bitrate_max, bitrate_min = _summary_stats(bitrate_diff_pct_series)
    bitrate_df = pd.DataFrame(
        {
            "平均": [bitrate_avg],
            "最大": [bitrate_max],
            "最小": [bitrate_min],
        },
        index=["Bitrate"],
    )

    metrics_col, perf_bitrate_col = st.columns(2)
    with metrics_col:
        _render_overall_table(
            "Metrics",
            metrics_df,
            "+.4f",
            "",
            ("green", "red"),
            empty_text="暂无 Metrics 数据。",
        )
    with perf_bitrate_col:
        _render_overall_table(
            "Performance",
            performance_df,
            "+.2f",
            "%",
            ("green", "red"),
            row_rules={"CPU Usage": ("red", "green")},
            empty_text="暂无 Performance 数据。",
        )
        _render_overall_table(
            "Bitrate",
            bitrate_df,
            "+.2f",
            "%",
            ("red", "green"),
            empty_text="暂无 Bitrate 数据。",
        )


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


# ========== Metrics Analysis 共享函数 ==========

def list_metrics_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    """列出 Metrics Analysis 任务"""
    return list_jobs("metrics_analysis/metrics_analysis.json", limit=limit, check_status=True)


def format_job_label(job: Dict[str, Any]) -> str:
    """格式化任务显示标签: <template-name>_<yyyy-MM-dd_hh:mm:ss>_<task-id>"""
    from datetime import datetime

    job_id = job.get("job_id", "unknown")
    template_name = job.get("report_data", {}).get("template_name", "unknown")

    mtime = job.get("mtime", 0)
    dt = datetime.fromtimestamp(mtime)
    timestamp = dt.strftime("%Y-%m-%d_%H:%M:%S")

    return f"{template_name}_{timestamp}_{job_id}"


def load_analyse(job_id: str) -> Dict[str, Any]:
    """加载 Metrics Analysis 任务数据"""
    return load_json_report(job_id, "metrics_analysis/metrics_analysis.json")


def metric_value(metrics: Dict[str, Any], name: str, field: str) -> Optional[float]:
    """从 metrics 字典中提取指标值"""
    block = metrics.get(name) or {}
    if not isinstance(block, dict):
        return None
    return block.get(field)


def _format_encoder_type(value: Optional[Any]) -> str:
    """格式化编码器类型"""
    if isinstance(value, str):
        return value or "-"
    if value is not None:
        return getattr(value, "value", str(value))
    return "-"


def _format_encoder_params(encoder_params: Optional[str]) -> str:
    """格式化编码器参数"""
    return encoder_params or "-"


def _format_points(points: Optional[List[float]]) -> str:
    """格式化码率点位列表"""
    if not points:
        return "-"
    clean = [p for p in points if isinstance(p, (int, float))]
    if not clean:
        return "-"
    return ", ".join(f"{p:g}" for p in sorted(set(clean)))


def _format_env_info_with_diff(env: Dict[str, Any], other_env: Dict[str, Any]) -> str:
    """格式化环境信息，标红不同的字段

    Args:
        env: 当前环境信息
        other_env: 对比环境信息

    Returns:
        包含 HTML 标签的 Markdown 字符串
    """
    if not env:
        return "未采集到环境信息。"

    def _highlight_if_diff(value: Any, other_value: Any) -> str:
        """如果值不同，返回红色高亮的 HTML"""
        value_str = str(value) if value is not None else 'N/A'
        other_str = str(other_value) if other_value is not None else 'N/A'
        if value_str != other_str:
            return f'<span style="color: red;">{value_str}</span>'
        return value_str

    lines = []

    # 系统信息
    lines.append("**系统信息**")
    os_name = env.get('os', 'N/A')
    other_os = other_env.get('os', 'N/A')
    hostname = env.get('hostname', 'N/A')
    other_hostname = other_env.get('hostname', 'N/A')
    linux_distro = env.get('linux_distro', '')
    other_distro = other_env.get('linux_distro', '')

    lines.append(f"- **操作系统**: {_highlight_if_diff(os_name, other_os)}")
    lines.append(f"- **主机名**: {_highlight_if_diff(hostname, other_hostname)}")
    if os_name == "Linux" and linux_distro:
        lines.append(f"- **发行版**: {_highlight_if_diff(linux_distro, other_distro)}")

    lines.append("")  # 空行

    # CPU 信息
    lines.append("**CPU 信息**")
    cpu_model = env.get('cpu_model', env.get('cpu', 'N/A'))
    other_cpu_model = other_env.get('cpu_model', other_env.get('cpu', 'N/A'))
    cpu_arch = env.get('cpu_arch', 'N/A')
    other_cpu_arch = other_env.get('cpu_arch', 'N/A')
    phys_cores = env.get('cpu_phys_cores', env.get('phys_cores', 'N/A'))
    other_phys_cores = other_env.get('cpu_phys_cores', other_env.get('phys_cores', 'N/A'))
    log_cores = env.get('cpu_log_cores', env.get('log_cores', 'N/A'))
    other_log_cores = other_env.get('cpu_log_cores', other_env.get('log_cores', 'N/A'))
    cpu_freq = env.get('cpu_freq_mhz', 'N/A')
    other_cpu_freq = other_env.get('cpu_freq_mhz', 'N/A')
    numa_nodes = env.get('numa_nodes', 'N/A')
    other_numa_nodes = other_env.get('numa_nodes', 'N/A')
    cpu_percent = env.get('cpu_percent_before', env.get('cpu_percent_start', 'N/A'))
    other_cpu_percent = other_env.get('cpu_percent_before', other_env.get('cpu_percent_start', 'N/A'))

    lines.append(f"- **CPU 型号**: {_highlight_if_diff(cpu_model, other_cpu_model)}")
    lines.append(f"- **CPU 架构**: {_highlight_if_diff(cpu_arch, other_cpu_arch)}")

    cores_str = f"{phys_cores}C/{log_cores}T"
    other_cores_str = f"{other_phys_cores}C/{other_log_cores}T"
    lines.append(f"- **核心/线程**: {_highlight_if_diff(cores_str, other_cores_str)}")

    freq_str = f"{cpu_freq} MHz"
    other_freq_str = f"{other_cpu_freq} MHz"
    lines.append(f"- **CPU 主频**: {_highlight_if_diff(freq_str, other_freq_str)}")

    lines.append(f"- **NUMA Nodes**: {_highlight_if_diff(numa_nodes, other_numa_nodes)}")

    percent_str = f"{cpu_percent}%"
    other_percent_str = f"{other_cpu_percent}%"
    lines.append(f"- **CPU 占用率**: {_highlight_if_diff(percent_str, other_percent_str)}")

    lines.append("")  # 空行

    # 内存信息
    lines.append("**内存信息**")
    # 兼容新旧格式
    mem_total_gb = env.get('mem_total_gb')
    other_mem_total_gb = other_env.get('mem_total_gb')
    mem_used_gb = env.get('mem_used_gb')
    other_mem_used_gb = other_env.get('mem_used_gb')
    mem_available_gb = env.get('mem_available_gb')
    other_mem_available_gb = other_env.get('mem_available_gb')
    mem_percent = env.get('mem_percent_used')
    other_mem_percent = other_env.get('mem_percent_used')

    # 如果是旧格式（MB），转换为 GB
    if mem_total_gb is None and env.get('mem_total_mb'):
        try:
            mem_total_gb = round(env.get('mem_total_mb') / 1024, 2)
        except (ValueError, TypeError):
            pass
    if other_mem_total_gb is None and other_env.get('mem_total_mb'):
        try:
            other_mem_total_gb = round(other_env.get('mem_total_mb') / 1024, 2)
        except (ValueError, TypeError):
            pass
    if mem_available_gb is None and env.get('mem_available_mb'):
        try:
            mem_available_gb = round(env.get('mem_available_mb') / 1024, 2)
        except (ValueError, TypeError):
            pass
    if other_mem_available_gb is None and other_env.get('mem_available_mb'):
        try:
            other_mem_available_gb = round(other_env.get('mem_available_mb') / 1024, 2)
        except (ValueError, TypeError):
            pass
    if mem_used_gb is None and mem_total_gb and mem_available_gb:
        mem_used_gb = round(mem_total_gb - mem_available_gb, 2)
    if other_mem_used_gb is None and other_mem_total_gb and other_mem_available_gb:
        other_mem_used_gb = round(other_mem_total_gb - other_mem_available_gb, 2)

    # 计算可用率
    mem_avail_percent = None
    other_mem_avail_percent = None
    if mem_percent is not None:
        mem_avail_percent = round(100 - mem_percent, 1)
    elif mem_total_gb and mem_available_gb:
        mem_avail_percent = round((mem_available_gb / mem_total_gb) * 100, 1)
    if other_mem_percent is not None:
        other_mem_avail_percent = round(100 - other_mem_percent, 1)
    elif other_mem_total_gb and other_mem_available_gb:
        other_mem_avail_percent = round((other_mem_available_gb / other_mem_total_gb) * 100, 1)

    total_str = f"{mem_total_gb if mem_total_gb else 'N/A'} GB"
    other_total_str = f"{other_mem_total_gb if other_mem_total_gb else 'N/A'} GB"
    lines.append(f"- **总内存**: {_highlight_if_diff(total_str, other_total_str)}")

    used_str = f"{mem_used_gb if mem_used_gb else 'N/A'} GB"
    other_used_str = f"{other_mem_used_gb if other_mem_used_gb else 'N/A'} GB"
    lines.append(f"- **已使用**: {_highlight_if_diff(used_str, other_used_str)}")

    avail_str = f"{mem_available_gb if mem_available_gb else 'N/A'} GB"
    other_avail_str = f"{other_mem_available_gb if other_mem_available_gb else 'N/A'} GB"
    lines.append(f"- **可用内存**: {_highlight_if_diff(avail_str, other_avail_str)}")

    avail_pct_str = f"{mem_avail_percent if mem_avail_percent is not None else 'N/A'}%"
    other_avail_pct_str = f"{other_mem_avail_percent if other_mem_avail_percent is not None else 'N/A'}%"
    lines.append(f"- **可用率**: {_highlight_if_diff(avail_pct_str, other_avail_pct_str)}")

    lines.append("")  # 空行

    # 其他信息
    lines.append("**其他信息**")
    exec_time = env.get('execution_time', 'N/A')
    other_exec_time = other_env.get('execution_time', 'N/A')
    lines.append(f"- **运行时间**: {_highlight_if_diff(exec_time, other_exec_time)}")

    return "\n".join(lines)


def render_machine_info(
    env_anchor: Dict[str, Any],
    env_test: Optional[Dict[str, Any]] = None,
    anchor_label: str = "Anchor",
    test_label: str = "Test",
) -> None:
    """渲染环境信息

    Args:
        env_anchor: 基准环境信息（或单个环境信息）
        env_test: 测试环境信息（可选，用于对比模式）
        anchor_label: 基准环境标签
        test_label: 测试环境标签
    """
    st.header("Machine Info", anchor="环境信息")

    # 如果 env_test 为 None 或两个环境相同，显示单列
    if env_test is None or env_anchor == env_test:
        # 单个环境模式
        if env_anchor:
            st.markdown(format_env_info(env_anchor))
        else:
            st.info("未采集到环境信息。")
    else:
        # 对比模式：显示两列，并标红不同的字段
        if env_anchor or env_test:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader(anchor_label)
                st.markdown(_format_env_info_with_diff(env_anchor, env_test), unsafe_allow_html=True)
            with col2:
                st.subheader(test_label)
                st.markdown(_format_env_info_with_diff(env_test, env_anchor), unsafe_allow_html=True)
        else:
            st.info("未采集到环境信息。")
