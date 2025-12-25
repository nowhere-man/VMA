"""
模板 Metrics对比 报告页面（Baseline / Experimental）

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

from src.config import settings


def _jobs_root_dir() -> Path:
    root = settings.jobs_root_dir
    if root.is_absolute():
        return root
    return (project_root / root).resolve()


def _list_template_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    root = _jobs_root_dir()
    if not root.exists():
        return []
    items: List[Dict[str, Any]] = []
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        report_path = job_dir / "metrics_analysis" / "report_data.json"
        if report_path.exists():
            items.append(
                {
                    "job_id": job_dir.name,
                    "mtime": report_path.stat().st_mtime,
                    "report_path": report_path,
                }
            )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def _get_job_id() -> Optional[str]:
    job_id = st.query_params.get("template_job_id")
    if job_id:
        if isinstance(job_id, list):
            job_id = job_id[0] if job_id else None
        return str(job_id) if job_id else None
    return None


def _load_report(job_id: str) -> Dict[str, Any]:
    report_path = _jobs_root_dir() / job_id / "metrics_analysis" / "report_data.json"
    if not report_path.exists():
        raise FileNotFoundError(f"未找到报告数据文件: {report_path}")
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_point(label: str) -> Tuple[Optional[str], Optional[float]]:
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
    except Exception:
        return rc, None
    return rc, val


st.set_page_config(page_title="Metrics对比", page_icon="📊", layout="wide")
st.markdown("<h1 style='text-align:center;'>📊 Metrics对比报告</h1>", unsafe_allow_html=True)

job_id = _get_job_id()
if not job_id:
    jobs = _list_template_jobs()
    if not jobs:
        st.warning("暂未找到报告，请先创建任务。")
        st.stop()
    st.subheader("全部Metrics对比报告")
    for item in jobs:
        jid = item["job_id"]
        st.markdown(
            f"- <a href='?template_job_id={jid}' target='_blank'>{jid} · metrics_analysis/report_data.json</a>",
            unsafe_allow_html=True,
        )
    st.stop()
else:
    # 提供返回列表入口，清空参数后回到列表视图
    if st.button("返回报告列表", type="secondary"):
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.session_state.pop("template_job_id", None)
        st.rerun()

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

st.caption(
    f"Job: {job_id} | 模板: {report.get('template_name') or report.get('template_id')} | "
    f"码控: {report.get('rate_control')} | 点位: {', '.join(str(p) for p in report.get('bitrate_points') or [])}"
)

# ========== 侧边栏目录 ==========
with st.sidebar:
    st.markdown("### 📑 目录")
    st.markdown("""
- [Metrics](#metrics)
  - [RD Curve](#rd-curve)
  - [Delta](#delta)
  - [Details](#details)
- [BD-Rate](#bd-rate)
- [BD-Metrics](#bd-metrics)
- [码率分析](#码率分析)
- [Performance](#performance)
  - [Diff](#perf-diff)
  - [CPU占用折线图](#cpu-chart)
  - [详细数据](#perf-details)
- [环境信息](#环境信息)
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
    for side_key, side_name in (("baseline", "Baseline"), ("experimental", "Experimental")):
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
st.subheader("RD Curve", anchor="rd-curve")
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
exp_data = video_df[video_df["Side"] == "Experimental"].sort_values("Bitrate_kbps")

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
        x=exp_data["Bitrate_kbps"],
        y=exp_data[selected_metric],
        mode="lines+markers",
        name="Experimental",
        marker=dict(size=10),
        line=dict(width=2, shape="spline", smoothing=1.3),
    )
)
fig_rd.update_layout(
    title=f"RD Curve - {selected_video}",
    xaxis_title="Bitrate (kbps)",
    yaxis_title=selected_metric,
    hovermode="x unified",
    legend=dict(orientation="h", y=-0.15),
)
with col_chart:
    st.plotly_chart(fig_rd, use_container_width=True)

# Diff 对比表（Baseline vs Experimental）
base_df = df_metrics[df_metrics["Side"] == "Baseline"]
exp_df = df_metrics[df_metrics["Side"] == "Experimental"]
merged = base_df.merge(
    exp_df,
    on=["Video", "RC", "Point"],
    suffixes=("_base", "_exp"),
)
if not merged.empty:
    merged["Bitrate Δ%"] = ((merged["Bitrate_kbps_exp"] - merged["Bitrate_kbps_base"]) / merged["Bitrate_kbps_base"].replace(0, pd.NA)) * 100
    merged["PSNR Δ"] = merged["PSNR_exp"] - merged["PSNR_base"]
    merged["SSIM Δ"] = merged["SSIM_exp"] - merged["SSIM_base"]
    merged["VMAF Δ"] = merged["VMAF_exp"] - merged["VMAF_base"]
    merged["VMAF-NEG Δ"] = merged["VMAF-NEG_exp"] - merged["VMAF-NEG_base"]

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
    styled_df = diff_df.style.applymap(_color_diff, subset=diff_cols)

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
    st.dataframe(df_metrics.sort_values(by=["Video", "RC", "Point", "Side"]), use_container_width=True, hide_index=True)


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
    )
    st.dataframe(styled_bd_rate, use_container_width=True, hide_index=True)

    # BD-Rate 柱状图（Tab 页形式）
    tab_psnr, tab_ssim, tab_vmaf, tab_vmaf_neg = st.tabs(
        ["BD-Rate PSNR", "BD-Rate SSIM", "BD-Rate VMAF", "BD-Rate VMAF-NEG"]
    )

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

    with tab_psnr:
        st.plotly_chart(_create_bd_bar_chart(df_bd, "bd_rate_psnr", "BD-Rate PSNR"), use_container_width=True)
    with tab_ssim:
        st.plotly_chart(_create_bd_bar_chart(df_bd, "bd_rate_ssim", "BD-Rate SSIM"), use_container_width=True)
    with tab_vmaf:
        st.plotly_chart(_create_bd_bar_chart(df_bd, "bd_rate_vmaf", "BD-Rate VMAF"), use_container_width=True)
    with tab_vmaf_neg:
        st.plotly_chart(_create_bd_bar_chart(df_bd, "bd_rate_vmaf_neg", "BD-Rate VMAF-NEG"), use_container_width=True)
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
    )
    st.dataframe(styled_bd_metrics, use_container_width=True, hide_index=True)

    # BD-Metrics 柱状图（Tab 页形式）
    tab_bd_psnr, tab_bd_ssim, tab_bd_vmaf, tab_bd_vmaf_neg = st.tabs(
        ["BD PSNR", "BD SSIM", "BD VMAF", "BD VMAF-NEG"]
    )

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

    with tab_bd_psnr:
        st.plotly_chart(_create_bd_metrics_bar_chart(df_bdm, "bd_psnr", "BD PSNR"), use_container_width=True)
    with tab_bd_ssim:
        st.plotly_chart(_create_bd_metrics_bar_chart(df_bdm, "bd_ssim", "BD SSIM"), use_container_width=True)
    with tab_bd_vmaf:
        st.plotly_chart(_create_bd_metrics_bar_chart(df_bdm, "bd_vmaf", "BD VMAF"), use_container_width=True)
    with tab_bd_vmaf_neg:
        st.plotly_chart(_create_bd_metrics_bar_chart(df_bdm, "bd_vmaf_neg", "BD VMAF-NEG"), use_container_width=True)
else:
    st.info("暂无 BD-Metrics 数据。")


# ========== Bitrate 分析 ==========
st.header("码率分析", anchor="码率分析")

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

    # 找到对应的 baseline 和 experimental 数据
    baseline_bitrate = None
    exp_bitrate = None
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

            for item in (entry.get("experimental") or {}).get("encoded") or []:
                rc, point = _parse_point(item.get("label", ""))
                if point == selected_point_br:
                    exp_bitrate = item.get("bitrate") or {}
                    break
            break

    if baseline_bitrate and exp_bitrate:
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
        exp_x, exp_y = _aggregate_bitrate(exp_bitrate, bin_seconds)

        fig_br = go.Figure()
        if chart_type == "柱状图":
            fig_br.add_trace(go.Bar(x=base_x, y=base_y, name="Baseline", opacity=0.7))
            fig_br.add_trace(go.Bar(x=exp_x, y=exp_y, name="Experimental", opacity=0.7))
            fig_br.update_layout(barmode="group")
        else:
            fig_br.add_trace(go.Scatter(x=base_x, y=base_y, mode="lines+markers", name="Baseline", line_shape="hv"))
            fig_br.add_trace(go.Scatter(x=exp_x, y=exp_y, mode="lines+markers", name="Experimental", line_shape="hv"))

        fig_br.update_layout(
            title=f"码率对比 - {selected_video_br} ({selected_point_br})",
            xaxis_title="Time (s)",
            yaxis_title="Bitrate (kbps)",
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig_br, use_container_width=True)

        # 显示平均码率对比
        base_avg = (baseline_bitrate.get("avg_bitrate_bps") or sum(baseline_bitrate.get("frame_sizes", [])) * 8 / (len(baseline_bitrate.get("frame_timestamps", [])) / ref_fps if baseline_bitrate.get("frame_timestamps") else 1)) / 1000
        exp_avg = (exp_bitrate.get("avg_bitrate_bps") or sum(exp_bitrate.get("frame_sizes", [])) * 8 / (len(exp_bitrate.get("frame_timestamps", [])) / ref_fps if exp_bitrate.get("frame_timestamps") else 1)) / 1000

        # 从 entries 中获取 avg_bitrate_bps
        for entry in entries:
            if entry.get("source") == selected_video_br:
                for item in (entry.get("baseline") or {}).get("encoded") or []:
                    rc, point = _parse_point(item.get("label", ""))
                    if point == selected_point_br:
                        base_avg = item.get("avg_bitrate_bps", 0) / 1000
                        break
                for item in (entry.get("experimental") or {}).get("encoded") or []:
                    rc, point = _parse_point(item.get("label", ""))
                    if point == selected_point_br:
                        exp_avg = item.get("avg_bitrate_bps", 0) / 1000
                        break
                break

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Baseline 平均码率", f"{base_avg:.2f} kbps")
        col_m2.metric("Experimental 平均码率", f"{exp_avg:.2f} kbps")
        diff_pct = ((exp_avg - base_avg) / base_avg * 100) if base_avg > 0 else 0
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
    for side_key, side_name in (("baseline", "Baseline"), ("experimental", "Experimental")):
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
    st.subheader("Diff", anchor="perf-diff")
    base_perf = df_perf[df_perf["Side"] == "Baseline"]
    exp_perf = df_perf[df_perf["Side"] == "Experimental"]
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
            "FPS_base": "Baseline FPS",
            "FPS_exp": "Exp FPS",
            "CPU Avg(%)_base": "Baseline CPU(%)",
            "CPU Avg(%)_exp": "Exp CPU(%)",
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

        styled_perf = diff_perf_df.style.applymap(_color_perf_diff, subset=["Δ FPS", "Δ CPU Avg(%)"])
        st.dataframe(styled_perf, use_container_width=True, hide_index=True)

    # 2. CPU折线图
    st.subheader("CPU占用折线图", anchor="cpu-chart")

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
    exp_samples = []
    for _, row in df_perf.iterrows():
        if row["Video"] == selected_video_perf and row["Point"] == selected_point_perf:
            if row["Side"] == "Baseline":
                base_samples = row.get("cpu_samples", []) or []
            else:
                exp_samples = row.get("cpu_samples", []) or []

    def _aggregate_samples(samples: List[float], interval_ms: int) -> Tuple[List[float], List[float]]:
        """聚合CPU采样数据"""
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

    if base_samples or exp_samples:
        base_x, base_y = _aggregate_samples(base_samples, agg_interval)
        exp_x, exp_y = _aggregate_samples(exp_samples, agg_interval)

        fig_cpu = go.Figure()

        # Baseline 折线
        if base_y:
            fig_cpu.add_trace(go.Scatter(
                x=base_x, y=base_y,
                mode="lines",
                name="Baseline",
                line=dict(color="#2563eb", width=2),
            ))
            # 标记最大值
            if base_y:
                max_idx = base_y.index(max(base_y))
                fig_cpu.add_trace(go.Scatter(
                    x=[base_x[max_idx]], y=[base_y[max_idx]],
                    mode="markers+text",
                    name="Baseline Max",
                    marker=dict(color="#2563eb", size=12, symbol="star"),
                    text=[f"Max: {base_y[max_idx]:.1f}%"],
                    textposition="top center",
                    showlegend=False,
                ))

        # Experimental 折线
        if exp_y:
            fig_cpu.add_trace(go.Scatter(
                x=exp_x, y=exp_y,
                mode="lines",
                name="Experimental",
                line=dict(color="#dc2626", width=2),
            ))
            # 标记最大值
            if exp_y:
                max_idx = exp_y.index(max(exp_y))
                fig_cpu.add_trace(go.Scatter(
                    x=[exp_x[max_idx]], y=[exp_y[max_idx]],
                    mode="markers+text",
                    name="Exp Max",
                    marker=dict(color="#dc2626", size=12, symbol="star"),
                    text=[f"Max: {exp_y[max_idx]:.1f}%"],
                    textposition="top center",
                    showlegend=False,
                ))

        fig_cpu.update_layout(
            title=f"CPU占用率 - {selected_video_perf} ({selected_point_perf})",
            xaxis_title="Time (s)",
            yaxis_title="CPU (%)",
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig_cpu, use_container_width=True)
    else:
        st.info("该视频/点位没有CPU采样数据。")

    # 3. 详细数据表格（默认折叠）
    st.subheader("详细数据", anchor="perf-details")
    with st.expander("查看详细性能数据", expanded=False):
        df_perf_detail = pd.DataFrame(perf_detail_rows)
        st.dataframe(df_perf_detail.sort_values(by=["Video", "Point", "Side"]), use_container_width=True, hide_index=True)
else:
    st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")

# ========== 环境信息 ==========
st.header("环境信息", anchor="环境信息")
env = report.get("environment") or {}
if env:
    # 使用卡片式布局展示环境信息
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("系统信息")
        os_name = env.get('os', 'N/A')
        os_version = env.get('os_version', '')
        os_full = env.get('os_full', env.get('os', 'N/A'))
        hostname = env.get('hostname', 'N/A')
        exec_time = env.get('execution_time', 'N/A')

        st.markdown(f"""
- **执行时间**: {exec_time}
- **操作系统**: {os_name} {os_version}
- **主机名**: {hostname}
""")

    with col2:
        st.subheader("CPU 信息")
        cpu_arch = env.get('cpu_arch', 'N/A')
        cpu_model = env.get('cpu_model', env.get('cpu', 'N/A'))
        phys_cores = env.get('cpu_phys_cores', env.get('phys_cores', 'N/A'))
        log_cores = env.get('cpu_log_cores', env.get('log_cores', 'N/A'))
        cpu_percent = env.get('cpu_percent_before', env.get('cpu_percent_start', 'N/A'))

        st.markdown(f"""
- **CPU 型号**: {cpu_model}
- **CPU 架构**: {cpu_arch}
- **核心/线程**: {phys_cores} / {log_cores}
- **执行前占用**: {cpu_percent}%
""")

    st.subheader("内存信息")
    # 兼容旧格式和新格式
    mem_total = env.get('mem_total_mb')
    mem_available = env.get('mem_available_mb')
    if mem_total is None and env.get('mem_total'):
        try:
            mem_total = round(int(env.get('mem_total')) / (1024 * 1024), 2)
        except (ValueError, TypeError):
            mem_total = None
    if mem_available is None and env.get('mem_available'):
        try:
            mem_available = round(int(env.get('mem_available')) / (1024 * 1024), 2)
        except (ValueError, TypeError):
            mem_available = None

    mem_percent = env.get('mem_percent_used')
    # 如果没有 mem_percent_used，从 total 和 available 计算
    if mem_percent is None and mem_total and mem_available:
        mem_percent = round((1 - mem_available / mem_total) * 100, 1)

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("内存总量", f"{mem_total:.0f} MB" if mem_total else 'N/A')
    col_m2.metric("执行前可用", f"{mem_available:.0f} MB" if mem_available else 'N/A')
    col_m3.metric("内存使用率", f"{mem_percent}%" if mem_percent is not None else 'N/A')
else:
    st.write("未采集到环境信息。")
