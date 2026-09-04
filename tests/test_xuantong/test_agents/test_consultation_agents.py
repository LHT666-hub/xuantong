"""会诊阶段 Agent（护士 / 公卫 / 药师）智能逻辑测试。"""

import json

import pytest

from app.schemas.agent import ConsultationNote
from app.xuantong.agents.nurse import NurseAgent
from app.xuantong.agents.pharmacist import PharmacistAgent
from app.xuantong.agents.public_health import PublicHealthAgent
from tests.test_xuantong.test_agents.conftest import make_runtime

NURSE_JSON = json.dumps(
    {
        "observation": "收缩压168mmHg，舒张压103mmHg，均高于目标值",
        "assessment": "血压控制不佳，伴头晕",
        "trend_analysis": "需对比历史数据确认急性升高还是持续不佳",
        "recommendations": ["安静休息后复测", "确认规律服药"],
        "red_flags": ["头晕伴血压升高需警惕高血压急症"],
        "confidence": 0.85,
    },
    ensure_ascii=False,
)

PUBLIC_HEALTH_JSON = json.dumps(
    {
        "observation": "血压168/103属高血压2级，伴症状",
        "guideline_reference": "《国家基本公共卫生服务规范》高血压健康管理",
        "management_level": "二级管理（中危）",
        "followup_requirement": "每月至少1次，当前事件48小时内电话随访",
        "recommendations": ["48小时内电话随访", "缩短随访周期至每2周"],
        "referral_needed": False,
        "referral_criteria": "血压≥180/110或靶器官损害则转诊",
        "confidence": 0.8,
    },
    ensure_ascii=False,
)

PHARMACIST_JSON = json.dumps(
    {
        "observation": "当前服氨氯地平5mg qd，血压168/103控制不佳",
        "medication_review": "单药控制不佳，需评估依从性",
        "ddi_findings": ["避免与强效CYP3A4抑制剂合用"],
        "assessment": "首先排查用药依从性",
        "recommendations": ["核实近一周是否规律服药"],
        "red_flags": [],
        "confidence": 0.8,
    },
    ensure_ascii=False,
)


@pytest.mark.asyncio
async def test_nurse_consult(bp_event, zhang_ayi_patient):
    agent = NurseAgent(make_runtime(default=NURSE_JSON))
    note = await agent.consult(bp_event, zhang_ayi_patient)

    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "nurse"
    assert note.observation
    assert note.trend_analysis
    assert note.confidence == 0.85
    assert len(note.red_flags) == 1
    assert len(note.recommendations) == 2


@pytest.mark.asyncio
async def test_nurse_degrades_on_invalid_json(bp_event):
    agent = NurseAgent(make_runtime(default="抱歉，我无法输出"))
    note = await agent.consult(bp_event)
    assert isinstance(note, ConsultationNote)
    assert note.agent_role == "nurse"
    assert "模型不可用" in note.summary


@pytest.mark.asyncio
async def test_nurse_retries_then_succeeds(bp_event):
    agent = NurseAgent(make_runtime(sequence=["第一次不是JSON", NURSE_JSON]))
    note = await agent.consult(bp_event)
    assert note.observation
    assert note.confidence == 0.85


@pytest.mark.asyncio
async def test_public_health_consult(bp_event, zhang_ayi_patient):
    agent = PublicHealthAgent(make_runtime(default=PUBLIC_HEALTH_JSON))
    note = await agent.consult(bp_event, zhang_ayi_patient)

    assert note.agent_role == "public_health"
    assert note.management_level == "二级管理（中危）"
    assert note.referral_needed is False
    assert note.guideline_reference
    assert len(note.recommendations) == 2


@pytest.mark.asyncio
async def test_public_health_degrades_without_runtime(bp_event):
    agent = PublicHealthAgent(None)
    note = await agent.consult(bp_event)
    assert isinstance(note, ConsultationNote)
    assert "模型不可用" in note.summary


@pytest.mark.asyncio
async def test_pharmacist_consult(bp_event, zhang_ayi_patient):
    agent = PharmacistAgent(make_runtime(default=PHARMACIST_JSON))
    note = await agent.consult(bp_event, zhang_ayi_patient)

    assert note.agent_role == "pharmacist"
    assert note.medication_review
    assert len(note.ddi_findings) == 1
    assert note.red_flags == []


@pytest.mark.asyncio
async def test_consultation_execute_returns_agent_result(bp_event):
    agent = NurseAgent(make_runtime(default=NURSE_JSON))
    result = await agent.execute(event_data=bp_event)
    assert result.agent_role == "nurse"
    assert result.summary
    assert result.data["observation"]


@pytest.mark.asyncio
async def test_code_fence_wrapped_json_is_parsed(bp_event):
    fenced = "```json\n" + NURSE_JSON + "\n```"
    agent = NurseAgent(make_runtime(default=fenced))
    note = await agent.consult(bp_event)
    assert note.observation
