"""营养师临床会诊与食养排序测试。"""

import json

import pytest

from app.schemas.agent import ConsultationNote
from app.xuantong.agents.nutrition import NutritionAgent
from tests.test_xuantong.test_agents.conftest import make_runtime

NUTRITION_JSON = json.dumps(
    {
        "dietary_assessment": "饮食偏咸、蔬果不足",
        "disease_diet_principle": "高血压：DASH + 低钠",
        "meal_plan_suggestions": ["限盐", "增加蔬菜"],
        "nutrient_supplements": [],
        "weight_management": "保持合理体重",
        "observation": "钠摄入偏高",
        "assessment": "需要调整饮食结构",
        "recommendations": ["采用 DASH 饮食", "注意隐形钠"],
        "red_flags": [],
        "confidence": 0.8,
    },
    ensure_ascii=False,
)

PAYLOAD = {
    "pantry_ids": ["tomato", "egg"],
    "excluded_ids": [],
    "max_minutes": 20,
    "low_salt": True,
    "candidate_recipes": [
        {"id": "tomato-egg", "title": "番茄炒蛋", "minutes": 15},
        {"id": "tofu-pot", "title": "豆腐煲", "minutes": 20},
        {"id": "noodles", "title": "汤面", "minutes": 20},
    ],
}


@pytest.mark.asyncio
async def test_nutrition_consult_returns_clinical_note(bp_event, zhang_ayi_patient):
    note = await NutritionAgent(make_runtime(default=NUTRITION_JSON)).consult(
        bp_event, zhang_ayi_patient
    )
    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "nutrition"
    assert note.confidence == 0.8
    assert "DASH" in note.data["disease_diet_principle"]
    assert note.recommendations


@pytest.mark.asyncio
async def test_nutrition_consult_degrades_without_model(bp_event):
    note = await NutritionAgent(None).consult(bp_event)
    assert note.data["degraded"] is True
    assert note.recommendations


@pytest.mark.asyncio
async def test_nutrition_ranks_only_known_recipe_ids():
    response = json.dumps(
        {
            "recipe_ids": ["invented", "tomato-egg", "tofu-pot"],
            "summary": "先用家里已有的食材。",
            "notices": ["少盐调味。"],
        },
        ensure_ascii=False,
    )
    result = await NutritionAgent(make_runtime(default=response)).recommend(PAYLOAD)
    assert result.data["recipe_ids"] == ["tomato-egg", "tofu-pot", "noodles"]
    assert result.data["degraded"] is False


@pytest.mark.asyncio
async def test_nutrition_recommendation_degrades_to_local_order():
    result = await NutritionAgent(make_runtime(default="not json")).recommend(PAYLOAD)
    assert result.data["recipe_ids"] == ["tomato-egg", "tofu-pot", "noodles"]
    assert result.data["degraded"] is True


@pytest.mark.asyncio
async def test_execute_keeps_clinical_and_food_paths_separate(bp_event):
    clinical = await NutritionAgent(make_runtime(default=NUTRITION_JSON)).execute(
        event_data=bp_event
    )
    food_response = json.dumps(
        {"recipe_ids": ["tomato-egg"], "summary": "适合今天。", "notices": []},
        ensure_ascii=False,
    )
    food = await NutritionAgent(make_runtime(default=food_response)).execute(
        nutrition_payload=PAYLOAD
    )
    assert clinical.data["data"]["dietary_assessment"]
    assert food.data["recipe_ids"][0] == "tomato-egg"
