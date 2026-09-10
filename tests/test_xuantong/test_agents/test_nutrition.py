import json

import pytest

from app.xuantong.agents.nutrition import NutritionAgent
from tests.test_xuantong.test_agents.conftest import make_runtime


PAYLOAD = {
    "pantry_ids": ["tomato", "egg"],
    "excluded_ids": [],
    "max_minutes": 20,
    "low_salt": True,
    "candidate_recipes": [
        {"id": "tomato-egg", "title": "番茄炒蛋", "minutes": 15, "ingredient_ids": ["tomato", "egg"]},
        {"id": "tofu-pot", "title": "豆腐煲", "minutes": 20, "ingredient_ids": ["tofu"]},
        {"id": "noodles", "title": "汤面", "minutes": 20, "ingredient_ids": ["noodles"]},
    ],
}


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
    assert result.summary == "先用家里已有的食材。"


@pytest.mark.asyncio
async def test_nutrition_degrades_to_local_order_when_model_fails():
    result = await NutritionAgent(make_runtime(default="not json")).recommend(PAYLOAD)

    assert result.data["recipe_ids"] == ["tomato-egg", "tofu-pot", "noodles"]
    assert result.data["degraded"] is True
