"""数据库基础模型与跨数据库 JSON 类型。

提供 Base 声明基类、时间戳/软删除 Mixin，以及自动适配 PostgreSQL / SQLite 的
JSON 列类型（PostgreSQL 使用原生 JSONB，其他数据库使用标准 JSON）。
"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator
from datetime import datetime
from uuid import UUID, uuid4
import sqlalchemy as sa


# ── 跨数据库 JSON 类型 ─────────────────────────────────────────────────────
# PostgreSQL 使用原生 JSONB（支持索引和高效查询），其他数据库使用标准 JSON。
class JsonType(TypeDecorator):
    """跨数据库 JSON 类型：PostgreSQL → JSONB，其他 → JSON。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


# 便捷别名，可在模型中直接使用
JsonColumn = JsonType


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, default=None
    )
