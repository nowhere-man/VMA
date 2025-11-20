"""
任务存储服务

负责任务元数据的持久化和检索（使用文件系统 + JSON）
"""
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from nanoid import generate

from src.config import settings
from src.models import Job, JobMetadata, JobStatus


class JobStorage:
    """任务存储服务"""

    def __init__(self, root_dir: Optional[Path] = None):
        """
        初始化任务存储服务

        Args:
            root_dir: 任务根目录，默认使用配置中的 jobs_root_dir
        """
        self.root_dir = root_dir or settings.jobs_root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, metadata: JobMetadata) -> Job:
        """
        创建新任务

        Args:
            metadata: 任务元数据

        Returns:
            Job: 创建的任务对象

        Raises:
            ValueError: 如果任务 ID 已存在
        """
        job_dir = self.root_dir / metadata.job_id

        if job_dir.exists():
            raise ValueError(f"Job {metadata.job_id} already exists")

        # 创建任务目录
        job_dir.mkdir(parents=True, exist_ok=True)

        # 保存元数据
        job = Job(metadata=metadata, job_dir=job_dir)
        self._save_metadata(job)

        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """
        获取任务

        Args:
            job_id: 任务 ID

        Returns:
            Job 对象，如果不存在则返回 None
        """
        job_dir = self.root_dir / job_id

        if not job_dir.exists():
            return None

        metadata_path = job_dir / "metadata.json"
        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata_dict = json.load(f)
                metadata = JobMetadata(**metadata_dict)
                return Job(metadata=metadata, job_dir=job_dir)
        except Exception:
            return None

    def update_job(self, job: Job) -> None:
        """
        更新任务元数据

        Args:
            job: 任务对象
        """
        job.metadata.updated_at = datetime.utcnow()
        self._save_metadata(job)

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: Optional[int] = None,
    ) -> List[Job]:
        """
        列出所有任务

        Args:
            status: 可选的状态过滤
            limit: 可选的数量限制

        Returns:
            任务列表，按创建时间倒序排列
        """
        jobs: List[Job] = []

        # 遍历所有子目录
        if not self.root_dir.exists():
            return jobs

        for job_dir in self.root_dir.iterdir():
            if not job_dir.is_dir():
                continue

            metadata_path = job_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata_dict = json.load(f)
                    metadata = JobMetadata(**metadata_dict)

                    # 状态过滤
                    if status and metadata.status != status:
                        continue

                    jobs.append(Job(metadata=metadata, job_dir=job_dir))
            except Exception:
                # 跳过无效的元数据文件
                continue

        # 按创建时间倒序排列
        jobs.sort(key=lambda j: j.metadata.created_at, reverse=True)

        # 应用数量限制
        if limit:
            jobs = jobs[:limit]

        return jobs

    def delete_job(self, job_id: str) -> bool:
        """
        删除任务及其所有文件

        Args:
            job_id: 任务 ID

        Returns:
            是否成功删除
        """
        job_dir = self.root_dir / job_id

        if not job_dir.exists():
            return False

        try:
            # 删除任务目录及其所有内容
            import shutil

            shutil.rmtree(job_dir)
            return True
        except Exception:
            return False

    def generate_job_id(self) -> str:
        """
        生成唯一的任务 ID

        Returns:
            12 字符的 nanoid
        """
        return generate(size=12)

    def _save_metadata(self, job: Job) -> None:
        """
        保存任务元数据到 JSON 文件

        Args:
            job: 任务对象
        """
        metadata_path = job.get_metadata_path()

        with open(metadata_path, "w", encoding="utf-8") as f:
            # 使用 Pydantic 的 model_dump 方法序列化
            metadata_dict = job.metadata.model_dump(mode="json")
            json.dump(metadata_dict, f, ensure_ascii=False, indent=2)


# 全局单例
job_storage = JobStorage()
