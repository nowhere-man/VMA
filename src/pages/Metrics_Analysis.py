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
    format_env_info,
    render_overall_section,
)
from src.services.template_storage import template_storage


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


def _format_points(points: Optional[List[float]]) -> str:
    if not points:
        return "-"
    clean = [p for p in points if isinstance(p, (int, float))]
    if not clean:
        return "-"
    return ", ".join(f"{p:g}" for p in sorted(set(clean)))


def _format_encoder_type(value: Optional[Any]) -> str:
    if isinstance(value, str):
        return value or "-"
    if value is not None:
        return getattr(value, "value", str(value))
    return "-"


def _format_encoder_params(encoder_params: Optional[str]) -> str:
    return encoder_params or "-"


def _get_report_info(data: Dict[str, Any]) -> Dict[str, Any]:
    template_id = data.get("template_id")
    template = template_storage.get_template(template_id) if template_id else None
    template_info: Dict[str, Any] = {}
    if template:
        anchor = template.metadata.anchor
        template_info = {
            "source_dir": anchor.source_dir,
            "encoder_type": anchor.encoder_type,
            "encoder_params": anchor.encoder_params,
            "bitrate_points": anchor.bitrate_points,
        }
    return {
        "source_dir": template_info.get("source_dir") or data.get("source_dir") or "-",
        "encoder_type": template_info.get("encoder_type") or data.get("encoder_type"),
        "encoder_params": template_info.get("encoder_params") or data.get("encoder_params"),
        "bitrate_points": template_info.get("bitrate_points") or data.get("bitrate_points") or [],
    }


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
        anchor = g[g["Side"] == "Anchor"]
        test = g[g["Side"] == "Test"]
        if anchor.empty or test.empty:
            continue
        merge = anchor.merge(test, on=["Video", "RC", "Point"], suffixes=("_anchor", "_test"))
        if merge.empty:
            continue
        def _collect(col_anchor: str, col_test: str) -> Tuple[List[float], List[float], List[float], List[float]]:
            merged = merge.dropna(subset=[col_anchor, col_test, "Bitrate_kbps_anchor", "Bitrate_kbps_test"])
            if merged.empty:
                return [], [], [], []
            return (
                merged["Bitrate_kbps_anchor"].tolist(),
                merged[col_anchor].tolist(),
                merged["Bitrate_kbps_test"].tolist(),
                merged[col_test].tolist(),
            )

        anchor_rates, anchor_psnr, test_rates, test_psnr = _collect("PSNR_anchor", "PSNR_test")
        _, anchor_ssim, _, test_ssim = _collect("SSIM_anchor", "SSIM_test")
        _, anchor_vmaf, _, test_vmaf = _collect("VMAF_anchor", "VMAF_test")
        _, anchor_vn, _, test_vn = _collect("VMAF-NEG_anchor", "VMAF-NEG_test")
        # BD-Rate
        bd_rate_rows.append(
            {
                "Video": video,
                "BD-Rate PSNR (%)": _bd_rate(anchor_rates, anchor_psnr, test_rates, test_psnr),
                "BD-Rate SSIM (%)": _bd_rate(anchor_rates, anchor_ssim, test_rates, test_ssim),
                "BD-Rate VMAF (%)": _bd_rate(anchor_rates, anchor_vmaf, test_rates, test_vmaf),
                "BD-Rate VMAF-NEG (%)": _bd_rate(anchor_rates, anchor_vn, test_rates, test_vn),
            }
        )
        # BD-Metrics
        bd_metric_rows.append(
            {
                "Video": video,
                "BD PSNR": _bd_metrics(anchor_rates, anchor_psnr, test_rates, test_psnr),
                "BD SSIM": _bd_metrics(anchor_rates, anchor_ssim, test_rates, test_ssim),
                "BD VMAF": _bd_metrics(anchor_rates, anchor_vmaf, test_rates, test_vmaf),
                "BD VMAF-NEG": _bd_metrics(anchor_rates, anchor_vn, test_rates, test_vn),
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
    anchor_job_id = st.selectbox("Anchor 任务", options=options, key="metrics_job_a")
with col2:
    test_job_id = st.selectbox("Test 任务", options=[o for o in options if o != anchor_job_id], key="metrics_job_b")

if not anchor_job_id or not test_job_id:
    st.stop()

anchor_data = _load_analyse(anchor_job_id)
test_data = _load_analyse(test_job_id)

anchor_rows, anchor_perf_rows = _build_rows(anchor_data, "Anchor")
test_rows, test_perf_rows = _build_rows(test_data, "Test")
rows = anchor_rows + test_rows
perf_rows = anchor_perf_rows + test_perf_rows
df = pd.DataFrame(rows)
if df.empty:
    st.warning("没有可用于对比的指标数据。")
    st.stop()

df = df.sort_values(by=["Video", "RC", "Point", "Side"])
point_count = df["Point"].dropna().nunique()
has_bd = point_count >= 4

# ========== 侧边栏目录 ==========
with st.sidebar:
    st.markdown("### 📑 Contents")
    contents = [
        "- [Information](#information)",
        "- [Overall](#overall)",
        "- [Metrics](#metrics)",
        "  - [Anchor vs Test 对比](#anchor-vs-test-对比)",
    ]
    if has_bd:
        contents += [
            "- [BD-Rate](#bd-rate)",
            "- [BD-Metrics](#bd-metrics)",
    ]
    contents += [
        "- [Performance](#performance)",
        "  - [Delta](#perf-diff)",
        "  - [CPU Usage](#cpu-chart)",
        "  - [FPS](#fps-chart)",
        "  - [Details](#perf-details)",
        "- [Machine Info](#环境信息)",
    ]
    st.markdown("\n".join(contents), unsafe_allow_html=True)

inject_smooth_scroll_css()

# ========== Information ==========
st.header("Information", anchor="information")

info_anchor = _get_report_info(anchor_data)
info_test = _get_report_info(test_data)

info_df = pd.DataFrame(
    [
        {"项目": "编码器类型", "Anchor": _format_encoder_type(info_anchor.get("encoder_type")), "Test": _format_encoder_type(info_test.get("encoder_type"))},
        {
            "项目": "编码参数",
            "Anchor": _format_encoder_params(info_anchor.get("encoder_params")),
            "Test": _format_encoder_params(info_test.get("encoder_params")),
        },
        {
            "项目": "码率点位",
            "Anchor": _format_points(info_anchor.get("bitrate_points")),
            "Test": _format_points(info_test.get("bitrate_points")),
        },
    ]
)
st.dataframe(info_df, use_container_width=True, hide_index=True)

bd_list_for_overall: List[Dict[str, Any]] = []
bd_rate_rows: List[Dict[str, Any]] = []
bd_metric_rows: List[Dict[str, Any]] = []
if has_bd:
    bd_rate_rows, bd_metric_rows = _build_bd_rows(df)
    if bd_rate_rows and bd_metric_rows:
        for i, rate_row in enumerate(bd_rate_rows):
            metric_row = bd_metric_rows[i] if i < len(bd_metric_rows) else {}
            bd_list_for_overall.append({
                "source": rate_row.get("Video"),
                "bd_rate_psnr": rate_row.get("BD-Rate PSNR (%)"),
                "bd_rate_ssim": rate_row.get("BD-Rate SSIM (%)"),
                "bd_rate_vmaf": rate_row.get("BD-Rate VMAF (%)"),
                "bd_rate_vmaf_neg": rate_row.get("BD-Rate VMAF-NEG (%)"),
                "bd_psnr": metric_row.get("BD PSNR"),
                "bd_ssim": metric_row.get("BD SSIM"),
                "bd_vmaf": metric_row.get("BD VMAF"),
                "bd_vmaf_neg": metric_row.get("BD VMAF-NEG"),
            })

# ========== Overall ==========
st.header("Overall", anchor="overall")

# 构建性能数据 DataFrame
df_perf_overall = pd.DataFrame(perf_rows) if perf_rows else pd.DataFrame()

render_overall_section(
    df_metrics=df,
    df_perf=df_perf_overall,
    bd_list=bd_list_for_overall,
    anchor_label="Anchor",
    test_label="Test",
    show_bd=has_bd,
)

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

anchor_df = df[df["Side"] == "Anchor"]
test_df = df[df["Side"] == "Test"]
merged = anchor_df.merge(test_df, on=["Video", "RC", "Point"], suffixes=("_anchor", "_test"))
if not merged.empty:
    merged["Bitrate Δ%"] = ((merged["Bitrate_kbps_test"] - merged["Bitrate_kbps_anchor"]) / merged["Bitrate_kbps_anchor"].replace(0, pd.NA)) * 100
    merged["PSNR Δ"] = merged["PSNR_test"] - merged["PSNR_anchor"]
    merged["SSIM Δ"] = merged["SSIM_test"] - merged["SSIM_anchor"]
    merged["VMAF Δ"] = merged["VMAF_test"] - merged["VMAF_anchor"]
    merged["VMAF-NEG Δ"] = merged["VMAF-NEG_test"] - merged["VMAF-NEG_anchor"]
    st.subheader("Anchor vs Test 对比", anchor="anchor-vs-test-对比")

    # 格式化精度
    comparison_format = {
        "Point": "{:.2f}",
        "Bitrate_kbps_anchor": "{:.2f}",
        "Bitrate_kbps_test": "{:.2f}",
        "Bitrate Δ%": "{:.2f}",
        "PSNR_anchor": "{:.4f}",
        "PSNR_test": "{:.4f}",
        "PSNR Δ": "{:.4f}",
        "SSIM_anchor": "{:.4f}",
        "SSIM_test": "{:.4f}",
        "SSIM Δ": "{:.4f}",
        "VMAF_anchor": "{:.2f}",
        "VMAF_test": "{:.2f}",
        "VMAF Δ": "{:.2f}",
        "VMAF-NEG_anchor": "{:.2f}",
        "VMAF-NEG_test": "{:.2f}",
        "VMAF-NEG Δ": "{:.2f}",
    }

    styled_comparison = merged[
        [
            "Video",
            "RC",
            "Point",
            "Bitrate_kbps_anchor",
            "Bitrate_kbps_test",
            "Bitrate Δ%",
            "PSNR_anchor",
            "PSNR_test",
            "PSNR Δ",
            "SSIM_anchor",
            "SSIM_test",
            "SSIM Δ",
            "VMAF_anchor",
            "VMAF_test",
            "VMAF Δ",
            "VMAF-NEG_anchor",
            "VMAF-NEG_test",
            "VMAF-NEG Δ",
        ]
    ].sort_values(by=["Video", "Point"]).style.format(comparison_format, na_rep="-")

    st.dataframe(
        styled_comparison,
        use_container_width=True,
        hide_index=True,
    )

if has_bd:
    st.header("BD-Rate", anchor="bd-rate")
    if bd_rate_rows:
        st.dataframe(pd.DataFrame(bd_rate_rows), use_container_width=True, hide_index=True)
    else:
        st.info("无法计算 BD-Rate（点位不足或缺少共同视频）。")

    st.header("BD-Metrics", anchor="bd-metrics")
    if bd_metric_rows:
        st.dataframe(pd.DataFrame(bd_metric_rows), use_container_width=True, hide_index=True)
    else:
        st.info("无法计算 BD-Metrics（点位不足或缺少共同视频）。")

if perf_rows:
    df_perf = pd.DataFrame(perf_rows)
    perf_detail_format = {
        "Point": "{:.2f}",
        "FPS": "{:.2f}",
        "CPU Avg(%)": "{:.2f}",
        "CPU Max(%)": "{:.2f}",
    }
    render_performance_section(
        df_perf=df_perf,
        anchor_label="Anchor",
        test_label="Test",
        detail_df=df_perf.drop(columns=["cpu_samples"], errors="ignore"),
        detail_format=perf_detail_format,
        delta_point_key="perf_delta_point_analysis",
        delta_metric_key="perf_delta_metric_analysis",
        cpu_video_key="perf_video",
        cpu_point_key="perf_point",
        cpu_agg_key="cpu_agg",
    )
else:
    st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")

st.header("Machine Info", anchor="环境信息")

env_anchor = anchor_data.get("environment") or {}
env_test = test_data.get("environment") or {}
if env_anchor or env_test:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Anchor 任务")
        st.markdown(format_env_info(env_anchor))
    with col2:
        st.subheader("Test 任务")
        st.markdown(format_env_info(env_test))
else:
    st.info("未采集到环境信息。")
