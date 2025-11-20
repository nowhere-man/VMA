"""
指标对比页面

对比多个报告或任务的质量指标
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import requests

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.report_scanner import report_scanner

# 页面配置
st.set_page_config(
    page_title="指标对比 - VQMR",
    page_icon="📉",
    layout="wide",
)

st.title("📉 质量指标对比")

# 选择对比模式
comparison_mode = st.radio(
    "选择对比模式",
    options=["报告对比", "任务对比"],
    horizontal=True,
    help="报告对比：对比两个转码报告；任务对比：对比多个任务的质量指标"
)

st.divider()


# BD-Rate 计算函数
def calculate_bd_rate(rate1, quality1, rate2, quality2):
    """
    计算BD-Rate (Bjøntegaard Delta Rate)

    Args:
        rate1: 参考曲线的码率列表
        quality1: 参考曲线的质量指标列表
        rate2: 测试曲线的码率列表
        quality2: 测试曲线的质量指标列表

    Returns:
        BD-Rate值 (百分比)
    """
    try:
        # 转换为numpy数组并过滤无效值
        r1 = np.array([r for r in rate1 if r and r > 0])
        q1 = np.array([q for q in quality1 if q and not np.isnan(q)])
        r2 = np.array([r for r in rate2 if r and r > 0])
        q2 = np.array([q for q in quality2 if q and not np.isnan(q)])

        if len(r1) < 2 or len(r2) < 2:
            return None

        # 对数变换码率
        log_r1 = np.log(r1)
        log_r2 = np.log(r2)

        # 找到公共质量范围
        min_q = max(min(q1), min(q2))
        max_q = min(max(q1), max(q2))

        if min_q >= max_q:
            return None

        # 使用分段线性插值
        from scipy.interpolate import interp1d

        # 插值函数
        f1 = interp1d(q1, log_r1, kind='linear', fill_value='extrapolate')
        f2 = interp1d(q2, log_r2, kind='linear', fill_value='extrapolate')

        # 在公共质量范围内计算积分
        q_range = np.linspace(min_q, max_q, 100)
        avg_diff = np.mean(f2(q_range) - f1(q_range))

        # BD-Rate = (exp(avg_diff) - 1) * 100%
        bd_rate = (np.exp(avg_diff) - 1) * 100

        return bd_rate
    except Exception as e:
        st.warning(f"BD-Rate计算失败: {str(e)}")
        return None


def calculate_bd_metric(rate1, quality1, rate2, quality2):
    """
    计算BD-Metric (质量指标差异)

    Returns:
        BD-Metric值 (质量指标的平均差异)
    """
    try:
        r1 = np.array([r for r in rate1 if r and r > 0])
        q1 = np.array([q for q in quality1 if q and not np.isnan(q)])
        r2 = np.array([r for r in rate2 if r and r > 0])
        q2 = np.array([q for q in quality2 if q and not np.isnan(q)])

        if len(r1) < 2 or len(r2) < 2:
            return None

        # 找到公共码率范围 (对数空间)
        log_r1 = np.log(r1)
        log_r2 = np.log(r2)
        min_r = max(min(log_r1), min(log_r2))
        max_r = min(max(log_r1), max(log_r2))

        if min_r >= max_r:
            return None

        from scipy.interpolate import interp1d

        # 插值函数
        f1 = interp1d(log_r1, q1, kind='linear', fill_value='extrapolate')
        f2 = interp1d(log_r2, q2, kind='linear', fill_value='extrapolate')

        # 在公共码率范围内计算平均差异
        r_range = np.linspace(min_r, max_r, 100)
        avg_diff = np.mean(f2(r_range) - f1(r_range))

        return avg_diff
    except Exception as e:
        st.warning(f"BD-Metric计算失败: {str(e)}")
        return None


# ========== 报告对比模式 ==========
if comparison_mode == "报告对比":
    all_reports = report_scanner.scan_all_reports()

    if not all_reports or len(all_reports) < 2:
        st.warning("至少需要2个报告才能进行对比")
        st.info("请先执行转码模板生成更多质量分析报告")
        st.stop()

    # 报告选择
    st.header("选择要对比的报告")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("报告 A")
        report_options_a = [
            f"{r['template_name']} - {r['file_name']} ({r['created_at']})"
            for r in all_reports
        ]
        selected_a = st.selectbox("选择报告A", report_options_a, key="report_a")
        report_a_idx = report_options_a.index(selected_a)
        report_a = all_reports[report_a_idx]

    with col2:
        st.subheader("报告 B")
        report_options_b = [
            f"{r['template_name']} - {r['file_name']} ({r['created_at']})"
            for r in all_reports
        ]
        default_b_idx = 1 if len(all_reports) > 1 else 0
        selected_b = st.selectbox("选择报告B", report_options_b, index=default_b_idx, key="report_b")
        report_b_idx = report_options_b.index(selected_b)
        report_b = all_reports[report_b_idx]

    if report_a['report_id'] == report_b['report_id']:
        st.error("请选择不同的报告进行对比")
        st.stop()

    st.divider()

    # 对比分析
    st.header("📊 对比分析")

    metrics_a = report_a.get('metrics', {})
    metrics_b = report_b.get('metrics', {})

    # 创建对比表格
    st.subheader("指标对比表")

    comparison_data = {
        '指标': [],
        '报告 A': [],
        '报告 B': [],
        '差值 (B - A)': [],
        '差值百分比': []
    }

    # PSNR对比
    if 'psnr_avg' in metrics_a and 'psnr_avg' in metrics_b:
        psnr_a = metrics_a['psnr_avg']
        psnr_b = metrics_b['psnr_avg']
        diff = psnr_b - psnr_a
        diff_pct = (diff / psnr_a * 100) if psnr_a > 0 else 0

        comparison_data['指标'].append('PSNR (dB)')
        comparison_data['报告 A'].append(f"{psnr_a:.2f}")
        comparison_data['报告 B'].append(f"{psnr_b:.2f}")
        comparison_data['差值 (B - A)'].append(f"{diff:+.2f}")
        comparison_data['差值百分比'].append(f"{diff_pct:+.2f}%")

    # VMAF对比
    if 'vmaf_mean' in metrics_a and 'vmaf_mean' in metrics_b:
        vmaf_a = metrics_a['vmaf_mean']
        vmaf_b = metrics_b['vmaf_mean']
        diff = vmaf_b - vmaf_a
        diff_pct = (diff / vmaf_a * 100) if vmaf_a > 0 else 0

        comparison_data['指标'].append('VMAF')
        comparison_data['报告 A'].append(f"{vmaf_a:.2f}")
        comparison_data['报告 B'].append(f"{vmaf_b:.2f}")
        comparison_data['差值 (B - A)'].append(f"{diff:+.2f}")
        comparison_data['差值百分比'].append(f"{diff_pct:+.2f}%")

    # SSIM对比
    if 'ssim_avg' in metrics_a and 'ssim_avg' in metrics_b:
        ssim_a = metrics_a['ssim_avg']
        ssim_b = metrics_b['ssim_avg']
        diff = ssim_b - ssim_a
        diff_pct = (diff / ssim_a * 100) if ssim_a > 0 else 0

        comparison_data['指标'].append('SSIM')
        comparison_data['报告 A'].append(f"{ssim_a:.4f}")
        comparison_data['报告 B'].append(f"{ssim_b:.4f}")
        comparison_data['差值 (B - A)'].append(f"{diff:+.4f}")
        comparison_data['差值百分比'].append(f"{diff_pct:+.2f}%")

    if comparison_data['指标']:
        df = pd.DataFrame(comparison_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.warning("这两个报告没有可对比的指标")

    st.divider()

    # 可视化对比
    st.subheader("可视化对比")

    # 并排条形图
    fig = go.Figure()

    metrics_names = []
    values_a = []
    values_b = []

    if 'psnr_avg' in metrics_a and 'psnr_avg' in metrics_b:
        metrics_names.append('PSNR (dB)')
        values_a.append(metrics_a['psnr_avg'])
        values_b.append(metrics_b['psnr_avg'])

    if 'vmaf_mean' in metrics_a and 'vmaf_mean' in metrics_b:
        metrics_names.append('VMAF')
        values_a.append(metrics_a['vmaf_mean'])
        values_b.append(metrics_b['vmaf_mean'])

    if 'ssim_avg' in metrics_a and 'ssim_avg' in metrics_b:
        metrics_names.append('SSIM (×100)')
        values_a.append(metrics_a['ssim_avg'] * 100)
        values_b.append(metrics_b['ssim_avg'] * 100)

    if metrics_names:
        fig.add_trace(go.Bar(
            name='报告 A',
            x=metrics_names,
            y=values_a,
            marker_color='rgb(31, 119, 180)'
        ))

        fig.add_trace(go.Bar(
            name='报告 B',
            x=metrics_names,
            y=values_b,
            marker_color='rgb(255, 127, 14)'
        ))

        fig.update_layout(
            title='质量指标并排对比',
            barmode='group',
            yaxis_title='指标值',
            xaxis_title='指标类型'
        )

        st.plotly_chart(fig, use_container_width=True)

    # YUV分量对比
    st.subheader("YUV分量对比")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**PSNR YUV分量对比**")
        if all(k in metrics_a for k in ['psnr_y', 'psnr_u', 'psnr_v']) and \
           all(k in metrics_b for k in ['psnr_y', 'psnr_u', 'psnr_v']):

            fig_psnr = go.Figure()
            fig_psnr.add_trace(go.Bar(
                name='报告 A',
                x=['Y', 'U', 'V'],
                y=[metrics_a['psnr_y'], metrics_a['psnr_u'], metrics_a['psnr_v']],
                marker_color='rgb(31, 119, 180)'
            ))
            fig_psnr.add_trace(go.Bar(
                name='报告 B',
                x=['Y', 'U', 'V'],
                y=[metrics_b['psnr_y'], metrics_b['psnr_u'], metrics_b['psnr_v']],
                marker_color='rgb(255, 127, 14)'
            ))
            fig_psnr.update_layout(
                barmode='group',
                yaxis_title='PSNR (dB)',
                xaxis_title='分量'
            )
            st.plotly_chart(fig_psnr, use_container_width=True)
        else:
            st.info("部分报告缺少PSNR YUV分量数据")

    with col2:
        st.write("**SSIM YUV分量对比**")
        if all(k in metrics_a for k in ['ssim_y', 'ssim_u', 'ssim_v']) and \
           all(k in metrics_b for k in ['ssim_y', 'ssim_u', 'ssim_v']):

            fig_ssim = go.Figure()
            fig_ssim.add_trace(go.Bar(
                name='报告 A',
                x=['Y', 'U', 'V'],
                y=[metrics_a['ssim_y'], metrics_a['ssim_u'], metrics_a['ssim_v']],
                marker_color='rgb(31, 119, 180)'
            ))
            fig_ssim.add_trace(go.Bar(
                name='报告 B',
                x=['Y', 'U', 'V'],
                y=[metrics_b['ssim_y'], metrics_b['ssim_u'], metrics_b['ssim_v']],
                marker_color='rgb(255, 127, 14)'
            ))
            fig_ssim.update_layout(
                barmode='group',
                yaxis_title='SSIM',
                xaxis_title='分量'
            )
            st.plotly_chart(fig_ssim, use_container_width=True)
        else:
            st.info("部分报告缺少SSIM YUV分量数据")

    # 模板参数对比
    st.divider()
    st.subheader("📝 模板参数对比")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**报告 A - 模板参数**")
        st.write(f"- 模板: {report_a['template_name']}")
        st.write(f"- 编码器: {report_a.get('encoder_type', 'N/A')}")
        st.write(f"- 序列类型: {report_a.get('sequence_type', 'N/A')}")
        if report_a.get('encoder_params'):
            st.code(report_a['encoder_params'], language='bash')

    with col2:
        st.write("**报告 B - 模板参数**")
        st.write(f"- 模板: {report_b['template_name']}")
        st.write(f"- 编码器: {report_b.get('encoder_type', 'N/A')}")
        st.write(f"- 序列类型: {report_b.get('sequence_type', 'N/A')}")
        if report_b.get('encoder_params'):
            st.code(report_b['encoder_params'], language='bash')


# ========== 任务对比模式 ==========
else:  # 任务对比
    st.header("选择要对比的任务")

    # 获取所有已完成的任务
    try:
        response = requests.get("http://localhost:8080/api/jobs?status=completed")
        if response.status_code == 200:
            all_jobs = response.json()
        else:
            st.error("获取任务列表失败")
            st.stop()
    except Exception as e:
        st.error(f"连接API失败: {str(e)}")
        st.stop()

    if not all_jobs or len(all_jobs) < 2:
        st.warning("至少需要2个已完成的任务才能进行对比")
        st.info("请先创建并完成更多任务")
        st.stop()

    # 多选任务
    job_options = {
        f"任务 {job['job_id'][:8]} - {job['created_at']}": job['job_id']
        for job in all_jobs
    }

    selected_jobs = st.multiselect(
        "选择要对比的任务（至少2个）",
        options=list(job_options.keys()),
        help="按住Ctrl/Cmd可以多选"
    )

    if len(selected_jobs) < 2:
        st.info("请至少选择2个任务进行对比")
        st.stop()

    selected_job_ids = [job_options[job] for job in selected_jobs]

    # 获取任务对比数据
    if st.button("开始对比", type="primary"):
        try:
            response = requests.post(
                "http://localhost:8080/api/jobs/compare",
                json=selected_job_ids
            )

            if response.status_code != 200:
                st.error(f"对比失败: {response.json().get('detail', '未知错误')}")
                st.stop()

            comparison_result = response.json()
            jobs_data = comparison_result['jobs']

            st.success(f"成功获取 {len(jobs_data)} 个任务的数据")

            st.divider()

            # 提取指标数据
            bitrates = []
            psnr_values = []
            ssim_values = []
            vmaf_values = []
            job_labels = []

            for i, job in enumerate(jobs_data):
                metrics = job['metrics']
                job_labels.append(f"任务 {i+1}")

                # 假设每个job有码率信息（可能需要从其他地方获取）
                # 这里使用一个简化的假设值，实际应用中需要从任务数据中提取
                bitrate = metrics.get('bitrate', (i+1) * 1000)  # 示例值
                bitrates.append(bitrate)

                psnr_values.append(metrics.get('psnr_avg'))
                ssim_values.append(metrics.get('ssim_avg'))
                vmaf_values.append(metrics.get('vmaf_mean'))

            # ========== 码率对比 ==========
            st.header("📊 码率对比")

            fig_bitrate = go.Figure()
            fig_bitrate.add_trace(go.Bar(
                x=job_labels,
                y=bitrates,
                marker_color='rgb(55, 83, 109)',
                text=[f"{b/1000:.1f} kbps" for b in bitrates],
                textposition='auto'
            ))
            fig_bitrate.update_layout(
                title='各任务码率对比',
                xaxis_title='任务',
                yaxis_title='码率 (bps)',
                showlegend=False
            )
            st.plotly_chart(fig_bitrate, use_container_width=True)

            # ========== PSNR对比 ==========
            st.header("📈 PSNR 对比")

            col1, col2 = st.columns(2)

            with col1:
                # PSNR条形图
                fig_psnr = go.Figure()
                fig_psnr.add_trace(go.Bar(
                    x=job_labels,
                    y=psnr_values,
                    marker_color='rgb(26, 118, 255)',
                    text=[f"{p:.2f} dB" if p else "N/A" for p in psnr_values],
                    textposition='auto'
                ))
                fig_psnr.update_layout(
                    title='PSNR 对比',
                    xaxis_title='任务',
                    yaxis_title='PSNR (dB)',
                    showlegend=False
                )
                st.plotly_chart(fig_psnr, use_container_width=True)

            with col2:
                # BD-PSNR表格
                st.subheader("BD-PSNR 分析")

                if len(jobs_data) >= 2:
                    # 计算第一个任务相对于其他任务的BD-Rate
                    ref_bitrate = [bitrates[0]]
                    ref_psnr = [psnr_values[0]] if psnr_values[0] else []

                    bd_psnr_data = {
                        '对比': [],
                        'BD-Rate (%)': [],
                        'BD-PSNR (dB)': []
                    }

                    for i in range(1, len(jobs_data)):
                        test_bitrate = [bitrates[i]]
                        test_psnr = [psnr_values[i]] if psnr_values[i] else []

                        if len(ref_psnr) > 0 and len(test_psnr) > 0:
                            bd_rate = calculate_bd_rate(ref_bitrate, ref_psnr, test_bitrate, test_psnr)
                            bd_metric = calculate_bd_metric(ref_bitrate, ref_psnr, test_bitrate, test_psnr)

                            bd_psnr_data['对比'].append(f"任务{i+1} vs 任务1")
                            bd_psnr_data['BD-Rate (%)'].append(f"{bd_rate:.2f}" if bd_rate is not None else "N/A")
                            bd_psnr_data['BD-PSNR (dB)'].append(f"{bd_metric:.2f}" if bd_metric is not None else "N/A")

                    if bd_psnr_data['对比']:
                        df_bd_psnr = pd.DataFrame(bd_psnr_data)
                        st.dataframe(df_bd_psnr, use_container_width=True, hide_index=True)
                    else:
                        st.info("数据不足，无法计算BD-PSNR")
                else:
                    st.info("至少需要2个任务才能计算BD-PSNR")

            # ========== SSIM对比 ==========
            st.header("📈 SSIM 对比")

            col1, col2 = st.columns(2)

            with col1:
                # SSIM条形图
                fig_ssim = go.Figure()
                fig_ssim.add_trace(go.Bar(
                    x=job_labels,
                    y=ssim_values,
                    marker_color='rgb(255, 127, 14)',
                    text=[f"{s:.4f}" if s else "N/A" for s in ssim_values],
                    textposition='auto'
                ))
                fig_ssim.update_layout(
                    title='SSIM 对比',
                    xaxis_title='任务',
                    yaxis_title='SSIM',
                    showlegend=False
                )
                st.plotly_chart(fig_ssim, use_container_width=True)

            with col2:
                # BD-SSIM表格
                st.subheader("BD-SSIM 分析")

                if len(jobs_data) >= 2:
                    ref_bitrate = [bitrates[0]]
                    ref_ssim = [ssim_values[0]] if ssim_values[0] else []

                    bd_ssim_data = {
                        '对比': [],
                        'BD-Rate (%)': [],
                        'BD-SSIM': []
                    }

                    for i in range(1, len(jobs_data)):
                        test_bitrate = [bitrates[i]]
                        test_ssim = [ssim_values[i]] if ssim_values[i] else []

                        if len(ref_ssim) > 0 and len(test_ssim) > 0:
                            bd_rate = calculate_bd_rate(ref_bitrate, ref_ssim, test_bitrate, test_ssim)
                            bd_metric = calculate_bd_metric(ref_bitrate, ref_ssim, test_bitrate, test_ssim)

                            bd_ssim_data['对比'].append(f"任务{i+1} vs 任务1")
                            bd_ssim_data['BD-Rate (%)'].append(f"{bd_rate:.2f}" if bd_rate is not None else "N/A")
                            bd_ssim_data['BD-SSIM'].append(f"{bd_metric:.4f}" if bd_metric is not None else "N/A")

                    if bd_ssim_data['对比']:
                        df_bd_ssim = pd.DataFrame(bd_ssim_data)
                        st.dataframe(df_bd_ssim, use_container_width=True, hide_index=True)
                    else:
                        st.info("数据不足，无法计算BD-SSIM")
                else:
                    st.info("至少需要2个任务才能计算BD-SSIM")

            # ========== VMAF对比 ==========
            st.header("📈 VMAF 对比")

            col1, col2 = st.columns(2)

            with col1:
                # VMAF条形图
                fig_vmaf = go.Figure()
                fig_vmaf.add_trace(go.Bar(
                    x=job_labels,
                    y=vmaf_values,
                    marker_color='rgb(44, 160, 44)',
                    text=[f"{v:.2f}" if v else "N/A" for v in vmaf_values],
                    textposition='auto'
                ))
                fig_vmaf.update_layout(
                    title='VMAF 对比',
                    xaxis_title='任务',
                    yaxis_title='VMAF',
                    showlegend=False
                )
                st.plotly_chart(fig_vmaf, use_container_width=True)

            with col2:
                # BD-VMAF表格
                st.subheader("BD-VMAF 分析")

                if len(jobs_data) >= 2:
                    ref_bitrate = [bitrates[0]]
                    ref_vmaf = [vmaf_values[0]] if vmaf_values[0] else []

                    bd_vmaf_data = {
                        '对比': [],
                        'BD-Rate (%)': [],
                        'BD-VMAF': []
                    }

                    for i in range(1, len(jobs_data)):
                        test_bitrate = [bitrates[i]]
                        test_vmaf = [vmaf_values[i]] if vmaf_values[i] else []

                        if len(ref_vmaf) > 0 and len(test_vmaf) > 0:
                            bd_rate = calculate_bd_rate(ref_bitrate, ref_vmaf, test_bitrate, test_vmaf)
                            bd_metric = calculate_bd_metric(ref_bitrate, ref_vmaf, test_bitrate, test_vmaf)

                            bd_vmaf_data['对比'].append(f"任务{i+1} vs 任务1")
                            bd_vmaf_data['BD-Rate (%)'].append(f"{bd_rate:.2f}" if bd_rate is not None else "N/A")
                            bd_vmaf_data['BD-VMAF'].append(f"{bd_metric:.2f}" if bd_metric is not None else "N/A")

                    if bd_vmaf_data['对比']:
                        df_bd_vmaf = pd.DataFrame(bd_vmaf_data)
                        st.dataframe(df_bd_vmaf, use_container_width=True, hide_index=True)
                    else:
                        st.info("数据不足，无法计算BD-VMAF")
                else:
                    st.info("至少需要2个任务才能计算BD-VMAF")

            # ========== RD曲线对比（如果有多个码率点）==========
            st.header("📊 RD 曲线对比")
            st.info("注意：当前每个任务只有一个码率点，RD曲线需要每个任务有多个不同码率的编码结果。此功能将在有多码率点数据时自动显示。")

        except Exception as e:
            st.error(f"对比过程出错: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

# 页脚
st.markdown("---")
st.caption("VQMR - Video Quality Metrics Report | Powered by Streamlit")
