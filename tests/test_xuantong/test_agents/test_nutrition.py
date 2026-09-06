"""营养师 Agent（Nutrition）智能逻辑测试。"""

import json

import pytest

from app.schemas.agent import ConsultationNote
from app.xuantong.agents.nutrition import NutritionAgent
from tests.test_xuantong.test_agents.conftest import make_runtime

NUTRITION_JSON = json.dumps(
    {
        "dietary_assessment": "饮食偏咸、蔬果不足、精制碳水偏多，与控糖控压目标不符",
        "disease_diet_principle": "高血压合并糖尿病：DASH + 低钠(<5g/天) + 低 GI + 碳水计数",
        "meal_plan_suggestions": [
            "主食粗细搭配，全谷物占 1/3",
            "每日蔬菜 500g、低 GI 水果 200g",
            "限盐<5g/天，注意隐形钠",
        ],
        "nutrient_supplements": ["评估维生素D", "膳食纤维不足时酌情补充"],
        "weight_management": "如超重，每周减重 0.5kg，能量缺口 300-500kcal/天",
        "observation": "患者高血压合并2型糖尿病，饮食结构存在高钠、精制碳水偏多",
        "assessment": "饮食干预是血压血糖控制基础，需系统调整",
        "recommendations": ["推行 DASH 饮食并限钠<5g/天", "低 GI 主食与碳水计数"],
        "red_flags": [],
        "confidence": 0.8,
    },
    ensure_ascii=False,
)

HYPERTENSION_JSON = json.dumps(
    {
        "dietary_assessment": "钠摄入偏高，钾摄入不足",
        "disease_diet_principle": "高血压：DASH 饮食、低钠(<5g/天)、高钾高钙高镁、限酒",
        "meal_plan_suggestions": ["限盐<5g/天", "增加富钾蔬果（肾功能正常时）"],
        "nutrient_supplements": [],
        "weight_management": "控制体重、限酒",
        "observation": "血压168/103，饮食高钠是重要可控因素",
        "assessment": "限钠与 DASH 饮食有助于降压",
        "recommendations": ["严格限钠<5g/天", "采用 DASH 饮食模式", "增加富钾食物"],
        "red_flags": [],
        "confidence": 0.82,
    },
    ensure_ascii=False,
)


@pytest.mark.asyncio
async def test_nutrition_consult(bp_event, zhang_ayi_patient):
    agent = NutritionAgent(make_runtime(default=NUTRITION_JSON))
    note = await agent.consult(bp_event, zhang_ayi_patient)

    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "nutrition"
    assert note.confidence == 0.8
    assert note.data["dietary_assessment"]
    assert "DASH" in note.data["disease_diet_principle"]
    assert len(note.data["meal_plan_suggestions"]) == 3
    assert note.recommendations


@pytest.mark.asyncio
async def test_nutrition_hypertension(bp_event, zhang_ayi_patient):
    """高血压场景应给出低钠/DASH 相关饮食建议。"""
    agent = NutritionAgent(make_runtime(default=HYPERTENSION_JSON))
    note = await agent.consult(bp_event, zhang_ayi_patient)

    assert note.agent_role == "nutrition"
    assert "DASH" in note.data["disease_diet_principle"]
    assert "低钠" in note.data["disease_diet_principle"]
    assert any("限钠" in r or "限盐" in r for r in note.recommendations)


@pytest.mark.asyncio
async def test_nutrition_degraded(bp_event):
    """LLM 不可用（无 runtime）时返回模板化降级建议。"""
    agent = NutritionAgent(None)
    note = await agent.consult(bp_event)

    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "nutrition"
    assert "模型不可用" in note.summary
    assert note.data.get("degraded") is True
    assert note.recommendations


@pytest.mark.asyncio
async def test_nutrition_degraded_on_invalid_json(bp_event):
    agent = NutritionAgent(make_runtime(default="无法评估"))
    note = await agent.consult(bp_event)
    assert "模型不可用" in note.summary


@pytest.mark.asyncio
async def test_nutrition_execute_returns_agent_result(bp_event):
    agent = NutritionAgent(make_runtime(default=NUTRITION_JSON))
    result = await agent.execute(event_data=bp_event)
    assert result.agent_role == "nutrition"
    assert result.summary
    assert result.data["data"]["dietary_assessment"]
