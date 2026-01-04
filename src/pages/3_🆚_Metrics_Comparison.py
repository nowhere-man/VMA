"""
Metrics 对比页面

支持三种模式：
1. 无参数：显示选择界面 + 报告列表
2. ?anchor_job=xxx&test_job=yyy：显示 Metrics Analysis 详情对比报告
3. ?template_job_id=xxx：显示 Metrics Comparison 模板报告
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.utils.bd_rate import bd_rate as _bd_rate, bd_metrics as _bd_metrics
from src.utils.streamlit_helpers import (
    get_query_param,
    load_json_report,
    list_jobs,
    parse_rate_point as _parse_point,
    render_overall_section,
    list_metrics_jobs as _list_metrics_jobs,
    format_job_label as _format_job_label,
    load_analyse as _load_analyse,
    metric_value as _metric_value,
    render_machine_info,
    _format_encoder_type,
    _format_encoder_params,
    _format_points,
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


# ========== Metrics Analysis 任务对比相关函数 ==========

def _build_rows(data: Dict[str, Any], side_label: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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
                "Side": side_label,
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


def _build_bd_rows(df: pd.DataFrame) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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

        def _collect(col_anchor: str, col_test: str) -> tuple[List[float], List[float], List[float], List[float]]:
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

        bd_rate_rows.append({
            "source": video,
            "bd_rate_psnr": _bd_rate(anchor_rates, anchor_psnr, test_rates, test_psnr),
            "bd_rate_ssim": _bd_rate(anchor_rates, anchor_ssim, test_rates, test_ssim),
            "bd_rate_vmaf": _bd_rate(anchor_rates, anchor_vmaf, test_rates, test_vmaf),
            "bd_rate_vmaf_neg": _bd_rate(anchor_rates, anchor_vn, test_rates, test_vn),
        })
        bd_metric_rows.append({
            "source": video,
            "bd_psnr": _bd_metrics(anchor_rates, anchor_psnr, test_rates, test_psnr),
            "bd_ssim": _bd_metrics(anchor_rates, anchor_ssim, test_rates, test_ssim),
            "bd_vmaf": _bd_metrics(anchor_rates, anchor_vmaf, test_rates, test_vmaf),
            "bd_vmaf_neg": _bd_metrics(anchor_rates, anchor_vn, test_rates, test_vn),
        })
    return bd_rate_rows, bd_metric_rows


def _get_report_info(data: Dict[str, Any]) -> Dict[str, Any]:
    from src.services.template_storage import template_storage

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


# ========== Metrics Comparison 模板报告相关函数 ==========

def _list_template_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    return list_jobs("metrics_analysis/metrics_comparison.json", limit=limit)


def _load_template_report(job_id: str) -> Dict[str, Any]:
    return load_json_report(job_id, "metrics_analysis/metrics_comparison.json")


def _collect_points(entries: List[Dict[str, Any]], side_key: str) -> List[float]:
    points: List[float] = []
    for entry in entries:
        side = entry.get(side_key) or {}
        for item in side.get("encoded", []) or []:
            _, val = _parse_point(item.get("label", ""))
            if isinstance(val, (int, float)):
                points.append(val)
    return points


# ========== 页面主逻辑 ==========

st.set_page_config(
    page_title="Metrics对比 - VMR",
    page_icon="🆚",
    layout="wide",
)

# 检查 URL 参数
anchor_job = get_query_param("anchor_job")
test_job = get_query_param("test_job")
template_job_id = get_query_param("template_job_id")

# 模式1: Metrics Analysis 详情对比报告
if anchor_job and test_job:
    st.markdown("""
<style>
    [data-testid="stSidebarNav"] {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

    try:
        anchor_data = _load_analyse(anchor_job)
        test_data = _load_analyse(test_job)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    anchor_template_name = anchor_data.get("template_name", "Unknown")
    test_template_name = test_data.get("template_name", "Unknown")

    st.markdown(f"<h1 style='text-align:center;'>{anchor_template_name} 🆚 {test_template_name} 对比报告</h1>", unsafe_allow_html=True)

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

    bd_list_for_overall: List[Dict[str, Any]] = []
    if has_bd:
        bd_rate_rows, bd_metric_rows = _build_bd_rows(df)
        if bd_rate_rows and bd_metric_rows:
            for i, rate_row in enumerate(bd_rate_rows):
                metric_row = bd_metric_rows[i] if i < len(bd_metric_rows) else {}
                bd_list_for_overall.append({
                    "source": rate_row.get("source"),
                    "bd_rate_psnr": rate_row.get("bd_rate_psnr"),
                    "bd_rate_ssim": rate_row.get("bd_rate_ssim"),
                    "bd_rate_vmaf": rate_row.get("bd_rate_vmaf"),
                    "bd_rate_vmaf_neg": rate_row.get("bd_rate_vmaf_neg"),
                    "bd_psnr": metric_row.get("bd_psnr"),
                    "bd_ssim": metric_row.get("bd_ssim"),
                    "bd_vmaf": metric_row.get("bd_vmaf"),
                    "bd_vmaf_neg": metric_row.get("bd_vmaf_neg"),
                })

    with st.sidebar:
        render_sidebar_contents(has_bd=has_bd)

    inject_smooth_scroll_css()

    st.header("Information", anchor="information")
    info_anchor = _get_report_info(anchor_data)
    info_test = _get_report_info(test_data)
    info_df = pd.DataFrame([
        {"项目": "编码器类型", "Anchor": _format_encoder_type(info_anchor.get("encoder_type")), "Test": _format_encoder_type(info_test.get("encoder_type"))},
        {"项目": "编码参数", "Anchor": _format_encoder_params(info_anchor.get("encoder_params")), "Test": _format_encoder_params(info_test.get("encoder_params"))},
        {"项目": "码率点位", "Anchor": _format_points(info_anchor.get("bitrate_points")), "Test": _format_points(info_test.get("bitrate_points"))},
    ])
    st.dataframe(info_df, use_container_width=True, hide_index=True)

    st.header("Overall", anchor="overall")
    df_perf_overall = pd.DataFrame(perf_rows) if perf_rows else pd.DataFrame()
    render_overall_section(df_metrics=df, df_perf=df_perf_overall, bd_list=bd_list_for_overall, anchor_label="Anchor", test_label="Test", show_bd=has_bd)

    st.header("Metrics", anchor="metrics")
    render_rd_curves(df, anchor_label="Anchor", test_label="Test")
    render_metrics_delta(df, anchor_label="Anchor", test_label="Test", point_key="metrics_delta_point_analysis", metric_key="metrics_delta_metric_analysis")

    st.subheader("Details", anchor="details")
    with st.expander("查看详细Metrics数据", expanded=False):
        details_format = {"Point": "{:.2f}", "Bitrate_kbps": "{:.2f}", "PSNR": "{:.4f}", "SSIM": "{:.4f}", "VMAF": "{:.2f}", "VMAF-NEG": "{:.2f}"}
        styled_details = df.sort_values(by=["Video", "RC", "Point", "Side"]).style.format(details_format, na_rep="-")
        st.dataframe(styled_details, use_container_width=True, hide_index=True)

    if has_bd:
        render_bd_rate_section(bd_list_for_overall)
        render_bd_metrics_section(bd_list_for_overall)

    if perf_rows:
        df_perf = pd.DataFrame(perf_rows)
        perf_detail_format = {"Point": "{:.2f}", "FPS": "{:.2f}", "CPU Avg(%)": "{:.2f}", "CPU Max(%)": "{:.2f}"}
        render_performance_section(df_perf=df_perf, anchor_label="Anchor", test_label="Test", detail_df=df_perf.drop(columns=["cpu_samples"], errors="ignore"), detail_format=perf_detail_format, delta_point_key="perf_delta_point_analysis", delta_metric_key="perf_delta_metric_analysis", cpu_video_key="perf_video_analysis", cpu_point_key="perf_point_analysis", cpu_agg_key="cpu_agg_analysis")
    else:
        st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")

    env_anchor = anchor_data.get("environment") or {}
    env_test = test_data.get("environment") or {}
    render_machine_info(env_anchor, env_test, "Anchor", "Test")

# 模式2: Metrics Comparison 模板报告
elif template_job_id:
    st.session_state["template_job_id"] = template_job_id
    try:
        if st.query_params.get("template_job_id") != template_job_id:
            st.query_params["template_job_id"] = template_job_id
    except Exception:
        pass

    try:
        report = _load_template_report(template_job_id)
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

    st.markdown("""
<style>
    [data-testid="stSidebarNav"] {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

    template_name = report.get('template_name') or report.get('template_id', 'Unknown')
    st.markdown(f"<h1 style='text-align:center;'>{template_name} - 对比报告</h1>", unsafe_allow_html=True)
    st.markdown(f"<h4 style='text-align:right;'>{template_job_id}</h4>", unsafe_allow_html=True)

    with st.sidebar:
        render_sidebar_contents(has_bd=has_bd)

    inject_smooth_scroll_css()

    # Information
    st.header("Information", anchor="information")
    anchor_info = report.get("anchor", {}) or {}
    test_info = report.get("test", {}) or {}
    anchor_points = _collect_points(entries, "anchor")
    test_points = _collect_points(entries, "test")

    def _format_encoder_type_template(info: Dict[str, Any]) -> str:
        return info.get("encoder_type") or "-"

    def _format_encoder_params_template(info: Dict[str, Any]) -> str:
        return info.get("encoder_params") or "-"

    info_df = pd.DataFrame([
        {"项目": "编码器类型", "Anchor": _format_encoder_type_template(anchor_info), "Test": _format_encoder_type_template(test_info)},
        {"项目": "编码参数", "Anchor": _format_encoder_params_template(anchor_info), "Test": _format_encoder_params_template(test_info)},
        {"项目": "码率点位", "Anchor": _format_points(anchor_points), "Test": _format_points(test_points)},
    ])
    st.dataframe(info_df, use_container_width=True, hide_index=True)

    # Overall
    st.header("Overall", anchor="overall")
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
    render_overall_section(df_metrics=_df_overall, df_perf=_df_overall_perf, bd_list=bd_list if has_bd else [], anchor_label="Anchor", test_label="Test", show_bd=has_bd)

    # Metrics
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
                rows.append({
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

    df_metrics = pd.DataFrame(rows)
    if df_metrics.empty:
        st.warning("报告中没有可用的指标数据。")
        st.stop()

    render_rd_curves(df_metrics, anchor_label="Anchor", test_label="Test")
    render_metrics_delta(df_metrics, anchor_label="Anchor", test_label="Test", point_key="metrics_delta_point", metric_key="metrics_delta_metric")

    st.subheader("Details", anchor="details")
    with st.expander("查看详细Metrics数据", expanded=False):
        details_format = {"Point": "{:.2f}", "Bitrate_kbps": "{:.2f}", "PSNR": "{:.4f}", "SSIM": "{:.4f}", "VMAF": "{:.2f}", "VMAF-NEG": "{:.2f}"}
        styled_details = df_metrics.sort_values(by=["Video", "RC", "Point", "Side"]).style.format(details_format, na_rep="-")
        st.dataframe(styled_details, use_container_width=True, hide_index=True)

    if has_bd:
        render_bd_rate_section(bd_list)
        render_bd_metrics_section(bd_list)

    # Bitrates
    st.header("Bitrates", anchor="码率分析")
    video_point_options = []
    for entry in entries:
        video = entry.get("source")
        anchor_enc = (entry.get("anchor") or {}).get("encoded") or []
        for item in anchor_enc:
            rc, point = _parse_point(item.get("label", ""))
            if point is not None:
                video_point_options.append({"video": video, "point": point, "rc": rc, "label": f"{video} - {rc}_{point}"})

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

            fig_br.update_layout(title=f"码率对比 - {selected_video_br} ({selected_point_br})", xaxis_title="Time (s)", yaxis_title="Bitrate (kbps)", hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
            st.plotly_chart(fig_br, use_container_width=True)

            anchor_avg = 0
            test_avg = 0
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

    # Performance
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
                    perf_rows.append({"Video": video, "Side": side_name, "Point": point, "FPS": perf.get("encoding_fps"), "CPU Avg(%)": perf.get("cpu_avg_percent"), "CPU Max(%)": perf.get("cpu_max_percent"), "cpu_samples": perf.get("cpu_samples", [])})
                    perf_detail_rows.append({"Video": video, "Side": side_name, "Point": point, "FPS": perf.get("encoding_fps"), "CPU Avg(%)": perf.get("cpu_avg_percent"), "CPU Max(%)": perf.get("cpu_max_percent"), "Total Time(s)": perf.get("total_encoding_time_s"), "Frames": perf.get("total_frames")})

    if perf_rows:
        df_perf = pd.DataFrame(perf_rows)
        perf_detail_df = pd.DataFrame(perf_detail_rows)
        perf_detail_format = {"Point": "{:.2f}", "FPS": "{:.2f}", "CPU Avg(%)": "{:.2f}", "CPU Max(%)": "{:.2f}", "Total Time(s)": "{:.2f}"}
        render_performance_section(df_perf=df_perf, anchor_label="Anchor", test_label="Test", detail_df=perf_detail_df, detail_format=perf_detail_format, delta_point_key="perf_delta_point", delta_metric_key="perf_delta_metric", cpu_video_key="perf_video", cpu_point_key="perf_point", cpu_agg_key="cpu_agg")
    else:
        st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")

    # Machine Info
    env_single = report.get("environment") or {}
    render_machine_info(env_single, None, "Anchor", "Test")

# 模式3: 显示选择界面 + 报告列表
else:
    st.markdown("<h1 style='text-align:left;'>🆚 Metrics 对比</h1>", unsafe_allow_html=True)

    # 详情对比报告
    st.markdown("---")
    st.subheader("详情对比报告")

    jobs = _list_metrics_jobs()
    valid_jobs = [j for j in jobs if j["status_ok"]]
    job_label_map = {_format_job_label(j): j["job_id"] for j in valid_jobs}
    job_options = list(job_label_map.keys())

    col1, col2 = st.columns(2)
    with col1:
        anchor_label = st.selectbox("Anchor", options=job_options, index=None, placeholder="请选择一个任务", key="comparison_anchor")
    with col2:
        test_options = [o for o in job_options if o != anchor_label] if anchor_label else job_options
        test_label = st.selectbox("Test", options=test_options, index=None, placeholder="请选择一个任务", key="comparison_test")

    col_btn1, col_btn2 = st.columns([1, 1])
    with col_btn1:
        button_disabled = not (anchor_label and test_label)
        if anchor_label and test_label:
            anchor_job_id = job_label_map[anchor_label]
            test_job_id = job_label_map[test_label]
            report_url = f"/Metrics_Comparison?anchor_job={anchor_job_id}&test_job={test_job_id}"
            st.link_button("生成报告", report_url, type="primary", disabled=button_disabled, use_container_width=True)
        else:
            st.button("生成报告", type="primary", disabled=True, use_container_width=True)

    # 模板对比报告
    st.markdown("---")
    st.subheader("模板对比报告")

    template_jobs = _list_template_jobs()
    if not template_jobs:
        st.info("暂未找到报告，请先创建任务。")
    else:
        for item in template_jobs:
            jid = item["job_id"]
            report_data = item.get("report_data", {})
            template_name = report_data.get("template_name", "Unknown")

            from datetime import datetime
            dt = datetime.fromtimestamp(item["mtime"])
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M:%S")

            display_name = f"{template_name}-{date_str}-{time_str}-{jid}"
            st.markdown(f"- [{display_name}](?template_job_id={jid})", unsafe_allow_html=True)
