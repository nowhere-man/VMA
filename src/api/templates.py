"""
提供模板创建、查询、更新、删除等 RESTful API
"""
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from src.models.template import EncodingTemplateMetadata, TemplateType
from src.schemas.templates import (
    CreateTemplateRequest,
    CreateTemplateResponse,
    TemplateListItem,
    UpdateTemplateRequest,
    ValidateTemplateResponse,
)
from src.models import JobMetadata, JobMode, JobStatus
from src.services.metrics_comparison_runner import template_runner
from src.services.storage import job_storage
from src.services.template_storage import template_storage
from src.models.template import TemplateSideConfig
from src.utils.template_helpers import fingerprint as _fingerprint
from src.utils.path_helpers import dir_exists, dir_writable

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.post(
    "",
    response_model=CreateTemplateResponse,
    status_code=201,
    summary="创建转码模板",
)
async def create_template(request: CreateTemplateRequest) -> CreateTemplateResponse:
    """
    创建新的转码模板

    - **name**: 模板名称
    - **description**: 模板描述
    - **sequence_type**: 序列类型（Media/YUV 420P）
    - **enable_encode**: 是否进行编码（不编码则直接使用输出目录中的已编码文件做指标）
    - **encoder_type/params/path**: 编码相关参数（仅当进行编码时生效）
    - **source_path**: 源视频路径
    - **output_dir**: 输出目录（转码输出或已编码码流所在目录）
    """
    # 生成模板 ID
    template_id = template_storage.generate_template_id()

    try:
        anchor_cfg = TemplateSideConfig(**request.anchor.model_dump())
        test_cfg = TemplateSideConfig(**request.test.model_dump())

        # 创建模板元数据
        metadata = EncodingTemplateMetadata(
            template_id=template_id,
            name=request.name,
            description=request.description,
            anchor=anchor_cfg,
            test=test_cfg,
        )
        metadata.anchor_fingerprint = _fingerprint(metadata.anchor)

        template = template_storage.create_template(metadata)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return CreateTemplateResponse(
        template_id=template.template_id,
    )


@router.get(
    "/{template_id}",
    summary="获取模板详情",
)
async def get_template(template_id: str) -> dict:
    """
    获取模板详情

    - **template_id**: 模板 ID
    """
    template = template_storage.get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    metadata = template.metadata
    return metadata.model_dump(mode="json")


@router.get(
    "",
    response_model=List[TemplateListItem],
    summary="列出所有模板",
)
async def list_templates(
    limit: Optional[int] = None,
    template_type: Optional[TemplateType] = None,
    encoder_type: Optional[str] = None,
) -> List[TemplateListItem]:
    """
    列出所有模板

    - **encoder_type**: 可选的编码器类型过滤（ffmpeg/x264/x265/vvenc）
    - **template_type**: 可选的模板类型过滤
    - **limit**: 可选的数量限制
    """
    templates = template_storage.list_templates(limit=limit, template_type=template_type)

    # 额外的 encoder_type 过滤（在存储层过滤后进行二次过滤）
    if encoder_type:
        templates = [
            t for t in templates
            if t.metadata.anchor.encoder_type == encoder_type or
            (t.metadata.test and t.metadata.test.encoder_type == encoder_type)
        ]

    return [
        TemplateListItem(
            template_id=t.metadata.template_id,
            name=t.metadata.name,
            description=t.metadata.description,
            created_at=t.metadata.created_at,
            template_type=t.metadata.template_type.value,
            anchor_source_dir=t.metadata.anchor.source_dir,
            anchor_bitstream_dir=t.metadata.anchor.bitstream_dir,
            test_source_dir=t.metadata.test.source_dir if t.metadata.test else None,
            test_bitstream_dir=t.metadata.test.bitstream_dir if t.metadata.test else None,
            anchor_computed=t.metadata.anchor_computed,
            anchor_encoder_params=t.metadata.anchor.encoder_params,
            anchor_bitrate_points=t.metadata.anchor.bitrate_points,
            test_encoder_params=t.metadata.test.encoder_params if t.metadata.test else None,
            test_bitrate_points=t.metadata.test.bitrate_points if t.metadata.test else [],
        )
        for t in templates
    ]


@router.put(
    "/{template_id}",
    summary="更新模板",
)
async def update_template(
    template_id: str, request: UpdateTemplateRequest
) -> dict:
    """
    更新模板配置

    - **template_id**: 模板 ID
    - 其他字段为可选更新项
    """
    template = template_storage.get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    anchor_changed = False
    if request.name is not None:
        template.metadata.name = request.name
    if request.description is not None:
        template.metadata.description = request.description
    if request.anchor is not None:
        try:
            template.metadata.anchor = TemplateSideConfig(**request.anchor.model_dump())
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        anchor_changed = True
    if request.test is not None:
        try:
            template.metadata.test = TemplateSideConfig(**request.test.model_dump())
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    if anchor_changed:
        template.metadata.anchor_computed = False
        template.metadata.anchor_fingerprint = _fingerprint(template.metadata.anchor)
        try:
            anchor_dir = Path(template.metadata.anchor.bitstream_dir)
            if anchor_dir.is_dir():
                for p in anchor_dir.iterdir():
                    if p.is_file():
                        p.unlink()
        except Exception:
            pass

    # 保存更新
    template_storage.update_template(template)

    metadata = template.metadata

    return metadata.model_dump(mode="json")


@router.post(
    "/{template_id}/copy",
    response_model=CreateTemplateResponse,
    status_code=201,
    summary="复制模板",
)
async def copy_template(template_id: str) -> CreateTemplateResponse:
    """
    复制模板，生成一个新的模板，名称后缀添加 copy

    - **template_id**: 源模板 ID
    """
    new_template = template_storage.copy_template(template_id)

    if not new_template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    return CreateTemplateResponse(template_id=new_template.template_id)


@router.delete(
    "/{template_id}",
    status_code=204,
    summary="删除模板",
)
async def delete_template(template_id: str) -> None:
    """
    删除模板

    - **template_id**: 模板 ID
    """
    success = template_storage.delete_template(template_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")


@router.get(
    "/{template_id}/validate",
    response_model=ValidateTemplateResponse,
    summary="验证模板路径",
)
async def validate_template(template_id: str) -> ValidateTemplateResponse:
    """
    验证模板配置的路径是否有效

    - **template_id**: 模板 ID
    """
    template = template_storage.get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    b = template.metadata.anchor
    e = template.metadata.test
    source_ok = dir_exists(b.source_dir) and dir_exists(e.source_dir)
    output_ok = dir_writable(b.bitstream_dir) and dir_writable(e.bitstream_dir)

    return ValidateTemplateResponse(
        template_id=template_id,
        source_exists=source_ok,
        output_dir_writable=output_ok,
        all_valid=source_ok and output_ok,
    )


@router.post(
    "/{template_id}/execute",
    response_model=dict,
    summary="执行模板转码",
)
async def execute_template(
    template_id: str, request: dict = None, background_tasks: BackgroundTasks = None
) -> dict:
    """
    使用模板执行视频转码

    - **template_id**: 模板 ID
    - **source_files**: 可选的源文件列表
    """
    from src.models import CommandLog, CommandStatus
    from datetime import datetime
    from nanoid import generate

    template = template_storage.get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    # 创建任务记录
    job_id = job_storage.generate_job_id()
    metadata = JobMetadata(
        job_id=job_id,
        mode=JobMode.METRICS_COMPARISON,
        status=JobStatus.PENDING,
        template_a_id=template_id,
        template_name=template.metadata.name,
    )
    job = job_storage.create_job(metadata)

    # 命令状态更新回调
    def update_command_status(command_id: str, status: str, error: str = None):
        for cmd_log in job.metadata.command_logs:
            if cmd_log.command_id == command_id:
                cmd_log.status = CommandStatus(status)
                if status == "running":
                    cmd_log.started_at = datetime.utcnow()
                elif status in ("completed", "failed"):
                    cmd_log.completed_at = datetime.utcnow()
                if error:
                    cmd_log.error_message = error
                break
        job_storage.update_job(job)

    # 添加命令日志
    def add_command_log(command_type: str, command: str, source_file: str = None) -> str:
        command_id = generate(size=8)
        cmd_log = CommandLog(
            command_id=command_id,
            command_type=command_type,
            command=command,
            status=CommandStatus.PENDING,
            source_file=source_file,
        )
        job.metadata.command_logs.append(cmd_log)
        job_storage.update_job(job)
        return command_id

    # 后台执行转码任务
    async def execute_encoding():
        try:
            job.metadata.status = JobStatus.PROCESSING
            job_storage.update_job(job)

            result = await template_runner.execute(
                template,
                job=job,
            )
            # 保存 anchor 状态更新
            template_storage.update_template(template)

            # 保存执行结果
            job.metadata.execution_result = result
            if result.get("failed"):
                job.metadata.status = JobStatus.FAILED
                first_err = (result.get("errors") or [{}])[0].get("error")
                job.metadata.error_message = first_err or "执行失败"
            else:
                job.metadata.status = JobStatus.COMPLETED
            job.metadata.completed_at = datetime.utcnow()
            job_storage.update_job(job)

        except Exception as e:
            job.metadata.status = JobStatus.FAILED
            job.metadata.error_message = str(e)
            job_storage.update_job(job)

    background_tasks.add_task(execute_encoding)

    return {
        "job_id": job_id,
        "status": job.metadata.status.value,
        "message": "转码任务已创建，正在后台执行"
    }


@router.post(
    "/compare",
    response_model=dict,
    summary="创建模板对比任务",
)
async def compare_templates() -> dict:
    raise HTTPException(status_code=404, detail="Template compare is removed")
