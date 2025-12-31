"""
模板 Metrics对比 报告页面（Anchor / Test）

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
    color_positive_green,
    color_positive_red,
    format_env_info,
    render_overall_section,
    render_delta_bar_chart_by_point,
    render_delta_table_expander,
)
from src.utils.streamlit_metrics_components import (
    inject_smooth_scroll_css,
    render_performance_section,
    render_sidebar_contents,
    render_rd_curves,
    render_metrics_delta,
    render_bd_rate_section,
    render_bd_metrics_section,
)


def _list_template_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    return list_jobs("metrics_analysis/report_data.json", limit=limit)


def _get_job_id() -> Optional[str]:
    return get_query_param("template_job_id")


def _load_report(job_id: str) -> Dict[str, Any]:
    return load_json_report(job_id, "metrics_analysis/report_data.json")


def _format_points(points: List[float]) -> str:
    clean = [p for p in points if isinstance(p, (int, float))]
    if not clean:
        return "-"
    return ", ".join(f"{p:g}" for p in sorted(set(clean)))


def _format_encoder_type(info: Dict[str, Any]) -> str:
    return info.get("encoder_type") or "-"


def _format_encoder_params(info: Dict[str, Any]) -> str:
    return info.get("encoder_params") or "-"


def _collect_points(entries: List[Dict[str, Any]], side_key: str) -> List[float]:
    points: List[float] = []
    for entry in entries:
        side = entry.get(side_key) or {}
        for item in side.get("encoded", []) or []:
            _, val = _parse_point(item.get("label", ""))
            if isinstance(val, (int, float)):
                points.append(val)
    return points


st.set_page_config(page_title="Metrics对比", page_icon="🆚", layout="wide")

job_id = _get_job_id()
if not job_id:
    st.markdown("<h1 style='text-align:center;'>🆚 Metrics对比报告</h1>", unsafe_allow_html=True)
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

point_values: set = set()
for entry in entries:
    for side_key in ("anchor", "test"):
        side = entry.get(side_key) or {}
        for item in side.get("encoded", []) or []:
            _, val = _parse_point(item.get("label", ""))
            if isinstance(val, (int, float)):
                point_values.add(val)

has_bd = len(point_values) >= 4
if not has_bd:
    bd_list = []

# 隐藏默认的 pages 导航，只显示 Contents 目录
st.markdown("""
<style>
    [data-testid="stSidebarNav"] {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

# 显示报告标题
template_name = report.get('template_name') or report.get('template_id', 'Unknown')
st.markdown(f"<h1 style='text-align:center;'>{template_name} - 对比报告</h1>", unsafe_allow_html=True)
st.markdown(f"<h4 style='text-align:right;'>{job_id}</h4>", unsafe_allow_html=True)
# ========== 侧边栏目录 ==========
with st.sidebar:
    render_sidebar_contents(has_bd=has_bd)

inject_smooth_scroll_css()

# ========== Information ==========
st.header("Information", anchor="information")

anchor_info = report.get("anchor", {}) or {}
test_info = report.get("test", {}) or {}
anchor_points = _collect_points(entries, "anchor")
test_points = _collect_points(entries, "test")

info_df = pd.DataFrame(
    [
        {"项目": "编码器类型", "Anchor": _format_encoder_type(anchor_info), "Test": _format_encoder_type(test_info)},
        {"项目": "编码参数", "Anchor": _format_encoder_params(anchor_info), "Test": _format_encoder_params(test_info)},
        {"项目": "码率点位", "Anchor": _format_points(anchor_points), "Test": _format_points(test_points)},
    ]
)
st.dataframe(info_df, use_container_width=True, hide_index=True)


# ========== Overall ==========
st.header("Overall", anchor="overall")

# 先构建数据用于 Overall 计算
_overall_rows = []
_overall_perf_rows = []
for entry in entries:
    video = entry.get("source")
    for side_key, side_name in (("anchor", "Anchor"), ("test", "Test")):
        side = (entry.get(side_key) or {})
        for item in side.get("encoded", []) or []:
            rc, val = _parse_point(item.get("label", ""))
            psnr_avg = (item.get("psnr") or {}).get("psnr_avg")
            ssim_avg = (item.get("ssim") or {}).get("ssim_avg")
            vmaf_mean = (item.get("vmaf") or {}).get("vmaf_mean")
            vmaf_neg_mean = (item.get("vmaf") or {}).get("vmaf_neg_mean")
            _overall_rows.append({
                "Video": video,
                "Side": side_name,
                "RC": rc,
                "Point": val,
                "Bitrate_kbps": (item.get("avg_bitrate_bps") or 0) / 1000,
                "PSNR": psnr_avg,
                "SSIM": ssim_avg,
                "VMAF": vmaf_mean,
                "VMAF-NEG": vmaf_neg_mean,
            })
            perf = item.get("performance") or {}
            if perf:
                _overall_perf_rows.append({
                    "Video": video,
                    "Side": side_name,
                    "Point": val,
                    "FPS": perf.get("encoding_fps"),
                    "CPU Avg(%)": perf.get("cpu_avg_percent"),
                })

_df_overall = pd.DataFrame(_overall_rows)
_df_overall_perf = pd.DataFrame(_overall_perf_rows) if _overall_perf_rows else pd.DataFrame()

render_overall_section(
    df_metrics=_df_overall,
    df_perf=_df_overall_perf,
    bd_list=bd_list if has_bd else [],
    anchor_label="Anchor",
    test_label="Test",
    show_bd=has_bd,
)


# ========== Metrics ==========
st.header("Metrics", anchor="metrics")

rows = []
for entry in entries:
    video = entry.get("source")
    for side_key, side_name in (("anchor", "Anchor"), ("test", "Test")):
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

# RD Curves
render_rd_curves(df_metrics, anchor_label="Anchor", test_label="Test")

# Delta
render_metrics_delta(df_metrics, anchor_label="Anchor", test_label="Test", point_key="metrics_delta_point", metric_key="metrics_delta_metric")

# 详细表格（默认折叠）
st.subheader("Details", anchor="details")
with st.expander("查看详细Metrics数据", expanded=False):
    # 格式化精度
    details_format = {
        "Point": "{:.2f}",
        "Bitrate_kbps": "{:.2f}",
        "PSNR": "{:.4f}",
        "SSIM": "{:.4f}",
        "VMAF": "{:.2f}",
        "VMAF-NEG": "{:.2f}",
    }
    styled_details = df_metrics.sort_values(by=["Video", "RC", "Point", "Side"]).style.format(details_format, na_rep="-")
    st.dataframe(styled_details, use_container_width=True, hide_index=True)


if has_bd:
    render_bd_rate_section(bd_list)
    render_bd_metrics_section(bd_list)


# ========== Bitrate 分析 ==========
st.header("Bitrates", anchor="码率分析")

# 构建可选的视频和点位列表
video_point_options = []
for entry in entries:
    video = entry.get("source")
    anchor_enc = (entry.get("anchor") or {}).get("encoded") or []
    for item in anchor_enc:
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

    # 找到对应的 anchor 和 test 数据
    anchor_bitrate = None
    test_bitrate = None
    ref_fps = 30.0

    for entry in entries:
        if entry.get("source") == selected_video_br:
            ref_info = (entry.get("anchor") or {}).get("reference") or {}
            ref_fps = ref_info.get("fps") or 30.0

            for item in (entry.get("anchor") or {}).get("encoded") or []:
                rc, point = _parse_point(item.get("label", ""))
                if point == selected_point_br:
                    anchor_bitrate = item.get("bitrate") or {}
                    break

            for item in (entry.get("test") or {}).get("encoded") or []:
                rc, point = _parse_point(item.get("label", ""))
                if point == selected_point_br:
                    test_bitrate = item.get("bitrate") or {}
                    break
            break

    if anchor_bitrate and test_bitrate:
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

        anchor_x, anchor_y = _aggregate_bitrate(anchor_bitrate, bin_seconds)
        test_x, test_y = _aggregate_bitrate(test_bitrate, bin_seconds)

        fig_br = go.Figure()
        if chart_type == "柱状图":
            fig_br.add_trace(go.Bar(x=anchor_x, y=anchor_y, name="Anchor", opacity=0.7, marker_color="#636efa"))
            fig_br.add_trace(go.Bar(x=test_x, y=test_y, name="Test", opacity=0.7, marker_color="#f0553b"))
            fig_br.update_layout(barmode="group")
        else:
            fig_br.add_trace(go.Scatter(x=anchor_x, y=anchor_y, mode="lines+markers", name="Anchor", line=dict(color="#636efa"), marker=dict(color="#636efa")))
            fig_br.add_trace(go.Scatter(x=test_x, y=test_y, mode="lines+markers", name="Test", line=dict(color="#f0553b"), marker=dict(color="#f0553b")))

        fig_br.update_layout(
            title=f"码率对比 - {selected_video_br} ({selected_point_br})",
            xaxis_title="Time (s)",
            yaxis_title="Bitrate (kbps)",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        )
        st.plotly_chart(fig_br, use_container_width=True)

        # 显示平均码率对比
        anchor_avg = (anchor_bitrate.get("avg_bitrate_bps") or sum(anchor_bitrate.get("frame_sizes", [])) * 8 / (len(anchor_bitrate.get("frame_timestamps", [])) / ref_fps if anchor_bitrate.get("frame_timestamps") else 1)) / 1000
        test_avg = (test_bitrate.get("avg_bitrate_bps") or sum(test_bitrate.get("frame_sizes", [])) * 8 / (len(test_bitrate.get("frame_timestamps", [])) / ref_fps if test_bitrate.get("frame_timestamps") else 1)) / 1000

        # 从 entries 中获取 avg_bitrate_bps
        for entry in entries:
            if entry.get("source") == selected_video_br:
                for item in (entry.get("anchor") or {}).get("encoded") or []:
                    rc, point = _parse_point(item.get("label", ""))
                    if point == selected_point_br:
                        anchor_avg = item.get("avg_bitrate_bps", 0) / 1000
                        break
                for item in (entry.get("test") or {}).get("encoded") or []:
                    rc, point = _parse_point(item.get("label", ""))
                    if point == selected_point_br:
                        test_avg = item.get("avg_bitrate_bps", 0) / 1000
                        break
                break

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Anchor 平均码率", f"{anchor_avg:.2f} kbps")
        col_m2.metric("Test 平均码率", f"{test_avg:.2f} kbps")
        diff_pct = ((test_avg - anchor_avg) / anchor_avg * 100) if anchor_avg > 0 else 0
        col_m3.metric("码率差异", f"{diff_pct:+.2f}%", delta=f"{diff_pct:+.2f}%", delta_color="inverse")
    else:
        st.warning("未找到对应的码率数据。请确保报告包含帧级码率信息。")
else:
    st.info("暂无码率对比数据。")


# ========== Performance ==========
# 收集性能数据
perf_rows = []
perf_detail_rows = []
for entry in entries:
    video = entry.get("source")
    for side_key, side_name in (("anchor", "Anchor"), ("test", "Test")):
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
    perf_detail_df = pd.DataFrame(perf_detail_rows)
    perf_detail_format = {
        "Point": "{:.2f}",
        "FPS": "{:.2f}",
        "CPU Avg(%)": "{:.2f}",
        "CPU Max(%)": "{:.2f}",
        "Total Time(s)": "{:.2f}",
    }
    render_performance_section(
        df_perf=df_perf,
        anchor_label="Anchor",
        test_label="Test",
        detail_df=perf_detail_df,
        detail_format=perf_detail_format,
        delta_point_key="perf_delta_point",
        delta_metric_key="perf_delta_metric",
        cpu_video_key="perf_video",
        cpu_point_key="perf_point",
        cpu_agg_key="cpu_agg",
    )
else:
    st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")


# ========== 环境信息 ==========
st.header("Machine Info", anchor="环境信息")

# 使用 anchor_environment（Anchor 侧环境，任务开始时的环境状态）
env = report.get("anchor_environment") or report.get("test_environment") or {}

if env:
    st.markdown(format_env_info(env))
else:
    st.write("未采集到环境信息。")
