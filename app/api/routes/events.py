"""事件路由。

Phase 2：接收健康事件 → 触发玄同 LangGraph 工作流引擎 → 将 workflow 产出
（生成的任务、时间线、处理状态）持久化，返回事件记录 + workflow 摘要 +
task_ids。workflow 失败不阻断事件创建（降级返回）。

支持两种持久化模式：
- 数据库模式（生产）：使用 DbEventService / DbTaskService / DbTimelineService
- 内存模式（测试）：使用 EventService / TaskService / TimelineService（InMemoryStore）
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from app.schemas.event import EventCreate, EventResponse
from app.services import EventService, TaskService, TimelineService
from app.utils import normalize_patient_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


def _build_event_data(event: EventCreate, event_id: str, now: datetime) -> dict[str, Any]:
    """将 EventCreate 组装为 workflow 入口事件数据。"""
    payload = event.payload or {}
    data: dict[str, Any] = {
        "event_id": event_id,
        "patient_id": normalize_patient_id(event.patient_id),
        "event_type": event.event_type,
        "channel": event.channel,
        "source": event.source or "",
        "occurred_at": (event.occurred_at or now).isoformat(),
        "metadata": event.metadata or {},
        "payload": payload,
    }
    for key, value in payload.items():
        data.setdefault(key, value)
    return data


def _summarize_workflow(state: dict[str, Any]) -> dict[str, Any]:
    """从最终 State 提炼对外可见的 workflow 摘要。"""
    plan = state.get("action_plan")
    risk = state.get("clinical_risk")
    decision = state.get("dispatch_decision")
    execution = state.get("execution_result")
    return {
        "status": "pending_human" if state.get("human_required") else "completed",
        "thread_id": state.get("thread_id"),
        "severity": decision.severity if decision else None,
        "clinical_risk": risk.level if risk else None,
        "consultations": len(state.get("consultation_notes") or []),
        "action_summary": plan.summary if plan else None,
        "patient_communication": plan.patient_communication if plan else None,
        "tasks_generated": len(state.get("generated_tasks") or []),
        "execution_tasks": len(execution.tasks) if execution else 0,
        "steps": [e.get("node") for e in (state.get("flow_log") or [])],
    }


def _get_db_session(request: Request):
    """尝试从 app.state 获取数据库会话工厂，如果不可用返回 None。"""
    session_factory = getattr(request.app.state, "session_factory", None)
    return session_factory


async def _get_services(request: Request):
    """根据配置返回合适的服务实例（数据库或内存）。"""
    session_factory = _get_db_session(request)

    # 如果有数据库会话工厂，使用数据库服务
    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbEventService, DbTaskService, DbTimelineService

        # 创建数据库上下文
        db_context = get_db_context(session_factory)
        db = await db_context.__aenter__()

        event_service = DbEventService(db)
        task_service = DbTaskService(db)
        timeline_service = DbTimelineService(db)

        return event_service, task_service, timeline_service, db_context, db
    else:
        # 回退到内存存储（测试模式）
        return EventService(), TaskService(), TimelineService(), None, None


@router.post("", status_code=201)
async def create_event(request: Request, event: EventCreate):
    """创建事件 → 触发 workflow → 持久化结果。"""
    now = datetime.now(timezone.utc)
    event_id = str(uuid4())

    # 规范化 patient_id：非 UUID 格式时生成确定性 UUID，保证全链路一致
    patient_id = normalize_patient_id(event.patient_id)

    # 获取服务实例
    event_service, task_service, timeline_service, db_context, db = await _get_services(request)

    try:
        # 1) 持久化事件（状态 received）
        await event_service.create_event(
            {
                "id": event_id,
                "patient_id": patient_id,
                "event_type": event.event_type,
                "channel": event.channel,
                "source": event.source or "",
                "payload": event.payload or {},
                "metadata": event.metadata or {},
                "occurred_at": (event.occurred_at or now).isoformat(),
                "received_at": now.isoformat(),
            }
        )

        event_response = EventResponse(
            id=event_id,
            patient_id=patient_id,
            event_type=event.event_type,
            channel=event.channel,
            source=event.source or "",
            payload=event.payload,
            occurred_at=event.occurred_at or now,
            received_at=now,
        )

        # 2) 触发 workflow（异常降级不阻断事件创建）
        workflow_summary, workflow_state = await _run_workflow(request, event, event_id, now)

        # 3) 持久化 workflow 产出：任务 + 时间线 + 事件状态
        task_ids: list[str] = []
        if workflow_state is not None:
            tasks = await task_service.create_tasks_from_workflow(
                event_id=event_id,
                patient_id=patient_id,
                action_plan=workflow_state.get("action_plan"),
                generated_tasks=workflow_state.get("generated_tasks") or [],
            )
            task_ids = [t["id"] for t in tasks]
            await timeline_service.record_workflow_timeline(
                patient_id=patient_id, event_id=event_id, workflow_state=workflow_state
            )

        status = _map_event_status(workflow_summary)
        await event_service.update_event_status(
            event_id=event_id,
            status=status,
            workflow_result=workflow_summary,
            task_ids=task_ids,
        )

        # 提交数据库事务
        if db is not None:
            await db.commit()

        return {
            "event": event_response.model_dump(mode="json"),
            "workflow": workflow_summary,
            "task_ids": task_ids,
        }
    except Exception:
        # 回滚数据库事务
        if db is not None:
            await db.rollback()
        raise
    finally:
        # 关闭数据库上下文
        if db_context is not None:
            await db_context.__aexit__(None, None, None)


def _map_event_status(workflow_summary: dict[str, Any]) -> str:
    """将 workflow 摘要状态映射为事件处理状态。"""
    status = workflow_summary.get("status")
    if status == "skipped":
        return "received"
    if status == "failed":
        return "failed"
    if status == "pending_human":
        return "pending_human"
    return "completed"


@router.get("/{event_id}")
async def get_event(request: Request, event_id: str):
    """查询事件及其处理状态。"""
    session_factory = _get_db_session(request)

    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbEventService

        async with get_db_context(session_factory) as db:
            record = await DbEventService(db).get_event(event_id)
    else:
        record = await EventService().get_event(event_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"event": record}


@router.get("/{event_id}/status")
async def get_event_status(request: Request, event_id: str):
    """查询事件的 workflow 执行状态。"""
    session_factory = _get_db_session(request)

    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbEventService

        async with get_db_context(session_factory) as db:
            record = await DbEventService(db).get_event(event_id)
    else:
        record = await EventService().get_event(event_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return {
        "event_id": event_id,
        "status": record.get("status"),
        "thread_id": record.get("thread_id"),
        "task_ids": record.get("task_ids", []),
        "workflow": record.get("workflow"),
    }


async def _run_workflow(
    request: Request, event: EventCreate, event_id: str, now: datetime
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """触发 workflow，返回 (摘要, 最终State)。异常降级不阻断事件创建。"""
    workflow = getattr(request.app.state, "workflow", None)
    if workflow is None:
        return {"status": "skipped", "reason": "workflow_not_initialized"}, None

    event_data = _build_event_data(event, event_id, now)
    try:
        state = await workflow.run(event_data=event_data, thread_id=str(uuid4()))
        return _summarize_workflow(state), state
    except Exception as e:
        logger.exception(f"events: workflow 执行失败 event_id={event_id}: {e}")
        return {"status": "failed", "reason": str(e)}, None
