"""患者路由。

Phase 2：患者主数据尚未接入独立存储，此处基于事件 / 任务活动派生患者概览，
使 Event → Task → Outcome → Timeline 闭环在演示阶段自洽。
"""

from fastapi import APIRouter, HTTPException

from app.services import EventService, OutcomeService, TaskService
from app.utils import normalize_patient_id

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("")
async def list_patients():
    """获取有活动记录的患者列表（从事件派生）。"""
    events = await EventService().list_events(limit=1000)
    seen: dict[str, dict] = {}
    for e in events:
        pid = e.get("patient_id")
        if pid and pid not in seen:
            seen[pid] = {"patient_id": pid, "last_event_at": e.get("received_at")}
    patients = list(seen.values())
    return {"patients": patients, "total": len(patients)}


@router.get("/{patient_id}")
async def get_patient(patient_id: str):
    """获取患者概览：聚合事件 / 任务 / 结果计数。

    若该患者无任何活动记录则返回 404。
    """
    patient_id = normalize_patient_id(patient_id)
    events = await EventService().list_events(patient_id=patient_id, limit=1000)
    tasks, task_total = await TaskService().list_tasks(patient_id=patient_id, size=1000)
    outcomes = await OutcomeService().get_outcomes_for_patient(patient_id)

    if not events and task_total == 0:
        raise HTTPException(status_code=404, detail="Patient not found")

    open_tasks = sum(1 for t in tasks if t.get("status") not in ("completed", "cancelled"))
    return {
        "patient_id": patient_id,
        "event_count": len(events),
        "task_count": task_total,
        "open_task_count": open_tasks,
        "outcome_count": len(outcomes),
        "last_event_at": events[0].get("received_at") if events else None,
    }
