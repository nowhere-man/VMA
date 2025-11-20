"""
页面路由

提供 Web 界面的 HTML 页面
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.models import JobStatus
from src.services import job_storage
from src.services.template_storage import template_storage

router = APIRouter(tags=["pages"])

# 配置模板
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_report_page(request: Request, job_id: str) -> HTMLResponse:
    """任务报告页面"""
    job = job_storage.get_job(job_id)

    if not job:
        # 返回 404 页面
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "error": f"Job {job_id} not found",
            },
            status_code=404,
        )

    metadata = job.metadata

    # 准备模板数据
    context = {
        "request": request,
        "job": {
            "job_id": metadata.job_id,
            "status": metadata.status.value,
            "mode": metadata.mode.value,
            "created_at": metadata.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": metadata.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": (
                metadata.completed_at.strftime("%Y-%m-%d %H:%M:%S")
                if metadata.completed_at
                else None
            ),
            "template_name": metadata.template_name,
            "reference_filename": (
                metadata.reference_video.filename if metadata.reference_video else None
            ),
            "distorted_filename": (
                metadata.distorted_video.filename if metadata.distorted_video else None
            ),
            "preset": metadata.preset,
            "metrics": metadata.metrics,
            "error_message": metadata.error_message,
            "template_a_id": metadata.template_a_id,
            "template_b_id": metadata.template_b_id,
            "comparison_result": metadata.comparison_result,
            "command_logs": [
                {
                    "command_id": cmd.command_id,
                    "command_type": cmd.command_type,
                    "command": cmd.command,
                    "status": cmd.status.value,
                    "source_file": cmd.source_file,
                    "started_at": cmd.started_at.strftime("%Y-%m-%d %H:%M:%S") if cmd.started_at else None,
                    "completed_at": cmd.completed_at.strftime("%Y-%m-%d %H:%M:%S") if cmd.completed_at else None,
                    "error_message": cmd.error_message,
                }
                for cmd in metadata.command_logs
            ],
        },
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
            "template_name": job.metadata.template_name or "N/A",
            "created_at": job.metadata.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": (
                job.metadata.completed_at.strftime("%Y-%m-%d %H:%M:%S")
                if job.metadata.completed_at
                else "-"
            ),
        }
        for job in jobs
    ]

    return templates.TemplateResponse(
        "jobs_list.html",
        {
            "request": request,
            "jobs": jobs_data,
            "status": status,
        },
    )


@router.get("/templates", response_class=HTMLResponse)
async def templates_list_page(request: Request) -> HTMLResponse:
    """转码模板列表页面"""
    return templates.TemplateResponse("templates_list.html", {"request": request})


@router.get("/templates/new", response_class=HTMLResponse)
async def create_template_page(request: Request) -> HTMLResponse:
    """创建新模板页面"""
    return templates.TemplateResponse(
        "template_form.html", {"request": request, "template_id": None}
    )


@router.get("/templates/compare", response_class=HTMLResponse)
async def compare_templates_page(request: Request) -> HTMLResponse:
    """模板对比页面"""

    return templates.TemplateResponse(
        "template_compare.html", {"request": request}
    )


@router.get("/templates/{template_id}", response_class=HTMLResponse)
async def template_detail_page(request: Request, template_id: str) -> HTMLResponse:
    """模板详情页面"""
    template = template_storage.get_template(template_id)

    if not template:
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "error": f"Template {template_id} not found",
            },
            status_code=404,
        )

    metadata = template.metadata

    context = {
        "request": request,
        "template": {
            "template_id": metadata.template_id,
            "name": metadata.name,
            "description": metadata.description,
            "sequence_type": metadata.sequence_type.value,
            "width": metadata.width,
            "height": metadata.height,
            "fps": metadata.fps,
            "source_path_type": metadata.source_path_type.value,
            "source_path": metadata.source_path,
            "encoder_type": metadata.encoder_type.value if metadata.encoder_type else None,
            "encoder_params": metadata.encoder_params,
            "encoder_path": metadata.encoder_path,
            "output_type": metadata.output_type.value,
            "output_dir": metadata.output_dir,
            "metrics_report_dir": metadata.metrics_report_dir,
            "skip_metrics": metadata.skip_metrics,
            "metrics_types": metadata.metrics_types,
            "created_at": metadata.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": metadata.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }

    return templates.TemplateResponse("template_detail.html", context)


@router.get("/templates/{template_id}/edit", response_class=HTMLResponse)
async def edit_template_page(request: Request, template_id: str) -> HTMLResponse:
    """编辑模板页面"""
    template = template_storage.get_template(template_id)

    if not template:
        return templates.TemplateResponse(
            "base.html",
            {
                "request": request,
                "error": f"Template {template_id} not found",
            },
            status_code=404,
        )

    return templates.TemplateResponse(
        "template_form.html", {"request": request, "template_id": template_id}
    )
