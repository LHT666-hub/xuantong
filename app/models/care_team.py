"""家庭医生团队模型。"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class CareTeam(TimestampMixin, Base):
    """真实家庭医生团队。"""

    __tablename__ = "care_teams"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    org_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("organizations.id"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # ── relationships ──────────────────────────────────────────────
    organization = relationship("Organization", back_populates="care_teams")
    members = relationship("CareTeamMember", back_populates="care_team")
    patient_assignments = relationship(
        "PatientTeamAssignment", back_populates="care_team"
    )


class CareTeamMember(TimestampMixin, Base):
    """团队成员。"""

    __tablename__ = "care_team_members"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    care_team_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("care_teams.id"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("users.id"), index=True
    )
    role: Mapped[str] = mapped_column(
        sa.String(50)
    )  # doctor / nurse / public_health_worker
    display_name: Mapped[str] = mapped_column(sa.String(100))

    # ── relationships ──────────────────────────────────────────────
    care_team = relationship("CareTeam", back_populates="members")
    user = relationship("User")


class PatientTeamAssignment(TimestampMixin, Base):
    """患者签约 / 分配到团队。"""

    __tablename__ = "patient_team_assignments"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    patient_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("patients.id"), index=True
    )
    care_team_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("care_teams.id"), index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    # ── relationships ──────────────────────────────────────────────
    patient = relationship("Patient", back_populates="care_team_assignments")
    care_team = relationship("CareTeam", back_populates="patient_assignments")
