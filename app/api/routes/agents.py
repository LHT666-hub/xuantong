"""数字团队花名册"""
from fastapi import APIRouter

from app.xuantong.runtime.registry import AgentRegistry

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents():
    """获取数字化家庭医生团队花名册（8 个 Agent）"""
    agents = AgentRegistry.list_all()
    return {
        "agents": [
            {
                "key": a.key,
                "role": a.role,
                "display_name": a.display_name,
                "description": a.description,
                "phase": a.phase,
                "implemented": a.implemented,
                "capabilities": a.capabilities,
            }
            for a in agents
        ],
        "total": len(agents),
    }
