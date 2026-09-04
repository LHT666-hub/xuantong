"""健康记录路由（V0.1 Phase 1 stub）"""
from fastapi import APIRouter

router = APIRouter(prefix="/health-records", tags=["health-records"])


@router.get("/{patient_id}")
async def get_health_records(patient_id: str):
    """获取患者健康记录。V0.1 Phase 1 stub。"""
    return {"records": [], "total": 0}
