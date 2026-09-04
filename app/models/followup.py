"""随访模型。"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Followup(TimestampMixin, Base):
    __tablename__ = "followups"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("tasks.id"), nullable=True
    )
    followup_type: Mapped[str] = mapped_column(sa.String(50))
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(30), default="pending", server_default="pending"
    )
    due_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="followups")
    task = relationship("Task", back_populates="followups")
