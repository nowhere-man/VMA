"""
模板存储服务

负责模板元数据的持久化和检索（使用文件系统 + JSON）
"""
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from nanoid import generate

from src.config import settings
from src.models.template import EncodingTemplate, EncodingTemplateMetadata, TemplateType


class TemplateStorage:
    """转码模板存储服务"""

    def __init__(self, root_dir: Optional[Path] = None):
        """
        初始化模板存储服务

        Args:
            root_dir: 模板根目录，默认使用 templates_root_dir（不再放在 jobs 下）
        """
        self.root_dir = root_dir or settings.templates_root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def create_template(self, metadata: EncodingTemplateMetadata) -> EncodingTemplate:
        """
        创建新模板

        Args:
            metadata: 模板元数据

        Returns:
            EncodingTemplate: 创建的模板对象

        Raises:
            ValueError: 如果模板 ID 已存在
        """
        template_dir = self.root_dir / metadata.template_id

        if template_dir.exists():
            raise ValueError(f"Template {metadata.template_id} already exists")

        # 创建模板目录
        template_dir.mkdir(parents=True, exist_ok=True)

        # 保存元数据
        template = EncodingTemplate(metadata=metadata, template_dir=template_dir)
        self._save_metadata(template)

        return template

    def get_template(self, template_id: str) -> Optional[EncodingTemplate]:
        """
        获取模板

        Args:
            template_id: 模板 ID

        Returns:
            EncodingTemplate 对象，如果不存在则返回 None
        """
        template_dir = self.root_dir / template_id

        if not template_dir.exists():
            return None

        metadata_path = template_dir / "template.json"
        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata_dict = json.load(f)
                metadata = EncodingTemplateMetadata.model_validate(metadata_dict, context={"skip_path_check": True})
                return EncodingTemplate(metadata=metadata, template_dir=template_dir)
        except Exception:
            return None

    def update_template(self, template: EncodingTemplate) -> None:
        """
        更新模板元数据

        Args:
            template: 模板对象
        """
        template.metadata.updated_at = datetime.utcnow()
        self._save_metadata(template)

    def list_templates(
        self,
        limit: Optional[int] = None,
        template_type: Optional[TemplateType] = None,
    ) -> List[EncodingTemplate]:
        """
        列出所有模板

        Args:
            encoder_type: 可选的编码器类型过滤
            limit: 可选的数量限制
            template_type: 可选的模板类型过滤

        Returns:
            模板列表，按创建时间倒序排列
        """
        templates: List[EncodingTemplate] = []

        if not self.root_dir.exists():
            return templates

        for template_dir in self.root_dir.iterdir():
            if not template_dir.is_dir():
                continue

            metadata_path = template_dir / "template.json"
            if not metadata_path.exists():
                continue

            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata_dict = json.load(f)
                    metadata = EncodingTemplateMetadata(**metadata_dict)

                    if template_type is None or metadata.template_type == template_type:
                        templates.append(
                            EncodingTemplate(metadata=metadata, template_dir=template_dir)
                        )
            except Exception:
                # 跳过无效的元数据文件
                continue

        # 按创建时间倒序排列
        templates.sort(key=lambda t: t.metadata.created_at, reverse=True)

        # 应用数量限制
        if limit:
            templates = templates[:limit]

        return templates

    def delete_template(self, template_id: str) -> bool:
        """
        删除模板及其所有文件

        Args:
            template_id: 模板 ID

        Returns:
            是否成功删除
        """
        template_dir = self.root_dir / template_id

        if not template_dir.exists():
            return False

        try:
            import shutil

            shutil.rmtree(template_dir)
            return True
        except Exception:
            return False

    def copy_template(self, template_id: str) -> Optional[EncodingTemplate]:
        """
        复制模板

        Args:
            template_id: 源模板 ID

        Returns:
            新创建的 EncodingTemplate 对象，如果源模板不存在则返回 None
        """
        source_template = self.get_template(template_id)
        if not source_template:
            return None

        # 生成新的模板 ID
        new_template_id = self.generate_template_id()

        # 复制元数据并修改
        source_metadata = source_template.metadata
        new_metadata = EncodingTemplateMetadata(
            template_id=new_template_id,
            name=f"{source_metadata.name} copy",
            description=source_metadata.description,
            template_type=source_metadata.template_type,
            anchor=source_metadata.anchor.model_copy(deep=True),
            test=source_metadata.test.model_copy(deep=True) if source_metadata.test else None,
            anchor_computed=False,  # 复制的模板需要重新计算
            anchor_fingerprint=source_metadata.anchor_fingerprint,
        )

        # 创建新模板
        return self.create_template(new_metadata)

    def generate_template_id(self) -> str:
        """
        生成唯一的模板 ID

        Returns:
            12 字符的 nanoid
        """
        return generate(size=12)

    def _save_metadata(self, template: EncodingTemplate) -> None:
        """
        保存模板元数据到 JSON 文件

        Args:
            template: 模板对象
        """
        metadata_path = template.get_metadata_path()

        with open(metadata_path, "w", encoding="utf-8") as f:
            metadata_dict = template.metadata.model_dump(mode="json")
            json.dump(metadata_dict, f, ensure_ascii=False)


# 全局单例
template_storage = TemplateStorage()
