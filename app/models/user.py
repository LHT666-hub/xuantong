"""用户模型。"""

from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    username: Mapped[str] = mapped_column(
        sa.String(60), unique=True, index=True
    )
    email: Mapped[str] = mapped_column(
        sa.String(255), unique=True, index=True
    )
    hashed_password: Mapped[str] = mapped_column(sa.String(255))
    role: Mapped[str] = mapped_column(
        sa.String(20), index=True
    )  # patient / doctor / nurse / admin
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, default=True
    )

    # ── relationships ──────────────────────────────────────────────
    patient_profile = relationship(
        "Patient", back_populates="user", uselist=False
    )
