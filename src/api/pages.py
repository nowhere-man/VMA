"""
页面路由

提供 Web 界面的 HTML 页面
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.models import JobStatus
from src.services import job_storage
from src.services.template_storage import template_storage
from src.utils.url_helpers import build_reports_base_url

router = APIRouter(tags=["pages"])

# 配置模板
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _fmt_time(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def _not_found_response(request: Request, resource_type: str, resource_id: str) -> HTMLResponse:
    """返回 404 页面响应"""
    return templates.TemplateResponse(
        "base.html",
        {
            "request": request,
            "reports_base_url": build_reports_base_url(request),
            "error": f"{resource_type} {resource_id} not found",
        },
        status_code=404,
    )


def _base_context(request: Request) -> dict:
    """基础模板上下文"""
    return {"request": request, "reports_base_url": build_reports_base_url(request)}


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_report_page(request: Request, job_id: str) -> HTMLResponse:
    """任务报告页面"""
    job = job_storage.get_job(job_id)

    if not job:
        return _not_found_response(request, "Job", job_id)

    metadata = job.metadata

    # 准备模板数据
    context = _base_context(request)
    context["job"] = {
        "job_id": metadata.job_id,
        "status": metadata.status.value,
        "mode": metadata.mode.value,
        "created_at": _fmt_time(metadata.created_at),
        "updated_at": _fmt_time(metadata.updated_at),
        "completed_at": _fmt_time(metadata.completed_at),
        "template_name": metadata.template_name,
        "reference_filename": (
            metadata.reference_video.filename if metadata.reference_video else None
        ),
        "distorted_filename": (
            metadata.distorted_video.filename if metadata.distorted_video else None
        ),
        "encoded_filenames": [v.filename for v in (metadata.encoded_videos or [])],
        "metrics": metadata.metrics,
        "error_message": metadata.error_message,
        "template_a_id": metadata.template_a_id,
        "template_b_id": metadata.template_b_id,
        "comparison_result": metadata.comparison_result,
        "execution_result": metadata.execution_result,
        "command_logs": [
            {
                "command_id": cmd.command_id,
                "command_type": cmd.command_type,
                "command": cmd.command,
                "status": cmd.status.value,
                "source_file": cmd.source_file,
                "started_at": cmd.started_at.isoformat() if cmd.started_at else None,
                "completed_at": cmd.completed_at.isoformat() if cmd.completed_at else None,
                "error_message": cmd.error_message,
            }
            for cmd in metadata.command_logs
        ],
    }

    return templates.TemplateResponse("job_report.html", context)


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_list_page(
    request: Request, status: Optional[str] = None
) -> HTMLResponse:
    """任务列表页面"""
    # 解析状态过滤
    filter_status = None
    if status:
        try:
            filter_status = JobStatus(status)
        except ValueError:
            pass

    # 获取任务列表
    jobs = job_storage.list_jobs(status=filter_status)

    # 准备模板数据
    jobs_data = [
        {
            "job_id": job.metadata.job_id,
            "status": job.metadata.status.value,
            "mode": job.metadata.mode.value,
            "template_name": job.metadata.template_name or "N/A",
            "created_at": _fmt_time(job.metadata.created_at) or "-",
            "completed_at": _fmt_time(job.metadata.completed_at) or "-",
            "error_message": job.metadata.error_message,
        }
        for job in jobs
    ]

    context = _base_context(request)
    context.update({"jobs": jobs_data, "status": status})
    return templates.TemplateResponse("jobs_list.html", context)


@router.get("/templates", response_class=HTMLResponse)
async def templates_list_page(request: Request) -> HTMLResponse:
    """转码模板列表页面"""
    return templates.TemplateResponse("templates_list.html", _base_context(request))


@router.get("/templates/new", response_class=HTMLResponse)
async def create_template_page(request: Request) -> HTMLResponse:
    """创建新模板页面"""
    context = _base_context(request)
    context.update({"template_id": None, "readonly": False})
    return templates.TemplateResponse("template_form.html", context)


@router.get("/templates/{template_id}", response_class=HTMLResponse)
async def template_detail_page(request: Request, template_id: str) -> HTMLResponse:
    """模板只读详情页面（复用表单样式，禁用编辑）"""
    template = template_storage.get_template(template_id)

    if not template:
        return _not_found_response(request, "Template", template_id)

    context = _base_context(request)
    context.update({"template_id": template_id, "readonly": True})
    return templates.TemplateResponse("template_form.html", context)


@router.get("/templates/{template_id}/edit", response_class=HTMLResponse)
async def edit_template_page(request: Request, template_id: str) -> HTMLResponse:
    """编辑模板页面"""
    template = template_storage.get_template(template_id)

    if not template:
        return _not_found_response(request, "Template", template_id)

    context = _base_context(request)
    context.update({"template_id": template_id, "readonly": False})
    return templates.TemplateResponse("template_form.html", context)


@router.get("/templates/{template_id}/view", response_class=HTMLResponse)
async def template_view_page(request: Request, template_id: str) -> HTMLResponse:
    """模板只读详情页面"""
    template = template_storage.get_template(template_id)

    if not template:
        return _not_found_response(request, "Template", template_id)

    context = _base_context(request)
    context.update({"template": template.metadata})
    return templates.TemplateResponse("template_view.html", context)


@router.get("/bitstream", response_class=HTMLResponse)
async def bitstream_analysis_page(request: Request) -> HTMLResponse:
    """码流分析页面"""
    return templates.TemplateResponse("bitstream_analysis.html", _base_context(request))


# Schedule 页面路由

@router.get("/schedules", response_class=HTMLResponse)
async def schedules_list_page(request: Request) -> HTMLResponse:
    """Schedule 列表页面"""
    return templates.TemplateResponse("schedules_list.html", _base_context(request))


@router.get("/schedules/new", response_class=HTMLResponse)
async def create_schedule_page(request: Request) -> HTMLResponse:
    """创建 Schedule 页面"""
    context = _base_context(request)
    context.update({"schedule_id": None})
    return templates.TemplateResponse("schedule_form.html", context)


@router.get("/schedules/{schedule_id}", response_class=HTMLResponse)
async def schedule_detail_page(request: Request, schedule_id: str) -> HTMLResponse:
    """Schedule 详情页面"""
    context = _base_context(request)
    context.update({"schedule_id": schedule_id})
    return templates.TemplateResponse("schedule_detail.html", context)


@router.get("/schedules/{schedule_id}/edit", response_class=HTMLResponse)
async def edit_schedule_page(request: Request, schedule_id: str) -> HTMLResponse:
    """编辑 Schedule 页面"""
    context = _base_context(request)
    context.update({"schedule_id": schedule_id})
    return templates.TemplateResponse("schedule_form.html", context)

