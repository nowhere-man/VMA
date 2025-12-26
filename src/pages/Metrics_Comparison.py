"""
模板 Metrics对比 报告页面（Baseline / Test）

通过 `?template_job_id=<job_id>` 打开对应任务的报告。
"""

from __future__ import annotations

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

from src.utils.streamlit_helpers import (
    jobs_root_dir as _jobs_root_dir,
    list_jobs,
    get_query_param,
    load_json_report,
    parse_rate_point as _parse_point,
    create_cpu_chart,
)


def _list_template_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    return list_jobs("metrics_analysis/report_data.json", limit=limit)


def _get_job_id() -> Optional[str]:
    return get_query_param("template_job_id")


def _load_report(job_id: str) -> Dict[str, Any]:
    return load_json_report(job_id, "metrics_analysis/report_data.json")


st.set_page_config(page_title="Metrics对比", page_icon="📊", layout="wide")

job_id = _get_job_id()
if not job_id:
    st.markdown("<h1 style='text-align:center;'>📊 Metrics对比报告</h1>", unsafe_allow_html=True)
    jobs = _list_template_jobs()
    if not jobs:
        st.warning("暂未找到报告，请先创建任务。")
        st.stop()
    st.subheader("全部Metrics对比报告")
    for item in jobs:
        jid = item["job_id"]
        report_data = item.get("report_data", {})

        # 格式：模板名-报告日期-报告时间-任务id
        template_name = report_data.get("template_name", "Unknown")

        # 从 mtime 提取日期和时间
        from datetime import datetime
        dt = datetime.fromtimestamp(item["mtime"])
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        display_name = f"{template_name}-{date_str}-{time_str}-{jid}"

        st.markdown(
            f"- [{display_name}](?template_job_id={jid})",
            unsafe_allow_html=True,
        )
    st.stop()

st.session_state["template_job_id"] = job_id
try:
    if st.query_params.get("template_job_id") != job_id:
        st.query_params["template_job_id"] = job_id
except Exception:
    pass

try:
    report = _load_report(job_id)
except Exception as exc:
    st.error(str(exc))
    st.stop()

if report.get("kind") != "template_metrics":
    st.error("该任务不是模板指标报告或数据格式不匹配。")
    st.stop()

entries: List[Dict[str, Any]] = report.get("entries", []) or []
bd_list: List[Dict[str, Any]] = report.get("bd_metrics", []) or []

# 显示报告标题
template_name = report.get('template_name') or report.get('template_id', 'Unknown')
st.markdown(f"<h1 style='text-align:center;'>{template_name} - {job_id} - Metrics对比</h1>", unsafe_allow_html=True)

# ========== 侧边栏目录 ==========
with st.sidebar:
    st.markdown("### 📑 Contents")
    st.markdown("""
- [Metrics](#metrics)
  - [RD Curves](#rd-curve)
  - [Delta](#delta)
  - [Details](#details)
- [BD-Rate](#bd-rate)
  - [BD-Rate PSNR](#bd-rate-psnr)
  - [BD-Rate SSIM](#bd-rate-ssim)
  - [BD-Rate VMAF](#bd-rate-vmaf)
  - [BD-Rate VMAF-NEG](#bd-rate-vmaf-neg)
- [BD-Metrics](#bd-metrics)
  - [BD PSNR](#bd-psnr)
  - [BD SSIM](#bd-ssim)
  - [BD VMAF](#bd-vmaf)
  - [BD VMAF-NEG](#bd-vmaf-neg)
- [Bitrates](#码率分析)
- [Performance](#performance)
  - [Delta](#perf-diff)
  - [CPU Usage](#cpu-chart)
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


# ========== Metrics ==========
st.header("Metrics", anchor="metrics")

rows = []
for entry in entries:
    video = entry.get("source")
    for side_key, side_name in (("baseline", "Baseline"), ("test", "Test")):
        side = (entry.get(side_key) or {})
        for item in side.get("encoded", []) or []:
            rc, val = _parse_point(item.get("label", ""))
            psnr_avg = (item.get("psnr") or {}).get("psnr_avg")
            ssim_avg = (item.get("ssim") or {}).get("ssim_avg")
            vmaf_mean = (item.get("vmaf") or {}).get("vmaf_mean")
            vmaf_neg_mean = (item.get("vmaf") or {}).get("vmaf_neg_mean")
            rows.append(
                {
                    "Video": video,
                    "Side": side_name,
                    "RC": rc,
                    "Point": val,
                    "Bitrate_kbps": (item.get("avg_bitrate_bps") or 0) / 1000,
                    "PSNR": psnr_avg,
                    "SSIM": ssim_avg,
                    "VMAF": vmaf_mean,
                    "VMAF-NEG": vmaf_neg_mean,
                }
            )

df_metrics = pd.DataFrame(rows)
if df_metrics.empty:
    st.warning("报告中没有可用的指标数据。")
    st.stop()

# RD Curve
st.subheader("RD Curves", anchor="rd-curve")
video_list = df_metrics["Video"].unique().tolist()
metric_options = ["PSNR", "SSIM", "VMAF", "VMAF-NEG"]

col_select, col_chart = st.columns([1, 3])
with col_select:
    st.write("")  # 添加空行使选择器垂直居中
    st.write("")
    selected_video = st.selectbox("选择视频", video_list, key="rd_video")
    selected_metric = st.selectbox("选择指标", metric_options, key="rd_metric")

# 筛选数据并绘制 RD 曲线
video_df = df_metrics[df_metrics["Video"] == selected_video]
baseline_data = video_df[video_df["Side"] == "Baseline"].sort_values("Bitrate_kbps")
test_data = video_df[video_df["Side"] == "Test"].sort_values("Bitrate_kbps")

fig_rd = go.Figure()
fig_rd.add_trace(
    go.Scatter(
        x=baseline_data["Bitrate_kbps"],
        y=baseline_data[selected_metric],
        mode="lines+markers",
        name="Baseline",
        marker=dict(size=10),
        line=dict(width=2, shape="spline", smoothing=1.3),
    )
)
fig_rd.add_trace(
    go.Scatter(
        x=test_data["Bitrate_kbps"],
        y=test_data[selected_metric],
        mode="lines+markers",
        name="Test",
        marker=dict(size=10),
        line=dict(width=2, shape="spline", smoothing=1.3),
    )
)
fig_rd.update_layout(
    title=f"RD Curves - {selected_video}",
    xaxis_title="Bitrate (kbps)",
    yaxis_title=selected_metric,
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
)
with col_chart:
    st.plotly_chart(fig_rd, use_container_width=True)

# Diff 对比表（Baseline vs Test）
base_df = df_metrics[df_metrics["Side"] == "Baseline"]
test_df = df_metrics[df_metrics["Side"] == "Test"]
merged = base_df.merge(
    test_df,
    on=["Video", "RC", "Point"],
    suffixes=("_base", "_test"),
)
if not merged.empty:
    merged["Bitrate Δ%"] = ((merged["Bitrate_kbps_test"] - merged["Bitrate_kbps_base"]) / merged["Bitrate_kbps_base"].replace(0, pd.NA)) * 100
    merged["PSNR Δ"] = merged["PSNR_test"] - merged["PSNR_base"]
    merged["SSIM Δ"] = merged["SSIM_test"] - merged["SSIM_base"]
    merged["VMAF Δ"] = merged["VMAF_test"] - merged["VMAF_base"]
    merged["VMAF-NEG Δ"] = merged["VMAF-NEG_test"] - merged["VMAF-NEG_base"]

    diff_df = merged[
        ["Video", "RC", "Point", "Bitrate Δ%", "PSNR Δ", "SSIM Δ", "VMAF Δ", "VMAF-NEG Δ"]
    ].sort_values(by=["Video", "Point"]).reset_index(drop=True)

    # 合并同一视频的名称（只在第一行显示）
    prev_video = None
    for idx in diff_df.index:
        if diff_df.at[idx, "Video"] == prev_video:
            diff_df.at[idx, "Video"] = ""
        else:
            prev_video = diff_df.at[idx, "Video"]

    # 定义颜色样式函数
    def _color_diff(val):
        if pd.isna(val) or not isinstance(val, (int, float)):
            return ""
        if val > 0:
            return "color: green"
        elif val < 0:
            return "color: red"
        return ""

    diff_cols = ["Bitrate Δ%", "PSNR Δ", "SSIM Δ", "VMAF Δ", "VMAF-NEG Δ"]

    # 格式化精度
    format_dict = {
        "Bitrate Δ%": "{:.2f}",
        "PSNR Δ": "{:.4f}",
        "SSIM Δ": "{:.4f}",
        "VMAF Δ": "{:.2f}",
        "VMAF-NEG Δ": "{:.2f}",
    }
    styled_df = diff_df.style.applymap(_color_diff, subset=diff_cols).format(format_dict, na_rep="-")

    st.subheader("Delta", anchor="delta")
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Video": st.column_config.TextColumn("Video", width="medium"),
        },
    )

# 详细表格（默认折叠）
st.subheader("Details", anchor="details")
with st.expander("查看详细Metrics数据", expanded=False):
    # 格式化精度
    details_format = {
        "Bitrate_kbps": "{:.2f}",
        "PSNR": "{:.4f}",
        "SSIM": "{:.4f}",
        "VMAF": "{:.2f}",
        "VMAF-NEG": "{:.2f}",
    }
    styled_details = df_metrics.sort_values(by=["Video", "RC", "Point", "Side"]).style.format(details_format, na_rep="-")
    st.dataframe(styled_details, use_container_width=True, hide_index=True)


# ========== BD-Rate ==========
st.header("BD-Rate", anchor="bd-rate")
if bd_list:
    df_bd = pd.DataFrame(bd_list)

    # BD-Rate 颜色样式：小于0绿色，大于0红色
    def _color_bd_rate(val):
        if pd.isna(val) or not isinstance(val, (int, float)):
            return ""
        if val < 0:
            return "color: green"
        elif val > 0:
            return "color: red"
        return ""

    bd_rate_cols = ["bd_rate_psnr", "bd_rate_ssim", "bd_rate_vmaf", "bd_rate_vmaf_neg"]
    bd_rate_display = df_bd[["source"] + bd_rate_cols].rename(
        columns={
            "source": "Video",
            "bd_rate_psnr": "BD-Rate PSNR (%)",
            "bd_rate_ssim": "BD-Rate SSIM (%)",
            "bd_rate_vmaf": "BD-Rate VMAF (%)",
            "bd_rate_vmaf_neg": "BD-Rate VMAF-NEG (%)",
        }
    )
    styled_bd_rate = bd_rate_display.style.applymap(
        _color_bd_rate,
        subset=["BD-Rate PSNR (%)", "BD-Rate SSIM (%)", "BD-Rate VMAF (%)", "BD-Rate VMAF-NEG (%)"],
    ).format({
        "BD-Rate PSNR (%)": "{:.2f}",
        "BD-Rate SSIM (%)": "{:.2f}",
        "BD-Rate VMAF (%)": "{:.2f}",
        "BD-Rate VMAF-NEG (%)": "{:.2f}",
    }, na_rep="-")
    st.dataframe(styled_bd_rate, use_container_width=True, hide_index=True)

    # BD-Rate 柱状图（拆分为独立子标题）
    def _create_bd_bar_chart(df, col, title):
        colors = ["green" if v < 0 else "red" if v > 0 else "gray" for v in df[col].fillna(0)]
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=df["source"],
                y=df[col],
                marker_color=colors,
                text=[f"{v:.2f}%" if pd.notna(v) else "" for v in df[col]],
                textposition="outside",
            )
        )
        fig.update_layout(
            title=title,
            xaxis_title="Video",
            yaxis_title="BD-Rate (%)",
            showlegend=False,
        )
        return fig

    st.subheader("BD-Rate PSNR", anchor="bd-rate-psnr")
    st.plotly_chart(_create_bd_bar_chart(df_bd, "bd_rate_psnr", "BD-Rate PSNR, the less, the better"), use_container_width=True)

    st.subheader("BD-Rate SSIM", anchor="bd-rate-ssim")
    st.plotly_chart(_create_bd_bar_chart(df_bd, "bd_rate_ssim", "BD-Rate SSIM, the less, the better"), use_container_width=True)

    st.subheader("BD-Rate VMAF", anchor="bd-rate-vmaf")
    st.plotly_chart(_create_bd_bar_chart(df_bd, "bd_rate_vmaf", "BD-Rate VMAF, the less, the better"), use_container_width=True)

    st.subheader("BD-Rate VMAF-NEG", anchor="bd-rate-vmaf-neg")
    st.plotly_chart(_create_bd_bar_chart(df_bd, "bd_rate_vmaf_neg", "BD-Rate VMAF-NEG, the less, the better"), use_container_width=True)
else:
    st.info("暂无 BD-Rate 数据。")


# ========== BD-Metrics ==========
st.header("BD-Metrics", anchor="bd-metrics")
if bd_list:
    df_bdm = pd.DataFrame(bd_list)

    # BD-Metrics 颜色样式：大于0绿色，小于0红色
    def _color_bd_metrics(val):
        if pd.isna(val) or not isinstance(val, (int, float)):
            return ""
        if val > 0:
            return "color: green"
        elif val < 0:
            return "color: red"
        return ""

    bd_metrics_cols = ["bd_psnr", "bd_ssim", "bd_vmaf", "bd_vmaf_neg"]
    bd_metrics_display = df_bdm[["source"] + bd_metrics_cols].rename(
        columns={
            "source": "Video",
            "bd_psnr": "BD PSNR",
            "bd_ssim": "BD SSIM",
            "bd_vmaf": "BD VMAF",
            "bd_vmaf_neg": "BD VMAF-NEG",
        }
    )
    styled_bd_metrics = bd_metrics_display.style.applymap(
        _color_bd_metrics,
        subset=["BD PSNR", "BD SSIM", "BD VMAF", "BD VMAF-NEG"],
    ).format({
        "BD PSNR": "{:.4f}",
        "BD SSIM": "{:.4f}",
        "BD VMAF": "{:.2f}",
        "BD VMAF-NEG": "{:.2f}",
    }, na_rep="-")
    st.dataframe(styled_bd_metrics, use_container_width=True, hide_index=True)

    # BD-Metrics 柱状图（拆分为独立子标题）
    def _create_bd_metrics_bar_chart(df, col, title):
        colors = ["green" if v > 0 else "red" if v < 0 else "gray" for v in df[col].fillna(0)]
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=df["source"],
                y=df[col],
                marker_color=colors,
                text=[f"{v:.4f}" if pd.notna(v) else "" for v in df[col]],
                textposition="outside",
            )
        )
        fig.update_layout(
            title=title,
            xaxis_title="Video",
            yaxis_title="Δ Metric",
            showlegend=False,
        )
        return fig

    st.subheader("BD PSNR", anchor="bd-psnr")
    st.plotly_chart(_create_bd_metrics_bar_chart(df_bdm, "bd_psnr", "BD PSNR, the more, the better"), use_container_width=True)

    st.subheader("BD SSIM", anchor="bd-ssim")
    st.plotly_chart(_create_bd_metrics_bar_chart(df_bdm, "bd_ssim", "BD SSIM, the more, the better"), use_container_width=True)

    st.subheader("BD VMAF", anchor="bd-vmaf")
    st.plotly_chart(_create_bd_metrics_bar_chart(df_bdm, "bd_vmaf", "BD VMAF, the more, the better"), use_container_width=True)

    st.subheader("BD VMAF-NEG", anchor="bd-vmaf-neg")
    st.plotly_chart(_create_bd_metrics_bar_chart(df_bdm, "bd_vmaf_neg", "BD VMAF-NEG"), use_container_width=True)
else:
    st.info("暂无 BD-Metrics 数据。")


# ========== Bitrate 分析 ==========
st.header("Bitrates", anchor="码率分析")

# 构建可选的视频和点位列表
video_point_options = []
for entry in entries:
    video = entry.get("source")
    base_enc = (entry.get("baseline") or {}).get("encoded") or []
    for item in base_enc:
        rc, point = _parse_point(item.get("label", ""))
        if point is not None:
            video_point_options.append({
                "video": video,
                "point": point,
                "rc": rc,
                "label": f"{video} - {rc}_{point}",
            })

if video_point_options:
    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        video_list_br = list(dict.fromkeys([opt["video"] for opt in video_point_options]))
        selected_video_br = st.selectbox("选择源视频", video_list_br, key="br_video")
    with col_sel2:
        point_list_br = [opt["point"] for opt in video_point_options if opt["video"] == selected_video_br]
        point_list_br = list(dict.fromkeys(point_list_br))
        selected_point_br = st.selectbox("选择码率点位", point_list_br, key="br_point")

    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        chart_type = st.selectbox("图形类型", ["柱状图", "折线图"], key="br_chart_type", index=0)
    with col_opt2:
        bin_seconds = st.slider("聚合间隔 (秒)", min_value=0.1, max_value=5.0, value=1.0, step=0.1, key="br_bin")

    # 找到对应的 baseline 和 test 数据
    baseline_bitrate = None
    test_bitrate = None
    ref_fps = 30.0

    for entry in entries:
        if entry.get("source") == selected_video_br:
            ref_info = (entry.get("baseline") or {}).get("reference") or {}
            ref_fps = ref_info.get("fps") or 30.0

            for item in (entry.get("baseline") or {}).get("encoded") or []:
                rc, point = _parse_point(item.get("label", ""))
                if point == selected_point_br:
                    baseline_bitrate = item.get("bitrate") or {}
                    break

            for item in (entry.get("test") or {}).get("encoded") or []:
                rc, point = _parse_point(item.get("label", ""))
                if point == selected_point_br:
                    test_bitrate = item.get("bitrate") or {}
                    break
            break

    if baseline_bitrate and test_bitrate:
        def _aggregate_bitrate(bitrate_data, bin_sec):
            ts = bitrate_data.get("frame_timestamps", []) or []
            sizes = bitrate_data.get("frame_sizes", []) or []
            bins = {}
            for t, s in zip(ts, sizes):
                try:
                    idx = int(float(t) / bin_sec)
                except (TypeError, ValueError):
                    continue
                bins[idx] = bins.get(idx, 0.0) + float(s) * 8.0
            xs = sorted(bins.keys())
            x_times = [i * bin_sec for i in xs]
            y_kbps = [(bins[i] / bin_sec) / 1000.0 for i in xs]
            return x_times, y_kbps

        base_x, base_y = _aggregate_bitrate(baseline_bitrate, bin_seconds)
        test_x, test_y = _aggregate_bitrate(test_bitrate, bin_seconds)

        fig_br = go.Figure()
        if chart_type == "柱状图":
            fig_br.add_trace(go.Bar(x=base_x, y=base_y, name="Baseline", opacity=0.7))
            fig_br.add_trace(go.Bar(x=test_x, y=test_y, name="Test", opacity=0.7))
            fig_br.update_layout(barmode="group")
        else:
            fig_br.add_trace(go.Scatter(x=base_x, y=base_y, mode="lines+markers", name="Baseline"))
            fig_br.add_trace(go.Scatter(x=test_x, y=test_y, mode="lines+markers", name="Test"))

        fig_br.update_layout(
            title=f"码率对比 - {selected_video_br} ({selected_point_br})",
            xaxis_title="Time (s)",
            yaxis_title="Bitrate (kbps)",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        )
        st.plotly_chart(fig_br, use_container_width=True)

        # 显示平均码率对比
        base_avg = (baseline_bitrate.get("avg_bitrate_bps") or sum(baseline_bitrate.get("frame_sizes", [])) * 8 / (len(baseline_bitrate.get("frame_timestamps", [])) / ref_fps if baseline_bitrate.get("frame_timestamps") else 1)) / 1000
        test_avg = (test_bitrate.get("avg_bitrate_bps") or sum(test_bitrate.get("frame_sizes", [])) * 8 / (len(test_bitrate.get("frame_timestamps", [])) / ref_fps if test_bitrate.get("frame_timestamps") else 1)) / 1000

        # 从 entries 中获取 avg_bitrate_bps
        for entry in entries:
            if entry.get("source") == selected_video_br:
                for item in (entry.get("baseline") or {}).get("encoded") or []:
                    rc, point = _parse_point(item.get("label", ""))
                    if point == selected_point_br:
                        base_avg = item.get("avg_bitrate_bps", 0) / 1000
                        break
                for item in (entry.get("test") or {}).get("encoded") or []:
                    rc, point = _parse_point(item.get("label", ""))
                    if point == selected_point_br:
                        test_avg = item.get("avg_bitrate_bps", 0) / 1000
                        break
                break

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Baseline 平均码率", f"{base_avg:.2f} kbps")
        col_m2.metric("Test 平均码率", f"{test_avg:.2f} kbps")
        diff_pct = ((test_avg - base_avg) / base_avg * 100) if base_avg > 0 else 0
        col_m3.metric("码率差异", f"{diff_pct:+.2f}%")
    else:
        st.warning("未找到对应的码率数据。请确保报告包含帧级码率信息。")
else:
    st.info("暂无码率对比数据。")


# ========== Performance ==========
st.header("Performance", anchor="performance")

# 收集性能数据
perf_rows = []
perf_detail_rows = []
for entry in entries:
    video = entry.get("source")
    for side_key, side_name in (("baseline", "Baseline"), ("test", "Test")):
        side = (entry.get(side_key) or {})
        for item in side.get("encoded", []) or []:
            rc, point = _parse_point(item.get("label", ""))
            perf = item.get("performance") or {}
            if perf:
                perf_rows.append({
                    "Video": video,
                    "Side": side_name,
                    "Point": point,
                    "FPS": perf.get("encoding_fps"),
                    "CPU Avg(%)": perf.get("cpu_avg_percent"),
                    "CPU Max(%)": perf.get("cpu_max_percent"),
                    "cpu_samples": perf.get("cpu_samples", []),
                })
                perf_detail_rows.append({
                    "Video": video,
                    "Side": side_name,
                    "Point": point,
                    "FPS": perf.get("encoding_fps"),
                    "CPU Avg(%)": perf.get("cpu_avg_percent"),
                    "CPU Max(%)": perf.get("cpu_max_percent"),
                    "Total Time(s)": perf.get("total_encoding_time_s"),
                    "Frames": perf.get("total_frames"),
                })

if perf_rows:
    df_perf = pd.DataFrame(perf_rows)

    # 1. 汇总Diff表格
    st.subheader("Delta", anchor="perf-diff")
    base_perf = df_perf[df_perf["Side"] == "Baseline"]
    test_perf = df_perf[df_perf["Side"] == "Test"]
    merged_perf = base_perf.merge(
        test_perf,
        on=["Video", "Point"],
        suffixes=("_base", "_test"),
    )
    if not merged_perf.empty:
        merged_perf["Δ FPS"] = merged_perf["FPS_test"] - merged_perf["FPS_base"]
        merged_perf["Δ CPU Avg(%)"] = merged_perf["CPU Avg(%)_test"] - merged_perf["CPU Avg(%)_base"]

        diff_perf_df = merged_perf[
            ["Video", "Point", "FPS_base", "FPS_test", "Δ FPS", "CPU Avg(%)_base", "CPU Avg(%)_test", "Δ CPU Avg(%)"]
        ].rename(columns={
            "FPS_base": "Baseline FPS",
            "FPS_test": "Test FPS",
            "CPU Avg(%)_base": "Baseline CPU(%)",
            "CPU Avg(%)_test": "Test CPU(%)",
        }).sort_values(by=["Video", "Point"]).reset_index(drop=True)

        # 合并同一视频的名称
        prev_video = None
        for idx in diff_perf_df.index:
            if diff_perf_df.at[idx, "Video"] == prev_video:
                diff_perf_df.at[idx, "Video"] = ""
            else:
                prev_video = diff_perf_df.at[idx, "Video"]

        def _color_perf_diff(val):
            if pd.isna(val) or not isinstance(val, (int, float)):
                return ""
            if val > 0:
                return "color: green"
            elif val < 0:
                return "color: red"
            return ""

        # 格式化精度：FPS 和 CPU 都保留2位小数
        perf_format_dict = {
            "Baseline FPS": "{:.2f}",
            "Test FPS": "{:.2f}",
            "Δ FPS": "{:.2f}",
            "Baseline CPU(%)": "{:.2f}",
            "Test CPU(%)": "{:.2f}",
            "Δ CPU Avg(%)": "{:.2f}",
        }
        styled_perf = diff_perf_df.style.applymap(_color_perf_diff, subset=["Δ FPS", "Δ CPU Avg(%)"]).format(perf_format_dict, na_rep="-")
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
    base_samples = []
    test_samples = []
    for _, row in df_perf.iterrows():
        if row["Video"] == selected_video_perf and row["Point"] == selected_point_perf:
            if row["Side"] == "Baseline":
                base_samples = row.get("cpu_samples", []) or []
            else:
                test_samples = row.get("cpu_samples", []) or []

    if base_samples or test_samples:
        fig_cpu = create_cpu_chart(
            base_samples=base_samples,
            exp_samples=test_samples,
            agg_interval=agg_interval,
            title=f"CPU占用率 - {selected_video_perf} ({selected_point_perf})",
            base_label="Baseline",
            exp_label="Test",
        )
        st.plotly_chart(fig_cpu, use_container_width=True)
    else:
        st.info("该视频/点位没有CPU采样数据。")

    # 3. 详细数据表格（默认折叠）
    st.subheader("Details", anchor="perf-details")
    with st.expander("查看详细性能数据", expanded=False):
        df_perf_detail = pd.DataFrame(perf_detail_rows)
        # 格式化精度：FPS 和 CPU 保留2位小数
        perf_detail_format = {
            "FPS": "{:.2f}",
            "CPU Avg(%)": "{:.2f}",
            "CPU Max(%)": "{:.2f}",
            "Total Time(s)": "{:.2f}",
        }
        styled_perf_detail = df_perf_detail.sort_values(by=["Video", "Point", "Side"]).style.format(perf_detail_format, na_rep="-")
        st.dataframe(styled_perf_detail, use_container_width=True, hide_index=True)
else:
    st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")

# ========== 环境信息 ==========
st.header("Machine Info", anchor="环境信息")

def _format_env_info(env: Dict[str, Any]) -> str:
    """格式化环境信息为 Markdown 列表"""
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

# 使用 baseline_environment（任务开始时的环境状态）
env = report.get("baseline_environment") or report.get("test_environment") or {}

if env:
    st.markdown(_format_env_info(env))
else:
    st.write("未采集到环境信息。")
