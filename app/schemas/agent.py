from pydantic import BaseModel
from enum import Enum


class AgentRole(str, Enum):
    FAMILY_DOCTOR = "family_doctor"
    NURSE = "nurse"
    PUBLIC_HEALTH = "public_health"
    ASSISTANT = "assistant"
    PHARMACIST = "pharmacist"
    TCM = "tcm"
    NUTRITION = "nutrition"
    REHABILITATION = "rehabilitation"


class AgentRequest(BaseModel):
    """发送给 Agent 的请求"""
    patient_id: str
    patient_context: dict  # will be PatientContext but avoid circular import
    clinical_context: dict
    messages: list[dict]
    task_description: str | None = None


class AgentResult(BaseModel):
    """Agent 执行结果"""
    agent_role: str
    agent_display_name: str
    summary: str
    findings: list[str] = []
    recommendations: list[str] = []
    risk_observation: str | None = None  # 专业观察，非权威风险等级
    data: dict = {}  # Agent 特定的结构化数据


class ConsultationNote(BaseModel):
    """多 Agent 会诊笔记。

    兼容两类来源：
    1. 既有精简字段（summary/findings/recommendations）——供 workflow 与 API 复用；
    2. LLM 结构化会诊产出（observation/assessment/... ）——由各专科 Agent 填充。
    除 agent_role 外均为可选，便于 LLM 输出解析与降级构造。
    """
    agent_role: str
    agent_display_name: str = ""
    summary: str = ""
    findings: list[str] = []
    recommendations: list[str] = []
    risk_observation: str | None = None  # 专业观察，非权威风险等级

    # ── LLM 结构化会诊细节（各专科 Agent 按需填充）─────────────
    observation: str | None = None       # 客观观察（指标解读等）
    assessment: str | None = None        # 专业评估
    trend_analysis: str | None = None    # 趋势分析（护士）
    red_flags: list[str] = []            # 危险信号
    confidence: float | None = None      # 置信度 0~1
    guideline_reference: str | None = None   # 指南引用（公卫）
    management_level: str | None = None      # 管理等级（公卫）
    followup_requirement: str | None = None  # 随访要求（公卫）
    referral_needed: bool | None = None      # 是否需转诊（公卫）
    referral_criteria: str | None = None     # 转诊标准（公卫）
    medication_review: str | None = None     # 用药审查（药师）
    ddi_findings: list[str] = []             # 药物相互作用发现（药师）
    data: dict = {}                          # 其它角色特定结构化数据


def consultation_notes_reducer(left: list, right: list) -> list:
    """Reducer for consultation_notes in XuantongState."""
    return left + right
