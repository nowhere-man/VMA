"""
API 端点实现 - 任务管理

提供任务创建、查询、列表等 RESTful API
"""
import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Response

from src.models import JobMetadata, JobMode, JobStatus
from src.schemas import CreateJobResponse, ErrorResponse, JobDetailResponse, JobListItem
from src.services import job_storage
from src.utils import extract_video_info, save_uploaded_file

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=CreateJobResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}},
)
async def create_job(
    mode: str = Form(...),
    file: Optional[UploadFile] = File(None),
    reference: Optional[UploadFile] = File(None),
    distorted: Optional[UploadFile] = File(None),
    preset: Optional[str] = Form("medium"),
) -> CreateJobResponse:
    """
    创建新的视频质量分析任务

    - **mode**: 任务模式 (single_file 或 dual_file)
    - **file**: 单文件模式下的视频文件
    - **reference**: 双文件模式下的参考视频
    - **distorted**: 双文件模式下的待测视频
    - **preset**: 单文件模式下的转码预设（默认 medium）
    """
    # 验证模式
    try:
        job_mode = JobMode(mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {mode}. Must be 'single_file' or 'dual_file'",
        )

    # 生成任务 ID
    job_id = job_storage.generate_job_id()

    # 创建任务元数据
    metadata = JobMetadata(
        job_id=job_id,
        status=JobStatus.PENDING,
        mode=job_mode,
    )

    # 单文件模式
    if job_mode == JobMode.SINGLE_FILE:
        if not file:
            raise HTTPException(
                status_code=400,
                detail="File is required for single_file mode",
            )

        # 保存转码预设
        metadata.preset = preset

        # 创建任务
        job = job_storage.create_job(metadata)

        # 保存上传的文件
        file_content = await file.read()
        file_path = job.job_dir / file.filename
        save_uploaded_file(file_content, file_path)

        # 提取视频信息
        video_info = extract_video_info(file_path)
        metadata.reference_video = video_info

        # 更新元数据
        job_storage.update_job(job)

    # 双文件模式
    elif job_mode == JobMode.DUAL_FILE:
        if not reference:
            raise HTTPException(
                status_code=400,
                detail="Reference file is required for dual_file mode",
            )
        if not distorted:
            raise HTTPException(
                status_code=400,
                detail="Distorted file is required for dual_file mode",
            )

        # 创建任务
        job = job_storage.create_job(metadata)

        # 保存参考视频
        reference_content = await reference.read()
        reference_path = job.job_dir / reference.filename
        save_uploaded_file(reference_content, reference_path)
        metadata.reference_video = extract_video_info(reference_path)

        # 保存待测视频
        distorted_content = await distorted.read()
        distorted_path = job.job_dir / distorted.filename
        save_uploaded_file(distorted_content, distorted_path)
        metadata.distorted_video = extract_video_info(distorted_path)

        # 更新元数据
        job_storage.update_job(job)

    # 返回响应
    return CreateJobResponse(
        job_id=metadata.job_id,
        status=metadata.status,
        mode=metadata.mode,
        created_at=metadata.created_at,
    )


@router.get(
    "/{job_id}",
    response_model=JobDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_job(job_id: str) -> JobDetailResponse:
    """
    获取任务详情

    - **job_id**: 任务 ID
    """
    job = job_storage.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    metadata = job.metadata

    return JobDetailResponse(
        job_id=metadata.job_id,
        status=metadata.status,
        mode=metadata.mode,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
        completed_at=metadata.completed_at,
        template_name=metadata.template_name,
        reference_filename=(
            metadata.reference_video.filename if metadata.reference_video else None
        ),
        distorted_filename=(
            metadata.distorted_video.filename if metadata.distorted_video else None
        ),
        preset=metadata.preset,
        metrics=metadata.metrics,
        command_logs=metadata.command_logs,
        error_message=metadata.error_message,
    )


@router.get("", response_model=List[JobListItem])
async def list_jobs(
    status: Optional[JobStatus] = None,
    limit: Optional[int] = None,
) -> List[JobListItem]:
    """
    列出所有任务

    - **status**: 可选的状态过滤
    - **limit**: 可选的数量限制
    """
    jobs = job_storage.list_jobs(status=status, limit=limit)

    return [
        JobListItem(
            job_id=job.metadata.job_id,
            status=job.metadata.status,
            mode=job.metadata.mode,
            created_at=job.metadata.created_at,
        )
        for job in jobs
    ]


def _unique_destination(directory: Path, filename: str) -> Path:
    safe_name = Path(filename).name
    candidate = directory / safe_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for idx in range(1, 1000):
        attempt = directory / f"{stem}_{idx}{suffix}"
        if not attempt.exists():
            return attempt

    raise RuntimeError(f"Failed to allocate unique filename for {safe_name}")


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _parse_paths_field(value: Optional[str]) -> List[Path]:
    if not value:
        return []
    items: List[Path] = []
    normalized = value.replace(",", "\n")
    for line in normalized.splitlines():
        stripped = line.strip()
        if stripped:
            items.append(Path(stripped).testanduser())
    return items


@router.post(
    "/bitstream",
    response_model=CreateJobResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}},
)
async def create_bitstream_job(
    reference_path: Optional[str] = Form(None),
    encoded_paths: Optional[str] = Form(None),
    reference_file: Optional[UploadFile] = File(None),
    encoded_files: Optional[List[UploadFile]] = File(None),
    width: Optional[int] = Form(None),
    height: Optional[int] = Form(None),
    fps: Optional[float] = Form(None),
) -> CreateJobResponse:
    """
    创建码流分析任务，支持两种方式提供输入：
    - 服务器端路径（运行 uvicorn 的机器上的路径）
    - 通过浏览器上传文件
    """
    ref_path = Path(reference_path).testanduser() if reference_path else None
    enc_path_list = _parse_paths_field(encoded_paths)

    if not reference_file and not ref_path:
        raise HTTPException(status_code=400, detail="必须提供参考视频 reference_file 或 reference_path")

    if not encoded_files and not enc_path_list:
        raise HTTPException(status_code=400, detail="必须提供至少一个编码视频 encoded_files 或 encoded_paths")

    # 解析并校验服务器端路径输入
    if ref_path and (not ref_path.exists() or not ref_path.is_file()):
        raise HTTPException(status_code=400, detail=f"参考视频路径不存在或不是文件: {ref_path}")

    for p in enc_path_list:
        if not p.exists() or not p.is_file():
            raise HTTPException(status_code=400, detail=f"编码视频路径不存在或不是文件: {p}")

    def _is_yuv(name: str) -> bool:
        return Path(name).suffix.lower() == ".yuv"

    has_yuv = False
    if reference_file and reference_file.filename and _is_yuv(reference_file.filename):
        has_yuv = True
    if ref_path and _is_yuv(ref_path.name):
        has_yuv = True
    if encoded_files:
        for f in encoded_files:
            if f.filename and _is_yuv(f.filename):
                has_yuv = True
                break
    if not has_yuv:
        for p in enc_path_list:
            if _is_yuv(p.name):
                has_yuv = True
                break

    if has_yuv and (width is None or height is None or fps is None):
        raise HTTPException(status_code=400, detail="检测到 .yuv 输入，必须填写 width/height/fps")

    async def _read_upload(upload: Optional[UploadFile]) -> Optional[tuple[str, bytes]]:
        """只接受有文件名且非空内容的上传，返回 (filename, content)。"""
        if not upload or not upload.filename:
            return None
        content = await upload.read()
        if not content:
            return None
        return upload.filename, content

    # 读取有效的上传文件（过滤掉空文件或无文件名的部分）
    ref_upload = await _read_upload(reference_file)
    encoded_uploads: List[tuple[str, bytes]] = []
    if encoded_files:
        for upload in encoded_files:
            data = await _read_upload(upload)
            if data:
                encoded_uploads.append(data)

    if not ref_upload and not ref_path:
        raise HTTPException(status_code=400, detail="必须提供参考视频 reference_file 或 reference_path")

    if not encoded_uploads and not enc_path_list:
        raise HTTPException(status_code=400, detail="必须提供至少一个编码视频 encoded_files 或 encoded_paths")

    # 创建任务记录
    job_id = job_storage.generate_job_id()
    metadata = JobMetadata(
        job_id=job_id,
        mode=JobMode.BITSTREAM_ANALYSIS,
        status=JobStatus.PENDING,
        template_name="码流分析",
        rawvideo_width=width,
        rawvideo_height=height,
        rawvideo_fps=fps,
    )
    job = job_storage.create_job(metadata)

    # 保存/引用参考视频
    if ref_upload:
        ref_filename, ref_content = ref_upload
        ref_dest = _unique_destination(job.job_dir, ref_filename or "reference")
        save_uploaded_file(ref_content, ref_dest)
        metadata.reference_video = extract_video_info(ref_dest)
    else:
        # 直接使用原路径，不复制
        metadata.reference_video = extract_video_info(ref_path)

    # 保存/复制编码视频（支持多输入）
    encoded_infos = []

    if encoded_uploads:
        for filename, content in encoded_uploads:
            dest = _unique_destination(job.job_dir, filename or "encoded")
            save_uploaded_file(content, dest)
            encoded_infos.append(extract_video_info(dest))

    for p in enc_path_list:
        # 直接引用原路径
        encoded_infos.append(extract_video_info(p))

    metadata.encoded_videos = encoded_infos

    # 更新元数据
    job_storage.update_job(job)

    return CreateJobResponse(
        job_id=metadata.job_id,
        status=metadata.status,
        mode=metadata.mode,
        created_at=metadata.created_at,
    )


@router.post("/compare", response_model=dict)
async def compare_jobs(job_ids: List[str]) -> dict:
    """
    对比多个任务的质量指标

    - **job_ids**: 任务ID列表（至少2个）
    """
    raise HTTPException(status_code=404, detail="Job comparison is removed")


@router.delete(
    "/{job_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
)
async def delete_job(job_id: str) -> Response:
    """
    删除任务及其相关文件（目录下的所有资源）

    - **job_id**: 任务 ID
    """
    job = job_storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    success = job_storage.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete job resources")

    return Response(status_code=204)
