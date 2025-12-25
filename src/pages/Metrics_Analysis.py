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
import scipy.interpolate  # type: ignore
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


def _list_metrics_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    root = _jobs_root_dir()
    if not root.exists():
        return []
    items: List[Dict[str, Any]] = []
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        data_path = job_dir / "metrics_analysis" / "analyse_data.json"
        meta_path = job_dir / "metadata.json"
        if not data_path.exists():
            continue
        status_ok = True
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            status_ok = meta.get("status") == "COMPLETED"
        except Exception:
            status_ok = True
        items.append({"job_id": job_dir.name, "mtime": data_path.stat().st_mtime, "status_ok": status_ok})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def _load_analyse(job_id: str) -> Dict[str, Any]:
    path = _jobs_root_dir() / job_id / "metrics_analysis" / "analyse_data.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到数据文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_point(label: str) -> Tuple[Optional[str], Optional[float]]:
    if not label:
        return None, None
    parts = label.rsplit("_", 2)
    if len(parts) < 3:
        return None, None
    rc = parts[-2]
    try:
        val = float(parts[-1])
    except Exception:
        return rc, None
    return rc, val


def _metric_value(metrics: Dict[str, Any], name: str, field: str) -> Optional[float]:
    block = metrics.get(name) or {}
    if not isinstance(block, dict):
        return None
    summary = block.get("summary") or {}
    if isinstance(summary, dict) and field in summary:
        return summary.get(field)
    return block.get(field)


def _bd_rate(rate1: List[float], metric1: List[float], rate2: List[float], metric2: List[float], piecewise: int = 0) -> Optional[float]:
    if len(rate1) < 4 or len(rate2) < 4:
        return None
    lR1 = np.log(rate1)
    lR2 = np.log(rate2)
    try:
        p1 = np.polyfit(metric1, lR1, 3)
        p2 = np.polyfit(metric2, lR2, 3)
    except Exception:
        return None
    min_int = max(min(metric1), min(metric2))
    max_int = min(max(metric1), max(metric2))
    if max_int <= min_int:
        return None
    if piecewise == 0:
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)
        int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
        int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
    else:
        lin = np.linspace(min_int, max_int, num=100, retstep=True)
        interval = lin[1]
        samples = lin[0]
        v1 = scipy.interpolate.pchip_interpolate(np.sort(metric1), lR1[np.argsort(metric1)], samples)
        v2 = scipy.interpolate.pchip_interpolate(np.sort(metric2), lR2[np.argsort(metric2)], samples)
        int1 = np.trapz(v1, dx=interval)
        int2 = np.trapz(v2, dx=interval)
    avg_exp_diff = (int2 - int1) / (max_int - min_int)
    return (np.exp(avg_exp_diff) - 1) * 100


def _bd_metrics(rate1: List[float], metric1: List[float], rate2: List[float], metric2: List[float], piecewise: int = 0) -> Optional[float]:
    if len(rate1) < 4 or len(rate2) < 4:
        return None
    lR1 = np.log(rate1)
    lR2 = np.log(rate2)
    try:
        p1 = np.polyfit(lR1, metric1, 3)
        p2 = np.polyfit(lR2, metric2, 3)
    except Exception:
        return None
    min_int = max(min(lR1), min(lR2))
    max_int = min(max(lR1), max(lR2))
    if max_int <= min_int:
        return None
    if piecewise == 0:
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)
        int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
        int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
    else:
        lin = np.linspace(min_int, max_int, num=100, retstep=True)
        interval = lin[1]
        samples = lin[0]
        v1 = scipy.interpolate.pchip_interpolate(np.sort(lR1), metric1[np.argsort(lR1)], samples)
        v2 = scipy.interpolate.pchip_interpolate(np.sort(lR2), metric2[np.argsort(lR2)], samples)
        int1 = np.trapz(v1, dx=interval)
        int2 = np.trapz(v2, dx=interval)
    avg_diff = (int2 - int1) / (max_int - min_int)
    return avg_diff


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
    st.markdown("### 📑 目录")
    st.markdown("""
- [Metrics](#metrics)
  - [A vs B 对比](#a-vs-b-对比)
- [BD-Rate](#bd-rate)
- [BD-Metrics](#bd-metrics)
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

st.header("Metrics", anchor="metrics")
st.dataframe(df, use_container_width=True, hide_index=True)

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
    st.dataframe(
        merged[
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
        ].sort_values(by=["Video", "Point"]),
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
    st.subheader("Diff", anchor="perf-diff")
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
    base_samples: List[float] = []
    exp_samples: List[float] = []
    for _, row in df_perf.iterrows():
        if row["Video"] == selected_video_perf and row["Point"] == selected_point_perf:
            if row["Side"] == "A":
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

        # A 折线
        if base_y:
            fig_cpu.add_trace(go.Scatter(
                x=base_x, y=base_y,
                mode="lines",
                name="A",
                line=dict(color="#2563eb", width=2),
            ))
            # 标记最大值
            if base_y:
                max_idx = base_y.index(max(base_y))
                fig_cpu.add_trace(go.Scatter(
                    x=[base_x[max_idx]], y=[base_y[max_idx]],
                    mode="markers+text",
                    name="A Max",
                    marker=dict(color="#2563eb", size=12, symbol="star"),
                    text=[f"Max: {base_y[max_idx]:.1f}%"],
                    textposition="top center",
                    showlegend=False,
                ))

        # B 折线
        if exp_y:
            fig_cpu.add_trace(go.Scatter(
                x=exp_x, y=exp_y,
                mode="lines",
                name="B",
                line=dict(color="#dc2626", width=2),
            ))
            # 标记最大值
            if exp_y:
                max_idx = exp_y.index(max(exp_y))
                fig_cpu.add_trace(go.Scatter(
                    x=[exp_x[max_idx]], y=[exp_y[max_idx]],
                    mode="markers+text",
                    name="B Max",
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
        # 移除 cpu_samples 列用于展示
        df_perf_detail = df_perf.drop(columns=["cpu_samples"], errors="ignore")
        st.dataframe(df_perf_detail.sort_values(by=["Video", "Point", "Side"]), use_container_width=True, hide_index=True)
else:
    st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")

st.header("环境信息", anchor="环境信息")
env_a = data_a.get("environment") or {}
env_b = data_b.get("environment") or {}
if env_a or env_b:
    st.markdown("**任务 A 环境**")
    st.table(pd.DataFrame([{"项": k, "值": v} for k, v in env_a.items()]) if env_a else pd.DataFrame(columns=["项", "值"]))
    st.markdown("**任务 B 环境**")
    st.table(pd.DataFrame([{"项": k, "值": v} for k, v in env_b.items()]) if env_b else pd.DataFrame(columns=["项", "值"]))
else:
    st.info("未采集到环境信息。")
