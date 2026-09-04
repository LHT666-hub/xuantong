"""工作流运行记录模型。"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, JsonColumn


class WorkflowRun(TimestampMixin, Base):
    __tablename__ = "workflow_runs"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    workflow_name: Mapped[str] = mapped_column(sa.String(100))
    status: Mapped[str] = mapped_column(sa.String(30))
    steps_completed: Mapped[list] = mapped_column(
        JsonColumn, default=list, server_default="[]"
    )
    result_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    result_data: Mapped[dict] = mapped_column(
        JsonColumn, default=dict, server_default="{}"
    )

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="workflow_runs")
