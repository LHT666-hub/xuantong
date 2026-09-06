"""中医师 Agent（TCM）智能逻辑测试。"""

import json

import pytest

from app.schemas.agent import ConsultationNote
from app.xuantong.agents.tcm import TCMAgent
from tests.test_xuantong.test_agents.conftest import make_runtime

TCM_JSON = json.dumps(
    {
        "tcm_diagnosis": "眩晕（肝阳上亢证）",
        "syndrome_type": "肝阳上亢",
        "constitution_type": "阴虚质偏阳亢",
        "four_examination": "望：面红目赤；问：头晕胀痛、急躁易怒；切：脉弦有力",
        "recommended_formula": "天麻钩藤饮加减",
        "formula_composition": ["天麻", "钩藤", "石决明", "川牛膝"],
        "acupoints": ["太冲", "风池", "百会"],
        "tcm_therapy": ["针刺（泻法）", "耳穴压豆"],
        "observation": "血压168/103伴头晕、面红、急躁，脉弦，符合肝阳上亢",
        "assessment": "肝肾阴虚为本、肝阳上亢为标，治宜平肝潜阳",
        "recommendations": ["天麻钩藤饮平肝潜阳", "针刺太冲、风池"],
        "red_flags": [],
        "confidence": 0.75,
    },
    ensure_ascii=False,
)


@pytest.mark.asyncio
async def test_tcm_consult(bp_event, zhang_ayi_patient):
    agent = TCMAgent(make_runtime(default=TCM_JSON))
    note = await agent.consult(bp_event, zhang_ayi_patient)

    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "tcm"
    assert note.summary == "眩晕（肝阳上亢证）"
    assert note.confidence == 0.75
    assert note.data["syndrome_type"] == "肝阳上亢"
    assert note.data["recommended_formula"] == "天麻钩藤饮加减"
    assert "太冲" in note.data["acupoints"]
    assert "肝阳上亢" in note.findings


@pytest.mark.asyncio
async def test_tcm_degraded(bp_event):
    """LLM 不可用（无 runtime）时返回模板化降级建议。"""
    agent = TCMAgent(None)
    note = await agent.consult(bp_event)

    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "tcm"
    assert "模型不可用" in note.summary
    assert note.data.get("degraded") is True
    assert note.recommendations


@pytest.mark.asyncio
async def test_tcm_degraded_on_invalid_json(bp_event):
    agent = TCMAgent(make_runtime(default="抱歉，我无法辨证"))
    note = await agent.consult(bp_event)
    assert "模型不可用" in note.summary


@pytest.mark.asyncio
async def test_tcm_execute_returns_agent_result(bp_event):
    agent = TCMAgent(make_runtime(default=TCM_JSON))
    result = await agent.execute(event_data=bp_event)
    assert result.agent_role == "tcm"
    assert result.summary
    assert result.data["data"]["syndrome_type"] == "肝阳上亢"
