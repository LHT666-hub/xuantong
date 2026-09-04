"""任务管理服务。

将 workflow 产出的行动项落地为可查询、可更新、可完成的任务记录；
任务完成时联动记录 ServiceOutcome 与 Timeline，形成服务闭环。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from app.services.outcome_service import OutcomeService
from app.services.store import InMemoryStore, get_store
from app.services.timeline_service import TimelineService
from app.utils import normalize_patient_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# task_type → 中文标题，缺省回退到原始类型字符串
_TASK_TYPE_TITLES: dict[str, str] = {
    "followup": "随访跟进",
    "monitoring": "指标监测",
    "medication_review": "用药复核",
    "referral": "转诊建议",
    "education": "健康教育",
    "alert": "预警提醒",
}


class TaskService:
    """任务管理服务。"""

    def __init__(self, db_session: InMemoryStore | None = None) -> None:
        self.db = db_session or get_store()
        self.outcomes = OutcomeService(self.db)
        self.timeline = TimelineService(self.db)

    async def create_tasks_from_workflow(
        self,
        event_id: str,
        patient_id: str,
        action_plan: Any = None,
        generated_tasks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """从 workflow 结果创建任务记录。

        以 generated_tasks（task_gen_node 产出）为主，缺省时回退到
        action_plan.actions，保证任一来源都能落地为任务行。
        """
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

        for gt in source_tasks:
            task_id = str(gt.get("id") or f"task-{uuid4().hex[:12]}")
            task_type = str(gt.get("task_type") or "followup")
            role = gt.get("assignee_role") or "assistant"
            deadline_hours = gt.get("deadline_hours")
            deadline = (
                (now + timedelta(hours=float(deadline_hours))).isoformat()
                if deadline_hours
                else None
            )
            record: dict[str, Any] = {
                "id": task_id,
                "patient_id": normalize_patient_id(patient_id),
                "event_id": event_id,
                "title": _TASK_TYPE_TITLES.get(task_type, task_type),
                "description": gt.get("description", "") or "",
                "task_type": task_type,
                "status": gt.get("status") or "pending",
                "priority": gt.get("priority") or "medium",
                "assignee_type": "human" if str(role).startswith("human") else "agent",
                "assignee_role": role,
                "deadline": deadline,
                "created_at": _now_iso(),
                "completed_at": None,
                "result": None,
            }
            self.db.tasks[task_id] = record
            created.append(record)

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
        rows = list(self.db.tasks.values())
        if patient_id:
            patient_id = normalize_patient_id(patient_id)
            rows = [t for t in rows if t["patient_id"] == patient_id]
        if status:
            rows = [t for t in rows if t["status"] == status]
        if assignee_role:
            rows = [t for t in rows if t["assignee_role"] == assignee_role]
        rows.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        total = len(rows)
        page = max(1, page)
        size = max(1, size)
        start = (page - 1) * size
        return rows[start : start + size], total

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取单个任务。"""
        return self.db.tasks.get(task_id)

    async def update_task_status(self, task_id: str, status: str) -> dict[str, Any] | None:
        """更新任务状态。"""
        task = self.db.tasks.get(task_id)
        if task is None:
            return None
        task["status"] = status
        task["updated_at"] = _now_iso()
        return task

    async def complete_task(
        self,
        task_id: str,
        outcome_data: dict[str, Any] | None = None,
        completed_by: str = "",
    ) -> dict[str, Any] | None:
        """完成任务 + 记录 ServiceOutcome + 写入 Timeline。

        outcome_data: {outcome_type, notes, ...}。返回更新后的任务记录，
        若任务不存在返回 None。
        """
        task = self.db.tasks.get(task_id)
        if task is None:
            return None

        outcome_data = outcome_data or {}
        outcome_type = outcome_data.get("outcome_type") or "resolved"
        notes = outcome_data.get("notes", "") or ""
        measured_by = completed_by or outcome_data.get("completed_by", "") or ""

        now_iso = _now_iso()
        task["status"] = "completed"
        task["completed_at"] = now_iso
        task["result"] = {
            "outcome_type": outcome_type,
            "notes": notes,
            "completed_by": measured_by,
        }
        task["updated_at"] = now_iso

        # 记录服务结果
        outcome = await self.outcomes.record_outcome(
            task_id=task_id,
            outcome_type=outcome_type,
            notes=notes,
            measured_by=measured_by,
        )

        # 写入时间线：任务完成 + 结果记录
        patient_id = task.get("patient_id", "")
        await self.timeline.record(
            patient_id=patient_id,
            entry_type="task_completed",
            title=f"任务已完成：{task.get('title', task_id)}",
            description=notes,
            related_id=task_id,
            metadata={"task_id": task_id, "event_id": task.get("event_id")},
        )
        await self.timeline.record(
            patient_id=patient_id,
            entry_type="outcome_recorded",
            title=f"服务结果：{outcome_type}",
            description=notes,
            related_id=outcome["id"],
            metadata={"outcome_id": outcome["id"], "task_id": task_id},
        )
        return task


__all__ = ["TaskService"]
