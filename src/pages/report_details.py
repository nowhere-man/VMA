"""
报告详情页面

显示单个报告的详细质量指标和图表
"""
import streamlit as st
import plotly.graph_objects as go
from pathlib import Path
import sys

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.report_scanner import report_scanner

# 页面配置
st.set_page_config(
    page_title="报告详情 - VQMR",
    page_icon="📈",
    layout="wide",
)

st.title("📈 报告详情")

# 检查是否选择了报告
if 'selected_report_id' not in st.session_state:
    st.warning("请先从报告列表选择一个报告")
    if st.button("返回报告列表"):
        st.switch_page("streamlit_app.py")
    st.stop()

# 获取报告数据
report_id = st.session_state['selected_report_id']
report = report_scanner.get_report_by_id(report_id)

if not report:
    st.error(f"找不到报告: {report_id}")
    if st.button("返回报告列表"):
        st.switch_page("streamlit_app.py")
    st.stop()

# 返回按钮
if st.button("← 返回报告列表"):
    st.switch_page("streamlit_app.py")

st.divider()

# 报告基本信息
st.header(f"🎬 {report['file_name']}")
col1, col2, col3 = st.columns(3)

with col1:
    st.info(f"**模板名称**: {report['template_name']}")
with col2:
    st.info(f"**编码器**: {report.get('encoder_type', 'N/A')}")
with col3:
    st.info(f"**创建时间**: {report['created_at']}")

# 模板详细信息
with st.expander("📝 模板详细参数", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**模板ID**: `{report['template_id']}`")
        st.write(f"**序列类型**: {report.get('sequence_type', 'N/A')}")
        if report.get('template_description'):
            st.write(f"**描述**: {report['template_description']}")
    with col2:
        if report.get('encoder_params'):
            st.write(f"**编码参数**:")
            st.code(report['encoder_params'], language='bash')

st.divider()

# 质量指标
metrics = report.get("metrics", {})

if not metrics:
    st.warning("该报告没有质量指标数据")
else:
    st.header("📊 质量指标分析")

    # 创建三列显示主要指标
    col1, col2, col3 = st.columns(3)

    # PSNR指标
    with col1:
        if "psnr_avg" in metrics:
            st.subheader("PSNR (峰值信噪比)")

            # 主指标
            psnr_avg = metrics['psnr_avg']
            delta_color = "normal"
            if psnr_avg >= 40:
                delta_color = "normal"
                quality_label = "优秀"
            elif psnr_avg >= 30:
                delta_color = "normal"
                quality_label = "良好"
            else:
                delta_color = "inverse"
                quality_label = "较差"

            st.metric(
                "平均 PSNR",
                f"{psnr_avg:.2f} dB",
                delta=quality_label,
                delta_color=delta_color
            )

            # YUV分量
            if "psnr_y" in metrics or "psnr_u" in metrics or "psnr_v" in metrics:
                st.write("**YUV分量**:")
                if "psnr_y" in metrics:
                    st.write(f"- Y (亮度): {metrics['psnr_y']:.2f} dB")
                if "psnr_u" in metrics:
                    st.write(f"- U (色度): {metrics['psnr_u']:.2f} dB")
                if "psnr_v" in metrics:
                    st.write(f"- V (色度): {metrics['psnr_v']:.2f} dB")

    # VMAF指标
    with col2:
        if "vmaf_mean" in metrics:
            st.subheader("VMAF (视频质量评分)")

            vmaf_mean = metrics['vmaf_mean']
            if vmaf_mean >= 90:
                quality_label = "极好"
                delta_color = "normal"
            elif vmaf_mean >= 80:
                quality_label = "优秀"
                delta_color = "normal"
            elif vmaf_mean >= 70:
                quality_label = "良好"
                delta_color = "normal"
            else:
                quality_label = "较差"
                delta_color = "inverse"

            st.metric(
                "平均 VMAF",
                f"{vmaf_mean:.2f}",
                delta=quality_label,
                delta_color=delta_color
            )

            if "vmaf_harmonic_mean" in metrics:
                st.write(f"**调和平均**: {metrics['vmaf_harmonic_mean']:.2f}")

    # SSIM指标
    with col3:
        if "ssim_avg" in metrics:
            st.subheader("SSIM (结构相似性)")

            ssim_avg = metrics['ssim_avg']
            if ssim_avg >= 0.95:
                quality_label = "优秀"
                delta_color = "normal"
            elif ssim_avg >= 0.90:
                quality_label = "良好"
                delta_color = "normal"
            else:
                quality_label = "一般"
                delta_color = "inverse"

            st.metric(
                "平均 SSIM",
                f"{ssim_avg:.4f}",
                delta=quality_label,
                delta_color=delta_color
            )

            # YUV分量
            if "ssim_y" in metrics or "ssim_u" in metrics or "ssim_v" in metrics:
                st.write("**YUV分量**:")
                if "ssim_y" in metrics:
                    st.write(f"- Y (亮度): {metrics['ssim_y']:.4f}")
                if "ssim_u" in metrics:
                    st.write(f"- U (色度): {metrics['ssim_u']:.4f}")
                if "ssim_v" in metrics:
                    st.write(f"- V (色度): {metrics['ssim_v']:.4f}")

    st.divider()

    # 可视化图表
    st.header("📉 指标可视化")

    # 创建雷达图
    metrics_for_chart = []
    values_for_chart = []

    if "psnr_avg" in metrics:
        metrics_for_chart.append("PSNR")
        # 归一化PSNR到0-100范围（假设20-50dB映射到0-100）
        normalized_psnr = min(100, max(0, (metrics['psnr_avg'] - 20) * 100 / 30))
        values_for_chart.append(normalized_psnr)

    if "vmaf_mean" in metrics:
        metrics_for_chart.append("VMAF")
        values_for_chart.append(metrics['vmaf_mean'])

    if "ssim_avg" in metrics:
        metrics_for_chart.append("SSIM")
        # SSIM归一化到0-100
        values_for_chart.append(metrics['ssim_avg'] * 100)

    if metrics_for_chart:
        fig = go.Figure()

        fig.add_trace(go.Scatterpolar(
            r=values_for_chart,
            theta=metrics_for_chart,
            fill='toself',
            name='质量指标',
            line_color='rgb(31, 119, 180)'
        ))

        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 100]
                )
            ),
            showlegend=True,
            title="质量指标雷达图（归一化到0-100）"
        )

        st.plotly_chart(fig, use_container_width=True)

    # 条形图对比
    st.subheader("指标对比")

    col1, col2 = st.columns(2)

    with col1:
        # PSNR YUV分量对比
        if "psnr_y" in metrics and "psnr_u" in metrics and "psnr_v" in metrics:
            fig_psnr = go.Figure(data=[
                go.Bar(
                    x=['Y', 'U', 'V'],
                    y=[metrics['psnr_y'], metrics['psnr_u'], metrics['psnr_v']],
                    marker_color=['#1f77b4', '#ff7f0e', '#2ca02c']
                )
            ])
            fig_psnr.update_layout(
                title="PSNR YUV分量对比",
                yaxis_title="PSNR (dB)",
                xaxis_title="分量"
            )
            st.plotly_chart(fig_psnr, use_container_width=True)

    with col2:
        # SSIM YUV分量对比
        if "ssim_y" in metrics and "ssim_u" in metrics and "ssim_v" in metrics:
            fig_ssim = go.Figure(data=[
                go.Bar(
                    x=['Y', 'U', 'V'],
                    y=[metrics['ssim_y'], metrics['ssim_u'], metrics['ssim_v']],
                    marker_color=['#1f77b4', '#ff7f0e', '#2ca02c']
                )
            ])
            fig_ssim.update_layout(
                title="SSIM YUV分量对比",
                yaxis_title="SSIM",
                xaxis_title="分量"
            )
            st.plotly_chart(fig_ssim, use_container_width=True)

# 原始数据文件路径
st.divider()
with st.expander("📁 原始数据文件"):
    metric_files = report.get('metric_files', {})
    if metric_files:
        for metric_type, file_path in metric_files.items():
            st.code(f"{metric_type.upper()}: {file_path}", language='text')
    else:
        st.write("无原始文件信息")

# 页脚
st.markdown("---")
st.caption("VQMR - Video Quality Metrics Report | Powered by Streamlit")

# 快速导航
col1, col2 = st.columns(2)
with col1:
    if st.button("← 返回报告列表"):
        st.switch_page("streamlit_app.py")
with col2:
    if st.button("📉 指标对比分析"):
        st.switch_page("pages/3_📉_Metrics_Comparison.py")
