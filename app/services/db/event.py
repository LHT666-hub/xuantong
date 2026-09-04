"""事件持久化服务（数据库实现）。

使用 SQLAlchemy AsyncSession 将健康事件写入数据库。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.utils import normalize_patient_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DbEventService:
    """基于数据库的事件持久化服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_event(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """持久化事件到数据库，返回事件记录（dict）。"""
        now = datetime.now(timezone.utc)
        event_id = event_data.get("id") or str(uuid4())

        # 规范化 patient_id 为确定性 UUID
        patient_id = normalize_patient_id(event_data.get("patient_id", ""))

        event = Event(
            id=UUID(event_id) if isinstance(event_id, str) else event_id,
            patient_id=patient_id,
            tenant_id=uuid4(),  # 临时租户 ID
            organization_id=uuid4(),  # 临时组织 ID
            event_type=event_data.get("event_type", ""),
            channel=event_data.get("channel", ""),
            source=event_data.get("source", "") or "",
            payload=event_data.get("payload") or {},
            metadata_=event_data.get("metadata") or {},
            occurred_at=datetime.fromisoformat(event_data.get("occurred_at") or now.isoformat()),
            received_at=now,
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)

        return self._to_dict(event)

    async def get_event(self, event_id: str) -> dict[str, Any] | None:
        """查询事件。"""
        try:
            event_uuid = UUID(event_id)
        except ValueError:
            return None

        result = await self.db.execute(
            select(Event).where(Event.id == event_uuid)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return None
        return self._to_dict(event)

    async def update_event_status(
        self,
        event_id: str,
        status: str,
        workflow_result: dict[str, Any] | None = None,
        task_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """更新事件处理状态（workflow 完成后回写）。"""
        try:
            event_uuid = UUID(event_id)
        except ValueError:
            return None

        result = await self.db.execute(
            select(Event).where(Event.id == event_uuid)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return None

        # 更新状态和工作流结果（存储在 metadata 中）
        metadata = event.metadata_ or {}
        metadata["status"] = status
        if workflow_result is not None:
            metadata["workflow"] = workflow_result
            metadata["thread_id"] = workflow_result.get("thread_id")
        if task_ids is not None:
            metadata["task_ids"] = task_ids
        metadata["updated_at"] = _now_iso()

        event.metadata_ = metadata
        await self.db.flush()
        await self.db.refresh(event)

        return self._to_dict(event)

    async def list_events(
        self, patient_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """按患者查询事件（新→旧）。"""
        query = select(Event).order_by(Event.received_at.desc())

        if patient_id:
            patient_uuid = UUID(normalize_patient_id(patient_id))
            query = query.where(Event.patient_id == patient_uuid)

        query = query.limit(limit)
        result = await self.db.execute(query)
        events = result.scalars().all()
        return [self._to_dict(e) for e in events]

    def _to_dict(self, event: Event) -> dict[str, Any]:
        """将 ORM 对象转换为 dict（与 InMemoryStore 格式一致）。"""
        metadata = event.metadata_ or {}
        return {
            "id": str(event.id),
            "patient_id": str(event.patient_id),
            "event_type": event.event_type,
            "channel": event.channel,
            "source": event.source or "",
            "payload": event.payload or {},
            "metadata": metadata,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "received_at": event.received_at.isoformat() if event.received_at else None,
            "status": metadata.get("status", "received"),
            "workflow": metadata.get("workflow"),
            "thread_id": metadata.get("thread_id"),
            "task_ids": metadata.get("task_ids", []),
        }


__all__ = ["DbEventService"]
