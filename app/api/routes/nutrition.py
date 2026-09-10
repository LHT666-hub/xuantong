from fastapi import APIRouter, HTTPException

from app.config import Settings
from app.schemas.nutrition import (
    NutritionRecommendationRequest,
    NutritionRecommendationResponse,
)
from app.xuantong.runtime.registry import AgentRegistry

router = APIRouter(prefix="/nutrition", tags=["nutrition"])


@router.post("/recommendations", response_model=NutritionRecommendationResponse)
async def recommend_meals(body: NutritionRecommendationRequest) -> NutritionRecommendationResponse:
    """为常曦食养排序候选菜谱；模型失败时保留本地候选顺序。"""
    agent = AgentRegistry.get_instance("nutrition")
    if agent is None:
        raise HTTPException(status_code=503, detail="nutrition_agent_unavailable")

    result = await agent.recommend(body.model_dump(mode="json"))
    data = result.data
    return NutritionRecommendationResponse(
        model=Settings().llm_model_nutrition,
        recipe_ids=data.get("recipe_ids", []),
        summary=data.get("summary", result.summary),
        notices=data.get("notices", result.recommendations),
        degraded=bool(data.get("degraded", False)),
    )
