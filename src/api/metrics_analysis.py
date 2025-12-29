"""
Metrics 分析模板 API
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.models import JobMetadata, JobMode, JobStatus
from src.models.template import EncodingTemplateMetadata, TemplateType
from src.schemas.metrics_analysis import (
    CreateMetricsTemplateRequest,
    MetricsTemplateListItem,
    MetricsTemplateResponse,
    UpdateMetricsTemplateRequest,
    ValidateMetricsTemplateResponse,
)
from src.services.metrics_analysis_runner import metrics_analysis_runner
from src.services.storage import job_storage
from src.services.template_storage import template_storage
from src.models.template import TemplateSideConfig
from src.utils.path_helpers import dir_exists, dir_writable

router = APIRouter(prefix="/api/metrics-analysis", tags=["metrics-analysis"])


@router.post(
    "/templates",
    response_model=dict,
    status_code=201,
    summary="创建 Metrics 分析模板",
)
async def create_metrics_template(request: CreateMetricsTemplateRequest) -> dict:
    template_id = template_storage.generate_template_id()
    try:
        cfg = TemplateSideConfig(**request.config.model_dump())
        metadata = EncodingTemplateMetadata(
            template_id=template_id,
            name=request.name,
            description=request.description,
            template_type=TemplateType.METRICS_ANALYSIS,
            anchor=cfg,
            test=None,
        )
        template_storage.create_template(metadata)
    except Exception as e:
        # 直接返回校验错误，避免 500
        raise HTTPException(status_code=400, detail=str(e))
    return {"template_id": template_id, "status": "created"}


@router.get(
    "/templates",
    response_model=List[MetricsTemplateListItem],
    summary="列出 Metrics 分析模板",
)
async def list_metrics_templates(limit: Optional[int] = None) -> List[MetricsTemplateListItem]:
    templates = template_storage.list_templates(limit=limit, template_type=TemplateType.METRICS_ANALYSIS)
    items: List[MetricsTemplateListItem] = []
    for t in templates:
        items.append(
            MetricsTemplateListItem(
                template_id=t.template_id,
                name=t.metadata.name,
                description=t.metadata.description,
                created_at=t.metadata.created_at,
                source_dir=t.metadata.anchor.source_dir,
                bitstream_dir=t.metadata.anchor.bitstream_dir,
                template_type=t.metadata.template_type.value,
                encoder_params=t.metadata.anchor.encoder_params,
                bitrate_points=t.metadata.anchor.bitrate_points,
            )
        )
    return items


@router.get(
    "/templates/{template_id}",
    summary="获取 Metrics 分析模板详情",
)
async def get_metrics_template(template_id: str) -> dict:
    template = template_storage.get_template(template_id)
    if not template or template.metadata.template_type != TemplateType.METRICS_ANALYSIS:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    return template.metadata.model_dump(mode="json")


@router.put(
    "/templates/{template_id}",
    summary="更新 Metrics 分析模板",
)
async def update_metrics_template(template_id: str, request: UpdateMetricsTemplateRequest) -> dict:
    template = template_storage.get_template(template_id)
    if not template or template.metadata.template_type != TemplateType.METRICS_ANALYSIS:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    if request.name is not None:
        template.metadata.name = request.name
    if request.description is not None:
        template.metadata.description = request.description
    if request.config is not None:
        try:
            template.metadata.anchor = TemplateSideConfig(**request.config.model_dump())
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    template_storage.update_template(template)

    return template.metadata.model_dump(mode="json")


@router.delete(
    "/templates/{template_id}",
    status_code=204,
    summary="删除 Metrics 分析模板",
)
async def delete_metrics_template(template_id: str) -> None:
    template = template_storage.get_template(template_id)
    if not template or template.metadata.template_type != TemplateType.METRICS_ANALYSIS:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    template_storage.delete_template(template_id)


@router.post(
    "/templates/{template_id}/copy",
    response_model=dict,
    status_code=201,
    summary="复制 Metrics 分析模板",
)
async def copy_metrics_template(template_id: str) -> dict:
    """
    复制 Metrics 分析模板，生成一个新的模板，名称后缀添加 copy

    - **template_id**: 源模板 ID
    """
    template = template_storage.get_template(template_id)
    if not template or template.metadata.template_type != TemplateType.METRICS_ANALYSIS:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    new_template = template_storage.copy_template(template_id)
    if not new_template:
        raise HTTPException(status_code=500, detail="Failed to copy template")

    return {"template_id": new_template.template_id, "status": "created"}


@router.get(
    "/templates/{template_id}/validate",
    response_model=ValidateMetricsTemplateResponse,
    summary="验证 Metrics 模板路径",
)
async def validate_metrics_template(template_id: str) -> ValidateMetricsTemplateResponse:
    template = template_storage.get_template(template_id)
    if not template or template.metadata.template_type != TemplateType.METRICS_ANALYSIS:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    c = template.metadata.anchor
    source_ok = dir_exists(c.source_dir)
    output_ok = dir_writable(c.bitstream_dir)

    return ValidateMetricsTemplateResponse(
        template_id=template_id,
        source_exists=source_ok,
        output_dir_writable=output_ok,
        all_valid=source_ok and output_ok,
    )


@router.post(
    "/templates/{template_id}/execute",
    response_model=dict,
    summary="执行 Metrics 分析模板",
)
async def execute_metrics_template(template_id: str, background_tasks: BackgroundTasks) -> dict:
    template = template_storage.get_template(template_id)
    if not template or template.metadata.template_type != TemplateType.METRICS_ANALYSIS:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    job_id = job_storage.generate_job_id()
    metadata = JobMetadata(
        job_id=job_id,
        mode=JobMode.METRICS_ANALYSIS,
        status=JobStatus.PENDING,
        template_a_id=template_id,
        template_name=template.metadata.name,
    )
    job = job_storage.create_job(metadata)

    async def execute_task():
        try:
            job.metadata.status = JobStatus.PROCESSING
            job_storage.update_job(job)

            result = await metrics_analysis_runner.execute(template, job=job)
            job.metadata.execution_result = result
            if result.get("failed"):
                job.metadata.status = JobStatus.FAILED
                first_err = (result.get("errors") or [{}])[0].get("error")
                job.metadata.error_message = first_err or "执行失败"
            else:
                job.metadata.status = JobStatus.COMPLETED
            job.metadata.completed_at = datetime.utcnow()
            job_storage.update_job(job)
        except Exception as exc:
            job.metadata.status = JobStatus.FAILED
            job.metadata.error_message = str(exc)
            job_storage.update_job(job)

    background_tasks.add_task(execute_task)

    return {
        "job_id": job_id,
        "status": job.metadata.status.value,
        "message": "Metrics 分析任务已创建，正在后台执行",
    }
