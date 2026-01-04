"""
提供 Schedule 创建、查询、更新、删除等 RESTful API
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.models.schedule import ScheduleMetadata, ScheduleRepeat, ScheduleStatus
from src.schemas.schedules import (
    CreateScheduleRequest,
    CreateScheduleResponse,
    ExecutionDetailResponse,
    ExecutionListItem,
    ScheduleDetailResponse,
    ScheduleListItem,
    UpdateScheduleRequest,
)
from src.services.schedule_storage import schedule_storage
from src.services.scheduler import scheduler_service
from src.services.template_storage import template_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _schedule_to_detail_response(schedule: ScheduleMetadata) -> ScheduleDetailResponse:
    """将 ScheduleMetadata 转换为 ScheduleDetailResponse"""
    return ScheduleDetailResponse(
        schedule_id=schedule.schedule_id,
        name=schedule.name,
        description=schedule.description,
        encoder_type=schedule.encoder_type,
        encoder_config=schedule.encoder_config.model_dump(),
        template_id=schedule.template_id,
        template_type=schedule.template_type,
        template_name=schedule.template_name,
        start_time=schedule.start_time,
        repeat=schedule.repeat,
        status=schedule.status,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
        last_execution=schedule.last_execution,
        last_execution_status=schedule.last_execution_status,
        last_execution_job_id=schedule.last_execution_job_id,
        next_execution=schedule.next_execution,
    )


@router.post(
    "",
    response_model=CreateScheduleResponse,
    status_code=201,
    summary="创建 Schedule",
)
async def create_schedule(request: CreateScheduleRequest) -> CreateScheduleResponse:
    """
    创建新的 Schedule

    - **name**: Schedule 名称
    - **description**: Schedule 描述
    - **encoder_type**: 编码器类型 (ffmpeg/x264/x265/vvenc)
    - **encoder_config**: 编译配置（仓库、分支、构建脚本等）
    - **template_id**: 关联的模板 ID
    - **start_time**: 首次执行时间
    - **repeat**: 重复周期 (none/daily/weekly/monthly)
    """
    # 验证模板是否存在
    template = template_storage.get_template(request.template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {request.template_id} not found")

    # 生成 Schedule ID
    schedule_id = schedule_storage.generate_schedule_id()

    # 创建 Schedule 元数据
    metadata = ScheduleMetadata(
        schedule_id=schedule_id,
        name=request.name,
        description=request.description,
        encoder_type=request.encoder_type,
        encoder_config=request.encoder_config,
        template_id=request.template_id,
        template_type=template.metadata.template_type.value,
        template_name=template.metadata.name,
        start_time=request.start_time,
        repeat=request.repeat,
        status=ScheduleStatus.ACTIVE,
        next_execution=request.start_time,
    )

    # 保存到存储
    schedule_storage.create_schedule(metadata)

    # 添加到调度器
    scheduler_service.add_schedule(metadata)

    logger.info(f"Schedule created: {schedule_id}")

    return CreateScheduleResponse(schedule_id=schedule_id)


@router.get(
    "",
    response_model=List[ScheduleListItem],
    summary="列出所有 Schedules",
)
async def list_schedules(
    status: Optional[ScheduleStatus] = None,
    limit: Optional[int] = None,
) -> List[ScheduleListItem]:
    """
    列出所有 Schedules

    - **status**: 可选的状态过滤
    - **limit**: 可选的数量限制
    """
    schedules = schedule_storage.list_schedules()

    # 状态过滤
    if status:
        schedules = [s for s in schedules if s.status == status]

    # 数量限制
    if limit:
        schedules = schedules[:limit]

    return [
        ScheduleListItem(
            schedule_id=s.schedule_id,
            name=s.name,
            description=s.description,
            encoder_type=s.encoder_type,
            template_id=s.template_id,
            template_type=s.template_type,
            template_name=s.template_name,
            status=s.status,
            start_time=s.start_time,
            repeat=s.repeat,
            created_at=s.created_at,
            updated_at=s.updated_at,
            last_execution=s.last_execution,
            last_execution_status=s.last_execution_status,
            next_execution=s.next_execution,
        )
        for s in schedules
    ]


@router.get(
    "/{schedule_id}",
    response_model=ScheduleDetailResponse,
    summary="获取 Schedule 详情",
)
async def get_schedule(schedule_id: str) -> ScheduleDetailResponse:
    """
    获取 Schedule 详情

    - **schedule_id**: Schedule ID
    """
    schedule = schedule_storage.get_schedule(schedule_id)

    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # 获取调度器中的下次执行时间
    next_run = scheduler_service.get_next_run_time(schedule_id)
    if next_run:
        schedule.next_execution = next_run

    return _schedule_to_detail_response(schedule)


@router.put(
    "/{schedule_id}",
    response_model=ScheduleDetailResponse,
    summary="更新 Schedule",
)
async def update_schedule(
    schedule_id: str, request: UpdateScheduleRequest
) -> ScheduleDetailResponse:
    """
    更新 Schedule 配置

    注意：不能修改 encoder_config（编码器配置）

    - **schedule_id**: Schedule ID
    - 其他字段为可选更新项
    """
    schedule = schedule_storage.get_schedule(schedule_id)

    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # 更新字段
    if request.name is not None:
        schedule.name = request.name
    if request.description is not None:
        schedule.description = request.description
    if request.template_id is not None:
        # 验证新模板是否存在
        template = template_storage.get_template(request.template_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Template {request.template_id} not found")
        schedule.template_id = request.template_id
        schedule.template_type = template.metadata.template_type.value
        schedule.template_name = template.metadata.name
    if request.start_time is not None:
        schedule.start_time = request.start_time
    if request.repeat is not None:
        schedule.repeat = request.repeat
    if request.status is not None:
        schedule.status = request.status

    # 保存更新
    schedule_storage.update_schedule(schedule_id, schedule)

    # 重新加载调度器
    scheduler_service.update_schedule(schedule)

    # 获取调度器中的下次执行时间
    next_run = scheduler_service.get_next_run_time(schedule_id)
    if next_run:
        schedule.next_execution = next_run

    logger.info(f"Schedule updated: {schedule_id}")

    return _schedule_to_detail_response(schedule)


@router.delete(
    "/{schedule_id}",
    status_code=204,
    summary="删除 Schedule",
)
async def delete_schedule(schedule_id: str) -> None:
    """
    删除 Schedule

    - **schedule_id**: Schedule ID
    """
    schedule = schedule_storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # 从调度器移除
    scheduler_service.remove_schedule(schedule_id)

    # 删除存储
    schedule_storage.delete_schedule(schedule_id)

    logger.info(f"Schedule deleted: {schedule_id}")


@router.post(
    "/{schedule_id}/pause",
    summary="暂停 Schedule",
)
async def pause_schedule(schedule_id: str) -> dict:
    """
    暂停 Schedule

    - **schedule_id**: Schedule ID
    """
    schedule = schedule_storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # 更新状态
    schedule.status = ScheduleStatus.PAUSED
    schedule_storage.update_schedule(schedule_id, schedule)

    # 暂停调度器中的任务
    scheduler_service.pause_schedule(schedule_id)

    logger.info(f"Schedule paused: {schedule_id}")

    return {"status": "paused", "schedule_id": schedule_id}


@router.post(
    "/{schedule_id}/resume",
    summary="恢复 Schedule",
)
async def resume_schedule(schedule_id: str) -> dict:
    """
    恢复 Schedule

    - **schedule_id**: Schedule ID
    """
    schedule = schedule_storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # 更新状态
    schedule.status = ScheduleStatus.ACTIVE
    schedule_storage.update_schedule(schedule_id, schedule)

    # 恢复调度器中的任务
    scheduler_service.resume_schedule(schedule_id)

    logger.info(f"Schedule resumed: {schedule_id}")

    return {"status": "active", "schedule_id": schedule_id}


@router.post(
    "/{schedule_id}/trigger",
    summary="立即执行 Schedule",
)
async def trigger_schedule(schedule_id: str) -> dict:
    """
    立即执行一次 Schedule（不影响调度）

    - **schedule_id**: Schedule ID
    """
    schedule = schedule_storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # 异步执行
    from src.services.scheduler import scheduler_service

    async def execute():
        await scheduler_service._execute_schedule(schedule_id)

    import asyncio
    asyncio.create_task(execute())

    logger.info(f"Schedule triggered: {schedule_id}")

    return {"status": "triggered", "schedule_id": schedule_id}


@router.post(
    "/{schedule_id}/copy",
    response_model=CreateScheduleResponse,
    status_code=201,
    summary="复制 Schedule",
)
async def copy_schedule(schedule_id: str) -> CreateScheduleResponse:
    """
    复制 Schedule，生成一个新的 Schedule，名称后缀添加 " (copy)"

    - **schedule_id**: 源 Schedule ID
    """
    schedule = schedule_storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    # 生成新的 Schedule ID
    new_schedule_id = schedule_storage.generate_schedule_id()

    # 复制元数据
    import copy
    new_metadata = copy.deepcopy(schedule)
    new_metadata.schedule_id = new_schedule_id
    new_metadata.name = f"{schedule.name} (copy)"
    new_metadata.created_at = datetime.utcnow()
    new_metadata.updated_at = datetime.utcnow()
    new_metadata.last_execution = None
    new_metadata.last_execution_status = None
    new_metadata.last_execution_job_id = None
    new_metadata.next_execution = schedule.start_time

    # 保存新 Schedule
    schedule_storage.create_schedule(new_metadata)

    # 添加到调度器
    if new_metadata.status == ScheduleStatus.ACTIVE:
        scheduler_service.add_schedule(new_metadata)

    logger.info(f"Schedule copied: {schedule_id} -> {new_schedule_id}")

    return CreateScheduleResponse(schedule_id=new_schedule_id)


@router.get(
    "/{schedule_id}/executions",
    response_model=List[ExecutionListItem],
    summary="获取执行历史",
)
async def list_executions(
    schedule_id: str,
    limit: int = 100,
) -> List[ExecutionListItem]:
    """
    获取 Schedule 的执行历史

    - **schedule_id**: Schedule ID
    - **limit**: 返回数量限制（默认 100）
    """
    schedule = schedule_storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    executions = schedule_storage.list_executions(schedule_id, limit=limit)

    return [
        ExecutionListItem(
            execution_id=e.execution_id,
            schedule_id=e.schedule_id,
            executed_at=e.executed_at,
            job_id=e.job_id,
            build_status=e.build_status,
            build_log_path=e.build_log_path,
            error_message=e.error_message,
        )
        for e in executions
    ]


@router.get(
    "/{schedule_id}/executions/{execution_id}",
    response_model=ExecutionDetailResponse,
    summary="获取单次执行详情",
)
async def get_execution(
    schedule_id: str,
    execution_id: str,
) -> ExecutionDetailResponse:
    """
    获取单次执行详情

    - **schedule_id**: Schedule ID
    - **execution_id**: Execution ID
    """
    schedule = schedule_storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    executions = schedule_storage.list_executions(schedule_id, limit=1000)

    execution = None
    for e in executions:
        if e.execution_id == execution_id:
            execution = e
            break

    if not execution:
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

    return ExecutionDetailResponse(
        execution_id=execution.execution_id,
        schedule_id=execution.schedule_id,
        executed_at=execution.executed_at,
        job_id=execution.job_id,
        build_status=execution.build_status,
        build_log_path=execution.build_log_path,
        error_message=execution.error_message,
    )


@router.get(
    "/{schedule_id}/logs/{log_filename}",
    summary="获取构建日志",
)
async def get_build_log(
    schedule_id: str,
    log_filename: str,
) -> dict:
    """
    获取构建日志内容

    - **schedule_id**: Schedule ID
    - **log_filename**: 日志文件名
    """
    schedule = schedule_storage.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    log_content = schedule_storage.get_build_log(schedule_id, log_filename)
    if log_content is None:
        raise HTTPException(status_code=404, detail=f"Log file {log_filename} not found")

    return {
        "schedule_id": schedule_id,
        "log_filename": log_filename,
        "content": log_content,
    }
