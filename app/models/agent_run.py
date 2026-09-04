"""智能体运行记录模型。"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, JsonColumn


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    agent_role: Mapped[str] = mapped_column(sa.String(50))
    input_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    tokens_used: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default="0"
    )
    duration_ms: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(sa.String(30))
    flow_log: Mapped[list] = mapped_column(
        JsonColumn, default=list, server_default="[]"
    )

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="agent_runs")
