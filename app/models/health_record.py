"""健康记录模型。"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, JsonColumn


class HealthRecord(TimestampMixin, Base):
    __tablename__ = "health_records"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    record_type: Mapped[str] = mapped_column(
        sa.String(50)
    )  # visit / lab / imaging
    title: Mapped[str] = mapped_column(sa.String(500))
    content: Mapped[dict] = mapped_column(
        JsonColumn, default=dict, server_default="{}"
    )
    source: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="health_records")
