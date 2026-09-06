"""服务结果路由。

Phase 2：ServiceOutcome 由任务完成时联动记录（见 tasks 路由），本模块提供
按患者 / 任务的结果查询能力。

支持两种持久化模式：数据库模式（生产）和内存模式（测试）。

``GET /api/outcomes`` 在 patient_id / task_id 均缺省时执行**全量分页查询**
（此前恒返回空数组），按 created_at 倒序，默认 page=1 / size=20。
响应结构 ``{"outcomes": [...], "total": int}`` 保持不变，并新增 ``page`` /
``size`` 字段（纯增量，不破坏 iOS 端既有解码）。
"""

from fastapi import APIRouter, Query, Request

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
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
):
    """获取服务结果列表（可按患者 / 任务过滤；均缺省时全量分页返回）。"""
    session_factory = _get_db_session(request)

    if patient_id:
        patient_id = normalize_patient_id(patient_id)

    # 过滤查询（patient_id / task_id）返回全部命中项，total 即命中数；
    # 全量查询走分页，total 为库中总数。
    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbOutcomeService

        async with get_db_context(session_factory) as db:
            service = DbOutcomeService(db)
            if task_id:
                rows = await service.get_outcomes_for_task(task_id)
                total = len(rows)
            elif patient_id:
                rows = await service.get_outcomes_for_patient(patient_id)
                total = len(rows)
            else:
                rows, total = await service.list_all_outcomes(page=page, size=size)
    else:
        service = OutcomeService()
        if task_id:
            rows = await service.get_outcomes_for_task(task_id)
            total = len(rows)
        elif patient_id:
            rows = await service.get_outcomes_for_patient(patient_id)
            total = len(rows)
        else:
            all_rows = list(service.db.outcomes.values())
            all_rows.sort(key=lambda r: r.get("measured_at") or "", reverse=True)
            total = len(all_rows)
            start = (page - 1) * size
            rows = all_rows[start:start + size]

    return {"outcomes": rows, "total": total, "page": page, "size": size}
