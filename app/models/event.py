"""事件模型。"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, JsonColumn


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(sa.Uuid, index=True)
    organization_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(sa.String(100), index=True)
    source: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    channel: Mapped[str | None] = mapped_column(sa.String(30), nullable=True)
    payload: Mapped[dict] = mapped_column(
        JsonColumn, default=dict, server_default="{}"
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JsonColumn, default=dict, server_default="{}"
    )
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="events")
    organization = relationship("Organization")
    tasks = relationship("Task", back_populates="event")
    service_outcomes = relationship("ServiceOutcome", back_populates="event")
