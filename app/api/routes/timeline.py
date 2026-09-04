"""患者时间线路由。

Phase 2：由 TimelineService 聚合 Event → Workflow → Task → Outcome 全链路的
关键节点，支持按类型过滤与分页查询。

支持两种持久化模式：数据库模式（生产）和内存模式（测试）。
"""

from fastapi import APIRouter, Request

from app.services import TimelineService
from app.utils import normalize_patient_id

router = APIRouter(tags=["timeline"])


def _get_db_session(request: Request):
    """尝试从 app.state 获取数据库会话工厂。"""
    return getattr(request.app.state, "session_factory", None)


@router.get("/patients/{patient_id}/timeline")
async def get_patient_timeline(
    request: Request,
    patient_id: str,
    entry_type: str | None = None,
    page: int = 1,
    size: int = 50,
):
    """获取患者时间线（按类型过滤 + 分页，时间升序）。"""
    session_factory = _get_db_session(request)
    patient_id = normalize_patient_id(patient_id)

    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbTimelineService

        async with get_db_context(session_factory) as db:
            entries, total = await DbTimelineService(db).get_timeline(
                patient_id=patient_id, entry_type=entry_type, page=page, size=size
            )
    else:
        entries, total = await TimelineService().get_timeline(
            patient_id=patient_id, entry_type=entry_type, page=page, size=size
        )
    return {
        "timeline": entries,
        "patient_id": patient_id,
        "total": total,
        "page": page,
        "size": size,
    }
