"""
VQMR 报告应用 - Streamlit主界面

质量分析报告可视化应用
"""
import streamlit as st
from pathlib import Path
import sys

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.services.report_scanner import report_scanner


# 页面配置
st.set_page_config(
    page_title="VQMR 质量分析报告",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 自定义CSS样式
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        padding: 1rem 0;
    }
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 0.5rem;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    .report-card {
        border: 1px solid #e0e0e0;
        border-radius: 0.5rem;
        padding: 1.5rem;
        margin: 1rem 0;
        background-color: white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 主标题
st.markdown('<h1 class="main-header">📊 视频质量分析报告</h1>', unsafe_allow_html=True)

# 侧边栏
with st.sidebar:
    st.header("🔍 筛选选项")

    # 获取所有报告
    all_reports = report_scanner.scan_all_reports()

    if not all_reports:
        st.warning("暂无报告数据")
        st.info("请先执行转码模板生成质量分析报告")
        st.stop()

    # 获取唯一的模板列表
    unique_templates = list(set((r["template_id"], r["template_name"]) for r in all_reports))
    template_options = ["全部模板"] + [f"{name} ({tid[:8]}...)" for tid, name in unique_templates]

    selected_template = st.selectbox("选择模板", template_options)

    # 排序选项
    sort_by = st.selectbox(
        "排序方式",
        ["时间（最新优先）", "时间（最旧优先）", "PSNR（降序）", "VMAF（降序）", "SSIM（降序）"]
    )

    st.divider()
    st.caption(f"共找到 {len(all_reports)} 个报告")

# 筛选报告
filtered_reports = all_reports.copy()

if selected_template != "全部模板":
    # 从选择的模板选项中提取模板ID
    template_id = [tid for tid, name in unique_templates if f"{name} ({tid[:8]}...)" == selected_template][0]
    filtered_reports = [r for r in filtered_reports if r["template_id"] == template_id]

# 排序报告
if sort_by == "时间（最新优先）":
    filtered_reports.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
elif sort_by == "时间（最旧优先）":
    filtered_reports.sort(key=lambda x: x.get("timestamp", 0))
elif sort_by == "PSNR（降序）":
    filtered_reports.sort(key=lambda x: x.get("metrics", {}).get("psnr_avg", 0), reverse=True)
elif sort_by == "VMAF（降序）":
    filtered_reports.sort(key=lambda x: x.get("metrics", {}).get("vmaf_mean", 0), reverse=True)
elif sort_by == "SSIM（降序）":
    filtered_reports.sort(key=lambda x: x.get("metrics", {}).get("ssim_avg", 0), reverse=True)

# 主内容区域
st.subheader(f"📋 报告列表 ({len(filtered_reports)} 个)")

if not filtered_reports:
    st.info("没有符合筛选条件的报告")
else:
    # 显示报告卡片
    for idx, report in enumerate(filtered_reports):
        with st.container():
            st.markdown('<div class="report-card">', unsafe_allow_html=True)

            # 报告标题
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"### 🎬 {report['file_name']}")
                st.caption(f"模板: {report['template_name']} | 时间: {report['created_at']}")
            with col2:
                if st.button("查看详情", key=f"detail_{idx}"):
                    st.session_state['selected_report_id'] = report['report_id']
                    st.switch_page("src/pages/report_details.py")

            # 模板信息
            with st.expander("📝 模板参数", expanded=False):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**编码器**: {report.get('encoder_type', 'N/A')}")
                with col2:
                    st.write(f"**序列类型**: {report.get('sequence_type', 'N/A')}")
                with col3:
                    st.write(f"**模板ID**: `{report['template_id'][:12]}...`")

                if report.get('encoder_params'):
                    st.write(f"**编码参数**: `{report['encoder_params']}`")
                if report.get('template_description'):
                    st.write(f"**描述**: {report['template_description']}")

            # 质量指标
            metrics = report.get("metrics", {})
            if metrics:
                st.markdown("**📊 质量指标**")
                cols = st.columns(3)

                # PSNR
                if "psnr_avg" in metrics:
                    with cols[0]:
                        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                        st.metric("PSNR (峰值信噪比)", f"{metrics['psnr_avg']:.2f} dB")
                        if "psnr_y" in metrics:
                            st.caption(f"Y: {metrics['psnr_y']:.2f} dB")
                        st.markdown('</div>', unsafe_allow_html=True)

                # VMAF
                if "vmaf_mean" in metrics:
                    with cols[1]:
                        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                        st.metric("VMAF (质量评分)", f"{metrics['vmaf_mean']:.2f}")
                        if "vmaf_harmonic_mean" in metrics:
                            st.caption(f"调和平均: {metrics['vmaf_harmonic_mean']:.2f}")
                        st.markdown('</div>', unsafe_allow_html=True)

                # SSIM
                if "ssim_avg" in metrics:
                    with cols[2]:
                        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                        st.metric("SSIM (结构相似性)", f"{metrics['ssim_avg']:.4f}")
                        if "ssim_y" in metrics:
                            st.caption(f"Y: {metrics['ssim_y']:.4f}")
                        st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)
            st.divider()

# 页脚
st.markdown("---")
st.caption("VQMR - Video Quality Metrics Report | Powered by Streamlit")

# 快速导航
with st.expander("🔗 快速导航", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📈 查看报告详情"):
            st.info("请先从上方报告列表选择一个报告")
    with col2:
        if st.button("📉 指标对比分析"):
            st.switch_page("src/pages/metrics_comparison.py")
