"""患者时间线服务。

将 Event → Workflow → Task → Outcome 全链路的关键节点统一沉淀为时间线条目，
支持按患者、按类型过滤与分页查询。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.store import InMemoryStore, get_store
from app.utils import normalize_patient_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TimelineService:
    """时间线服务。"""

    def __init__(self, db_session: InMemoryStore | None = None) -> None:
        self.db = db_session or get_store()

    async def record(
        self,
        patient_id: str,
        entry_type: str,
        title: str,
        description: str = "",
        metadata: dict[str, Any] | None = None,
        related_id: str | None = None,
    ) -> dict[str, Any]:
        """记录一条时间线条目。"""
        entry: dict[str, Any] = {
            "id": str(uuid4()),
            "patient_id": normalize_patient_id(patient_id),
            "entry_type": entry_type,
            "title": title,
            "description": description or "",
            "related_id": related_id,
            "metadata": metadata or {},
            "created_at": _now_iso(),
        }
        self.db.timeline.append(entry)
        return entry

    async def record_workflow_timeline(
        self, patient_id: str, event_id: str, workflow_state: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """从 workflow 结果批量记录时间线。

        覆盖节点：event_received / risk_assessed / consultation_complete /
        action_planned / tasks_created / execution_started。
        """
        state = workflow_state or {}
        entries: list[dict[str, Any]] = []

        # 1) 事件接收
        entries.append(
            await self.record(
                patient_id=patient_id,
                entry_type="event_received",
                title="健康事件已接收",
                description="系统已接收并进入玄同工作流引擎处理。",
                related_id=event_id,
                metadata={"event_id": event_id},
            )
        )

        # 2) 风险评估
        risk = state.get("clinical_risk")
        if risk is not None:
            level = getattr(risk, "level", None)
            score = getattr(risk, "score", None)
            triggers = getattr(risk, "trigger_indicators", None) or []
            entries.append(
                await self.record(
                    patient_id=patient_id,
                    entry_type="risk_assessed",
                    title=f"临床风险评估：{level}",
                    description=f"风险等级 {level}，评分 {score}。",
                    related_id=event_id,
                    metadata={"level": level, "score": score, "triggers": list(triggers)},
                )
            )

        # 3) 会诊完成
        notes = state.get("consultation_notes") or []
        if notes:
            roles = [getattr(n, "agent_role", None) for n in notes]
            entries.append(
                await self.record(
                    patient_id=patient_id,
                    entry_type="consultation_complete",
                    title=f"多学科会诊完成（{len(notes)} 位成员）",
                    description="、".join(str(r) for r in roles if r),
                    related_id=event_id,
                    metadata={"count": len(notes), "roles": roles},
                )
            )

        # 4) 行动计划
        plan = state.get("action_plan")
        if plan is not None:
            summary = getattr(plan, "summary", "") or ""
            entries.append(
                await self.record(
                    patient_id=patient_id,
                    entry_type="action_planned",
                    title="行动计划已生成",
                    description=summary,
                    related_id=event_id,
                    metadata={"actions": len(getattr(plan, "actions", []) or [])},
                )
            )

        # 5) 任务创建
        generated = state.get("generated_tasks") or []
        if generated:
            entries.append(
                await self.record(
                    patient_id=patient_id,
                    entry_type="tasks_created",
                    title=f"已生成 {len(generated)} 项任务",
                    description="；".join(
                        str(t.get("description", "")) for t in generated if isinstance(t, dict)
                    ),
                    related_id=event_id,
                    metadata={
                        "count": len(generated),
                        "task_ids": [t.get("id") for t in generated if isinstance(t, dict)],
                    },
                )
            )

        # 6) 执行启动
        execution = state.get("execution_result")
        if execution is not None:
            exec_tasks = getattr(execution, "tasks", []) or []
            entries.append(
                await self.record(
                    patient_id=patient_id,
                    entry_type="execution_started",
                    title="执行阶段已启动",
                    description=f"助理拆解出 {len(exec_tasks)} 项可执行任务。",
                    related_id=event_id,
                    metadata={"execution_tasks": len(exec_tasks)},
                )
            )

        return entries

    async def get_timeline(
        self,
        patient_id: str,
        entry_type: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """查询患者时间线（按类型过滤 + 分页，时间升序）。"""
        patient_id = normalize_patient_id(patient_id)
        rows = [e for e in self.db.timeline if e["patient_id"] == patient_id]
        if entry_type:
            rows = [e for e in rows if e["entry_type"] == entry_type]
        rows.sort(key=lambda e: e.get("created_at", ""))
        total = len(rows)
        page = max(1, page)
        size = max(1, size)
        start = (page - 1) * size
        return rows[start : start + size], total


__all__ = ["TimelineService"]
