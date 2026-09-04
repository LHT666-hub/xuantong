"""服务结果模型。"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, JsonColumn


class ServiceOutcome(TimestampMixin, Base):
    __tablename__ = "service_outcomes"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    event_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("events.id")
    )
    task_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("tasks.id")
    )
    outcome_type: Mapped[str] = mapped_column(sa.String(100))
    handled_by: Mapped[str] = mapped_column(sa.String(200))
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    structured_result: Mapped[dict] = mapped_column(
        JsonColumn, default=dict, server_default="{}"
    )
    next_action: Mapped[str | None] = mapped_column(
        sa.String(200), nullable=True
    )
    followup_required: Mapped[bool] = mapped_column(
        sa.Boolean, default=False
    )
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="service_outcomes")
    event = relationship("Event", back_populates="service_outcomes")
    task = relationship("Task", back_populates="service_outcomes")
