"""体征测量模型。"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Measurement(TimestampMixin, Base):
    __tablename__ = "measurements"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    measurement_type: Mapped[str] = mapped_column(
        sa.String(50), index=True
    )  # blood_pressure / blood_glucose / heart_rate / weight / temperature
    value: Mapped[float] = mapped_column(sa.Float)
    secondary_value: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )
    unit: Mapped[str] = mapped_column(sa.String(20))
    measured_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), index=True
    )

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="measurements")
