"""任务模型。"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, JsonColumn


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    event_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("events.id"), nullable=True, index=True
    )
    title: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    task_type: Mapped[str] = mapped_column(sa.String(100))
    status: Mapped[str] = mapped_column(
        sa.String(30), default="pending", server_default="pending", index=True
    )
    priority: Mapped[str] = mapped_column(
        sa.String(20), default="normal", server_default="normal"
    )
    assignee_type: Mapped[str | None] = mapped_column(
        sa.String(20), nullable=True
    )  # agent / human / team / patient / family
    assignee_role: Mapped[str | None] = mapped_column(
        sa.String(50), nullable=True
    )  # nurse / pharmacist / doctor / ...
    assignee_id: Mapped[str | None] = mapped_column(
        sa.String(100), nullable=True
    )
    human_owner_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, nullable=True, index=True
    )
    team_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("care_teams.id"), nullable=True
    )
    result: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="tasks")
    event = relationship("Event", back_populates="tasks")
    team = relationship("CareTeam")
    service_outcomes = relationship("ServiceOutcome", back_populates="task")
    followups = relationship("Followup", back_populates="task")
