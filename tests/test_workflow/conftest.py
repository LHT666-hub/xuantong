"""Workflow 测试脚手架：可编程 Mock Provider 响应与 workflow 工厂。

通过 MockProvider(responses={关键词: JSON}) 精确控制每个 Agent 在每个提示词下的
结构化输出，从而稳定地驱动完整 LangGraph 流程（分析 → 并行会诊 → 综合 → 安检 → 执行）。
"""

import json

import pytest

from app.domain.rules.risk_classification import RiskRuleService
from app.xuantong.agents import register_all_agents
from app.xuantong.llm import LLMRuntime, MockProvider
from app.xuantong.runtime.registry import AgentRegistry
from app.xuantong.safety import (
    ActionGuard,
    HITLService,
    InputGuard,
    OutputGuard,
)
from app.xuantong.workflow import XuantongWorkflow


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ── 各 Agent 在各提示词下的结构化响应 ──────────────────────────
DISPATCH_JSON = _j(
    {
        "intent": "health_event_triage",
        "event_summary": "张阿姨血压168/103，伴头晕症状",
        "severity": "moderate",
        "selected_agents": ["nurse", "public_health", "pharmacist"],
        "reasoning": "血压明显升高伴症状，需护士、公卫、药师联合会诊",
        "immediate_actions": ["通知患者安静休息", "准备复测血压"],
        "requires_urgent_response": False,
    }
)

ACTION_PLAN_JSON = _j(
    {
        "summary": "张阿姨血压控制不佳，需加强监测与随访",
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
                "type": "education",
                "description": "低盐饮食与规律服药宣教",
                "assignee_role": "assistant",
                "priority": "medium",
            },
        ],
        "patient_communication": "张阿姨您好，您的血压有些偏高，建议安静休息并尽快复测。",
        "followup_plan": "3天后复测，如无改善建议门诊就诊",
    }
)

# 含转诊（referral）行动项的计划 —— 触发 ActionGuard HIGH → HITL
ACTION_PLAN_REFERRAL_JSON = _j(
    {
        "summary": "血压持续升高，建议转诊上级医院",
        "clinical_assessment": "血压控制不佳，需专科评估",
        "actions": [
            {
                "type": "referral",
                "description": "转诊至上级医院心内科",
                "assignee_role": "human_doctor",
                "priority": "high",
                "deadline_hours": 24,
            }
        ],
        "patient_communication": "张阿姨您好，建议尽快到医院进一步检查。",
        "followup_plan": "转诊后由专科随访",
    }
)

NURSE_JSON = _j(
    {
        "observation": "收缩压168mmHg、舒张压103mmHg，均明显高于目标值",
        "assessment": "血压控制不佳，伴头晕需警惕",
        "trend_analysis": "需对比历史数据确认急性或持续升高",
        "recommendations": ["安静休息后复测血压", "确认近期是否规律服药"],
        "red_flags": [],
        "confidence": 0.85,
    }
)

PUBLIC_HEALTH_JSON = _j(
    {
        "observation": "血压属高血压2级范围",
        "guideline_reference": "《国家基本公共卫生服务规范》",
        "management_level": "二级管理（中危）",
        "followup_requirement": "48小时内电话随访",
        "recommendations": ["48小时内安排电话随访", "缩短随访周期"],
        "referral_needed": False,
        "confidence": 0.8,
    }
)

PHARMACIST_JSON = _j(
    {
        "observation": "氨氯地平单药控制不佳",
        "medication_review": "评估依从性与剂量充足性",
        "assessment": "首先排查用药依从性",
        "recommendations": ["核实近一周是否规律服药"],
        "ddi_findings": [],
        "red_flags": [],
        "confidence": 0.8,
    }
)

ASSISTANT_JSON = _j(
    {
        "tasks": [
            {
                "title": "电话随访张阿姨血压情况",
                "description": "联系患者确认血压复测结果，询问头晕是否缓解",
                "assignee_type": "agent",
                "assignee_role": "assistant",
                "priority": "high",
                "deadline_hours": 24,
                "status": "pending",
            }
        ],
        "patient_message": "张阿姨您好，我是您的家庭医生团队助理，稍后会与您联系沟通后续安排。",
        "family_notification": None,
    }
)

# 关键词 → 响应（关键词取自各 Agent 提示词的稳定前缀）
HAPPY_RESPONSES: dict[str, str] = {
    "请分析以下健康事件": DISPATCH_JSON,
    "以下是团队各成员的会诊意见": ACTION_PLAN_JSON,
    "请从护理角度": NURSE_JSON,
    "请从公共卫生与慢病管理规范角度": PUBLIC_HEALTH_JSON,
    "请从临床药学角度": PHARMACIST_JSON,
    "以下是家庭医生制定的行动计划": ASSISTANT_JSON,
}


@pytest.fixture
def make_workflow():
    """workflow 工厂：按给定 responses 构建使用可编程 Mock 的 XuantongWorkflow。"""

    def _make(responses: dict[str, str] | None = None) -> XuantongWorkflow:
        llm = LLMRuntime(MockProvider(responses=dict(responses or {})))
        AgentRegistry.clear()
        register_all_agents(llm)
        return XuantongWorkflow(
            llm_runtime=llm,
            agent_registry=AgentRegistry,
            risk_service=RiskRuleService(),
            input_guard=InputGuard(),
            output_guard=OutputGuard(),
            action_guard=ActionGuard(),
            hitl_service=HITLService(),
        )

    yield _make
    AgentRegistry.clear()


@pytest.fixture
def bp_event():
    """张阿姨血压 168/103 + 头晕 事件。"""
    return {
        "event_type": "vital_sign_abnormal",
        "patient_id": "p-001",
        "measurements": [
            {
                "type": "blood_pressure",
                "value": 168,
                "secondary_value": 103,
                "unit": "mmHg",
            }
        ],
        "symptoms": ["头晕"],
    }


@pytest.fixture
def zhang_ayi_patient():
    from app.schemas.patient import MedicationInfo, PatientContext

    return PatientContext(
        patient_id="p-001",
        name="张阿姨",
        age=68,
        gender="女",
        chronic_diseases=["高血压", "2型糖尿病"],
        allergies=["青霉素"],
        current_medications=[
            MedicationInfo(drug_name="氨氯地平", dosage="5mg", frequency="qd")
        ],
        risk_level="yellow",
    )
