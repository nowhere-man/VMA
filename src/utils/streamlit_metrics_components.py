"""
Streamlit UI 复用组件

提取 Metrics 页面常用片段（平滑滚动样式、性能对比区域），减少重复代码。
"""
from typing import Dict, Optional

import pandas as pd
import streamlit as st

from src.utils.streamlit_helpers import (
    create_cpu_chart,
    create_fps_chart,
    color_positive_green,
    color_positive_red,
    render_delta_bar_chart_by_point,
    render_delta_table_expander,
)


def inject_smooth_scroll_css() -> None:
    """开启页面平滑滚动"""
    st.markdown(
        """
<style>
html {
    scroll-behavior: smooth;
}
</style>
""",
        unsafe_allow_html=True,
    )


def render_performance_section(
    df_perf: pd.DataFrame,
    anchor_label: str,
    test_label: str,
    detail_df: Optional[pd.DataFrame] = None,
    detail_format: Optional[Dict[str, str]] = None,
    delta_point_key: str = "perf_delta_point",
    delta_metric_key: str = "perf_delta_metric",
    cpu_video_key: str = "perf_video",
    cpu_point_key: str = "perf_point",
    cpu_agg_key: str = "cpu_agg",
) -> None:
    """统一渲染性能对比区块（Delta + CPU + FPS + Details）"""
    st.header("Performance", anchor="performance")

    if df_perf is None or df_perf.empty:
        st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")
        return

    # 1) 汇总 Diff
    anchor_perf = df_perf[df_perf["Side"] == anchor_label]
    test_perf = df_perf[df_perf["Side"] == test_label]
    merged_perf = anchor_perf.merge(
        test_perf,
        on=["Video", "Point"],
        suffixes=("_anchor", "_test"),
    )
    if not merged_perf.empty:
        merged_perf["Δ FPS"] = merged_perf["FPS_test"] - merged_perf["FPS_anchor"]
        merged_perf["Δ CPU Avg(%)"] = merged_perf["CPU Avg(%)_test"] - merged_perf["CPU Avg(%)_anchor"]

        diff_perf_df = merged_perf[
            ["Video", "Point", "FPS_anchor", "FPS_test", "Δ FPS", "CPU Avg(%)_anchor", "CPU Avg(%)_test", "Δ CPU Avg(%)"]
        ].rename(
            columns={
                "FPS_anchor": f"{anchor_label} FPS",
                "FPS_test": f"{test_label} FPS",
                "CPU Avg(%)_anchor": f"{anchor_label} CPU(%)",
                "CPU Avg(%)_test": f"{test_label} CPU(%)",
            }
        ).sort_values(by=["Video", "Point"]).reset_index(drop=True)

        prev_video = None
        for idx in diff_perf_df.index:
            if diff_perf_df.at[idx, "Video"] == prev_video:
                diff_perf_df.at[idx, "Video"] = ""
            else:
                prev_video = diff_perf_df.at[idx, "Video"]

        perf_format_dict = {
            "Point": "{:.2f}",
            f"{anchor_label} FPS": "{:.2f}",
            f"{test_label} FPS": "{:.2f}",
            "Δ FPS": "{:.2f}",
            f"{anchor_label} CPU(%)": "{:.2f}",
            f"{test_label} CPU(%)": "{:.2f}",
            "Δ CPU Avg(%)": "{:.2f}",
        }

        styled_perf = (
            diff_perf_df.style.applymap(color_positive_green, subset=["Δ FPS"])
            .applymap(color_positive_red, subset=["Δ CPU Avg(%)"])
            .format(perf_format_dict, na_rep="-")
        )

        st.subheader("Delta", anchor="perf-diff")

        perf_metric_config = {
            "Δ FPS": {"fmt": "{:+.2f}", "pos": "#00cc96", "neg": "#ef553b"},
            "Δ CPU Avg(%)": {"fmt": "{:+.2f}%", "pos": "#ef553b", "neg": "#00cc96"},
        }
        render_delta_bar_chart_by_point(
            merged_perf,
            point_col="Point",
            metric_options=["Δ FPS", "Δ CPU Avg(%)"],
            metric_config=perf_metric_config,
            point_select_label="选择码率点位",
            metric_select_label="选择指标",
            point_select_key=delta_point_key,
            metric_select_key=delta_metric_key,
        )

        render_delta_table_expander("查看 Delta 表格", styled_perf)

    # 2) CPU 折线
    st.subheader("CPU Usage", anchor="cpu-chart")
    video_list_perf = df_perf["Video"].unique().tolist()
    if video_list_perf:
        col_sel_perf1, col_sel_perf2 = st.columns(2)
        with col_sel_perf1:
            selected_video_perf = st.selectbox("选择视频", video_list_perf, key=cpu_video_key)
        with col_sel_perf2:
            point_list_perf = df_perf[df_perf["Video"] == selected_video_perf]["Point"].unique().tolist()
            selected_point_perf = st.selectbox("选择码率点位", point_list_perf, key=cpu_point_key)

        agg_interval = st.slider("聚合间隔 (ms)", min_value=100, max_value=1000, value=100, step=100, key=cpu_agg_key)

        anchor_samples = []
        test_samples = []
        for _, row in df_perf.iterrows():
            if row["Video"] == selected_video_perf and row["Point"] == selected_point_perf:
                if row["Side"] == anchor_label:
                    anchor_samples = row.get("cpu_samples", []) or []
                else:
                    test_samples = row.get("cpu_samples", []) or []

        if anchor_samples or test_samples:
            fig_cpu = create_cpu_chart(
                anchor_samples=anchor_samples,
                test_samples=test_samples,
                agg_interval=agg_interval,
                title=f"CPU占用率 - {selected_video_perf} ({selected_point_perf})",
                anchor_label=anchor_label,
                test_label=test_label,
            )
            st.plotly_chart(fig_cpu, use_container_width=True)

            anchor_avg_cpu = sum(anchor_samples) / len(anchor_samples) if anchor_samples else 0
            test_avg_cpu = sum(test_samples) / len(test_samples) if test_samples else 0
            cpu_diff_pct = ((test_avg_cpu - anchor_avg_cpu) / anchor_avg_cpu * 100) if anchor_avg_cpu > 0 else 0

            col_cpu1, col_cpu2, col_cpu3 = st.columns(3)
            col_cpu1.metric(f"{anchor_label} Average CPU Usage", f"{anchor_avg_cpu:.2f}%")
            col_cpu2.metric(f"{test_label} Average CPU Usage", f"{test_avg_cpu:.2f}%")
            col_cpu3.metric("CPU Usage 差异", f"{cpu_diff_pct:+.2f}%", delta=f"{cpu_diff_pct:+.2f}%", delta_color="inverse")
        else:
            st.info("该视频/点位没有CPU采样数据。")

    # 3) FPS
    st.subheader("FPS", anchor="fps-chart")
    fig_fps = create_fps_chart(
        df_perf=df_perf,
        anchor_label=anchor_label,
        test_label=test_label,
    )
    st.plotly_chart(fig_fps, use_container_width=True)

    # 4) 详情
    st.subheader("Details", anchor="perf-details")
    with st.expander("查看详细性能数据", expanded=False):
        df_detail = detail_df.copy() if detail_df is not None else df_perf.copy()
        df_detail = df_detail.drop(columns=["cpu_samples"], errors="ignore")

        fmt = detail_format or {
            "Point": "{:.2f}",
            "FPS": "{:.2f}",
            "CPU Avg(%)": "{:.2f}",
        }
        if "CPU Max(%)" in df_detail.columns:
            fmt.setdefault("CPU Max(%)", "{:.2f}")
        if "Total Time(s)" in df_detail.columns:
            fmt.setdefault("Total Time(s)", "{:.2f}")
        if "Frames" in df_detail.columns:
            fmt.setdefault("Frames", "{:.0f}")

        styled_perf_detail = df_detail.sort_values(by=["Video", "Point", "Side"]).style.format(fmt, na_rep="-")
        st.dataframe(styled_perf_detail, use_container_width=True, hide_index=True)


def render_sidebar_contents(has_bd: bool = False) -> None:
    """渲染侧边栏目录"""
    st.markdown("### 📑 Contents")
    contents = [
        "- [Information](#information)",
        "- [Overall](#overall)",
        "- [Metrics](#metrics)",
        "  - [RD Curves](#rd-curve)",
        "  - [Delta](#delta)",
        "  - [Details](#details)",
    ]
    if has_bd:
        contents += [
            "- [BD-Rate](#bd-rate)",
            "  - [BD-Rate PSNR](#bd-rate-psnr)",
            "  - [BD-Rate SSIM](#bd-rate-ssim)",
            "  - [BD-Rate VMAF](#bd-rate-vmaf)",
            "  - [BD-Rate VMAF-NEG](#bd-rate-vmaf-neg)",
            "- [BD-Metrics](#bd-metrics)",
            "  - [BD PSNR](#bd-psnr)",
            "  - [BD SSIM](#bd-ssim)",
            "  - [BD VMAF](#bd-vmaf)",
            "  - [BD VMAF-NEG](#bd-vmaf-neg)",
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


def render_rd_curves(df: "pd.DataFrame", anchor_label: str = "Anchor", test_label: str = "Test") -> None:
    """渲染 RD 曲线"""
    import plotly.graph_objects as go

    st.subheader("RD Curves", anchor="rd-curve")
    video_list = df["Video"].unique().tolist()
    metric_options = ["PSNR", "SSIM", "VMAF", "VMAF-NEG"]

    col_select, col_chart = st.columns([1, 3])
    with col_select:
        st.write("")
        st.write("")
        selected_video = st.selectbox("选择视频", video_list, key="rd_video")
        selected_metric = st.selectbox("选择指标", metric_options, key="rd_metric")

    video_df = df[df["Video"] == selected_video]
    anchor_data = video_df[video_df["Side"] == anchor_label].sort_values("Bitrate_kbps")
    test_data = video_df[video_df["Side"] == test_label].sort_values("Bitrate_kbps")

    fig_rd = go.Figure()
    fig_rd.add_trace(
        go.Scatter(
            x=anchor_data["Bitrate_kbps"],
            y=anchor_data[selected_metric],
            mode="lines+markers",
            name=anchor_label,
            marker=dict(size=10, color="#636efa"),
            line=dict(width=2, shape="spline", smoothing=1.3, color="#636efa"),
        )
    )
    fig_rd.add_trace(
        go.Scatter(
            x=test_data["Bitrate_kbps"],
            y=test_data[selected_metric],
            mode="lines+markers",
            name=test_label,
            marker=dict(size=10, color="#f0553b"),
            line=dict(width=2, shape="spline", smoothing=1.3, color="#f0553b"),
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


def render_metrics_delta(
    df: "pd.DataFrame",
    anchor_label: str = "Anchor",
    test_label: str = "Test",
    point_key: str = "metrics_delta_point",
    metric_key: str = "metrics_delta_metric",
) -> None:
    """渲染 Metrics Delta 对比"""
    import pandas as pd
    from src.utils.streamlit_helpers import render_delta_bar_chart_by_point, render_delta_table_expander

    anchor_df = df[df["Side"] == anchor_label]
    test_df = df[df["Side"] == test_label]
    merged = anchor_df.merge(test_df, on=["Video", "RC", "Point"], suffixes=("_anchor", "_test"))

    if not merged.empty:
        merged["Bitrate Δ%"] = ((merged["Bitrate_kbps_test"] - merged["Bitrate_kbps_anchor"]) / merged["Bitrate_kbps_anchor"].replace(0, pd.NA)) * 100
        merged["PSNR Δ"] = merged["PSNR_test"] - merged["PSNR_anchor"]
        merged["SSIM Δ"] = merged["SSIM_test"] - merged["SSIM_anchor"]
        merged["VMAF Δ"] = merged["VMAF_test"] - merged["VMAF_anchor"]
        merged["VMAF-NEG Δ"] = merged["VMAF-NEG_test"] - merged["VMAF-NEG_anchor"]

        diff_df = merged[
            ["Video", "RC", "Point", "Bitrate Δ%", "PSNR Δ", "SSIM Δ", "VMAF Δ", "VMAF-NEG Δ"]
        ].sort_values(by=["Video", "Point"]).reset_index(drop=True)
        chart_df = diff_df.copy()

        prev_video = None
        for idx in diff_df.index:
            if diff_df.at[idx, "Video"] == prev_video:
                diff_df.at[idx, "Video"] = ""
            else:
                prev_video = diff_df.at[idx, "Video"]

        def _color_diff(val):
            if pd.isna(val) or not isinstance(val, (int, float)):
                return ""
            if val > 0:
                return "color: green"
            elif val < 0:
                return "color: red"
            return ""

        diff_cols = ["Bitrate Δ%", "PSNR Δ", "SSIM Δ", "VMAF Δ", "VMAF-NEG Δ"]
        format_dict = {
            "Point": "{:.2f}",
            "Bitrate Δ%": "{:.2f}",
            "PSNR Δ": "{:.4f}",
            "SSIM Δ": "{:.4f}",
            "VMAF Δ": "{:.2f}",
            "VMAF-NEG Δ": "{:.2f}",
        }
        styled_df = diff_df.style.applymap(_color_diff, subset=diff_cols).format(format_dict, na_rep="-")

        st.subheader("Delta", anchor="delta")

        metric_config = {
            "Bitrate Δ%": {"fmt": "{:+.2f}%", "pos": "#ef553b", "neg": "#00cc96"},
            "PSNR Δ": {"fmt": "{:+.4f}", "pos": "#00cc96", "neg": "#ef553b"},
            "SSIM Δ": {"fmt": "{:+.4f}", "pos": "#00cc96", "neg": "#ef553b"},
            "VMAF Δ": {"fmt": "{:+.2f}", "pos": "#00cc96", "neg": "#ef553b"},
            "VMAF-NEG Δ": {"fmt": "{:+.2f}", "pos": "#00cc96", "neg": "#ef553b"},
        }
        render_delta_bar_chart_by_point(
            chart_df,
            point_col="Point",
            metric_options=diff_cols,
            metric_config=metric_config,
            point_select_label="选择码率点位",
            metric_select_label="选择指标",
            point_select_key=point_key,
            metric_select_key=metric_key,
        )

        render_delta_table_expander(
            "查看详细Delta数据",
            styled_df,
            column_config={
                "Video": st.column_config.TextColumn("Video", width="medium"),
            },
        )


def render_bd_rate_section(bd_list: list) -> None:
    """渲染 BD-Rate 分析区块"""
    import pandas as pd
    import plotly.graph_objects as go

    st.header("BD-Rate", anchor="bd-rate")
    if bd_list:
        df_bd = pd.DataFrame(bd_list)

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

        def _create_bd_bar_chart(df, col, title):
            colors = ["#00cc96" if v < 0 else "#ef553b" if v > 0 else "gray" for v in df[col].fillna(0)]
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


def render_bd_metrics_section(bd_list: list) -> None:
    """渲染 BD-Metrics 分析区块"""
    import pandas as pd
    import plotly.graph_objects as go

    st.header("BD-Metrics", anchor="bd-metrics")
    if bd_list:
        df_bdm = pd.DataFrame(bd_list)

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

        def _create_bd_metrics_bar_chart(df, col, title):
            colors = ["#00cc96" if v > 0 else "#ef553b" if v < 0 else "gray" for v in df[col].fillna(0)]
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


def render_sidebar_contents_single() -> None:
    """渲染单侧报告的侧边栏目录"""
    st.markdown("### 📑 Contents")
    contents = [
        "- [Information](#information)",
        "- [Overall](#overall)",
        "- [Metrics](#metrics)",
        "  - [RD Curves](#rd-curves)",
        "  - [Details](#details)",
        "- [Performance](#performance)",
        "  - [CPU Usage](#cpu-usage)",
        "  - [FPS](#fps)",
        "  - [Details](#perf-details)",
        "- [Machine Info](#环境信息)",
    ]
    st.markdown("\n".join(contents), unsafe_allow_html=True)


def render_single_information(info: dict) -> None:
    """渲染单列Information表格"""
    import pandas as pd
    from src.utils.streamlit_helpers import _format_encoder_type, _format_encoder_params, _format_points

    info_df = pd.DataFrame([
        {"项目": "编码器类型", "值": _format_encoder_type(info.get("encoder_type"))},
        {"项目": "编码参数", "值": _format_encoder_params(info.get("encoder_params"))},
        {"项目": "码率点位", "值": _format_points(info.get("bitrate_points"))},
    ])
    st.dataframe(info_df, use_container_width=True, hide_index=True)


def render_single_overall(df_metrics: "pd.DataFrame", df_perf: "pd.DataFrame") -> None:
    """渲染单侧Overall（无BD-Rate）"""
    import pandas as pd
    from src.utils.streamlit_helpers import _summary_stats, _render_overall_table

    if df_metrics.empty:
        st.info("暂无可用的指标数据。")
        return

    point_list = sorted(df_metrics["Point"].dropna().unique().tolist())
    if not point_list:
        st.info("暂无可用的码率点位数据。")
        return

    point_label_col, point_select_col, point_spacer_col = st.columns([1, 2, 6])
    with point_label_col:
        st.markdown("**码率点位**")
    with point_select_col:
        selected_point = st.selectbox("选择码率点位", point_list, key="single_overall_point", label_visibility="collapsed")
    point_spacer_col.empty()

    point_df = df_metrics[df_metrics["Point"] == selected_point]
    if point_df.empty:
        st.warning("选中点位没有数据。")
        return

    psnr_avg, psnr_max, psnr_min = _summary_stats(point_df["PSNR"])
    ssim_avg, ssim_max, ssim_min = _summary_stats(point_df["SSIM"])
    vmaf_avg, vmaf_max, vmaf_min = _summary_stats(point_df["VMAF"])
    vmaf_neg_avg, vmaf_neg_max, vmaf_neg_min = _summary_stats(point_df["VMAF-NEG"])

    metrics_df = pd.DataFrame({
        "平均": [psnr_avg, ssim_avg, vmaf_avg, vmaf_neg_avg],
        "最大": [psnr_max, ssim_max, vmaf_max, vmaf_neg_max],
        "最小": [psnr_min, ssim_min, vmaf_min, vmaf_neg_min],
    }, index=["PSNR", "SSIM", "VMAF", "VMAF-NEG"])

    performance_df = pd.DataFrame()
    if not df_perf.empty:
        perf_point_df = df_perf[df_perf["Point"] == selected_point]
        if not perf_point_df.empty:
            cpu_avg, cpu_max, cpu_min = _summary_stats(perf_point_df["CPU Avg(%)"])
            fps_avg, fps_max, fps_min = _summary_stats(perf_point_df["FPS"])
            performance_df = pd.DataFrame({
                "平均": [cpu_avg, fps_avg],
                "最大": [cpu_max, fps_max],
                "最小": [cpu_min, fps_min],
            }, index=["CPU Usage", "FPS"])

    bitrate_avg, bitrate_max, bitrate_min = _summary_stats(point_df["Bitrate_kbps"])
    bitrate_df = pd.DataFrame({
        "平均": [bitrate_avg],
        "最大": [bitrate_max],
        "最小": [bitrate_min],
    }, index=["Bitrate"])

    metrics_col, perf_bitrate_col = st.columns(2)
    with metrics_col:
        _render_overall_table("Metrics", metrics_df, ".4f", "", ("green", "red"), empty_text="暂无 Metrics 数据。")
    with perf_bitrate_col:
        _render_overall_table("Performance", performance_df, ".2f", "%", ("green", "red"), row_rules={"CPU Usage": ("red", "green")}, empty_text="暂无 Performance 数据。")
        _render_overall_table("Bitrate", bitrate_df, ".2f", " kbps", ("red", "green"), empty_text="暂无 Bitrate 数据。")


def render_single_rd_curves(df: "pd.DataFrame") -> None:
    """渲染单条RD曲线"""
    import plotly.graph_objects as go

    st.subheader("RD Curves", anchor="rd-curves")
    video_list = df["Video"].unique().tolist()
    metric_options = ["PSNR", "SSIM", "VMAF", "VMAF-NEG"]

    col_select, col_chart = st.columns([1, 3])
    with col_select:
        st.write("")
        st.write("")
        selected_video = st.selectbox("选择视频", video_list, key="single_rd_video")
        selected_metric = st.selectbox("选择指标", metric_options, key="single_rd_metric")

    video_df = df[df["Video"] == selected_video].sort_values("Bitrate_kbps")

    fig_rd = go.Figure()
    fig_rd.add_trace(go.Scatter(
        x=video_df["Bitrate_kbps"],
        y=video_df[selected_metric],
        mode="lines+markers",
        name=selected_metric,
        marker=dict(size=10, color="#636efa"),
        line=dict(width=2, shape="spline", smoothing=1.3, color="#636efa"),
    ))
    fig_rd.update_layout(
        title=f"RD Curve - {selected_video}",
        xaxis_title="Bitrate (kbps)",
        yaxis_title=selected_metric,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    with col_chart:
        st.plotly_chart(fig_rd, use_container_width=True)


def render_single_performance(df_perf: "pd.DataFrame") -> None:
    """渲染单侧Performance"""
    import plotly.graph_objects as go
    from src.utils.streamlit_helpers import aggregate_cpu_samples, create_fps_chart

    st.header("Performance", anchor="performance")

    if df_perf is None or df_perf.empty:
        st.info("暂无性能数据。请确保编码任务已完成并采集了性能数据。")
        return

    # CPU Usage
    st.subheader("CPU Usage", anchor="cpu-usage")
    video_list_perf = df_perf["Video"].unique().tolist()
    if video_list_perf:
        col_sel_perf1, col_sel_perf2 = st.columns(2)
        with col_sel_perf1:
            selected_video_perf = st.selectbox("选择视频", video_list_perf, key="single_perf_video")
        with col_sel_perf2:
            point_list_perf = df_perf[df_perf["Video"] == selected_video_perf]["Point"].unique().tolist()
            selected_point_perf = st.selectbox("选择码率点位", point_list_perf, key="single_perf_point")

        agg_interval = st.slider("聚合间隔 (ms)", min_value=100, max_value=1000, value=100, step=100, key="single_cpu_agg")

        cpu_samples = []
        for _, row in df_perf.iterrows():
            if row["Video"] == selected_video_perf and row["Point"] == selected_point_perf:
                cpu_samples = row.get("cpu_samples", []) or []
                break

        if cpu_samples:
            cpu_x, cpu_y = aggregate_cpu_samples(cpu_samples, agg_interval)
            fig_cpu = go.Figure()
            fig_cpu.add_trace(go.Scatter(
                x=cpu_x, y=cpu_y,
                mode="lines",
                name="CPU",
                line=dict(color="#636efa", width=2),
            ))
            if cpu_y:
                max_idx = cpu_y.index(max(cpu_y))
                fig_cpu.add_trace(go.Scatter(
                    x=[cpu_x[max_idx]], y=[cpu_y[max_idx]],
                    mode="markers+text",
                    name="Max",
                    marker=dict(color="#636efa", size=12, symbol="star"),
                    text=[f"Max: {cpu_y[max_idx]:.1f}%"],
                    textposition="top center",
                    showlegend=False,
                ))
            fig_cpu.update_layout(
                title=f"CPU占用率 - {selected_video_perf} ({selected_point_perf})",
                xaxis_title="Time (s)",
                yaxis_title="CPU (%)",
                hovermode="x unified",
            )
            st.plotly_chart(fig_cpu, use_container_width=True)

            avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
            st.metric("Average CPU Usage", f"{avg_cpu:.2f}%")
        else:
            st.info("该视频/点位没有CPU采样数据。")

    # FPS
    st.subheader("FPS", anchor="fps")
    df_sorted = df_perf.sort_values(by=["Video", "Point"])
    df_sorted["x_label"] = df_sorted["Video"].astype(str) + "_" + df_sorted["Point"].astype(str)

    fig_fps = go.Figure()
    fig_fps.add_trace(go.Scatter(
        x=df_sorted["x_label"],
        y=df_sorted["FPS"],
        mode="lines+markers",
        name="FPS",
        line=dict(color="#636efa", width=2),
        marker=dict(size=8),
    ))
    fig_fps.update_layout(
        title="FPS",
        xaxis_title="Video_Point",
        yaxis_title="FPS",
        hovermode="x unified",
        xaxis=dict(tickangle=-45),
    )
    st.plotly_chart(fig_fps, use_container_width=True)

    # Details
    st.subheader("Details", anchor="perf-details")
    with st.expander("查看详细性能数据", expanded=False):
        df_detail = df_perf.drop(columns=["cpu_samples"], errors="ignore")
        fmt = {
            "Point": "{:.2f}",
            "FPS": "{:.2f}",
            "CPU Avg(%)": "{:.2f}",
            "CPU Max(%)": "{:.2f}",
            "Total Time(s)": "{:.2f}",
            "Frames": "{:.0f}",
        }
        styled_perf_detail = df_detail.sort_values(by=["Video", "Point"]).style.format(fmt, na_rep="-")
        st.dataframe(styled_perf_detail, use_container_width=True, hide_index=True)
