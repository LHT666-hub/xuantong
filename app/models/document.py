"""文档元数据模型 —— changxi 前端上传的报告/图片/处方等文档。

此前文档元数据由进程内单例 ``app.api.routes.documents._DOCUMENTS`` 承载，
服务重启即全部丢失。本模型将其落库，保证 iOS 端上传的文档在后端重启后依然存在。

字段与 ``POST /api/v1/documents`` 的响应契约逐字对应：
``document_id / id / patient_id / doc_type / file_name / file_size /
content_type / storage_path / created_at``。

注意：``patient_id`` 采用字符串而非 UUID 外键——文档上传接口接受任意业务侧
患者标识（如 ``p-doc-001``），与 patients 主数据表解耦，避免外键约束阻断上传。
"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Document(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    patient_id: Mapped[str] = mapped_column(sa.String(128), index=True)
    doc_type: Mapped[str] = mapped_column(
        sa.String(50), default="general", server_default="general"
    )
    file_name: Mapped[str] = mapped_column(sa.String(512))
    file_size: Mapped[int] = mapped_column(sa.BigInteger, default=0, server_default="0")
    content_type: Mapped[str] = mapped_column(
        sa.String(255), default="application/octet-stream",
        server_default="application/octet-stream",
    )
    storage_path: Mapped[str] = mapped_column(sa.String(1024))


__all__ = ["Document"]
