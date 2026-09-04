"""患者模型。"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, JsonColumn


class Patient(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "patients"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id"), unique=True
    )
    org_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(100))
    age: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(sa.String(10), nullable=True)
    chronic_diseases: Mapped[list] = mapped_column(
        JsonColumn, default=list, server_default="[]"
    )
    allergies: Mapped[list] = mapped_column(
        JsonColumn, default=list, server_default="[]"
    )
    current_medications: Mapped[list] = mapped_column(
        JsonColumn, default=list, server_default="[]"
    )
    risk_level: Mapped[str] = mapped_column(
        sa.String(20), default="green", server_default="green"
    )

    # ── relationships ──────────────────────────────────────────────
    user = relationship("User", back_populates="patient_profile")
    organization = relationship("Organization", back_populates="patients")
    health_records = relationship("HealthRecord", back_populates="patient")
    measurements = relationship("Measurement", back_populates="patient")
    medications = relationship("Medication", back_populates="patient")
    events = relationship("Event", back_populates="patient")
    tasks = relationship("Task", back_populates="patient")
    service_outcomes = relationship("ServiceOutcome", back_populates="patient")
    followups = relationship("Followup", back_populates="patient")
    agent_runs = relationship("AgentRun", back_populates="patient")
    workflow_runs = relationship("WorkflowRun", back_populates="patient")
    care_team_assignments = relationship(
        "PatientTeamAssignment", back_populates="patient"
    )
