"""
VMA 报告应用 - VMR
"""
import streamlit as st
from pathlib import Path
import sys
from typing import List, Dict

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.utils.streamlit_helpers import list_jobs


# 页面配置
st.set_page_config(
    page_title="首页 - VMR",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _list_bitstream_jobs(limit: int = 20) -> List[Dict]:
    """列出最近的Stream分析报告 job_id 列表（按 stream_analysis.json 修改时间倒序）。"""
    return list_jobs("analysis/stream_analysis.json", limit=limit)


def _list_metrics_analysis_jobs(limit: int = 20) -> List[Dict]:
    """列出📊 Metrics job_id 列表。"""
    return list_jobs("metrics_analysis/metrics_analysis.json", limit=limit, check_status=True)


def _list_template_jobs(limit: int = 20) -> List[Dict]:
    """列出最近的模板指标报告 job_id 列表。"""
    return list_jobs("metrics_analysis/metrics_comparison.json", limit=limit)


def _set_job_query_param(job_id: str) -> None:
    """使用新的 st.query_params API 设置 job_id，避免 old test API 冲突。"""
    try:
        if st.query_params.get("job_id") != job_id:
            st.query_params["job_id"] = job_id
    except Exception:
        pass


# 支持从 FastAPI 任务详情页直接跳转：
# - 码流分析：http://localhost:8079?job_id=<job_id>
# - 模板指标：http://localhost:8079?template_job_id=<job_id>
job_id = st.query_params.get("job_id")
template_job_id = st.query_params.get("template_job_id")

if template_job_id:
    if isinstance(template_job_id, list):
        template_job_id = template_job_id[0] if template_job_id else None
    if template_job_id:
        st.session_state["template_job_id"] = str(template_job_id)
        try:
            st.query_params["template_job_id"] = str(template_job_id)
        except Exception:
            pass
        st.switch_page("pages/Metrics_Analysis.py")

if job_id:
    if isinstance(job_id, list):
        job_id = job_id[0] if job_id else None
    if job_id:
        st.session_state["bitstream_job_id"] = str(job_id)
        _set_job_query_param(str(job_id))
        st.switch_page("pages/4_📈_Stream_Comparison.py")

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

# 主标题居中
st.markdown("<h1 class='main-header' style='text-align:left;'>📑 Video Metrics Reporter</h1>", unsafe_allow_html=True)

# 最近的Metrics详情报告列表
st.subheader("最近的Metrics详情报告")
metrics_analysis_jobs = _list_metrics_analysis_jobs(limit=5)
if not metrics_analysis_jobs:
    st.info("暂未找到报告，请先创建任务。")
else:
    from datetime import datetime

    for item in metrics_analysis_jobs:
        if not item.get("status_ok", True):
            continue
        job_id = item["job_id"]
        report_data = item.get("report_data", {})
        template_name = report_data.get("template_name", "Unknown")

        dt = datetime.fromtimestamp(item["mtime"])
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        display_name = f"{template_name}-{date_str}-{time_str}-{job_id}"

        st.markdown(
            f"- <a href='/Metrics_Details?job_id={job_id}' target='_blank'>{display_name}</a>",
            unsafe_allow_html=True,
        )

# 模板指标报告列表
st.subheader("最近的Metrics对比报告")
tpl_jobs = _list_template_jobs(limit=5)
if not tpl_jobs:
    st.info("暂未找到报告，请先创建任务。")
else:
    from datetime import datetime

    for item in tpl_jobs:
        job_id = item["job_id"]
        report_data = item.get("report_data", {})
        template_name = report_data.get("template_name", "Unknown")

        dt = datetime.fromtimestamp(item["mtime"])
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        display_name = f"{template_name}-{date_str}-{time_str}-{job_id}"

        st.markdown(
            f"- <a href='/Metrics_Comparison?template_job_id={job_id}' target='_blank'>{display_name}</a>",
            unsafe_allow_html=True,
        )

# 最近的Stream分析报告列表
st.subheader("最近的Stream分析报告")
recent_jobs = _list_bitstream_jobs(limit=5)
if not recent_jobs:
    st.info("暂未找到报告，请先创建任务。")
else:
    from datetime import datetime
    from pathlib import Path

    for item in recent_jobs:
        job_id = item["job_id"]
        report_data = item.get("report_data", {})

        ref = report_data.get("reference", {}) or {}
        ref_label = ref.get("label", "Unknown")
        source_name = Path(ref_label).stem

        dt = datetime.fromtimestamp(item["mtime"])
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        display_name = f"{source_name}-{date_str}-{time_str}-{job_id}"

        st.markdown(
            f"- <a href='/Stream_Comparison?job_id={job_id}' target='_blank'>{display_name}</a>",
            unsafe_allow_html=True,
        )
