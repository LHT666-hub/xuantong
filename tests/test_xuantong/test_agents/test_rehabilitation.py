"""康复师 Agent（Rehabilitation）智能逻辑测试。"""

import json

import pytest

from app.schemas.agent import ConsultationNote
from app.xuantong.agents.rehabilitation import RehabilitationAgent
from tests.test_xuantong.test_agents.conftest import make_runtime

REHAB_JSON = json.dumps(
    {
        "functional_assessment": "建议评估 ADL（Barthel）、平衡（TUG）、肌力、心肺耐力（6分钟步行）",
        "exercise_prescription": {
            "frequency": "每周 5-7 天有氧，抗阻 2-3 天",
            "intensity": "中等强度（RPE 12-13）",
            "time": "每次有氧 30 分钟",
            "type": "快走/太极 + 弹力带抗阻 + 平衡训练",
        },
        "home_program": ["每日快走 30 分钟", "弹力带抗阻隔天一次", "每日平衡训练防跌倒"],
        "safety_precautions": ["血压≥180/110 暂停运动", "避免屏气等长运动"],
        "contraindications": ["不稳定心绞痛", "急性感染发热期"],
        "observation": "患者高血压合并糖尿病，缺乏规律运动",
        "assessment": "有氧结合抗阻有助降压控糖，需安全阈值内个体化",
        "recommendations": ["从低-中强度有氧起步", "结合抗阻与平衡训练"],
        "red_flags": [],
        "confidence": 0.8,
    },
    ensure_ascii=False,
)

STROKE_JSON = json.dumps(
    {
        "functional_assessment": "评估偏瘫肢体运动功能（Brunnstrom）、平衡、ADL、吞咽与语言",
        "exercise_prescription": {
            "frequency": "每日多次、循序渐进",
            "intensity": "低-中强度，以不诱发疲劳为度",
            "time": "分次短时训练，逐步延长",
            "type": "良肢位摆放、肢体功能训练、平衡与步态训练、ADL 训练",
        },
        "home_program": ["良肢位摆放预防痉挛", "被动/主动关节活动度训练", "坐位与站立平衡训练"],
        "safety_precautions": ["防跌倒、防误吸", "监测血压，避免过度疲劳"],
        "contraindications": ["生命体征不稳定期暂缓康复训练"],
        "observation": "脑卒中后偏瘫，肢体功能与平衡障碍",
        "assessment": "早期规范康复有助功能恢复，需循序渐进",
        "recommendations": ["开展肢体功能与平衡训练", "必要时语言/吞咽康复"],
        "red_flags": [],
        "confidence": 0.78,
    },
    ensure_ascii=False,
)


@pytest.mark.asyncio
async def test_rehab_consult(bp_event, zhang_ayi_patient):
    agent = RehabilitationAgent(make_runtime(default=REHAB_JSON))
    note = await agent.consult(bp_event, zhang_ayi_patient)

    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "rehabilitation"
    assert note.confidence == 0.8
    assert note.data["functional_assessment"]
    assert note.data["exercise_prescription"]["type"]
    assert len(note.data["home_program"]) == 3
    assert note.data["safety_precautions"]


@pytest.mark.asyncio
async def test_rehab_stroke(bp_event):
    """脑卒中康复场景应给出肢体功能/平衡训练方案。"""
    agent = RehabilitationAgent(make_runtime(default=STROKE_JSON))
    note = await agent.consult(bp_event)

    assert note.agent_role == "rehabilitation"
    assert "良肢位" in note.data["exercise_prescription"]["type"]
    assert any("平衡" in p for p in note.data["home_program"])
    assert note.data["contraindications"]
    assert "不稳定" in note.findings[0] or note.findings


@pytest.mark.asyncio
async def test_rehab_exercise_prescription_non_dict_is_normalized(bp_event):
    """exercise_prescription 非对象时应被规整为 dict，不破坏结构。"""
    payload = json.loads(REHAB_JSON)
    payload["exercise_prescription"] = "每周快走 5 次"
    agent = RehabilitationAgent(
        make_runtime(default=json.dumps(payload, ensure_ascii=False))
    )
    note = await agent.consult(bp_event)
    assert isinstance(note.data["exercise_prescription"], dict)
    assert note.data["exercise_prescription"]["description"] == "每周快走 5 次"


@pytest.mark.asyncio
async def test_rehab_degraded(bp_event):
    """LLM 不可用（无 runtime）时返回模板化降级建议。"""
    agent = RehabilitationAgent(None)
    note = await agent.consult(bp_event)

    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "rehabilitation"
    assert "模型不可用" in note.summary
    assert note.data.get("degraded") is True
    assert note.recommendations


@pytest.mark.asyncio
async def test_rehab_degraded_on_invalid_json(bp_event):
    agent = RehabilitationAgent(make_runtime(default="无法评估"))
    note = await agent.consult(bp_event)
    assert "模型不可用" in note.summary


@pytest.mark.asyncio
async def test_rehab_execute_returns_agent_result(bp_event):
    agent = RehabilitationAgent(make_runtime(default=REHAB_JSON))
    result = await agent.execute(event_data=bp_event)
    assert result.agent_role == "rehabilitation"
    assert result.summary
    assert result.data["data"]["functional_assessment"]
