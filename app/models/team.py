"""团队模型（组织下的团队，如科室）。"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    org_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id")
    )
    name: Mapped[str] = mapped_column(sa.String(200))
    team_type: Mapped[str] = mapped_column(sa.String(50))

    # ── relationships ──────────────────────────────────────────────
    organization = relationship("Organization", back_populates="teams")
