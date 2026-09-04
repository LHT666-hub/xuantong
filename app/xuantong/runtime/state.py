"""玄同运行时状态。

使用 TypedDict + total=False，字段都是可选的。
使用 Pydantic 强类型模型，不用 dict。
"""

import operator
from typing import Annotated, Any, TypedDict

from app.schemas.action import ActionPlan, ExecutionResult, SafetyDecision
from app.schemas.agent import ConsultationNote, consultation_notes_reducer
from app.schemas.clinical import (
    ActionRiskAssessment,
    ClinicalContext,
    RiskAssessment,
)
from app.schemas.dispatch import DispatchDecision
from app.schemas.message import ChatMessage, add_chat_messages
from app.schemas.patient import PatientContext
from app.xuantong.rag.models import RAGContext


class XuantongState(TypedDict, total=False):
    """玄同图（LangGraph State）。

    所有字段可选；强类型由 Pydantic 模型保证。
    """

    # ── 患者信息（强类型）──────────────────────────────────
    patient_id: str
    patient_context: PatientContext
    clinical_context: ClinicalContext

    # ── 消息（玄同自有 ChatMessage）──────────────────────────
    messages: Annotated[list[ChatMessage], add_chat_messages]

    # ── 事件与来源─────────────────────────────────────────
    event_data: dict[str, Any]   # 原始健康事件数据（workflow 入口注入）
    channel: str        # changxi / doctor_workbench / admin_console / wecom / voice / system
    source: str
    actor_type: str     # patient / family / doctor / nurse / system
    actor_id: str

    # ── 并行会诊扇出（Send API 携带）──────────────────────────
    current_consult_agent: str   # 当前会诊分支对应的 Agent 角色

    # ── FamilyDoctorAgent 调度决策─────────────────────────
    dispatch_decision: DispatchDecision | None

    # ── 风险（拆分为两个维度）──────────────────────────────
    clinical_risk: RiskAssessment | None          # 由 domain/rules 产生
    action_risk: ActionRiskAssessment | None      # 由 Safety Layer 评估

    # ── 多 Agent 会诊结果──────────────────────────────────
    consultation_notes: Annotated[list[ConsultationNote], consultation_notes_reducer]

    # ── 行动计划与执行─────────────────────────────────────
    action_plan: ActionPlan | None
    generated_tasks: list[dict[str, Any]]   # task_gen_node 产出的任务清单
    execution_result: ExecutionResult | None  # AssistantAgent.execute_plan 产出

    # ── 安全───────────────────────────────────────────────
    safety_decision: SafetyDecision | None
    safety_retry_count: int
    human_required: bool
    human_reason: str

    # ── 多模态输入 ──────────────────────────────────────────
    image_data: str | None          # Base64 编码的图片
    image_type: str | None          # bp_monitor / medical_document / other
    audio_data: str | None          # Base64 编码的音频
    audio_type: str | None          # voice_report / other

    # ── 多模态内部路由标志（multimodal_detection 节点产出）──
    _has_image: bool
    _has_audio: bool

    # ── 多模态处理结果 ──────────────────────────────────────
    vision_result: dict | None      # VisionService 识别结果
    speech_text: str | None         # SpeechService 转写文本

    # ── 审计（reducer 追加，支持并行分支合并）──────────────
    flow_log: Annotated[list[dict[str, Any]], operator.add]

    # ── 记忆───────────────────────────────────────────────
    thread_id: str
    conversation_summary: str

    # ── RAG ──────────────────────────────────────────────────
    rag_context: RAGContext | None
