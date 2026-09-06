"""文档元数据持久化服务（数据库实现）。

提供文档的创建 / 分页查询 / 单条查询 / 软删除，遵循现有 db service 模式
（构造时注入 AsyncSession，方法内 flush，由调用方负责 commit）。

``_to_dict`` 输出严格对齐 ``POST/GET /api/v1/documents`` 的响应契约：
``document_id / id / patient_id / doc_type / file_name / file_size /
content_type / storage_path / created_at``（不增不减，保证 iOS 端解码稳定）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_uuid(value: Any) -> UUID | None:
    """尽力将输入解析为 UUID，失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


class DbDocumentService:
    """基于数据库的文档元数据服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_document(
        self,
        *,
        patient_id: str,
        doc_type: str,
        file_name: str,
        file_size: int,
        content_type: str,
        storage_path: str,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """登记一条文档元数据。

        ``document_id`` 可由调用方预先生成（与对象存储路径保持一致），
        缺省时自动生成新的 UUID。
        """
        doc_uuid = _parse_uuid(document_id) or uuid4()
        document = Document(
            id=doc_uuid,
            patient_id=patient_id,
            doc_type=doc_type or "general",
            file_name=file_name,
            file_size=int(file_size or 0),
            content_type=content_type or "application/octet-stream",
            storage_path=storage_path,
        )
        self.db.add(document)
        await self.db.flush()
        await self.db.refresh(document)
        return self._to_dict(document)

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        """获取单个未删除文档。"""
        doc_uuid = _parse_uuid(document_id)
        if doc_uuid is None:
            return None

        result = await self.db.execute(
            select(Document).where(
                Document.id == doc_uuid, Document.deleted_at.is_(None)
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            return None
        return self._to_dict(document)

    async def list_documents(
        self,
        patient_id: str,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """按患者分页列出文档（排除软删除，创建时间倒序）。"""
        page = max(1, page)
        size = max(1, min(size, 100))

        conditions = [
            Document.deleted_at.is_(None),
            Document.patient_id == patient_id,
        ]

        count_query = select(func.count()).select_from(Document).where(*conditions)
        total = (await self.db.execute(count_query)).scalar() or 0

        query = (
            select(Document)
            .where(*conditions)
            .order_by(Document.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        documents = (await self.db.execute(query)).scalars().all()
        return [self._to_dict(d) for d in documents], int(total)

    async def delete_document(self, document_id: str) -> bool:
        """软删除文档（标记 deleted_at）。返回是否命中记录。"""
        doc_uuid = _parse_uuid(document_id)
        if doc_uuid is None:
            return False

        result = await self.db.execute(
            select(Document).where(
                Document.id == doc_uuid, Document.deleted_at.is_(None)
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            return False

        document.deleted_at = _now()
        await self.db.flush()
        return True

    def _to_dict(self, document: Document) -> dict[str, Any]:
        """将 ORM 对象转换为响应契约 dict（字段逐字对齐内存实现）。"""
        doc_id = str(document.id)
        return {
            "document_id": doc_id,
            "id": doc_id,
            "patient_id": document.patient_id,
            "doc_type": document.doc_type,
            "file_name": document.file_name,
            "file_size": document.file_size,
            "content_type": document.content_type,
            "storage_path": document.storage_path,
            "created_at": document.created_at.isoformat() if document.created_at else None,
        }


__all__ = ["DbDocumentService"]
