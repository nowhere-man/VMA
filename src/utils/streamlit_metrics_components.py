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
