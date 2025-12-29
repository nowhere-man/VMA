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

from src.utils.streamlit_helpers import (
    jobs_root_dir as _jobs_root_dir,
    list_jobs,
    get_query_param,
    load_json_report,
)


def _list_bitstream_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """列出包含码流分析报告的任务（按报告文件修改时间倒序）。"""
    return list_jobs("bitstream_analysis/report_data.json", limit=limit)


def _get_job_id() -> Optional[str]:
    return get_query_param("job_id")


def _load_report(job_id: str) -> Dict[str, Any]:
    return load_json_report(job_id, "bitstream_analysis/report_data.json")


def _plot_frame_lines(
    encoded: List[Dict[str, Any]],
    y_series_getter,
    title: str,
    yaxis_title: str,
) -> None:
    fig = go.Figure()
    colors = ["#636efa", "#ef553b"]
    for idx, item in enumerate(encoded):
        label = item.get("label", "Encoded")
        values = y_series_getter(item)
        avg_val = None
        if values:
            numeric_vals = [v for v in values if isinstance(v, (int, float))]
            if numeric_vals:
                avg_val = sum(numeric_vals) / len(numeric_vals)
        legend_name = f"{label}: {avg_val:.4f}" if avg_val is not None else label
        color = colors[idx % len(colors)]
        fig.add_trace(go.Scatter(x=list(range(len(values))), y=values, mode="lines", name=legend_name, line=dict(color=color)))
    fig.update_layout(
        title=title,
        xaxis_title="Frame",
        yaxis_title=yaxis_title,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig, use_container_width=True)


st.set_page_config(page_title="码流分析", page_icon="📊", layout="wide")

job_id = _get_job_id()
if not job_id:
    st.markdown("<h1 style='text-align:center;'>📊 码流分析报告</h1>", unsafe_allow_html=True)
    st.subheader("全部码流分析报告")
    jobs = _list_bitstream_jobs()
    if not jobs:
        st.warning("暂未找到报告。请先创建任务。")
        st.stop()

    for item in jobs:
        jid = item["job_id"]
        report_data = item.get("report_data", {})

        # 格式：源流名字（不带后缀名）-日期-时间-任务id
        ref = report_data.get("reference", {}) or {}
        ref_label = ref.get("label", "Unknown")

        # 去掉文件扩展名
        from pathlib import Path
        source_name = Path(ref_label).stem

        # 从 mtime 提取日期和时间
        from datetime import datetime
        dt = datetime.fromtimestamp(item["mtime"])
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        display_name = f"{source_name}-{date_str}-{time_str}-{jid}"

        st.markdown(f"- [{display_name}](?job_id={jid})", unsafe_allow_html=True)
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

# 隐藏默认的 pages 导航，只显示 Contents 目录
st.markdown("""
<style>
    [data-testid="stSidebarNav"] {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

# 显示报告标题
ref_label = ref.get('label', 'Unknown')
st.markdown(f"<h1 style='text-align:center;'>{ref_label} - 分析报告</h1>", unsafe_allow_html=True)

if not encoded_items:
    st.warning("报告中未包含任何 Encoded 数据。")
    st.stop()

# ========== 侧边栏目录 ==========
with st.sidebar:
    st.markdown("### 📑 Contents")
    st.markdown("""
- [Streams Info](#streams-info)
- [Metrics](#metrics)
  - [Delta](#delta)
  - [PSNR](#psnr)
  - [SSIM](#ssim)
  - [VMAF](#vmaf)
  - [VMAF-NEG](#vmaf-neg)
- [Bitrate](#bitrate)
  - [By Time](#by-time)
  - [By Frame](#by-frame)
""", unsafe_allow_html=True)

# 平滑滚动 CSS
st.markdown("""
<style>
html {
    scroll-behavior: smooth;
}
</style>
""", unsafe_allow_html=True)


# ========== Streams Info ==========
st.header("Streams Info", anchor="streams-info")

stream_rows = []
# Reference stream
ref_format = ref.get("format", "YUV")
ref_bitrate = None if ref_format.upper() == "YUV" else (ref.get("avg_bitrate_bps", 0) / 1000)
stream_rows.append({
    "Stream": ref.get("label", "Reference"),
    "Format": ref_format,
    "Width": ref.get("width"),
    "Height": ref.get("height"),
    "FPS": ref.get("fps"),
    "Frames": ref.get("frames"),
    "Avg Bitrate (kbps)": ref_bitrate,
})

# Encoded streams
for item in encoded_items:
    bitrate = item.get("bitrate", {}) or {}

    # 计算帧数：优先使用 item.frames，否则从 bitrate 数据计算
    frames = item.get("frames")
    if not frames:
        frame_sizes = bitrate.get("frame_sizes", []) or []
        frames = len(frame_sizes) if frame_sizes else None

    stream_rows.append({
        "Stream": item.get("label"),
        "Format": item.get("format"),
        "Width": item.get("width"),
        "Height": item.get("height"),
        "FPS": item.get("fps"),
        "Frames": frames,
        "Avg Bitrate (kbps)": (bitrate.get("avg_bitrate_bps", 0) / 1000),
    })

df_streams = pd.DataFrame(stream_rows)
# 格式化：Width/Height 为整数，FPS 为2位小数，Bitrate 为2位小数
styled_streams = df_streams.style.format({
    "Width": "{:.0f}",
    "Height": "{:.0f}",
    "FPS": "{:.2f}",
    "Avg Bitrate (kbps)": "{:.2f}"
}, na_rep="N/A")
st.dataframe(styled_streams, use_container_width=True, hide_index=True)


# ========== Metrics ==========
st.header("Metrics", anchor="metrics")

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

anchor_columns = [
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
display_df.columns = pd.MultiIndex.from_tuples(anchor_columns)

# 格式化显示精度
format_dict = {
    ("PSNR", "Y"): "{:.4f}",
    ("PSNR", "U"): "{:.4f}",
    ("PSNR", "V"): "{:.4f}",
    ("PSNR", "AVG"): "{:.4f}",
    ("SSIM", "Y"): "{:.4f}",
    ("SSIM", "U"): "{:.4f}",
    ("SSIM", "V"): "{:.4f}",
    ("SSIM", "AVG"): "{:.4f}",
    ("VMAF", "VMAF"): "{:.2f}",
    ("VMAF", "VMAF_neg"): "{:.2f}",
    ("Bitrate", "Avg kbps"): "{:.2f}",
}

# 显示原始数据表格
styled_overall = display_df.style.format(format_dict, na_rep="-")
st.dataframe(styled_overall, use_container_width=True, hide_index=True)

# Delta 表格
st.subheader("Delta", anchor="delta")
if len(df_metrics) >= 2:
    anchor = df_metrics.iloc[0]
    diff_data = {
        ("Encoded", ""): df_metrics["Encoded"],
        ("PSNR", "Y"): df_metrics["PSNR_y"] - anchor["PSNR_y"],
        ("PSNR", "U"): df_metrics["PSNR_u"] - anchor["PSNR_u"],
        ("PSNR", "V"): df_metrics["PSNR_v"] - anchor["PSNR_v"],
        ("PSNR", "AVG"): df_metrics["PSNR_avg"] - anchor["PSNR_avg"],
        ("SSIM", "Y"): df_metrics["SSIM_y"] - anchor["SSIM_y"],
        ("SSIM", "U"): df_metrics["SSIM_u"] - anchor["SSIM_u"],
        ("SSIM", "V"): df_metrics["SSIM_v"] - anchor["SSIM_v"],
        ("SSIM", "AVG"): df_metrics["SSIM_avg"] - anchor["SSIM_avg"],
        ("VMAF", "VMAF"): df_metrics["VMAF"] - anchor["VMAF"],
        ("VMAF", "VMAF_neg"): df_metrics["VMAF_neg"] - anchor["VMAF_neg"],
        ("Bitrate", "Avg kbps"): df_metrics["Bitrate_kbps"] - anchor["Bitrate_kbps"],
    }
    diff_df = pd.DataFrame(diff_data)
    diff_df.iloc[0, 1:] = 0  # 基准行显示 0
    diff_df.columns = pd.MultiIndex.from_tuples(anchor_columns)

    # 定义颜色样式函数
    def _color_diff(val):
        if pd.isna(val) or not isinstance(val, (int, float)):
            return ""
        if val > 0:
            return "color: green"
        elif val < 0:
            return "color: red"
        return ""

    # 应用颜色样式和格式化精度到所有数值列（除了第一列 Encoded）
    styled_diff = diff_df.style.applymap(_color_diff, subset=diff_df.columns[1:]).format(format_dict, na_rep="-")
    st.dataframe(styled_diff, use_container_width=True, hide_index=True)

# PSNR 逐帧折线图
st.subheader("PSNR", anchor="psnr")
comp = st.selectbox("分量", ["avg", "y", "u", "v"], key="psnr_comp")
key_map = {"avg": "psnr_avg", "y": "psnr_y", "u": "psnr_u", "v": "psnr_v"}
metric_key = key_map[comp]
_plot_frame_lines(
    encoded_items,
    lambda item: (((item.get("metrics") or {}).get("psnr") or {}).get("frames") or {}).get(metric_key, []),
    f"PSNR ({metric_key}) - 每帧",
    "PSNR (dB)",
)

# SSIM 逐帧折线图
st.subheader("SSIM", anchor="ssim")
comp = st.selectbox("分量", ["avg", "y", "u", "v"], key="ssim_comp")
key_map = {"avg": "ssim_avg", "y": "ssim_y", "u": "ssim_u", "v": "ssim_v"}
metric_key = key_map[comp]
_plot_frame_lines(
    encoded_items,
    lambda item: (((item.get("metrics") or {}).get("ssim") or {}).get("frames") or {}).get(metric_key, []),
    f"SSIM ({metric_key}) - 每帧",
    "SSIM",
)

# VMAF 逐帧折线图
def _get_vmaf_frames(item: Dict[str, Any]) -> Dict[str, List[Any]]:
    return (((item.get("metrics") or {}).get("vmaf") or {}).get("frames") or {})

st.subheader("VMAF", anchor="vmaf")
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

# VMAF-NEG 逐帧折线图
st.subheader("VMAF-NEG", anchor="vmaf-neg")
_plot_frame_lines(
    encoded_items,
    lambda item: _get_vmaf_frames(item).get("vmaf_neg", []),
    "VMAF-NEG - 每帧",
    "VMAF-NEG",
)


# ========== 2) Bitrate ==========
st.header("Bitrate", anchor="bitrate")

bitrate_rows = []
for item in encoded_items:
    bitrate = item.get("bitrate", {}) or {}
    bitrate_rows.append(
        {
            "Encoded": item.get("label"),
            "Avg Bitrate (kbps)": (bitrate.get("avg_bitrate_bps") or 0) / 1000,
        }
    )

df_bitrate = pd.DataFrame(bitrate_rows)
styled_bitrate = df_bitrate.style.format({"Avg Bitrate (kbps)": "{:.2f}"}, na_rep="-")
st.dataframe(styled_bitrate, use_container_width=True, hide_index=True)

st.subheader("By Time", anchor="by-time")

# 默认展示柱状图
chart_type = st.selectbox("图形类型", ["柱状图", "折线图"], key="br_chart_type", index=0)
bin_seconds = st.slider("聚合间隔 (秒)", min_value=0.1, max_value=5.0, value=1.0, step=0.1, key="br_bin")

fig = go.Figure()
colors = ["#636efa", "#ef553b"]
for idx, item in enumerate(encoded_items):
    bitrate = item.get("bitrate", {}) or {}
    ts = bitrate.get("frame_timestamps", []) or []
    sizes = bitrate.get("frame_sizes", []) or []

    bins: Dict[int, float] = {}
    for t, s in zip(ts, sizes):
        try:
            idx_bin = int(float(t) / bin_seconds)
        except (TypeError, ValueError):
            continue
        bins[idx_bin] = bins.get(idx_bin, 0.0) + float(s) * 8.0

    xs = sorted(bins.keys())
    x_times = [i * bin_seconds for i in xs]
    y_kbps = [(bins[i] / bin_seconds) / 1000.0 for i in xs]

    color = colors[idx % len(colors)]
    if chart_type == "柱状图":
        fig.add_trace(go.Bar(x=x_times, y=y_kbps, name=item.get("label"), marker_color=color, opacity=0.7))
    else:
        fig.add_trace(
            go.Scatter(
                x=x_times,
                y=y_kbps,
                mode="lines+markers",
                name=item.get("label"),
                line=dict(color=color),
                marker=dict(color=color),
            )
        )

fig.update_layout(
    title=f"码率 (聚合间隔 {bin_seconds}s)",
    xaxis_title="Time (s)",
    yaxis_title="Bitrate (kbps)",
    hovermode="x unified",
    barmode="group",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("By Frame", anchor="by-frame")
st.caption("颜色提示：I/IDR=蓝, P=绿, B=橙, RAW/UNK=灰。")

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
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
)

st.plotly_chart(fig_frames, use_container_width=True)
