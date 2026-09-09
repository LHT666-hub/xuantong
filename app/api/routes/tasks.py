"""任务路由。

Phase 2：任务由事件 workflow 自动生成并持久化（见 events 路由），本模块提供
任务的查询、详情、状态更新与完成能力。完成任务时联动记录 ServiceOutcome 与
Timeline，形成服务闭环。

支持两种持久化模式：数据库模式（生产）和内存模式（测试）。
"""

from fastapi import APIRouter, HTTPException, Request

from app.schemas.task import TaskCompleteRequest
from app.services import OutcomeService, TaskService
from app.utils import normalize_patient_id

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_db_session(request: Request):
    """尝试从 app.state 获取数据库会话工厂。"""
    return getattr(request.app.state, "session_factory", None)


@router.get("")
async def list_tasks(
    request: Request,
    patient_id: str | None = None,
    status: str | None = None,
    assignee_role: str | None = None,
    page: int = 1,
    size: int = 20,
):
    """查询任务列表（支持按患者/状态/负责角色过滤 + 分页）。"""
    session_factory = _get_db_session(request)

    if patient_id:
        patient_id = normalize_patient_id(patient_id)

    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbTaskService

        async with get_db_context(session_factory) as db:
            tasks, total = await DbTaskService(db).list_tasks(
                patient_id=patient_id,
                status=status,
                assignee_role=assignee_role,
                page=page,
                size=size,
            )
    else:
        tasks, total = await TaskService().list_tasks(
            patient_id=patient_id,
            status=status,
            assignee_role=assignee_role,
            page=page,
            size=size,
        )
    return {"tasks": tasks, "total": total, "page": page, "size": size}


@router.get("/{task_id}")
async def get_task(request: Request, task_id: str):
    """获取单个任务详情。"""
    session_factory = _get_db_session(request)

    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbTaskService

        async with get_db_context(session_factory) as db:
            task = await DbTaskService(db).get_task(task_id)
    else:
        task = await TaskService().get_task(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task}


@router.post("/{task_id}/accept")
async def accept_proposed_task(request: Request, task_id: str):
    """患者确认一项建议后，将 proposed 工单激活为 pending。"""
    session_factory = _get_db_session(request)

    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbTaskService

        async with get_db_context(session_factory) as db:
            service = DbTaskService(db)
            current = await service.get_task(task_id)
            if current is None:
                raise HTTPException(status_code=404, detail="Task not found")
            if current.get("status") != "proposed":
                raise HTTPException(status_code=409, detail="Task is not awaiting patient confirmation")
            task = await service.update_task_status(task_id, "pending")
            await db.commit()
    else:
        service = TaskService()
        current = await service.get_task(task_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if current.get("status") != "proposed":
            raise HTTPException(status_code=409, detail="Task is not awaiting patient confirmation")
        task = await service.update_task_status(task_id, "pending")

    return {"status": "accepted", "task": task}


@router.post("/{task_id}/complete")
async def complete_task(request: Request, task_id: str, body: TaskCompleteRequest):
    """完成任务：更新状态 + 记录 ServiceOutcome + 写入 Timeline。"""
    session_factory = _get_db_session(request)

    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbTaskService, DbOutcomeService

        async with get_db_context(session_factory) as db:
            task_service = DbTaskService(db)
            if await task_service.get_task(task_id) is None:
                raise HTTPException(status_code=404, detail="Task not found")

            task = await task_service.complete_task(
                task_id=task_id,
                outcome_data={
                    "outcome_type": body.outcome_type,
                    "notes": body.notes or body.outcome_summary,
                    "completed_by": body.completed_by,
                },
                completed_by=body.completed_by,
            )

            outcomes = await DbOutcomeService(db).get_outcomes_for_task(task_id)
            outcome = outcomes[0] if outcomes else None
            return {"status": "ok", "task": task, "outcome": outcome}
    else:
        task_service = TaskService()
        if await task_service.get_task(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found")

        task = await task_service.complete_task(
            task_id=task_id,
            outcome_data={
                "outcome_type": body.outcome_type,
                "notes": body.notes or body.outcome_summary,
                "completed_by": body.completed_by,
            },
            completed_by=body.completed_by,
        )

        outcomes = await OutcomeService().get_outcomes_for_task(task_id)
        outcome = outcomes[0] if outcomes else None
        return {"status": "ok", "task": task, "outcome": outcome}
