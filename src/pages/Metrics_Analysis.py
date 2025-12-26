"""
Metrics 分析任务对比（选择两个 Metrics 分析任务，实时生成对比报告，不落盘）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.utils.bd_rate import bd_rate as _bd_rate, bd_metrics as _bd_metrics
from src.utils.streamlit_helpers import (
    jobs_root_dir as _jobs_root_dir,
    list_jobs,
    load_json_report,
    parse_rate_point as _parse_point,
    create_cpu_chart,
    create_fps_chart,
    color_positive_green,
    color_positive_red,
    format_env_info,
)


def _list_metrics_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    return list_jobs("metrics_analysis/analyse_data.json", limit=limit, check_status=True)


def _load_analyse(job_id: str) -> Dict[str, Any]:
    return load_json_report(job_id, "metrics_analysis/analyse_data.json")


def _metric_value(metrics: Dict[str, Any], name: str, field: str) -> Optional[float]:
    block = metrics.get(name) or {}
    if not isinstance(block, dict):
        return None
    summary = block.get("summary") or {}
    if isinstance(summary, dict) and field in summary:
        return summary.get(field)
    return block.get(field)


def _build_rows(data: Dict[str, Any], side_label: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """构建指标数据行和性能数据行"""
    rows: List[Dict[str, Any]] = []
    perf_rows: List[Dict[str, Any]] = []
    entries = data.get("entries") or []
    for entry in entries:
        video = entry.get("source")
        for item in entry.get("encoded") or []:
            rc, val = _parse_point(item.get("label", ""))
            metrics = item.get("metrics") or {}
            rows.append(
                {
                    "Video": video,
                    "Side": side_label,
                    "RC": rc,
                    "Point": val,
                    "Bitrate_kbps": ((item.get("bitrate") or {}).get("avg_bitrate_bps") or item.get("avg_bitrate_bps") or 0) / 1000,
                    "PSNR": _metric_value(metrics, "psnr", "psnr_avg"),
                    "SSIM": _metric_value(metrics, "ssim", "ssim_avg"),
                    "VMAF": _metric_value(metrics, "vmaf", "vmaf_mean"),
                    "VMAF-NEG": _metric_value(metrics, "vmaf_neg", "vmaf_neg_mean") or _metric_value(metrics, "vmaf", "vmaf_neg_mean"),
                }
            )
            # 提取性能数据
            perf = item.get("performance") or {}
            if perf:
                perf_rows.append({
                    "Video": video,
                    "Side": side_label,
                    "Point": val,
                    "FPS": perf.get("encoding_fps"),
                    "CPU Avg(%)": perf.get("cpu_avg_percent"),
                    "CPU Max(%)": perf.get("cpu_max_percent"),
                    "Total Time(s)": perf.get("total_encoding_time_s"),
                    "Frames": perf.get("total_frames"),
                    "cpu_samples": perf.get("cpu_samples", []),
                })
    return rows, perf_rows


def _build_bd_rows(df: pd.DataFrame) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    bd_rate_rows: List[Dict[str, Any]] = []
    bd_metric_rows: List[Dict[str, Any]] = []
    grouped = df.groupby("Video")
    for video, g in grouped:
        base = g[g["Side"] == "A"]
        exp = g[g["Side"] == "B"]
        if base.empty or exp.empty:
            continue
        merge = base.merge(exp, on=["Video", "RC", "Point"], suffixes=("_base", "_exp"))
        if merge.empty:
            continue
        def _collect(col_base: str, col_exp: str) -> Tuple[List[float], List[float], List[float], List[float]]:
            merged = merge.dropna(subset=[col_base, col_exp, "Bitrate_kbps_base", "Bitrate_kbps_exp"])
            if merged.empty:
                return [], [], [], []
            return (
                merged["Bitrate_kbps_base"].tolist(),
                merged[col_base].tolist(),
                merged["Bitrate_kbps_exp"].tolist(),
                merged[col_exp].tolist(),
            )

        base_rates, base_psnr, exp_rates, exp_psnr = _collect("PSNR_base", "PSNR_exp")
        _, base_ssim, _, exp_ssim = _collect("SSIM_base", "SSIM_exp")
        _, base_vmaf, _, exp_vmaf = _collect("VMAF_base", "VMAF_exp")
        _, base_vn, _, exp_vn = _collect("VMAF-NEG_base", "VMAF-NEG_exp")
        # BD-Rate
        bd_rate_rows.append(
            {
                "Video": video,
                "BD-Rate PSNR (%)": _bd_rate(base_rates, base_psnr, exp_rates, exp_psnr),
                "BD-Rate SSIM (%)": _bd_rate(base_rates, base_ssim, exp_rates, exp_ssim),
                "BD-Rate VMAF (%)": _bd_rate(base_rates, base_vmaf, exp_rates, exp_vmaf),
                "BD-Rate VMAF-NEG (%)": _bd_rate(base_rates, base_vn, exp_rates, exp_vn),
            }
        )
        # BD-Metrics
        bd_metric_rows.append(
            {
                "Video": video,
                "BD PSNR": _bd_metrics(base_rates, base_psnr, exp_rates, exp_psnr),
                "BD SSIM": _bd_metrics(base_rates, base_ssim, exp_rates, exp_ssim),
                "BD VMAF": _bd_metrics(base_rates, base_vmaf, exp_rates, exp_vmaf),
                "BD VMAF-NEG": _bd_metrics(base_rates, base_vn, exp_rates, exp_vn),
            }
        )
    return bd_rate_rows, bd_metric_rows


st.set_page_config(page_title="Metrics分析", page_icon="📊", layout="wide")
st.markdown("<h1 style='text-align:center;'>📊 Metrics分析</h1>", unsafe_allow_html=True)

jobs = _list_metrics_jobs()
if len(jobs) < 2:
    st.info("需要至少两个已完成的Metrics分析任务")
    st.stop()

options = [j["job_id"] for j in jobs if j["status_ok"]]
if len(options) < 2:
    st.info("任务数量不足，无法进行分析。")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    job_a = st.selectbox("任务 A", options=options, key="metrics_job_a")
with col2:
    job_b = st.selectbox("任务 B", options=[o for o in options if o != job_a], key="metrics_job_b")

if not job_a or not job_b:
    st.stop()

data_a = _load_analyse(job_a)
data_b = _load_analyse(job_b)

rows_a, perf_rows_a = _build_rows(data_a, "A")
rows_b, perf_rows_b = _build_rows(data_b, "B")
rows = rows_a + rows_b
perf_rows = perf_rows_a + perf_rows_b
df = pd.DataFrame(rows)
if df.empty:
    st.warning("没有可用于对比的指标数据。")
    st.stop()

df = df.sort_values(by=["Video", "RC", "Point", "Side"])

# ========== 侧边栏目录 ==========
with st.sidebar:
    st.markdown("### 📑 Contents")
    st.markdown("""
- [Metrics](#metrics)
  - [A vs B 对比](#a-vs-b-对比)
- [BD-Rate](#bd-rate)
- [BD-Metrics](#bd-metrics)
- [Performance](#performance)
  - [Delta](#perf-diff)
  - [CPU Usage](#cpu-chart)
  - [FPS](#fps-chart)
  - [Details](#perf-details)
- [Machine Info](#环境信息)
""", unsafe_allow_html=True)

# 平滑滚动 CSS
st.markdown("""
<style>
html {
    scroll-behavior: smooth;
}
</style>
""", unsafe_allow_html=True)

st.header("Metrics", anchor="metrics")

# 格式化精度
metrics_format = {
    "Point": "{:.2f}",
    "Bitrate_kbps": "{:.2f}",
    "PSNR": "{:.4f}",
    "SSIM": "{:.4f}",
    "VMAF": "{:.2f}",
    "VMAF-NEG": "{:.2f}",
}

styled_metrics = df.style.format(metrics_format, na_rep="-")
st.dataframe(styled_metrics, use_container_width=True, hide_index=True)

base_df = df[df["Side"] == "A"]
exp_df = df[df["Side"] == "B"]
merged = base_df.merge(exp_df, on=["Video", "RC", "Point"], suffixes=("_base", "_exp"))
if not merged.empty:
    merged["Bitrate Δ%"] = ((merged["Bitrate_kbps_exp"] - merged["Bitrate_kbps_base"]) / merged["Bitrate_kbps_base"].replace(0, pd.NA)) * 100
    merged["PSNR Δ"] = merged["PSNR_exp"] - merged["PSNR_base"]
    merged["SSIM Δ"] = merged["SSIM_exp"] - merged["SSIM_base"]
    merged["VMAF Δ"] = merged["VMAF_exp"] - merged["VMAF_base"]
    merged["VMAF-NEG Δ"] = merged["VMAF-NEG_exp"] - merged["VMAF-NEG_base"]
    st.subheader("A vs B 对比", anchor="a-vs-b-对比")

    # 格式化精度
    comparison_format = {
        "Point": "{:.2f}",
        "Bitrate_kbps_base": "{:.2f}",
        "Bitrate_kbps_exp": "{:.2f}",
        "Bitrate Δ%": "{:.2f}",
        "PSNR_base": "{:.4f}",
        "PSNR_exp": "{:.4f}",
        "PSNR Δ": "{:.4f}",
        "SSIM_base": "{:.4f}",
        "SSIM_exp": "{:.4f}",
        "SSIM Δ": "{:.4f}",
        "VMAF_base": "{:.2f}",
        "VMAF_exp": "{:.2f}",
        "VMAF Δ": "{:.2f}",
        "VMAF-NEG_base": "{:.2f}",
        "VMAF-NEG_exp": "{:.2f}",
        "VMAF-NEG Δ": "{:.2f}",
    }

    styled_comparison = merged[
        [
            "Video",
            "RC",
            "Point",
            "Bitrate_kbps_base",
            "Bitrate_kbps_exp",
            "Bitrate Δ%",
            "PSNR_base",
            "PSNR_exp",
            "PSNR Δ",
            "SSIM_base",
            "SSIM_exp",
            "SSIM Δ",
            "VMAF_base",
            "VMAF_exp",
            "VMAF Δ",
            "VMAF-NEG_base",
            "VMAF-NEG_exp",
            "VMAF-NEG Δ",
        ]
    ].sort_values(by=["Video", "Point"]).style.format(comparison_format, na_rep="-")

    st.dataframe(
        styled_comparison,
        use_container_width=True,
        hide_index=True,
    )

st.header("BD-Rate", anchor="bd-rate")
bd_rate_rows, bd_metric_rows = _build_bd_rows(merged)
if bd_rate_rows:
    st.dataframe(pd.DataFrame(bd_rate_rows), use_container_width=True, hide_index=True)
else:
    st.info("无法计算 BD-Rate（点位不足或缺少共同视频）。")

st.header("BD-Metrics", anchor="bd-metrics")
if bd_metric_rows:
    st.dataframe(pd.DataFrame(bd_metric_rows), use_container_width=True, hide_index=True)
else:
    st.info("无法计算 BD-Metrics（点位不足或缺少共同视频）。")

# ========== Performance ==========
st.header("Performance", anchor="performance")

if perf_rows:
    df_perf = pd.DataFrame(perf_rows)

    # 1. 汇总Diff表格
    st.subheader("Delta", anchor="perf-diff")
    base_perf = df_perf[df_perf["Side"] == "A"]
    exp_perf = df_perf[df_perf["Side"] == "B"]
    merged_perf = base_perf.merge(
        exp_perf,
        on=["Video", "Point"],
        suffixes=("_base", "_exp"),
    )
    if not merged_perf.empty:
        merged_perf["Δ FPS"] = merged_perf["FPS_exp"] - merged_perf["FPS_base"]
        merged_perf["Δ CPU Avg(%)"] = merged_perf["CPU Avg(%)_exp"] - merged_perf["CPU Avg(%)_base"]

        diff_perf_df = merged_perf[
            ["Video", "Point", "FPS_base", "FPS_exp", "Δ FPS", "CPU Avg(%)_base", "CPU Avg(%)_exp", "Δ CPU Avg(%)"]
        ].rename(columns={
            "FPS_base": "A FPS",
            "FPS_exp": "B FPS",
            "CPU Avg(%)_base": "A CPU(%)",
            "CPU Avg(%)_exp": "B CPU(%)",
        }).sort_values(by=["Video", "Point"]).reset_index(drop=True)

        # 合并同一视频的名称
        prev_video = None
        for idx in diff_perf_df.index:
            if diff_perf_df.at[idx, "Video"] == prev_video:
                diff_perf_df.at[idx, "Video"] = ""
            else:
                prev_video = diff_perf_df.at[idx, "Video"]

        # 格式化精度：Point、FPS 和 CPU 都保留2位小数
        perf_format_dict = {
            "Point": "{:.2f}",
            "A FPS": "{:.2f}",
            "B FPS": "{:.2f}",
            "Δ FPS": "{:.2f}",
            "A CPU(%)": "{:.2f}",
            "B CPU(%)": "{:.2f}",
            "Δ CPU Avg(%)": "{:.2f}",
        }

        styled_perf = diff_perf_df.style.applymap(color_positive_green, subset=["Δ FPS"]).applymap(color_positive_red, subset=["Δ CPU Avg(%)"]).format(perf_format_dict, na_rep="-")
        st.dataframe(styled_perf, use_container_width=True, hide_index=True)

    # 2. CPU折线图
    st.subheader("CPU Usage", anchor="cpu-chart")

    # 选择视频和点位
    video_list_perf = df_perf["Video"].unique().tolist()
    col_sel_perf1, col_sel_perf2 = st.columns(2)
    with col_sel_perf1:
        selected_video_perf = st.selectbox("选择视频", video_list_perf, key="perf_video")
    with col_sel_perf2:
        point_list_perf = df_perf[df_perf["Video"] == selected_video_perf]["Point"].unique().tolist()
        selected_point_perf = st.selectbox("选择码率点位", point_list_perf, key="perf_point")

    # 聚合间隔选择
    agg_interval = st.slider("聚合间隔 (ms)", min_value=100, max_value=1000, value=100, step=100, key="cpu_agg")

    # 获取对应的CPU采样数据
    base_samples: List[float] = []
    exp_samples: List[float] = []
    for _, row in df_perf.iterrows():
        if row["Video"] == selected_video_perf and row["Point"] == selected_point_perf:
            if row["Side"] == "A":
                base_samples = row.get("cpu_samples", []) or []
            else:
                exp_samples = row.get("cpu_samples", []) or []

    if base_samples or exp_samples:
        fig_cpu = create_cpu_chart(
            base_samples=base_samples,
            exp_samples=exp_samples,
            agg_interval=agg_interval,
            title=f"CPU占用率 - {selected_video_perf} ({selected_point_perf})",
            base_label="A",
            exp_label="B",
        )
        st.plotly_chart(fig_cpu, use_container_width=True)

        # 显示平均CPU占用率对比
        base_avg_cpu = sum(base_samples) / len(base_samples) if base_samples else 0
        exp_avg_cpu = sum(exp_samples) / len(exp_samples) if exp_samples else 0
        cpu_diff_pct = ((exp_avg_cpu - base_avg_cpu) / base_avg_cpu * 100) if base_avg_cpu > 0 else 0

        col_cpu1, col_cpu2, col_cpu3 = st.columns(3)
        col_cpu1.metric("A Average CPU Usage", f"{base_avg_cpu:.2f}%")
        col_cpu2.metric("B Average CPU Usage", f"{exp_avg_cpu:.2f}%")
        col_cpu3.metric("CPU Usage 差异", f"{cpu_diff_pct:+.2f}%", delta=f"{cpu_diff_pct:+.2f}%", delta_color="inverse")
    else:
        st.info("该视频/点位没有CPU采样数据。")

    # 3. FPS 对比图
    st.subheader("FPS", anchor="fps-chart")
    fig_fps = create_fps_chart(
        df_perf=df_perf,
        base_label="A",
        exp_label="B",
    )
    st.plotly_chart(fig_fps, use_container_width=True)

    # 4. 详细数据表格（默认折叠）
    st.subheader("Details", anchor="perf-details")
    with st.expander("查看详细性能数据", expanded=False):
        # 移除 cpu_samples 列用于展示
        df_perf_detail = df_perf.drop(columns=["cpu_samples"], errors="ignore")
        # 格式化精度
        perf_detail_format = {
            "Point": "{:.2f}",
            "FPS": "{:.2f}",
            "CPU Avg(%)": "{:.2f}",
            "CPU Max(%)": "{:.2f}",
        }
        styled_perf_detail = df_perf_detail.sort_values(by=["Video", "Point", "Side"]).style.format(perf_detail_format, na_rep="-")
        st.dataframe(styled_perf_detail, use_container_width=True, hide_index=True)
else:
    st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")

st.header("Machine Info", anchor="环境信息")

env_a = data_a.get("environment") or {}
env_b = data_b.get("environment") or {}
if env_a or env_b:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("任务 A")
        st.markdown(format_env_info(env_a))
    with col2:
        st.subheader("任务 B")
        st.markdown(format_env_info(env_b))
else:
    st.info("未采集到环境信息。")
