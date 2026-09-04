"""患者用药记录模型。"""

from datetime import date
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Medication(TimestampMixin, Base):
    __tablename__ = "medications"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    drug_name: Mapped[str] = mapped_column(sa.String(200))
    dosage: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    frequency: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    start_date: Mapped[date] = mapped_column(sa.Date)
    end_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    prescribed_by: Mapped[str | None] = mapped_column(
        sa.String(200), nullable=True
    )

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="medications")
