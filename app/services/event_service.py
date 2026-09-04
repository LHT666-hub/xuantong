"""事件持久化服务。

负责将健康事件写入存储、查询事件、并在 workflow 执行完成后回写处理状态。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.store import InMemoryStore, get_store
from app.utils import normalize_patient_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventService:
    """事件持久化服务。"""

    def __init__(self, db_session: InMemoryStore | None = None) -> None:
        # 兼容签名：db_session 传入则用之，否则回退到全局内存存储单例。
        self.db = db_session or get_store()

    async def create_event(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """持久化事件到存储，返回事件记录。"""
        now = _now_iso()
        event_id = str(event_data.get("id") or uuid4())
        record: dict[str, Any] = {
            "id": event_id,
            "patient_id": normalize_patient_id(event_data.get("patient_id", "")),
            "event_type": event_data.get("event_type", ""),
            "channel": event_data.get("channel", ""),
            "source": event_data.get("source", "") or "",
            "payload": event_data.get("payload") or {},
            "metadata": event_data.get("metadata") or {},
            "occurred_at": event_data.get("occurred_at") or now,
            "received_at": event_data.get("received_at") or now,
            # 处理状态：received → processing → completed / pending_human / failed
            "status": "received",
            "workflow": None,
            "thread_id": None,
            "task_ids": [],
        }
        self.db.events[event_id] = record
        return record

    async def get_event(self, event_id: str) -> dict[str, Any] | None:
        """查询事件。"""
        return self.db.events.get(event_id)

    async def update_event_status(
        self,
        event_id: str,
        status: str,
        workflow_result: dict[str, Any] | None = None,
        task_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """更新事件处理状态（workflow 完成后回写）。"""
        record = self.db.events.get(event_id)
        if record is None:
            return None
        record["status"] = status
        if workflow_result is not None:
            record["workflow"] = workflow_result
            record["thread_id"] = workflow_result.get("thread_id")
        if task_ids is not None:
            record["task_ids"] = task_ids
        record["updated_at"] = _now_iso()
        return record

    async def list_events(
        self, patient_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """按患者查询事件（新→旧）。"""
        events = list(self.db.events.values())
        if patient_id:
            patient_id = normalize_patient_id(patient_id)
            events = [e for e in events if e["patient_id"] == patient_id]
        events.sort(key=lambda e: e.get("received_at", ""), reverse=True)
        return events[:limit]


__all__ = ["EventService"]
