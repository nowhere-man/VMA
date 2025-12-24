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
    return st.session_state.get("template_job_id")


def _load_report(job_id: str) -> Dict[str, Any]:
    report_path = _jobs_root_dir() / job_id / "metrics_analysis" / "report_data.json"
    if not report_path.exists():
        raise FileNotFoundError(f"未找到报告数据文件: {report_path}")
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)


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


st.set_page_config(page_title="模板 Metrics 报告 - VMA", page_icon="📊", layout="wide")
st.title("📊 模板 Metrics 报告")

job_id = _get_job_id()
if not job_id:
    st.info("请选择一个模板任务，或从任务列表/详情页带参数跳转。")
    jobs = _list_template_jobs()
    if not jobs:
        st.warning("暂未找到模板指标报告。请先创建模板任务。")
        st.stop()
    options = {f"{item['job_id']} (最近修改)": item["job_id"] for item in jobs}
    selected = st.selectbox("选择报告", options=list(options.keys()))
    if selected:
        chosen_job = options[selected]
        st.session_state["template_job_id"] = chosen_job
        try:
            st.query_params["template_job_id"] = chosen_job
        except Exception:
            pass
        st.rerun()
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

st.caption(
    f"Job: {job_id} | 模板: {report.get('template_name') or report.get('template_id')} | "
    f"码控: {report.get('rate_control')} | 点位: {', '.join(str(p) for p in report.get('bitrate_points') or [])}"
)


# ========== Metrics ==========
st.header("Metrics")

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

st.dataframe(df_metrics.sort_values(by=["Video", "RC", "Point", "Side"]), use_container_width=True, hide_index=True)

# 对比表（Baseline vs Experimental）
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
    st.subheader("Baseline vs Experimental 对比")
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


# ========== BD-Rate ==========
st.header("BD-Rate")
if bd_list:
    df_bd = pd.DataFrame(bd_list)
    st.dataframe(
        df_bd[
            [
                "source",
                "bd_rate_psnr",
                "bd_rate_ssim",
                "bd_rate_vmaf",
                "bd_rate_vmaf_neg",
            ]
        ].rename(
            columns={
                "source": "Video",
                "bd_rate_psnr": "BD-Rate PSNR (%)",
                "bd_rate_ssim": "BD-Rate SSIM (%)",
                "bd_rate_vmaf": "BD-Rate VMAF (%)",
                "bd_rate_vmaf_neg": "BD-Rate VMAF-NEG (%)",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    fig = go.Figure()
    for key, name in [
        ("bd_rate_psnr", "BD-Rate PSNR"),
        ("bd_rate_ssim", "BD-Rate SSIM"),
        ("bd_rate_vmaf", "BD-Rate VMAF"),
        ("bd_rate_vmaf_neg", "BD-Rate VMAF-NEG"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df_bd["source"],
                y=df_bd[key],
                mode="lines+markers",
                name=name,
            )
        )
    fig.update_layout(yaxis_title="Δ Bitrate (%)", xaxis_title="Video")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("暂无 BD-Rate 数据。")


# ========== BD-Metrics ==========
st.header("BD-Metrics")
if bd_list:
    df_bdm = pd.DataFrame(bd_list)
    st.dataframe(
        df_bdm[
            [
                "source",
                "bd_psnr",
                "bd_ssim",
                "bd_vmaf",
                "bd_vmaf_neg",
            ]
        ].rename(
            columns={
                "source": "Video",
                "bd_psnr": "BD PSNR",
                "bd_ssim": "BD SSIM",
                "bd_vmaf": "BD VMAF",
                "bd_vmaf_neg": "BD VMAF-NEG",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    fig2 = go.Figure()
    for key, name in [
        ("bd_psnr", "BD PSNR"),
        ("bd_ssim", "BD SSIM"),
        ("bd_vmaf", "BD VMAF"),
        ("bd_vmaf_neg", "BD VMAF-NEG"),
    ]:
        fig2.add_trace(
            go.Scatter(
                x=df_bdm["source"],
                y=df_bdm[key],
                mode="lines+markers",
                name=name,
            )
        )
    fig2.update_layout(yaxis_title="Δ Metric", xaxis_title="Video")
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("暂无 BD-Metrics 数据。")


# ========== Bitrate 分析 ==========
st.header("码率分析")
if not merged.empty:
    st.dataframe(
        merged[
            [
                "Video",
                "RC",
                "Point",
                "Bitrate_kbps_base",
                "Bitrate_kbps_exp",
                "Bitrate Δ%",
            ]
        ].sort_values(by=["Video", "Point"]),
        use_container_width=True,
        hide_index=True,
    )
    fig3 = go.Figure()
    x_vals = merged.apply(lambda r: f"{r['Video']}_{r['Point']}", axis=1)
    for side, col in [("Baseline", "Bitrate_kbps_base"), ("Experimental", "Bitrate_kbps_exp")]:
        fig3.add_trace(
            go.Bar(
                x=x_vals,
                y=merged[col],
                name=side,
            )
        )
    fig3.update_layout(barmode="group", xaxis_title="Video_Point", yaxis_title="Bitrate (kbps)")
    st.plotly_chart(fig3, use_container_width=True)
else:
    st.info("暂无码率对比数据。")


# ========== Performance（占位） ==========
st.header("Performance")
st.info("TODO: 后续加入 CPU 占用、FPS 以及编码时间统计对比。")

# ========== 环境信息 ==========
st.header("环境信息")
env = report.get("environment") or {}
if env:
    env_rows = [{"项": k, "值": v} for k, v in env.items()]
    st.table(pd.DataFrame(env_rows))
else:
    st.write("未采集到环境信息。")
