"""
码流分析报告页面（Streamlit）

通过 `?job_id=<job_id>` 打开对应任务的报告。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.config import settings


def _jobs_root_dir() -> Path:
    root = settings.jobs_root_dir
    if root.is_absolute():
        return root
    return (project_root / root).resolve()


def _list_bitstream_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """列出包含码流分析报告的任务（按报告文件修改时间倒序）。"""
    root = _jobs_root_dir()
    if not root.exists():
        return []

    items: List[Dict[str, Any]] = []
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        report_path = job_dir / "bitstream_analysis" / "report_data.json"
        if report_path.exists():
            mtime = report_path.stat().st_mtime
            items.append(
                {
                    "job_id": job_dir.name,
                    "mtime": mtime,
                    "report_path": report_path,
                }
            )

    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def _get_job_id() -> Optional[str]:
    job_id = st.query_params.get("job_id")
    if job_id:
        if isinstance(job_id, list):
            job_id = job_id[0] if job_id else None
        return str(job_id) if job_id else None
    return st.session_state.get("bitstream_job_id")


def _load_report(job_id: str) -> Dict[str, Any]:
    report_path = _jobs_root_dir() / job_id / "bitstream_analysis" / "report_data.json"
    if not report_path.exists():
        raise FileNotFoundError(f"未找到报告数据文件: {report_path}")
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _plot_frame_lines(
    encoded: List[Dict[str, Any]],
    y_series_getter,
    title: str,
    yaxis_title: str,
) -> None:
    fig = go.Figure()
    for item in encoded:
        label = item.get("label", "Encoded")
        values = y_series_getter(item)
        avg_val = None
        if values:
            numeric_vals = [v for v in values if isinstance(v, (int, float))]
            if numeric_vals:
                avg_val = sum(numeric_vals) / len(numeric_vals)
        legend_name = f"{label}: {avg_val:.4f}" if avg_val is not None else label
        fig.add_trace(go.Scatter(x=list(range(len(values))), y=values, mode="lines", name=legend_name))
    fig.update_layout(
        title=title,
        xaxis_title="Frame",
        yaxis_title=yaxis_title,
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.2),
    )
    st.plotly_chart(fig, use_container_width=True)


st.set_page_config(page_title="码流分析报告 - VMR", page_icon="📊", layout="wide")
st.title("📊 码流分析报告")

job_id = _get_job_id()
if not job_id:
    st.info("请选择一个码流分析任务，或从任务列表/详情页带参数跳转。")
    jobs = _list_bitstream_jobs()
    if not jobs:
        st.warning("暂未找到码流分析报告。请先创建任务。")
        st.stop()

    options = {f"{item['job_id']} (最近修改)": item["job_id"] for item in jobs}
    selected = st.selectbox("选择报告", options=list(options.keys()))
    if selected:
        chosen_job = options[selected]
        st.session_state["bitstream_job_id"] = chosen_job
        try:
            st.query_params["job_id"] = chosen_job
        except Exception:
            pass
        st.rerun()
    st.stop()

# 保持 session_state，方便从首页跳转
st.session_state["bitstream_job_id"] = job_id
# 把 job_id 保存在 URL 查询参数里（使用新 API，避免与 st.query_params 冲突）
try:
    if st.query_params.get("job_id") != job_id:
        st.query_params["job_id"] = job_id
except Exception:
    pass

try:
    report = _load_report(job_id)
except Exception as exc:
    st.error(str(exc))
    st.stop()

if report.get("kind") != "bitstream_analysis":
    st.error("该任务不是码流分析报告或报告数据格式不匹配。")
    st.stop()

ref = report.get("reference", {}) or {}
encoded_items = report.get("encoded", []) or []

st.caption(
    f"Job: {job_id} | Ref: {ref.get('label')} | "
    f"{ref.get('width')}x{ref.get('height')} @ {ref.get('fps')} fps | {ref.get('frames')} frames"
)
st.info("说明：所有打分输入统一转换为 yuv420p；若 Encoded 分辨率不一致会先对齐到 Ref；若帧数/时长不一致任务会直接失败。")

if not encoded_items:
    st.warning("报告中未包含任何 Encoded 数据。")
    st.stop()


# ========== 1) Metrics ==========
st.header("1) Metrics")

rows = []
for item in encoded_items:
    metrics = item.get("metrics", {}) or {}
    psnr = (metrics.get("psnr", {}) or {}).get("summary", {}) or {}
    ssim = (metrics.get("ssim", {}) or {}).get("summary", {}) or {}
    vmaf = (metrics.get("vmaf", {}) or {}).get("summary", {}) or {}
    bitrate = item.get("bitrate", {}) or {}

    rows.append(
        {
            "Encoded": item.get("label"),
            "PSNR_y": psnr.get("psnr_y"),
            "PSNR_u": psnr.get("psnr_u"),
            "PSNR_v": psnr.get("psnr_v"),
            "PSNR_avg": psnr.get("psnr_avg"),
            "SSIM_y": ssim.get("ssim_y"),
            "SSIM_u": ssim.get("ssim_u"),
            "SSIM_v": ssim.get("ssim_v"),
            "SSIM_avg": ssim.get("ssim_avg"),
            "VMAF": vmaf.get("vmaf_mean"),
            "VMAF_neg": vmaf.get("vmaf_neg_mean"),
            "Bitrate_kbps": (bitrate.get("avg_bitrate_bps") or 0) / 1000,
        }
    )

df_metrics = pd.DataFrame(rows)

base_columns = [
    ("Encoded", ""),
    ("PSNR", "Y"),
    ("PSNR", "U"),
    ("PSNR", "V"),
    ("PSNR", "AVG"),
    ("SSIM", "Y"),
    ("SSIM", "U"),
    ("SSIM", "V"),
    ("SSIM", "AVG"),
    ("VMAF", "VMAF"),
    ("VMAF", "VMAF_neg"),
    ("Bitrate", "Avg kbps"),
]

display_df = pd.DataFrame(
    {
        ("Encoded", ""): df_metrics["Encoded"],
        ("PSNR", "Y"): df_metrics["PSNR_y"],
        ("PSNR", "U"): df_metrics["PSNR_u"],
        ("PSNR", "V"): df_metrics["PSNR_v"],
        ("PSNR", "AVG"): df_metrics["PSNR_avg"],
        ("SSIM", "Y"): df_metrics["SSIM_y"],
        ("SSIM", "U"): df_metrics["SSIM_u"],
        ("SSIM", "V"): df_metrics["SSIM_v"],
        ("SSIM", "AVG"): df_metrics["SSIM_avg"],
        ("VMAF", "VMAF"): df_metrics["VMAF"],
        ("VMAF", "VMAF_neg"): df_metrics["VMAF_neg"],
        ("Bitrate", "Avg kbps"): df_metrics["Bitrate_kbps"],
    }
)
display_df.columns = pd.MultiIndex.from_tuples(base_columns)
st.dataframe(display_df, use_container_width=True, hide_index=True)

# Diff vs first encoded (separate table, if 2+)
if len(df_metrics) >= 2:
    base = df_metrics.iloc[0]
    diff_data = {
        ("Encoded", ""): df_metrics["Encoded"],
        ("PSNR", "Y"): df_metrics["PSNR_y"] - base["PSNR_y"],
        ("PSNR", "U"): df_metrics["PSNR_u"] - base["PSNR_u"],
        ("PSNR", "V"): df_metrics["PSNR_v"] - base["PSNR_v"],
        ("PSNR", "AVG"): df_metrics["PSNR_avg"] - base["PSNR_avg"],
        ("SSIM", "Y"): df_metrics["SSIM_y"] - base["SSIM_y"],
        ("SSIM", "U"): df_metrics["SSIM_u"] - base["SSIM_u"],
        ("SSIM", "V"): df_metrics["SSIM_v"] - base["SSIM_v"],
        ("SSIM", "AVG"): df_metrics["SSIM_avg"] - base["SSIM_avg"],
        ("VMAF", "VMAF"): df_metrics["VMAF"] - base["VMAF"],
        ("VMAF", "VMAF_neg"): df_metrics["VMAF_neg"] - base["VMAF_neg"],
        ("Bitrate", "Avg kbps"): df_metrics["Bitrate_kbps"] - base["Bitrate_kbps"],
    }
    diff_df = pd.DataFrame(diff_data)
    diff_df.iloc[0, 1:] = 0  # 基准行显示 0
    diff_df.columns = pd.MultiIndex.from_tuples(base_columns)
    st.markdown("**Δ 相对于第一个 Encoded**")
    st.dataframe(diff_df, use_container_width=True, hide_index=True)

st.subheader("逐帧折线图")

tab_psnr, tab_ssim, tab_vmaf, tab_vmaf_neg = st.tabs(
    ["PSNR", "SSIM", "VMAF", "VMAF-NEG"]
)

with tab_psnr:
    comp = st.selectbox("分量", ["avg", "y", "u", "v"], key="psnr_comp")
    key_map = {"avg": "psnr_avg", "y": "psnr_y", "u": "psnr_u", "v": "psnr_v"}
    metric_key = key_map[comp]
    _plot_frame_lines(
        encoded_items,
        lambda item: (((item.get("metrics") or {}).get("psnr") or {}).get("frames") or {}).get(metric_key, []),
        f"PSNR ({metric_key}) - 每帧",
        "PSNR (dB)",
    )

with tab_ssim:
    comp = st.selectbox("分量", ["avg", "y", "u", "v"], key="ssim_comp")
    key_map = {"avg": "ssim_avg", "y": "ssim_y", "u": "ssim_u", "v": "ssim_v"}
    metric_key = key_map[comp]
    _plot_frame_lines(
        encoded_items,
        lambda item: (((item.get("metrics") or {}).get("ssim") or {}).get("frames") or {}).get(metric_key, []),
        f"SSIM ({metric_key}) - 每帧",
        "SSIM",
    )

def _get_vmaf_frames(item: Dict[str, Any]) -> Dict[str, List[Any]]:
    return (((item.get("metrics") or {}).get("vmaf") or {}).get("frames") or {})

with tab_vmaf:
    available_vmaf_metrics = set()
    for item in encoded_items:
        frames_dict = _get_vmaf_frames(item)
        for key, vals in frames_dict.items():
            if key == "vmaf_neg":
                continue
            if isinstance(vals, list) and any(v is not None for v in vals):
                available_vmaf_metrics.add(key)

    if not available_vmaf_metrics:
        st.info("该报告未包含 VMAF 帧级数据。")
    else:
        preferred_order = [
            "vmaf",
            "adm2",
            "motion2",
            "vif_scale0",
            "vif_scale1",
            "vif_scale2",
            "vif_scale3",
        ]
        ordered_metrics: List[str] = []
        for key in preferred_order:
            if key in available_vmaf_metrics:
                ordered_metrics.append(key)
                available_vmaf_metrics.discard(key)
        ordered_metrics.extend(sorted(available_vmaf_metrics))

        default_metric = "vmaf" if "vmaf" in ordered_metrics else ordered_metrics[0]
        default_index = ordered_metrics.index(default_metric)
        selected_metric = st.selectbox(
            "选择要绘制的 VMAF / 子特征指标（单选）",
            ordered_metrics,
            index=default_index,
            key="vmaf_metric",
        )
        display_name = selected_metric.upper()
        _plot_frame_lines(
            encoded_items,
            lambda item, metric_key=selected_metric: _get_vmaf_frames(item).get(metric_key, []),
            f"{display_name} - 每帧",
            display_name,
        )

with tab_vmaf_neg:
    _plot_frame_lines(
        encoded_items,
        lambda item: _get_vmaf_frames(item).get("vmaf_neg", []),
        "VMAF-NEG - 每帧",
        "VMAF-NEG",
    )


# ========== 2) Bitrate ==========
st.header("2) Bitrate")

bitrate_rows = []
for item in encoded_items:
    bitrate = item.get("bitrate", {}) or {}
    bitrate_rows.append(
        {
            "Encoded": item.get("label"),
            "Avg Bitrate (kbps)": (bitrate.get("avg_bitrate_bps") or 0) / 1000,
        }
    )

st.dataframe(pd.DataFrame(bitrate_rows), use_container_width=True, hide_index=True)

st.subheader("按时间间隔聚合的码率图")

# 默认展示柱状图
chart_type = st.selectbox("图形类型", ["柱状图", "折线图"], key="br_chart_type", index=0)
bin_seconds = st.slider("聚合间隔 (秒)", min_value=0.1, max_value=5.0, value=1.0, step=0.1, key="br_bin")

fig = go.Figure()
for item in encoded_items:
    bitrate = item.get("bitrate", {}) or {}
    ts = bitrate.get("frame_timestamps", []) or []
    sizes = bitrate.get("frame_sizes", []) or []

    bins: Dict[int, float] = {}
    for t, s in zip(ts, sizes):
        try:
            idx = int(float(t) / bin_seconds)
        except (TypeError, ValueError):
            continue
        bins[idx] = bins.get(idx, 0.0) + float(s) * 8.0

    xs = sorted(bins.keys())
    x_times = [i * bin_seconds for i in xs]
    y_kbps = [(bins[i] / bin_seconds) / 1000.0 for i in xs]

    if chart_type == "柱状图":
        fig.add_trace(go.Bar(x=x_times, y=y_kbps, name=item.get("label")))
    else:
        fig.add_trace(
            go.Scatter(
                x=x_times,
                y=y_kbps,
                mode="lines+markers",
                name=item.get("label"),
                line_shape="hv",  # 平行线过渡
            )
        )

fig.update_layout(
    title=f"码率 (聚合间隔 {bin_seconds}s)",
    xaxis_title="Time (s)",
    yaxis_title="Bitrate (kbps)",
    hovermode="x unified",
    barmode="group",
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("帧结构：帧类型与帧大小（多个 Encoded 共用一张图）")
st.caption("颜色提示：I/IDR=蓝, P=绿, B=橙, RAW/UNK=灰；多个 Encoded 叠加显示。")

color_map = {
    "I": "#2563eb",
    "IDR": "#2563eb",
    "P": "#16a34a",
    "B": "#f97316",
    "RAW": "#6b7280",
    "UNK": "#6b7280",
}

fig_frames = go.Figure()
for idx, item in enumerate(encoded_items):
    bitrate = item.get("bitrate", {}) or {}
    types = bitrate.get("frame_types", []) or []
    sizes = bitrate.get("frame_sizes", []) or []
    colors = [color_map.get(str(t), "#6b7280") for t in types]
    hover = [
        f"{item.get('label')}<br>Frame {i}<br>Type: {types[i] if i < len(types) else 'UNK'}<br>Size: {sizes[i]} bytes"
        for i in range(len(sizes))
    ]
    fig_frames.add_trace(
        go.Bar(
            x=list(range(len(sizes))),
            y=sizes,
            marker_color=colors,
            hovertext=hover,
            hoverinfo="text",
            name=item.get("label"),
            opacity=0.85,
            offsetgroup=str(idx),
            legendgroup=str(idx),
            showlegend=True,
        )
    )

fig_frames.update_layout(
    xaxis_title="Frame",
    yaxis_title="Bytes",
    barmode="group",
    hovermode="x unified",
)

st.plotly_chart(fig_frames, use_container_width=True)
