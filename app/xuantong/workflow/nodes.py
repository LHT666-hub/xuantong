"""玄同工作流节点实现。

本模块以 mixin 形式（WorkflowNodes）提供 XuantongWorkflow 的全部节点逻辑，
包括：三层 Guard 节点、FamilyDoctor 分析/调度/综合节点、Send 并行会诊节点、
确定性风险节点、HITL 节点、任务生成/执行节点与时间线节点，以及条件路由函数。

设计原则：
- 每个节点都是 async 函数，返回 dict（仅含要更新的 State 字段）。
- consultation_notes / flow_log 使用 reducer 合并（支持并行分支）。
- 节点内部异常不外抛中断图，尽量降级并记录 flow_log。
- 不直接操作数据库（Phase 2 后续任务做持久化）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from langgraph.types import Send

from app.domain.rules.risk_classification import RiskRuleService
from app.schemas.action import ActionItem, ActionPlan, SafetyDecision
from app.schemas.agent import AgentRole
from app.schemas.clinical import ClinicalContext, Measurement
from app.xuantong.runtime.state import XuantongState
from app.xuantong.safety import InputGuardAction, OutputGuardAction

logger = logging.getLogger(__name__)

# 可参与并行会诊的角色（consultation 阶段、具备 consult() 方法）。
# family_doctor 是调度者本身，assistant 属执行阶段，均不参与会诊扇出。
_NON_CONSULT_ROLES = {"family_doctor", "assistant"}

# ActionItem.type → ActionGuard 动作类型映射。
# ActionGuard 的规则表以具体动作命名（如 schedule_followup），
# 而 FamilyDoctor 综合产出的行动项以类别命名（如 followup），需在此桥接。
_ACTION_TYPE_TO_GUARD: dict[str, str] = {
    "followup": "schedule_followup",
    "monitoring": "schedule_followup",
    "medication_review": "suggest_medication_change",
    "referral": "suggest_referral",
    "education": "send_health_education",
    "alert": "send_reminder",
}

# InputGuard 命中危机时下发的患者可见文本（温和、不制造恐慌）。
_EMERGENCY_PATIENT_TEXT = (
    "我们已收到您的紧急情况，正在第一时间为您联系急救与家庭医生团队，"
    "请保持电话畅通，如情况危急请立即拨打 120。"
)


class WorkflowNodes:
    """XuantongWorkflow 的节点方法集合（mixin）。

    依赖以下实例属性（由 XuantongWorkflow.__init__ 注入）：
    llm_runtime / agent_registry / risk_service /
    input_guard / output_guard / action_guard / hitl_service。
    """

    # ══════════════════════════════════════════════════════════
    # 通用辅助
    # ══════════════════════════════════════════════════════════

    def _get_agent(self, role: str) -> Any:
        """从注册表按角色取 Agent 实例（兼容 get_instance / get_agent）。"""
        reg = self.agent_registry
        getter = getattr(reg, "get_instance", None) or getattr(reg, "get_agent", None)
        if getter is None:
            return None
        return getter(role)

    def _is_consultable(self, role: str) -> bool:
        """判断角色是否可参与并行会诊（已实现且具备 consult 方法）。"""
        if role in _NON_CONSULT_ROLES:
            return False
        agent = self._get_agent(role)
        if agent is None or not callable(getattr(agent, "consult", None)):
            return False
        get_def = getattr(self.agent_registry, "get", None)
        if get_def is not None:
            definition = get_def(role)
            if definition is not None and not getattr(definition, "implemented", True):
                return False
        return True

    @staticmethod
    def _role_value(role: Any) -> str:
        """将 AgentRole 枚举或字符串统一为字符串角色值。"""
        return getattr(role, "value", role) if not isinstance(role, str) else role

    @staticmethod
    def _entry(node: str, **fields: Any) -> dict[str, Any]:
        """构造一条 flow_log 审计条目。"""
        return {
            "node": node,
            "ts": datetime.now(timezone.utc).isoformat(),
            **fields,
        }

    @staticmethod
    def _parse_dt(value: Any) -> datetime:
        """稳健解析时间；缺失或非法时回退为当前时间。"""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    def _extract_input_text(self, state: XuantongState) -> str:
        """从 State 提取待安检的输入文本（优先消息，其次事件文本/症状）。"""
        messages = state.get("messages") or []
        if messages:
            content = getattr(messages[-1], "content", None)
            if content:
                return str(content)

        event = state.get("event_data") or {}
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        parts: list[str] = []
        for key in ("text", "content", "message", "chief_complaint"):
            for src in (event, payload):
                value = src.get(key) if isinstance(src, dict) else None
                if isinstance(value, str) and value:
                    parts.append(value)
        symptoms = event.get("symptoms") or (
            payload.get("symptoms") if isinstance(payload, dict) else None
        )
        if isinstance(symptoms, list):
            parts.extend(str(s) for s in symptoms)
        return "\n".join(parts)

    def _clinical_context_from_event(self, event_data: dict[str, Any]) -> ClinicalContext:
        """从事件数据构造 ClinicalContext（用于确定性风险评估）。"""
        event_data = event_data or {}
        payload = event_data.get("payload") if isinstance(event_data.get("payload"), dict) else {}
        raw = event_data.get("measurements") or (
            payload.get("measurements") if isinstance(payload, dict) else None
        ) or []

        measurements: list[Measurement] = []
        for m in raw:
            if isinstance(m, Measurement):
                measurements.append(m)
                continue
            if not isinstance(m, dict):
                continue
            try:
                secondary = m.get("secondary_value")
                measurements.append(
                    Measurement(
                        type=str(m.get("type", "")),
                        value=float(m.get("value", 0)),
                        unit=str(m.get("unit", "")),
                        secondary_value=float(secondary) if secondary is not None else None,
                        measured_at=self._parse_dt(m.get("measured_at")),
                    )
                )
            except (TypeError, ValueError) as e:
                logger.warning(f"workflow: 测量值解析失败已跳过: {e}")

        symptoms_raw = event_data.get("symptoms") or (
            payload.get("symptoms") if isinstance(payload, dict) else None
        ) or []
        symptoms = [str(s) for s in symptoms_raw]
        return ClinicalContext(latest_measurements=measurements, symptoms=symptoms)

    # ══════════════════════════════════════════════════════════
    # 节点：多模态检测 / 图片分析 / 语音转写
    # ══════════════════════════════════════════════════════════

    async def _multimodal_detection_node(self, state: XuantongState) -> dict:
        """检测输入类型（文本/图片/音频），设置路由标志。"""
        event_data = state.get("event_data") or {}
        payload = event_data.get("payload") if isinstance(event_data.get("payload"), dict) else {}

        has_image = bool(
            payload.get("image_data")
            or payload.get("image_url")
            or event_data.get("image_data")
            or event_data.get("image_url")
        )
        has_audio = bool(
            payload.get("audio_data")
            or payload.get("audio_url")
            or event_data.get("audio_data")
            or event_data.get("audio_url")
        )

        return {
            "image_data": payload.get("image_data") or event_data.get("image_data"),
            "image_type": payload.get("image_type") or event_data.get("image_type"),
            "audio_data": payload.get("audio_data") or event_data.get("audio_data"),
            "audio_type": payload.get("audio_type") or event_data.get("audio_type"),
            "flow_log": [
                self._entry(
                    "multimodal_detection",
                    has_image=has_image,
                    has_audio=has_audio,
                )
            ],
            # 临时标志字段，供条件路由使用
            "_has_image": has_image,
            "_has_audio": has_audio,
        }

    async def _image_analysis_node(self, state: XuantongState) -> dict:
        """调用 VisionService 分析图片。"""
        from app.xuantong.llm.vision import VisionService

        vision_service = VisionService(self.llm_runtime)
        event_data = dict(state.get("event_data") or {})
        payload = dict(event_data.get("payload") or {})
        image_data = state.get("image_data") or payload.get("image_data") or payload.get("image_url")
        image_type = state.get("image_type") or payload.get("image_type", "other")

        try:
            if image_type == "bp_monitor":
                result = await vision_service.recognize_bp_monitor(image_data)
                payload["systolic"] = result.systolic
                payload["diastolic"] = result.diastolic
                payload["pulse"] = result.pulse
                payload["source"] = "vision_recognition"
                payload["confidence"] = result.confidence
            elif image_type == "medical_document":
                text = await vision_service.ocr_medical_document(image_data)
                payload["text"] = text
                payload["source"] = "vision_ocr"
            else:
                analysis = await vision_service.analyze_image(image_data, "描述这张图片的内容")
                payload["image_description"] = analysis
                payload["source"] = "vision_analysis"

            event_data["payload"] = payload
            return {
                "event_data": event_data,
                "vision_result": {"status": "success", "image_type": image_type},
                "flow_log": [self._entry("image_analysis", image_type=image_type, status="success")],
            }
        except Exception as e:
            logger.error(f"image_analysis_node failed: {e}")
            return {
                "vision_result": {"status": "error", "message": str(e)},
                "flow_log": [self._entry("image_analysis", status="error", error=str(e))],
            }

    async def _speech_transcription_node(self, state: XuantongState) -> dict:
        """调用 SpeechService 转写音频。"""
        from app.xuantong.llm.speech import SpeechService

        speech_service = SpeechService(self.llm_runtime)
        event_data = dict(state.get("event_data") or {})
        payload = dict(event_data.get("payload") or {})
        audio_data = state.get("audio_data") or payload.get("audio_data") or payload.get("audio_url")

        try:
            result = await speech_service.transcribe(audio_data, language_hints=["zh"])
            payload["text"] = result.text
            if result.emotion:
                payload["emotion"] = result.emotion
            payload["source"] = "speech_transcription"
            event_data["payload"] = payload
            return {
                "event_data": event_data,
                "speech_text": result.text,
                "flow_log": [
                    self._entry(
                        "speech_transcription",
                        status="success",
                        text_length=len(result.text),
                    )
                ],
            }
        except Exception as e:
            logger.error(f"speech_transcription_node failed: {e}")
            return {
                "speech_text": None,
                "flow_log": [self._entry("speech_transcription", status="error", error=str(e))],
            }

    def _route_after_multimodal(self, state: XuantongState) -> str:
        """多模态检测后路由：图片 → image_analysis；音频 → speech_transcription；否则 → input_guard。"""
        if state.get("_has_image"):
            return "image"
        if state.get("_has_audio"):
            return "audio"
        return "text"

    # ══════════════════════════════════════════════════════════
    # 节点：输入安全 / 紧急
    # ══════════════════════════════════════════════════════════

    async def _input_guard_node(self, state: XuantongState) -> dict:
        """输入安全检查：危机 → emergency；注入/超长 → block；否则 pass。"""
        text = self._extract_input_text(state)
        result = self.input_guard.check(text)

        if result.action == InputGuardAction.EMERGENCY:
            decision = SafetyDecision(
                input_ok=False,
                output_action="emergency",
                reasons=[result.reason],
            )
        elif result.action == InputGuardAction.BLOCK:
            decision = SafetyDecision(
                input_ok=False,
                output_action="reject",
                reasons=[result.reason],
            )
        else:
            decision = SafetyDecision(input_ok=True, output_action="pass")

        return {
            "safety_decision": decision,
            "flow_log": [
                self._entry(
                    "input_guard",
                    action=result.action.value,
                    reason=result.reason,
                    emergency_type=result.emergency_type,
                )
            ],
        }

    async def _emergency_node(self, state: XuantongState) -> dict:
        """危机路径：直接生成紧急行动计划，标记需人工，跳过常规会诊。"""
        decision = state.get("safety_decision")
        reason = "; ".join(decision.reasons) if decision and decision.reasons else "检测到危机信号"

        plan = ActionPlan(
            summary="紧急事件：已触发危机响应通道",
            clinical_assessment=reason,
            actions=[
                ActionItem(
                    type="alert",
                    description="立即通知人工/紧急响应团队介入",
                    assignee_role="human_doctor",
                    priority="high",
                )
            ],
            patient_communication=_EMERGENCY_PATIENT_TEXT,
            followup_plan="紧急人工介入，跳过常规多 Agent 会诊流程。",
        )
        return {
            "action_plan": plan,
            "human_required": True,
            "human_reason": reason,
            "flow_log": [self._entry("emergency", reason=reason)],
        }

    def _route_after_input_guard(self, state: XuantongState) -> str:
        """输入安检后路由：危机 → emergency；RAG 启用 → rag_retrieval；其余 → analyze。"""
        decision = state.get("safety_decision")
        if decision is not None and decision.output_action == "emergency":
            return "emergency"
        # RAG 启用时先检索知识
        rag_loop = getattr(self, "rag_loop", None)
        rag_enabled = getattr(self, "rag_enabled", True)
        if rag_loop is not None and rag_enabled:
            return "rag_retrieval"
        return "analyze"

    # ══════════════════════════════════════════════════════════
    # 节点：RAG 检索
    # ══════════════════════════════════════════════════════════

    async def _rag_retrieval_node(self, state: XuantongState) -> dict:
        """RAG 检索节点 — 在分析前检索相关知识。"""
        rag_loop = getattr(self, "rag_loop", None)
        if rag_loop is None:
            return {"flow_log": [self._entry("rag_retrieval", skipped=True, reason="no_rag_loop")]}

        event_data = state.get("event_data") or {}
        query = self._extract_rag_query(event_data)

        if not query:
            return {"flow_log": [self._entry("rag_retrieval", skipped=True, reason="empty_query")]}

        try:
            from app.xuantong.rag.models import RAGContext

            result = await rag_loop.run(query)

            if result.success and result.documents:
                rag_context = RAGContext(
                    retrieved_docs=[doc.content for doc in result.documents],
                    confidence=(
                        sum(doc.score for doc in result.documents) / len(result.documents)
                        if result.documents else 0.0
                    ),
                    sources=[doc.source for doc in result.documents if doc.source],
                )
                return {
                    "rag_context": rag_context,
                    "flow_log": [
                        self._entry(
                            "rag_retrieval",
                            success=True,
                            doc_count=len(result.documents),
                            attempts=result.attempts,
                            query=result.query[:60],
                        )
                    ],
                }

            return {
                "flow_log": [
                    self._entry(
                        "rag_retrieval",
                        success=False,
                        attempts=result.attempts,
                        query=result.query[:60],
                    )
                ],
            }
        except Exception as e:
            logger.error("rag_retrieval_node failed: %s", e)
            return {
                "flow_log": [self._entry("rag_retrieval", status="error", error=str(e))],
            }

    def _extract_rag_query(self, event_data: dict[str, Any]) -> str:
        """从事件数据中提取 RAG 查询文本。"""
        payload = event_data.get("payload") if isinstance(event_data.get("payload"), dict) else {}
        parts: list[str] = []

        # 提取主诉/症状
        for key in ("chief_complaint", "text", "content", "message"):
            for src in (event_data, payload):
                value = src.get(key) if isinstance(src, dict) else None
                if isinstance(value, str) and value:
                    parts.append(value)

        symptoms = event_data.get("symptoms") or (
            payload.get("symptoms") if isinstance(payload, dict) else None
        )
        if isinstance(symptoms, list):
            parts.extend(str(s) for s in symptoms)

        return " ".join(parts).strip()

    # ══════════════════════════════════════════════════════════
    # 节点：分析 / 调度 / 并行会诊 / 综合
    # ══════════════════════════════════════════════════════════

    async def _analyze_node(self, state: XuantongState) -> dict:
        """FamilyDoctorAgent 分析事件，产出 DispatchDecision。"""
        agent = self._get_agent("family_doctor")
        event_data = state.get("event_data") or {}
        patient_context = state.get("patient_context")

        if agent is None:
            logger.error("workflow: family_doctor 未注册，无法分析事件")
            return {"flow_log": [self._entry("analyze", error="family_doctor_missing")]}

        decision = await agent.analyze_event(
            event_data, patient_context, state.get("clinical_risk")
        )
        return {
            "dispatch_decision": decision,
            "flow_log": [
                self._entry(
                    "analyze",
                    severity=decision.severity,
                    selected_agents=[self._role_value(a) for a in decision.selected_agents],
                )
            ],
        }

    async def _dispatch_node(self, state: XuantongState) -> dict:
        """调度归一化节点。

        analyze_event 已同时完成分析与团队选择（dispatch_team 为其语义别名，
        产出同为 DispatchDecision），故此处不再重复调用 LLM，仅校验/兜底决策，
        并记录最终参与会诊的团队，供下游 Send 扇出使用。
        """
        decision = state.get("dispatch_decision")
        if decision is None:
            logger.warning("workflow: 缺少 dispatch_decision，跳过会诊扇出")
            return {"flow_log": [self._entry("dispatch", fallback=True)]}

        consult_roles = [
            self._role_value(a)
            for a in decision.selected_agents
            if self._is_consultable(self._role_value(a))
        ]
        return {
            "flow_log": [
                self._entry(
                    "dispatch",
                    severity=decision.severity,
                    consult_roles=consult_roles,
                    urgent=decision.requires_urgent_response,
                )
            ]
        }

    def _route_to_consult(self, state: XuantongState) -> Any:
        """按 DispatchDecision 动态并行扇出到选中的会诊 Agent。

        使用 LangGraph Send API：为每个可会诊角色生成一个携带独立 payload 的
        Send("consult", ...)。consultation_notes 的 reducer 会自动合并各分支结果。
        无可会诊角色时直接路由到 synthesis。
        """
        decision = state.get("dispatch_decision")
        roles: list[str] = []
        if decision is not None:
            for a in decision.selected_agents:
                role = self._role_value(a)
                if self._is_consultable(role) and role not in roles:
                    roles.append(role)

        if not roles:
            return "synthesis"

        base = {
            "event_data": state.get("event_data") or {},
            "patient_context": state.get("patient_context"),
            "clinical_context": state.get("clinical_context"),
        }
        return [
            Send("consult", {**base, "current_consult_agent": role}) for role in roles
        ]

    async def _consult_node(self, state: XuantongState) -> dict:
        """单个 Agent 会诊分支（被 Send 并行调用多次）。"""
        role = state.get("current_consult_agent")
        agent = self._get_agent(role) if role else None
        if agent is None or not callable(getattr(agent, "consult", None)):
            logger.warning(f"workflow: 会诊角色 {role!r} 不可用，跳过")
            return {"flow_log": [self._entry("consult", role=role, skipped=True)]}

        note = await agent.consult(
            state.get("event_data") or {}, state.get("patient_context")
        )
        return {
            "consultation_notes": [note],
            "flow_log": [self._entry("consult", role=role, summary=note.summary)],
        }

    async def _synthesis_node(self, state: XuantongState) -> dict:
        """FamilyDoctorAgent 综合各方会诊意见，产出 ActionPlan。"""
        agent = self._get_agent("family_doctor")
        notes = state.get("consultation_notes") or []
        if agent is None:
            logger.error("workflow: family_doctor 未注册，无法综合决策")
            return {"flow_log": [self._entry("synthesis", error="family_doctor_missing")]}

        plan = await agent.synthesize(
            notes,
            state.get("event_data"),
            state.get("patient_context"),
            state.get("clinical_risk"),
        )
        return {
            "action_plan": plan,
            "flow_log": [
                self._entry("synthesis", note_count=len(notes), actions=len(plan.actions))
            ],
        }

    # ══════════════════════════════════════════════════════════
    # 节点：确定性风险 / 输出安全 / 动作安全 / HITL
    # ══════════════════════════════════════════════════════════

    async def _risk_node(self, state: XuantongState) -> dict:
        """RiskRuleService 产生权威 clinical_risk（唯一临床风险来源）。"""
        clinical_context = state.get("clinical_context")
        if clinical_context is None:
            clinical_context = self._clinical_context_from_event(state.get("event_data") or {})

        service = self.risk_service or RiskRuleService
        risk = service.evaluate(clinical_context)
        return {
            "clinical_risk": risk,
            "clinical_context": clinical_context,
            "flow_log": [
                self._entry(
                    "risk_assessment",
                    level=risk.level,
                    score=risk.score,
                    triggers=risk.trigger_indicators,
                )
            ],
        }

    async def _output_guard_node(self, state: XuantongState) -> dict:
        """OutputGuard 检查 synthesis 产出的患者可见文本（4 态处置）。"""
        plan = state.get("action_plan")
        updates: dict[str, Any] = {"flow_log": [self._entry("output_guard", action="pass")]}
        if plan is None or not plan.patient_communication:
            return updates

        result = self.output_guard.check(plan.patient_communication, "family_doctor")
        if result.action == OutputGuardAction.REWRITE and result.rewritten_content:
            plan.patient_communication = result.rewritten_content
            if plan.reply:
                plan.reply = result.rewritten_content
        elif result.action == OutputGuardAction.BLOCK:
            plan.patient_communication = "您的情况我们已记录，家庭医生团队会尽快与您联系，请留意后续通知。"
            if plan.reply:
                plan.reply = plan.patient_communication
        # ESCALATE：保留原文但记录，需人工医生审核（不阻断流程）。

        updates["action_plan"] = plan
        updates["flow_log"] = [
            self._entry(
                "output_guard",
                action=result.action.value,
                reason=result.reason,
                violations=result.violations,
            )
        ]
        return updates

    async def _action_guard_node(self, state: XuantongState) -> dict:
        """ActionGuard 评估动作风险，决定是否需人工介入（HITL）。"""
        plan = state.get("action_plan")
        guard_actions: list[str] = []
        if plan is not None:
            for item in plan.actions:
                guard_actions.append(
                    _ACTION_TYPE_TO_GUARD.get(item.type, item.type)
                )

        clinical_risk = state.get("clinical_risk")
        clinical_level = clinical_risk.level if clinical_risk is not None else "green"

        result = self.action_guard.check(guard_actions, clinical_level)
        action_risk = self.action_guard.to_action_risk_assessment(result)

        return {
            "action_risk": action_risk,
            "human_required": result.requires_human,
            "human_reason": "; ".join(result.reasons) if result.requires_human else "",
            "flow_log": [
                self._entry(
                    "action_guard",
                    level=result.level.value,
                    requires_human=result.requires_human,
                    blocked_actions=result.blocked_actions,
                )
            ],
        }

    def _route_after_action_guard(self, state: XuantongState) -> str:
        """动作安检后路由：需人工 → hitl；否则 → task_generation。"""
        return "hitl" if state.get("human_required") else "task_generation"

    async def _hitl_node(self, state: XuantongState) -> dict:
        """登记人工审核请求（暂停等待审批，Phase 2 记录待审队列后继续）。"""
        plan = state.get("action_plan")
        description = plan.summary if plan and plan.summary else "高风险动作待人工审核"
        action_risk = state.get("action_risk")
        risk_level = action_risk.level if action_risk is not None else "high"
        task_id = f"hitl-{uuid4().hex[:12]}"

        record = None
        if self.hitl_service is not None:
            try:
                record = await self.hitl_service.request_review(
                    task_id=task_id,
                    action_description=description,
                    risk_level=risk_level,
                )
            except Exception as e:  # HITL 登记失败不应中断主流程
                logger.error(f"workflow: HITL 登记失败: {e}")

        return {
            "flow_log": [
                self._entry(
                    "hitl",
                    task_id=task_id,
                    risk_level=risk_level,
                    registered=record is not None,
                    reason=state.get("human_reason", ""),
                )
            ]
        }

    # ══════════════════════════════════════════════════════════
    # 节点：任务生成 / 执行 / 时间线
    # ══════════════════════════════════════════════════════════

    async def _task_gen_node(self, state: XuantongState) -> dict:
        """将 ActionPlan.actions 转为任务清单（Phase 2 暂不落地数据库）。"""
        plan = state.get("action_plan")
        requires_human = bool(state.get("human_required"))
        # 会改变患者日程或触发后续服务的动作必须先由患者确认。
        # 健康教育等只读内容可以直接记录；人工审核事项仍优先进入 pending_human。
        patient_consent_types = {
            "followup",
            "monitoring",
            "medication_review",
            "referral",
            "appointment",
            "reminder",
        }
        tasks: list[dict[str, Any]] = []
        if plan is not None:
            for item in plan.actions:
                needs_consent = item.type in patient_consent_types
                tasks.append(
                    {
                        "id": f"task-{uuid4().hex[:12]}",
                        "task_type": item.type,
                        "description": item.description,
                        "assignee_role": item.assignee_role or "assistant",
                        "priority": item.priority,
                        "deadline_hours": item.deadline_hours,
                        "status": (
                            "pending_human"
                            if requires_human
                            else "proposed"
                            if needs_consent
                            else "pending"
                        ),
                    }
                )
        return {
            "generated_tasks": tasks,
            "flow_log": [self._entry("task_generation", count=len(tasks))],
        }

    async def _execute_node(self, state: XuantongState) -> dict:
        """AssistantAgent 拆解行动计划为可执行任务并生成患者沟通文本。"""
        plan = state.get("action_plan")
        if plan is None:
            return {"flow_log": [self._entry("execution", skipped=True)]}

        agent = self._get_agent("assistant")
        if agent is None or not callable(getattr(agent, "execute_plan", None)):
            logger.warning("workflow: assistant 不可用，跳过执行拆解")
            return {"flow_log": [self._entry("execution", skipped=True, reason="assistant_missing")]}

        result = await agent.execute_plan(plan, state.get("patient_context"))
        return {
            "execution_result": result,
            "flow_log": [
                self._entry("execution", task_count=len(result.tasks))
            ],
        }

    async def _timeline_node(self, state: XuantongState) -> dict:
        """汇总本次 workflow 关键节点，写入一条时间线审计条目。"""
        decision = state.get("dispatch_decision")
        risk = state.get("clinical_risk")
        plan = state.get("action_plan")
        execution = state.get("execution_result")

        summary = {
            "severity": decision.severity if decision else None,
            "clinical_risk": risk.level if risk else None,
            "consultations": len(state.get("consultation_notes") or []),
            "actions": len(plan.actions) if plan else 0,
            "execution_tasks": len(execution.tasks) if execution else 0,
            "human_required": bool(state.get("human_required")),
        }
        return {
            "flow_log": [self._entry("timeline", **summary)],
        }


__all__ = ["WorkflowNodes", "AgentRole"]
