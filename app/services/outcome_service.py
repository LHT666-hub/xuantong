"""服务结果（ServiceOutcome）记录服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.store import InMemoryStore, get_store
from app.utils import normalize_patient_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# 合法的结果类型
OUTCOME_TYPES = {"resolved", "escalated", "pending", "cancelled"}


class OutcomeService:
    """服务结果记录。"""

    def __init__(self, db_session: InMemoryStore | None = None) -> None:
        self.db = db_session or get_store()

    async def record_outcome(
        self,
        task_id: str,
        outcome_type: str,
        notes: str = "",
        measured_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录服务结果。

        outcome_type: resolved / escalated / pending / cancelled。
        patient_id / event_id 从关联任务回填，便于按患者聚合查询。
        """
        task = self.db.tasks.get(task_id) or {}
        record: dict[str, Any] = {
            "id": str(uuid4()),
            "task_id": task_id,
            "patient_id": task.get("patient_id", ""),
            "event_id": task.get("event_id"),
            "outcome_type": outcome_type,
            "notes": notes or "",
            "measured_by": measured_by or "",
            "measured_at": _now_iso(),
            "metadata": metadata or {},
        }
        self.db.outcomes[record["id"]] = record
        return record

    async def get_outcome(self, outcome_id: str) -> dict[str, Any] | None:
        return self.db.outcomes.get(outcome_id)

    async def get_outcomes_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """查询某任务的所有结果（新→旧）。"""
        rows = [o for o in self.db.outcomes.values() if o["task_id"] == task_id]
        rows.sort(key=lambda o: o.get("measured_at", ""), reverse=True)
        return rows

    async def get_outcomes_for_patient(
        self, patient_id: str
    ) -> list[dict[str, Any]]:
        """查询患者的所有服务结果（新→旧）。"""
        patient_id = normalize_patient_id(patient_id)
        rows = [o for o in self.db.outcomes.values() if o["patient_id"] == patient_id]
        rows.sort(key=lambda o: o.get("measured_at", ""), reverse=True)
        return rows


__all__ = ["OutcomeService", "OUTCOME_TYPES"]
