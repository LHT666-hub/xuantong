"""系统路由：健康检查"""
from fastapi import APIRouter, Request

from app.schemas.common import HealthResponse
from app.xuantong.runtime.registry import AgentRegistry

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """健康检查（轻量级，供负载均衡探针使用）"""
    return HealthResponse(status="ok", version="0.1.0")


@router.get("/health/detail")
async def health_detail(request: Request):
    """详细健康检查（含 LLM / Agent 状态）"""
    llm_health = await request.app.state.llm_runtime.health()
    agents = AgentRegistry.list_all()
    result = {
        "app": {"status": "ok", "version": "0.1.0"},
        "llm": llm_health,
        "agents": {
            "total": len(agents),
            "implemented": len([a for a in agents if a.implemented]),
        },
    }
    ruomu = getattr(request.app.state, "ruomu_service", None)
    result["knowledge"] = {
        "ruomu": {
            "enabled": ruomu is not None,
            "healthy": await ruomu.health() if ruomu is not None else None,
            "role": "evidence_retrieval",
        }
    }
    return result
