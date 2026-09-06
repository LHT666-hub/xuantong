"""对话消息模型。

changxi 前端会话消息持久化。会话（session）为逻辑分组，消息按 session_id
聚合，role 取值 user / assistant / system。
"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, JsonColumn


class ChatMessage(TimestampMixin, Base):
    # created_at / updated_at 由 TimestampMixin 提供
    __tablename__ = "chat_messages"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(sa.Uuid, index=True)
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    role: Mapped[str] = mapped_column(sa.String(20))
    content: Mapped[str] = mapped_column(sa.Text)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JsonColumn, default=dict, server_default="{}"
    )


__all__ = ["ChatMessage"]
