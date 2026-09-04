"""患者时间线模型。

沉淀 Event → Workflow → Task → Outcome 全链路关键节点，供按患者回溯。
"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, JsonColumn


class TimelineEntry(TimestampMixin, Base):
    __tablename__ = "timeline_entries"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    # event_received / risk_assessed / consultation_complete / action_planned /
    # tasks_created / execution_started / task_completed / outcome_recorded
    entry_type: Mapped[str] = mapped_column(sa.String(50), index=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # 关联的 event_id / task_id / outcome_id（跨类型，故不强约束外键）
    related_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JsonColumn, default=dict, server_default="{}"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


__all__ = ["TimelineEntry"]
