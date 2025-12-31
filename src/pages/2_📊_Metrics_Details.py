"""
Metrics 分析报告页面

显示所有 Metrics 分析任务的报告列表，点击后查看单个任务的详情报告
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.utils.streamlit_helpers import (
    get_query_param,
    parse_rate_point as _parse_point,
    list_metrics_jobs as _list_metrics_jobs,
    format_job_label as _format_job_label,
    load_analyse as _load_analyse,
    metric_value as _metric_value,
    render_machine_info,
)
from src.utils.streamlit_metrics_components import (
    inject_smooth_scroll_css,
    render_sidebar_contents_single,
    render_single_information,
    render_single_overall,
    render_single_rd_curves,
    render_single_performance,
)


def _build_rows(data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """构建指标数据行和性能数据行"""
    rows: List[Dict[str, Any]] = []
    perf_rows: List[Dict[str, Any]] = []
    entries = data.get("entries") or []
    for entry in entries:
        video = entry.get("source")
        for item in entry.get("encoded") or []:
            rc, val = _parse_point(item.get("label", ""))
            metrics = item
            rows.append({
                "Video": video,
                "RC": rc,
                "Point": val,
                "Bitrate_kbps": ((item.get("bitrate") or {}).get("avg_bitrate_bps") or item.get("avg_bitrate_bps") or 0) / 1000,
                "PSNR": _metric_value(metrics, "psnr", "psnr_avg"),
                "SSIM": _metric_value(metrics, "ssim", "ssim_avg"),
                "VMAF": _metric_value(metrics, "vmaf", "vmaf_mean"),
                "VMAF-NEG": _metric_value(metrics, "vmaf_neg", "vmaf_neg_mean") or _metric_value(metrics, "vmaf", "vmaf_neg_mean"),
            })
            perf = item.get("performance") or {}
            if perf:
                perf_rows.append({
                    "Video": video,
                    "Point": val,
                    "FPS": perf.get("encoding_fps"),
                    "CPU Avg(%)": perf.get("cpu_avg_percent"),
                    "CPU Max(%)": perf.get("cpu_max_percent"),
                    "Total Time(s)": perf.get("total_encoding_time_s"),
                    "Frames": perf.get("total_frames"),
                    "cpu_samples": perf.get("cpu_samples", []),
                })
    return rows, perf_rows


def _get_report_info(data: Dict[str, Any]) -> Dict[str, Any]:
    from src.services.template_storage import template_storage

    template_id = data.get("template_id")
    template = template_storage.get_template(template_id) if template_id else None
    template_info: Dict[str, Any] = {}
    if template:
        anchor = template.metadata.anchor
        template_info = {
            "encoder_type": anchor.encoder_type,
            "encoder_params": anchor.encoder_params,
            "bitrate_points": anchor.bitrate_points,
        }
    return {
        "encoder_type": template_info.get("encoder_type") or data.get("encoder_type"),
        "encoder_params": template_info.get("encoder_params") or data.get("encoder_params"),
        "bitrate_points": template_info.get("bitrate_points") or data.get("bitrate_points") or [],
    }


st.set_page_config(
    page_title="首页 - VMR",
    page_icon="📊",
    layout="wide",
)

# 检查是否通过 query params 传入了任务 ID（用于显示单个任务详情）
job_id = get_query_param("job_id")

if job_id:
    # 显示单个任务详情报告模式
    st.markdown("""
<style>
    [data-testid="stSidebarNav"] {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

    try:
        data = _load_analyse(job_id)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    # 获取模板名称和时间戳
    template_name = data.get("template_name", "Unknown")
    from datetime import datetime
    execution_time = data.get("execution_time", "")

    # 显示报告标题
    st.markdown(f"<h1 style='text-align:center;'>{template_name} 详情报告</h1>", unsafe_allow_html=True)
    st.markdown(f"<h4 style='text-align:right;'>{job_id} {execution_time}</h4>", unsafe_allow_html=True)

    # 构建数据
    rows, perf_rows = _build_rows(data)
    df = pd.DataFrame(rows)
    df_perf = pd.DataFrame(perf_rows) if perf_rows else pd.DataFrame()

    if df.empty:
        st.warning("没有可用的指标数据。")
        st.stop()

    df = df.sort_values(by=["Video", "RC", "Point"])

    # 侧边栏目录
    with st.sidebar:
        render_sidebar_contents_single()

    inject_smooth_scroll_css()

    # Information
    st.header("Information", anchor="information")
    info = _get_report_info(data)
    render_single_information(info)

    # Overall
    st.header("Overall", anchor="overall")
    render_single_overall(df, df_perf)

    # Metrics
    st.header("Metrics", anchor="metrics")
    render_single_rd_curves(df)

    # Details
    st.subheader("Details", anchor="details")
    with st.expander("查看详细Metrics数据", expanded=False):
        details_format = {
            "Point": "{:.2f}",
            "Bitrate_kbps": "{:.2f}",
            "PSNR": "{:.4f}",
            "SSIM": "{:.4f}",
            "VMAF": "{:.2f}",
            "VMAF-NEG": "{:.2f}",
        }
        styled_details = df.sort_values(by=["Video", "RC", "Point"]).style.format(details_format, na_rep="-")
        st.dataframe(styled_details, use_container_width=True, hide_index=True)

    # Performance
    if not df_perf.empty:
        render_single_performance(df_perf)
    else:
        st.header("Performance", anchor="performance")
        st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")

    # Machine Info
    env = data.get("environment") or {}
    render_machine_info(env)

else:
    # 显示报告列表模式
    st.markdown("<h1 style='text-align:left;'>📊 Metrics 详情</h1>", unsafe_allow_html=True)

    jobs = _list_metrics_jobs()
    valid_jobs = [j for j in jobs if j["status_ok"]]

    if not valid_jobs:
        st.warning("暂未找到报告，请先创建任务。")
        st.stop()

    st.subheader("全部Metrics详情报告")
    for job in valid_jobs:
        jid = job["job_id"]
        label = _format_job_label(job)
        st.markdown(f"- [{label}](?job_id={jid})", unsafe_allow_html=True)
