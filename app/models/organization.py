"""组织机构模型。"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, JsonColumn


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(sa.String(200))
    org_type: Mapped[str] = mapped_column(sa.String(50))
    settings: Mapped[dict] = mapped_column(
        JsonColumn, default=dict, server_default="{}"
    )

    # ── relationships ──────────────────────────────────────────────
    teams = relationship("Team", back_populates="organization")
    patients = relationship("Patient", back_populates="organization")
    care_teams = relationship("CareTeam", back_populates="organization")
