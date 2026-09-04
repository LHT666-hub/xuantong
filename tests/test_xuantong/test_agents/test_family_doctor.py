"""FamilyDoctorAgent 智能逻辑测试。"""

import json

import pytest

from app.schemas.action import ActionPlan
from app.schemas.dispatch import DispatchDecision
from app.xuantong.agents.family_doctor import FamilyDoctorAgent
from tests.test_xuantong.test_agents.conftest import make_runtime

DISPATCH_JSON = json.dumps(
    {
        "event_summary": "张阿姨血压168/103，伴头晕症状",
        "severity": "moderate",
        "selected_agents": ["nurse", "public_health"],
        "reasoning": "血压明显升高伴症状，需护士趋势分析与公卫随访判断",
        "immediate_actions": ["通知患者保持安静", "准备复测血压"],
        "requires_urgent_response": False,
    },
    ensure_ascii=False,
)

ACTION_PLAN_JSON = json.dumps(
    {
        "summary": "张阿姨血压控制不佳，需加强监测和随访",
        "clinical_assessment": "血压168/103属2级高血压范围，伴头晕症状",
        "actions": [
            {
                "type": "followup",
                "description": "安排3天内复诊测血压",
                "assignee_role": "assistant",
                "priority": "high",
                "deadline_hours": 72,
            },
            {
                "type": "medication_review",
                "description": "建议医生评估是否需要调整降压方案",
                "assignee_role": "human_doctor",
                "priority": "high",
                "deadline_hours": 72,
            },
        ],
        "patient_communication": "张阿姨您好，您的血压有些偏高，建议安静休息后复测。",
        "followup_plan": "3天后复测，如无改善建议门诊就诊",
    },
    ensure_ascii=False,
)


@pytest.mark.asyncio
async def test_analyze_event_returns_dispatch_decision(bp_event, zhang_ayi_patient):
    agent = FamilyDoctorAgent(make_runtime(default=DISPATCH_JSON))
    decision = await agent.analyze_event(bp_event, zhang_ayi_patient)

    assert isinstance(decision, DispatchDecision)
    assert decision.severity == "moderate"
    assert "张阿姨" in decision.event_summary
    assert decision.requires_urgent_response is False
    assert len(decision.immediate_actions) == 2


@pytest.mark.asyncio
async def test_acceptance_dispatch_nurse_and_public_health(bp_event, zhang_ayi_patient):
    """验收标准：张阿姨血压168/103+头晕 → dispatch nurse + public_health。"""
    agent = FamilyDoctorAgent(make_runtime(default=DISPATCH_JSON))
    decision = await agent.analyze_event(bp_event, zhang_ayi_patient)

    roles = {a.value for a in decision.selected_agents}
    assert "nurse" in roles
    assert "public_health" in roles


@pytest.mark.asyncio
async def test_dispatch_team_delegates_to_analyze(bp_event, zhang_ayi_patient):
    agent = FamilyDoctorAgent(make_runtime(default=DISPATCH_JSON))
    decision = await agent.dispatch_team(bp_event, zhang_ayi_patient)
    assert isinstance(decision, DispatchDecision)
    assert decision.severity == "moderate"


@pytest.mark.asyncio
async def test_analyze_event_filters_invalid_roles(bp_event):
    bad = json.dumps({"severity": "high", "selected_agents": ["nurse", "hacker", "chef"]})
    agent = FamilyDoctorAgent(make_runtime(default=bad))
    decision = await agent.analyze_event(bp_event)
    roles = {a.value for a in decision.selected_agents}
    assert roles == {"nurse"}


@pytest.mark.asyncio
async def test_analyze_event_degrades_on_invalid_json(bp_event):
    agent = FamilyDoctorAgent(make_runtime(default="这不是JSON"))
    decision = await agent.analyze_event(bp_event)
    assert isinstance(decision, DispatchDecision)
    # 降级：保守调度，包含护士
    assert any(a.value == "nurse" for a in decision.selected_agents)


@pytest.mark.asyncio
async def test_analyze_event_degrades_without_runtime(bp_event):
    agent = FamilyDoctorAgent(None)
    decision = await agent.analyze_event(bp_event)
    assert isinstance(decision, DispatchDecision)
    assert decision.severity == "moderate"


@pytest.mark.asyncio
async def test_synthesize_returns_action_plan(zhang_ayi_patient):
    notes = [
        {
            "agent_role": "nurse",
            "observation": "血压168/103明显高于目标",
            "recommendations": ["安静休息后复测"],
        }
    ]
    agent = FamilyDoctorAgent(make_runtime(default=ACTION_PLAN_JSON))
    plan = await agent.synthesize(notes, patient_context=zhang_ayi_patient)

    assert isinstance(plan, ActionPlan)
    assert plan.summary
    assert len(plan.actions) == 2
    assert plan.actions[0].type == "followup"
    assert plan.actions[1].assignee_role == "human_doctor"
    assert plan.patient_communication


@pytest.mark.asyncio
async def test_synthesize_degrades_aggregating_notes():
    notes = [{"agent_role": "nurse", "recommendations": ["复测血压", "确认服药"]}]
    agent = FamilyDoctorAgent(make_runtime(default="非法输出"))
    plan = await agent.synthesize(notes)
    assert isinstance(plan, ActionPlan)
    # 降级：把会诊建议聚合为行动项
    assert len(plan.actions) == 2


@pytest.mark.asyncio
async def test_execute_returns_agent_result(bp_event, zhang_ayi_patient):
    agent = FamilyDoctorAgent(make_runtime(default=DISPATCH_JSON))
    result = await agent.execute(
        patient_context=zhang_ayi_patient, event_data=bp_event
    )
    assert result.agent_role == "family_doctor"
    assert "dispatch_decision" in result.data
