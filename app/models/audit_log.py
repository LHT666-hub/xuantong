"""审计日志模型。"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, JsonColumn


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    actor_type: Mapped[str] = mapped_column(
        sa.String(20)
    )  # agent / user / system
    actor_id: Mapped[str] = mapped_column(sa.String(100))
    action: Mapped[str] = mapped_column(sa.String(100))
    resource_type: Mapped[str | None] = mapped_column(
        sa.String(50), nullable=True
    )
    resource_id: Mapped[str | None] = mapped_column(
        sa.String(100), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JsonColumn, default=dict, server_default="{}"
    )
