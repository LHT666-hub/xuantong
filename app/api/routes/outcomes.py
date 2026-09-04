"""服务结果路由。

Phase 2：ServiceOutcome 由任务完成时联动记录（见 tasks 路由），本模块提供
按患者 / 任务的结果查询能力。

支持两种持久化模式：数据库模式（生产）和内存模式（测试）。
"""

from fastapi import APIRouter, Request

from app.services import OutcomeService
from app.utils import normalize_patient_id

router = APIRouter(prefix="/outcomes", tags=["outcomes"])


def _get_db_session(request: Request):
    """尝试从 app.state 获取数据库会话工厂。"""
    return getattr(request.app.state, "session_factory", None)


@router.get("")
async def list_outcomes(
    request: Request,
    patient_id: str | None = None,
    task_id: str | None = None,
):
    """获取服务结果列表（可按患者 / 任务过滤）。"""
    session_factory = _get_db_session(request)

    if patient_id:
        patient_id = normalize_patient_id(patient_id)

    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbOutcomeService

        async with get_db_context(session_factory) as db:
            service = DbOutcomeService(db)
            if task_id:
                rows = await service.get_outcomes_for_task(task_id)
            elif patient_id:
                rows = await service.get_outcomes_for_patient(patient_id)
            else:
                # 返回所有结果（需要查询所有）
                rows = []  # 暂无全部查询接口，返回空
    else:
        service = OutcomeService()
        if task_id:
            rows = await service.get_outcomes_for_task(task_id)
        elif patient_id:
            rows = await service.get_outcomes_for_patient(patient_id)
        else:
            rows = list(service.db.outcomes.values())
    return {"outcomes": rows, "total": len(rows)}
