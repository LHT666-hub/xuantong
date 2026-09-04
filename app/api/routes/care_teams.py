"""真实家庭医生团队路由（V0.1 Phase 1 stub）"""
from fastapi import APIRouter

router = APIRouter(prefix="/care-teams", tags=["care-teams"])


@router.get("")
async def list_care_teams():
    """获取真实家庭医生团队列表。V0.1 Phase 1 stub。"""
    return {"care_teams": [], "total": 0}


@router.post("")
async def create_care_team():
    """创建团队。V0.1 Phase 1 stub。"""
    return {"status": "ok", "message": "Not yet implemented"}
