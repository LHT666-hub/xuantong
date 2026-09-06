"""服务结果持久化服务（数据库实现）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outcome import ServiceOutcome
from app.utils import normalize_patient_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DbOutcomeService:
    """基于数据库的服务结果记录服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_outcome(
        self,
        task_id: str,
        outcome_type: str,
        notes: str = "",
        measured_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录服务结果。"""
        # 从任务中获取 patient_id 和 event_id（需要查询任务）
        from app.models.task import Task

        try:
            task_uuid = UUID(task_id)
        except ValueError:
            task_uuid = None

        patient_id = uuid4()  # 默认
        event_id = uuid4()  # 默认

        if task_uuid:
            result = await self.db.execute(
                select(Task).where(Task.id == task_uuid)
            )
            task = result.scalar_one_or_none()
            if task:
                patient_id = task.patient_id
                event_id = task.event_id or uuid4()

        # 规范化 patient_id
        patient_id = UUID(normalize_patient_id(str(patient_id)))

        outcome = ServiceOutcome(
            id=uuid4(),
            patient_id=patient_id,
            event_id=event_id,
            task_id=task_uuid or uuid4(),
            outcome_type=outcome_type,
            handled_by=measured_by or "",
            summary=notes or "",
            structured_result=metadata or {},
            occurred_at=datetime.now(timezone.utc),
        )
        self.db.add(outcome)
        await self.db.flush()
        await self.db.refresh(outcome)

        return self._to_dict(outcome)

    async def get_outcome(self, outcome_id: str) -> dict[str, Any] | None:
        """查询单个结果。"""
        try:
            outcome_uuid = UUID(outcome_id)
        except ValueError:
            return None

        result = await self.db.execute(
            select(ServiceOutcome).where(ServiceOutcome.id == outcome_uuid)
        )
        outcome = result.scalar_one_or_none()
        if outcome is None:
            return None
        return self._to_dict(outcome)

    async def get_outcomes_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """查询某任务的所有结果（新→旧）。"""
        try:
            task_uuid = UUID(task_id)
        except ValueError:
            return []

        result = await self.db.execute(
            select(ServiceOutcome)
            .where(ServiceOutcome.task_id == task_uuid)
            .order_by(ServiceOutcome.occurred_at.desc())
        )
        outcomes = result.scalars().all()
        return [self._to_dict(o) for o in outcomes]

    async def get_outcomes_for_patient(
        self, patient_id: str
    ) -> list[dict[str, Any]]:
        """查询患者的所有服务结果（新→旧）。"""
        patient_uuid = UUID(normalize_patient_id(patient_id))

        result = await self.db.execute(
            select(ServiceOutcome)
            .where(ServiceOutcome.patient_id == patient_uuid)
            .order_by(ServiceOutcome.occurred_at.desc())
        )
        outcomes = result.scalars().all()
        return [self._to_dict(o) for o in outcomes]

    async def list_all_outcomes(
        self, page: int = 1, size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        """全量分页查询服务结果（创建时间倒序）。

        用于 ``GET /api/outcomes`` 在 patient_id / task_id 均缺省时的列表返回，
        此前该分支恒返回空数组。返回 (rows, total)。
        """
        page = max(1, page)
        size = max(1, min(size, 200))

        total = (
            await self.db.execute(
                select(func.count()).select_from(ServiceOutcome)
            )
        ).scalar() or 0

        result = await self.db.execute(
            select(ServiceOutcome)
            .order_by(ServiceOutcome.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        outcomes = result.scalars().all()
        return [self._to_dict(o) for o in outcomes], int(total)

    def _to_dict(self, outcome: ServiceOutcome) -> dict[str, Any]:
        """将 ORM 对象转换为 dict。"""
        return {
            "id": str(outcome.id),
            "task_id": str(outcome.task_id),
            "patient_id": str(outcome.patient_id),
            "event_id": str(outcome.event_id) if outcome.event_id else None,
            "outcome_type": outcome.outcome_type,
            "notes": outcome.summary or "",
            "measured_by": outcome.handled_by or "",
            "measured_at": outcome.occurred_at.isoformat() if outcome.occurred_at else None,
            "metadata": outcome.structured_result or {},
        }


__all__ = ["DbOutcomeService"]
