"""任务管理持久化服务（数据库实现）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.services.db.outcome import DbOutcomeService
from app.services.db.timeline import DbTimelineService
from app.utils import normalize_patient_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# task_type → 中文标题
_TASK_TYPE_TITLES: dict[str, str] = {
    "followup": "随访跟进",
    "monitoring": "指标监测",
    "medication_review": "用药复核",
    "referral": "转诊建议",
    "education": "健康教育",
    "alert": "预警提醒",
}


class DbTaskService:
    """基于数据库的任务管理服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.outcomes = DbOutcomeService(db)
        self.timeline = DbTimelineService(db)

    async def create_tasks_from_workflow(
        self,
        event_id: str,
        patient_id: str,
        action_plan: Any = None,
        generated_tasks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """从 workflow 结果创建任务记录。"""
        created: list[dict[str, Any]] = []
        now = _now()

        source_tasks: list[dict[str, Any]] = []
        for gt in generated_tasks or []:
            if isinstance(gt, dict):
                source_tasks.append(gt)

        # 回退：无 generated_tasks 时从 action_plan.actions 构造
        if not source_tasks and action_plan is not None:
            for item in getattr(action_plan, "actions", []) or []:
                source_tasks.append(
                    {
                        "task_type": getattr(item, "type", "followup"),
                        "description": getattr(item, "description", ""),
                        "assignee_role": getattr(item, "assignee_role", "assistant"),
                        "priority": getattr(item, "priority", "medium"),
                        "deadline_hours": getattr(item, "deadline_hours", None),
                        "status": "pending",
                    }
                )

        try:
            event_uuid = UUID(event_id) if event_id else None
        except ValueError:
            event_uuid = None
        patient_uuid = UUID(normalize_patient_id(patient_id))

        for gt in source_tasks:
            task_id = str(gt.get("id") or f"task-{uuid4().hex[:12]}")
            task_type = str(gt.get("task_type") or "followup")
            role = gt.get("assignee_role") or "assistant"
            deadline_hours = gt.get("deadline_hours")
            deadline = (
                (now + timedelta(hours=float(deadline_hours)))
                if deadline_hours
                else None
            )

            task = Task(
                id=UUID(task_id) if len(task_id) == 36 else uuid4(),
                patient_id=patient_uuid,
                event_id=event_uuid,
                task_type=task_type,
                title=_TASK_TYPE_TITLES.get(task_type, task_type),
                description=gt.get("description", "") or "",
                status=gt.get("status") or "pending",
                priority=gt.get("priority") or "medium",
                assignee_type="human" if str(role).startswith("human") else "agent",
                assignee_role=role,
                due_at=deadline,
            )
            self.db.add(task)
            await self.db.flush()
            await self.db.refresh(task)
            created.append(self._to_dict(task))

        return created

    async def list_tasks(
        self,
        patient_id: str | None = None,
        status: str | None = None,
        assignee_role: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """查询任务列表（支持过滤和分页，创建时间倒序）。"""
        query = select(Task).order_by(Task.created_at.desc())

        if patient_id:
            patient_uuid = UUID(normalize_patient_id(patient_id))
            query = query.where(Task.patient_id == patient_uuid)

        if status:
            query = query.where(Task.status == status)

        if assignee_role:
            query = query.where(Task.assignee_role == assignee_role)

        # 先查总数
        count_query = select(func.count()).select_from(Task)
        if patient_id:
            patient_uuid = UUID(normalize_patient_id(patient_id))
            count_query = count_query.where(Task.patient_id == patient_uuid)
        if status:
            count_query = count_query.where(Task.status == status)
        if assignee_role:
            count_query = count_query.where(Task.assignee_role == assignee_role)

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # 分页
        page = max(1, page)
        size = max(1, size)
        offset = (page - 1) * size
        query = query.offset(offset).limit(size)

        result = await self.db.execute(query)
        tasks = result.scalars().all()
        return [self._to_dict(t) for t in tasks], total

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取单个任务。"""
        try:
            task_uuid = UUID(task_id)
        except ValueError:
            return None

        result = await self.db.execute(
            select(Task).where(Task.id == task_uuid)
        )
        task = result.scalar_one_or_none()
        if task is None:
            return None
        return self._to_dict(task)

    async def update_task_status(self, task_id: str, status: str) -> dict[str, Any] | None:
        """更新任务状态。"""
        try:
            task_uuid = UUID(task_id)
        except ValueError:
            return None

        result = await self.db.execute(
            select(Task).where(Task.id == task_uuid)
        )
        task = result.scalar_one_or_none()
        if task is None:
            return None

        task.status = status
        await self.db.flush()
        await self.db.refresh(task)
        return self._to_dict(task)

    async def complete_task(
        self,
        task_id: str,
        outcome_data: dict[str, Any] | None = None,
        completed_by: str = "",
    ) -> dict[str, Any] | None:
        """完成任务 + 记录 ServiceOutcome + 写入 Timeline。"""
        try:
            task_uuid = UUID(task_id)
        except ValueError:
            return None

        result = await self.db.execute(
            select(Task).where(Task.id == task_uuid)
        )
        task = result.scalar_one_or_none()
        if task is None:
            return None

        outcome_data = outcome_data or {}
        outcome_type = outcome_data.get("outcome_type") or "resolved"
        notes = outcome_data.get("notes", "") or ""
        measured_by = completed_by or outcome_data.get("completed_by", "") or ""

        now_iso = _now_iso()
        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
        task.result = {
            "outcome_type": outcome_type,
            "notes": notes,
            "completed_by": measured_by,
        }
        await self.db.flush()
        await self.db.refresh(task)

        # 记录服务结果
        outcome = await self.outcomes.record_outcome(
            task_id=task_id,
            outcome_type=outcome_type,
            notes=notes,
            measured_by=measured_by,
        )

        # 写入时间线
        patient_id = str(task.patient_id)
        await self.timeline.record(
            patient_id=patient_id,
            entry_type="task_completed",
            title=f"任务已完成：{task.title or task_id}",
            description=notes,
            related_id=task_id,
            metadata={"task_id": task_id, "event_id": str(task.event_id) if task.event_id else None},
        )
        await self.timeline.record(
            patient_id=patient_id,
            entry_type="outcome_recorded",
            title=f"服务结果：{outcome_type}",
            description=notes,
            related_id=outcome["id"],
            metadata={"outcome_id": outcome["id"], "task_id": task_id},
        )

        return self._to_dict(task)

    def _to_dict(self, task: Task) -> dict[str, Any]:
        """将 ORM 对象转换为 dict。"""
        return {
            "id": str(task.id),
            "patient_id": str(task.patient_id),
            "event_id": str(task.event_id) if task.event_id else None,
            "title": task.title if hasattr(task, "title") else "",
            "description": task.description if hasattr(task, "description") else "",
            "task_type": task.task_type,
            "status": task.status,
            "priority": task.priority,
            "assignee_type": task.assignee_type,
            "assignee_role": task.assignee_role,
            "deadline": task.due_at.isoformat() if task.due_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "result": task.result,
        }


__all__ = ["DbTaskService"]
