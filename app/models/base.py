"""公共模型基类 —— 重新导出，方便其他模型统一导入。"""

from app.database.base import Base, TimestampMixin, SoftDeleteMixin, JsonColumn

__all__ = ["Base", "TimestampMixin", "SoftDeleteMixin", "JsonColumn"]
