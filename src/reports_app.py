"""
VMA 报告应用 - Streamlit主界面

质量分析报告可视化应用
"""
import streamlit as st
from pathlib import Path
import sys
from typing import List, Dict

# 添加项目根目录到Python路径（此文件位于 src/ 下，项目根在其父目录）
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.config import settings


# 页面配置
st.set_page_config(
    page_title="VMA 质量分析报告",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _list_bitstream_jobs(limit: int = 20) -> List[Dict]:
    """列出最近的码流分析报告 job_id 列表（按 report_data.json 修改时间倒序）。"""
    root = settings.jobs_root_dir
    if not root.is_absolute():
        root = (project_root / root).resolve()
    if not root.exists():
        return []

    items: List[Dict] = []
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        report_path = job_dir / "bitstream_analysis" / "report_data.json"
        if report_path.exists():
            mtime = report_path.stat().st_mtime
            items.append(
                {
                    "job_id": job_dir.name,
                    "mtime": mtime,
                    "report_path": report_path,
                }
            )

    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def _list_template_jobs(limit: int = 20) -> List[Dict]:
    """列出最近的模板指标报告 job_id 列表。"""
    root = settings.jobs_root_dir
    if not root.is_absolute():
        root = (project_root / root).resolve()
    if not root.exists():
        return []

    items: List[Dict] = []
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        report_path = job_dir / "metrics_analysis" / "report_data.json"
        if report_path.exists():
            mtime = report_path.stat().st_mtime
            items.append(
                {
                    "job_id": job_dir.name,
                    "mtime": mtime,
                    "report_path": report_path,
                }
            )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def _set_job_query_param(job_id: str) -> None:
    """使用新的 st.query_params API 设置 job_id，避免 old experimental API 冲突。"""
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
        st.switch_page("pages/template_metrics.py")

if job_id:
    if isinstance(job_id, list):
        job_id = job_id[0] if job_id else None
    if job_id:
        st.session_state["bitstream_job_id"] = str(job_id)
        _set_job_query_param(str(job_id))
        st.switch_page("pages/bitstream_report.py")

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

# 最近的码流分析报告列表
st.subheader("最近的码流分析报告")
recent_jobs = _list_bitstream_jobs()
if not recent_jobs:
    st.info("暂无码流分析报告。请先在任务列表创建任务或上传视频进行码流分析。")
else:
    for item in recent_jobs:
        job_id = item["job_id"]
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"- Job: `{job_id}`  (report at: `bitstream_analysis/report_data.json`)")
        with col2:
            if st.button("打开报告", key=f"open_{job_id}"):
                st.session_state["bitstream_job_id"] = job_id
                _set_job_query_param(job_id)
                st.switch_page("pages/bitstream_report.py")

# 模板指标报告列表
st.subheader("最近的模板指标报告")
tpl_jobs = _list_template_jobs()
if not tpl_jobs:
    st.info("暂无模板指标报告。请在 Metrics对比 中创建任务。")
else:
    for item in tpl_jobs:
        job_id = item["job_id"]
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"- Job: `{job_id}`  (report at: `metrics_analysis/report_data.json`)")
        with col2:
            if st.button("打开报告", key=f"open_tpl_{job_id}"):
                st.session_state["template_job_id"] = job_id
                try:
                    st.query_params["template_job_id"] = job_id
                except Exception:
                    pass
                st.switch_page("pages/template_metrics.py")

# 侧边栏（不再保留 legacy 报告扫描）
