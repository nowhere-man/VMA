"""
API 端点实现 - 转码模板管理

提供模板创建、查询、更新、删除等 RESTful API
"""
import math
from typing import Any, Dict, List, Optional

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from src.models_template import EncodingTemplateMetadata
from src.schemas_template import (
    CreateTemplateRequest,
    CreateTemplateResponse,
    TemplateComparisonMetrics,
    TemplateComparisonRequest,
    TemplateComparisonResponse,
    TemplateComparisonStat,
    TemplateExecutionSummary,
    TemplateListItem,
    TemplateResponse,
    UpdateTemplateRequest,
    ValidateTemplateResponse,
)
from src.models import JobMetadata, JobMode, JobStatus
from src.services.storage import job_storage
from src.services.template_encoder import template_encoder_service
from src.services.template_storage import template_storage

router = APIRouter(prefix="/api/templates", tags=["templates"])


class ExecuteTemplateRequest(BaseModel):
    """执行模板转码请求"""

    source_files: Optional[List[str]] = Field(
        None, description="可选的源文件列表，不提供则使用模板配置"
    )


def _mean(values: List[Optional[float]]) -> Optional[float]:
    valid = [v for v in values if isinstance(v, (int, float))]
    if not valid:
        return None
    return sum(valid) / len(valid)


def _build_stat(a: Optional[float], b: Optional[float]) -> TemplateComparisonStat:
    if a is None and b is None:
        return TemplateComparisonStat(template_a=None, template_b=None, delta=None, delta_percent=None)

    delta = None
    if a is not None and b is not None:
        delta = b - a

    delta_percent = None
    if a not in (None, 0) and b is not None:
        delta_percent = ((b - a) / a) * 100

    return TemplateComparisonStat(
        template_a=a,
        template_b=b,
        delta=delta,
        delta_percent=delta_percent,
    )


def _collect_metric_points(results: List[Any]) -> Dict[str, List[tuple[float, float]]]:
    points: Dict[str, List[tuple[float, float]]] = {
        "psnr": [],
        "ssim": [],
        "vmaf": [],
    }

    for item in results:
        if hasattr(item, "metrics"):
            metrics = getattr(item, "metrics") or {}
        else:
            metrics = (item.get("metrics") if isinstance(item, dict) else {}) or {}

        if hasattr(item, "output_info"):
            output_info = getattr(item, "output_info") or {}
        else:
            output_info = (item.get("output_info") if isinstance(item, dict) else {}) or {}

        bitrate = output_info.get("bitrate")
        if not isinstance(bitrate, (int, float)) or bitrate <= 0:
            continue

        psnr_avg = (metrics.get("psnr") or {}).get("psnr_avg")
        if isinstance(psnr_avg, (int, float)):
            points["psnr"].append((float(psnr_avg), float(bitrate)))

        ssim_avg = (metrics.get("ssim") or {}).get("ssim_avg")
        if isinstance(ssim_avg, (int, float)):
            points["ssim"].append((float(ssim_avg), float(bitrate)))

        vmaf_mean = (metrics.get("vmaf") or {}).get("vmaf_mean")
        if isinstance(vmaf_mean, (int, float)):
            points["vmaf"].append((float(vmaf_mean), float(bitrate)))

    return points


def _interpolate(points: List[tuple[float, float]], quality: float) -> Optional[float]:
    for idx in range(len(points) - 1):
        x0, y0 = points[idx]
        x1, y1 = points[idx + 1]
        if x0 <= quality <= x1 and x1 != x0:
            t = (quality - x0) / (x1 - x0)
            return math.log(y0) + t * (math.log(y1) - math.log(y0))
    return None


def _compute_bd_rate(
    points_a: List[tuple[float, float]], points_b: List[tuple[float, float]]
) -> Optional[float]:
    if len(points_a) < 2 or len(points_b) < 2:
        return None

    points_a = sorted(points_a, key=lambda item: item[0])
    points_b = sorted(points_b, key=lambda item: item[0])

    q_min = max(points_a[0][0], points_b[0][0])
    q_max = min(points_a[-1][0], points_b[-1][0])

    if q_max <= q_min:
        return None

    samples = 20
    step = (q_max - q_min) / samples
    accum = 0.0
    count = 0

    for i in range(samples + 1):
        q = q_min + step * i
        log_rate_a = _interpolate(points_a, q)
        log_rate_b = _interpolate(points_b, q)
        if log_rate_a is None or log_rate_b is None:
            continue

        rate_a = math.exp(log_rate_a)
        rate_b = math.exp(log_rate_b)
        if rate_a <= 0:
            continue

        accum += (rate_b - rate_a) / rate_a
        count += 1

    if count == 0:
        return None

    return (accum / count) * 100


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
    - **encoder_type**: 编码器类型（ffmpeg/x264/x265/vvenc）
    - **encoder_params**: 编码参数字符串
    - **source_path**: 源视频路径
    - **output_type**: 输出类型
    - **metrics_report_dir**: 报告目录
    """
    # 生成模板 ID
    template_id = template_storage.generate_template_id()

    # 创建模板元数据
    metadata = EncodingTemplateMetadata(
        template_id=template_id,
        name=request.name,
        description=request.description,
        sequence_type=request.sequence_type,
        width=request.width,
        height=request.height,
        fps=request.fps,
        source_path_type=request.source_path_type,
        source_path=request.source_path,
        encoder_type=request.encoder_type,
        encoder_path=request.encoder_path,
        encoder_params=request.encoder_params,
        output_type=request.output_type,
        output_dir=request.output_dir,
        metrics_report_dir=request.metrics_report_dir,
        skip_metrics=request.skip_metrics,
        metrics_types=request.metrics_types,
    )

    # 创建模板
    try:
        template = template_storage.create_template(metadata)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return CreateTemplateResponse(
        template_id=template.template_id,
        name=template.name,
        created_at=template.metadata.created_at,
    )


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    summary="获取模板详情",
)
async def get_template(template_id: str) -> TemplateResponse:
    """
    获取模板详情

    - **template_id**: 模板 ID
    """
    template = template_storage.get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    metadata = template.metadata

    return TemplateResponse(
        template_id=metadata.template_id,
        name=metadata.name,
        description=metadata.description,
        sequence_type=metadata.sequence_type,
        width=metadata.width,
        height=metadata.height,
        fps=metadata.fps,
        source_path_type=metadata.source_path_type,
        source_path=metadata.source_path,
        encoder_type=metadata.encoder_type,
        encoder_path=metadata.encoder_path,
        encoder_params=metadata.encoder_params,
        output_type=metadata.output_type,
        output_dir=metadata.output_dir,
        metrics_report_dir=metadata.metrics_report_dir,
        skip_metrics=metadata.skip_metrics,
        metrics_types=metadata.metrics_types,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
    )


@router.get(
    "",
    response_model=List[TemplateListItem],
    summary="列出所有模板",
)
async def list_templates(
    encoder_type: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[TemplateListItem]:
    """
    列出所有模板

    - **encoder_type**: 可选的编码器类型过滤
    - **limit**: 可选的数量限制
    """
    templates = template_storage.list_templates(encoder_type=encoder_type, limit=limit)

    return [
        TemplateListItem(
            template_id=t.metadata.template_id,
            name=t.metadata.name,
            description=t.metadata.description,
            sequence_type=t.metadata.sequence_type,
            encoder_type=t.metadata.encoder_type,
            created_at=t.metadata.created_at,
        )
        for t in templates
    ]


@router.put(
    "/{template_id}",
    response_model=TemplateResponse,
    summary="更新模板",
)
async def update_template(
    template_id: str, request: UpdateTemplateRequest
) -> TemplateResponse:
    """
    更新模板配置

    - **template_id**: 模板 ID
    - 其他字段为可选更新项
    """
    template = template_storage.get_template(template_id)

    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    fields_set = getattr(request, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(request, "__fields_set__", set())

    # 更新非空字段
    if request.name is not None:
        template.metadata.name = request.name
    if request.description is not None:
        template.metadata.description = request.description
    if request.sequence_type is not None:
        template.metadata.sequence_type = request.sequence_type
    if request.width is not None:
        template.metadata.width = request.width
    if request.height is not None:
        template.metadata.height = request.height
    if request.fps is not None:
        template.metadata.fps = request.fps
    if request.source_path_type is not None:
        template.metadata.source_path_type = request.source_path_type
    if request.source_path is not None:
        template.metadata.source_path = request.source_path
    if request.encoder_type is not None:
        template.metadata.encoder_type = request.encoder_type
    if "encoder_path" in fields_set:
        template.metadata.encoder_path = request.encoder_path
    if request.encoder_params is not None:
        template.metadata.encoder_params = request.encoder_params
    if request.output_type is not None:
        template.metadata.output_type = request.output_type
    if request.output_dir is not None:
        template.metadata.output_dir = request.output_dir
    if request.metrics_report_dir is not None:
        template.metadata.metrics_report_dir = request.metrics_report_dir
    if request.skip_metrics is not None:
        template.metadata.skip_metrics = request.skip_metrics
    if request.metrics_types is not None:
        template.metadata.metrics_types = request.metrics_types

    # 保存更新
    template_storage.update_template(template)

    metadata = template.metadata

    return TemplateResponse(
        template_id=metadata.template_id,
        name=metadata.name,
        description=metadata.description,
        sequence_type=metadata.sequence_type,
        width=metadata.width,
        height=metadata.height,
        fps=metadata.fps,
        source_path_type=metadata.source_path_type,
        source_path=metadata.source_path,
        encoder_type=metadata.encoder_type,
        encoder_path=metadata.encoder_path,
        encoder_params=metadata.encoder_params,
        output_type=metadata.output_type,
        output_dir=metadata.output_dir,
        metrics_report_dir=metadata.metrics_report_dir,
        skip_metrics=metadata.skip_metrics,
        metrics_types=metadata.metrics_types,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
    )


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

    try:
        validation_results = template.validate_paths()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证路径时出错: {str(e)}")

    all_valid = all(validation_results.values())

    return ValidateTemplateResponse(
        template_id=template_id,
        source_exists=validation_results["source_exists"],
        output_dir_writable=validation_results["output_dir_writable"],
        metrics_dir_writable=validation_results["metrics_dir_writable"],
        all_valid=all_valid,
    )


@router.post(
    "/{template_id}/execute",
    response_model=dict,
    summary="执行模板转码",
)
async def execute_template(
    template_id: str, request: ExecuteTemplateRequest, background_tasks: BackgroundTasks
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

    # 解析源文件路径
    from pathlib import Path

    source_files = None
    if request.source_files:
        source_files = [Path(f) for f in request.source_files]

    # 创建任务记录
    job_id = job_storage.generate_job_id()
    metadata = JobMetadata(
        job_id=job_id,
        mode=JobMode.TEMPLATE,
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

            result = await template_encoder_service.encode_with_template(
                template, source_files,
                add_command_callback=add_command_log,
                update_status_callback=update_command_status,
            )

            # 保存执行结果
            job.metadata.execution_result = result
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
async def compare_templates(
    request: TemplateComparisonRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    if request.template_a == request.template_b:
        raise HTTPException(status_code=400, detail="请选择不同的模板进行对比")

    template_a = template_storage.get_template(request.template_a)
    if not template_a:
        raise HTTPException(status_code=404, detail=f"Template {request.template_a} not found")

    template_b = template_storage.get_template(request.template_b)
    if not template_b:
        raise HTTPException(status_code=404, detail=f"Template {request.template_b} not found")

    meta_a = template_a.metadata
    meta_b = template_b.metadata

    # 验证编码器类型一致
    if meta_a.encoder_type != meta_b.encoder_type:
        raise HTTPException(status_code=400, detail="两个模板的编码器类型必须一致")

    # 验证质量指标设置一致
    if meta_a.skip_metrics != meta_b.skip_metrics:
        raise HTTPException(status_code=400, detail="两个模板的质量指标设置必须一致")

    if not meta_a.skip_metrics and sorted(meta_a.metrics_types) != sorted(meta_b.metrics_types):
        raise HTTPException(status_code=400, detail="两个模板的指标类型需保持一致")

    sources_a = template_encoder_service.resolve_source_files(template_a)
    sources_b = template_encoder_service.resolve_source_files(template_b)

    if not sources_a:
        raise HTTPException(status_code=400, detail="模板 A 未找到任何源文件")

    normalized_a = [str(path.resolve()) for path in sources_a]
    normalized_b = [str(path.resolve()) for path in sources_b]

    if sorted(normalized_a) != sorted(normalized_b):
        raise HTTPException(status_code=400, detail="两个模板的源文件集合不一致")

    # Create comparison job
    job_id = job_storage.generate_job_id()
    metadata = JobMetadata(
        job_id=job_id,
        mode=JobMode.COMPARISON,
        status=JobStatus.PENDING,
        template_a_id=request.template_a,
        template_b_id=request.template_b,
    )

    job = job_storage.create_job(metadata)

    # Schedule comparison execution in background
    async def execute_comparison():
        try:
            job.metadata.status = JobStatus.PROCESSING
            job_storage.update_job(job)

            source_paths = [Path(p) for p in normalized_a]

            result_a_raw = await template_encoder_service.encode_with_template(
                template_a, source_paths
            )
            result_b_raw = await template_encoder_service.encode_with_template(
                template_b, source_paths
            )

            if result_a_raw.get("failed") or result_a_raw.get("errors"):
                raise Exception("模板 A 执行失败")

            if result_b_raw.get("failed") or result_b_raw.get("errors"):
                raise Exception("模板 B 执行失败")

            summary_a = TemplateExecutionSummary(**result_a_raw)
            summary_b = TemplateExecutionSummary(**result_b_raw)

            speed_stat = _build_stat(
                summary_a.average_speed_fps,
                summary_b.average_speed_fps,
            )
            cpu_stat = _build_stat(
                summary_a.average_cpu_percent,
                summary_b.average_cpu_percent,
            )
            bitrate_stat = _build_stat(
                summary_a.average_bitrate,
                summary_b.average_bitrate,
            )

            def metric_avg(summary: TemplateExecutionSummary, metric_key: str, field: str) -> Optional[float]:
                values: List[float] = []
                for item in summary.results:
                    metric_block = (item.metrics or {}).get(metric_key) or {}
                    value = metric_block.get(field)
                    if isinstance(value, (int, float)):
                        values.append(float(value))
                return _mean(values)

            quality_metrics = {
                "psnr": _build_stat(
                    metric_avg(summary_a, "psnr", "psnr_avg"),
                    metric_avg(summary_b, "psnr", "psnr_avg"),
                ),
                "ssim": _build_stat(
                    metric_avg(summary_a, "ssim", "ssim_avg"),
                    metric_avg(summary_b, "ssim", "ssim_avg"),
                ),
                "vmaf": _build_stat(
                    metric_avg(summary_a, "vmaf", "vmaf_mean"),
                    metric_avg(summary_b, "vmaf", "vmaf_mean"),
                ),
            }

            points_a = _collect_metric_points(summary_a.results)
            points_b = _collect_metric_points(summary_b.results)

            bd_rate = {
                metric: _compute_bd_rate(points_a[metric], points_b[metric])
                for metric in ("psnr", "ssim", "vmaf")
            }

            comparisons = TemplateComparisonMetrics(
                speed_fps=speed_stat,
                cpu_percent=cpu_stat,
                bitrate=bitrate_stat,
                quality_metrics=quality_metrics,
                bd_rate=bd_rate,
            )

            comparison_result = TemplateComparisonResponse(
                template_a=summary_a,
                template_b=summary_b,
                comparisons=comparisons,
            )

            # Store comparison result
            job.metadata.comparison_result = comparison_result.model_dump()
            job.metadata.status = JobStatus.COMPLETED
            job_storage.update_job(job)

        except Exception as e:
            job.metadata.status = JobStatus.FAILED
            job.metadata.error_message = str(e)
            job_storage.update_job(job)

    background_tasks.add_task(execute_comparison)

    return {
        "job_id": job_id,
        "status": job.metadata.status.value,
        "message": "对比任务已创建，正在后台执行"
    }
