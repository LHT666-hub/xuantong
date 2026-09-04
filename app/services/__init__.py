"""app/services — 玄同服务层（Event / Task / Outcome / Timeline 持久化闭环）。

开发阶段由内存存储（InMemoryStore 单例）承载，后续可平滑迁移到
Supabase / PostgreSQL：仅需替换各服务的 self.db 实现，接口保持不变。
"""

from app.services.store import InMemoryStore, get_store, reset_store
from app.services.event_service import EventService
from app.services.task_service import TaskService
from app.services.outcome_service import OutcomeService, OUTCOME_TYPES
from app.services.timeline_service import TimelineService

__all__ = [
    "InMemoryStore",
    "get_store",
    "reset_store",
    "EventService",
    "TaskService",
    "OutcomeService",
    "OUTCOME_TYPES",
    "TimelineService",
]
