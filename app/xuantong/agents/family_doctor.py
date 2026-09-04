"""家庭医生主 Agent — 数字化家庭医生团队的统一入口和团队负责人。

职责：分析事件 → 选择团队成员 → 综合决策。
模型：qwen3-max（由 LLMRuntime 依据 agent_role="family_doctor" 自动路由到 lead 层级）。

对外方法：
- analyze_event(): 分析健康事件，产出 DispatchDecision（严重程度 + 团队调度）。
- dispatch_team(): 团队调度（委托 analyze_event，语义化别名）。
- synthesize():   综合各方 ConsultationNote，产出 ActionPlan。
- execute():      基类通用入口，内部路由到 analyze_event 并回包 AgentResult。
"""

import logging

from app.schemas.action import ActionItem, ActionPlan
from app.schemas.agent import AgentResult, AgentRole, ConsultationNote
from app.schemas.clinical import ClinicalContext, RiskAssessment
from app.schemas.dispatch import DispatchDecision
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent

logger = logging.getLogger(__name__)

# 合法的团队成员取值（用于过滤 LLM 输出，避免枚举校验失败）
_VALID_ROLES = {r.value for r in AgentRole}

_DISPATCH_SCHEMA = """{
  "event_summary": "张阿姨血压168/103，伴头晕症状",
  "severity": "moderate",
  "selected_agents": ["nurse", "public_health"],
  "reasoning": "血压明显升高伴症状，需要护士做趋势分析，公卫医师判断随访计划",
  "immediate_actions": ["通知患者保持安静", "准备复测血压"],
  "requires_urgent_response": false
}"""

_ACTION_PLAN_SCHEMA = """{
  "summary": "张阿姨血压控制不佳，需加强监测和随访",
  "clinical_assessment": "血压168/103属2级高血压范围，伴头晕症状……",
  "actions": [
    {
      "type": "followup",
      "description": "安排3天内复诊测血压",
      "assignee_role": "assistant",
      "priority": "high",
      "deadline_hours": 72
    }
  ],
  "patient_communication": "张阿姨您好，您的血压有些偏高……",
  "followup_plan": "3天后复测，如无改善建议门诊就诊"
}"""


class FamilyDoctorAgent(BaseAgent):
    """团队负责人 / 统一入口。

    职责：分析事件 → 选择团队成员 → 综合决策。
    """

    role = "family_doctor"
    display_name = "家庭医生"
    description = "团队负责人/统一入口：分析事件，选择团队成员，综合决策"
    max_llm_calls = 5   # 调度 + 综合可能需要多次

    SYSTEM_PROMPT = """你是一位经验丰富的家庭医生，作为数字化医疗团队的负责人。

你的职责：
1. 分析患者上报的健康事件（血压、血糖、症状等）
2. 判断事件严重程度，决定需要哪些团队成员参与会诊
3. 综合团队意见，制定后续行动计划

重要原则：
- 你不直接给患者诊断，而是协调团队提供专业意见
- 风险评估由规则引擎完成，你负责解读和决策
- 紧急情况下优先保障患者安全
- 所有建议必须符合基层医疗规范

你可以调用的团队成员：
- nurse: 护士（指标解读、趋势分析、专业观察）
- public_health: 公卫医师（随访管理、慢病管理规范）
- pharmacist: 药师（用药安全、药物相互作用）
- assistant: 家医助理（联系患者、预约、提醒、协调执行）

输出格式要求：严格按 JSON 格式输出，只输出一个 JSON 对象，不要包含 markdown 代码块或任何额外文字。

注意：请简洁高效地分析，避免过度思考。重点关注：
1. 事件严重程度
2. 需要哪些团队成员
3. 关键行动建议
"""

    # ────────────────────────────────────────────────────────
    # 事件分析与团队调度
    # ────────────────────────────────────────────────────────

    async def analyze_event(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
        clinical_risk: RiskAssessment | dict | None = None,
    ) -> DispatchDecision:
        """分析健康事件，判断严重程度并决定参与会诊的团队成员。

        Args:
            event_data: 事件数据（指标、症状、来源等）。
            patient_context: 患者上下文（可选）。
            clinical_risk: 规则引擎给出的权威风险等级（可选，仅供解读）。

        Returns:
            DispatchDecision。LLM 不可用或输出非法时返回保守降级决策。
        """
        self._reset_counters()

        user_content = (
            "请分析以下健康事件，判断严重程度并决定需要哪些团队成员参与会诊。\n\n"
            f"【患者信息】\n{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【事件数据】\n{self._dumps(event_data)}\n\n"
            f"【规则引擎风险评估（权威，供你解读）】\n"
            f"{self._dumps(self._to_plain(clinical_risk) or '未提供')}\n\n"
            "【输出格式】严格输出如下结构的 JSON（severity 取值 low/moderate/high/emergency；"
            "selected_agents 仅从 nurse/public_health/pharmacist/assistant 中选择）：\n"
            f"{_DISPATCH_SCHEMA}"
        )

        # 分诊场景不需要深度思考，关闭 enable_thinking 以加速响应
        data = await self._invoke_json(user_content, enable_thinking=False)
        if data is None:
            return self._degraded_dispatch(event_data)

        agents = [a for a in data.get("selected_agents", []) if a in _VALID_ROLES]
        severity = data.get("severity", "moderate")
        if severity not in {"low", "moderate", "high", "emergency"}:
            severity = "moderate"

        return DispatchDecision(
            intent=data.get("intent", "health_event_triage"),
            event_summary=data.get("event_summary", ""),
            severity=severity,
            selected_agents=agents,
            reasoning=data.get("reasoning", ""),
            reason=data.get("reasoning", ""),
            immediate_actions=[str(x) for x in data.get("immediate_actions", [])],
            requires_urgent_response=bool(data.get("requires_urgent_response", False)),
        )

    async def dispatch_team(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
        clinical_risk: RiskAssessment | dict | None = None,
    ) -> DispatchDecision:
        """决定哪些团队成员参与会诊。

        语义化别名，委托 analyze_event（二者产出同为 DispatchDecision）。
        """
        return await self.analyze_event(event_data, patient_context, clinical_risk)

    def _degraded_dispatch(self, event_data: dict) -> DispatchDecision:
        """LLM 不可用时的保守降级调度：默认转护士 + 家医助理跟进。"""
        logger.warning(f"{self.display_name}: 事件分析降级，使用默认调度")
        return DispatchDecision(
            intent="health_event_triage",
            event_summary="（模型不可用，未能生成事件摘要，请人工复核）",
            severity="moderate",
            selected_agents=[AgentRole.NURSE, AgentRole.ASSISTANT],
            reasoning="LLM 调用失败或输出非法，已降级为默认调度：护士评估 + 家医助理跟进。",
            reason="降级默认调度",
            immediate_actions=["建议人工复核该事件"],
            requires_urgent_response=False,
        )

    # ────────────────────────────────────────────────────────
    # 综合决策
    # ────────────────────────────────────────────────────────

    async def synthesize(
        self,
        consultation_notes: list[ConsultationNote | dict],
        event_data: dict | None = None,
        patient_context: PatientContext | dict | None = None,
        clinical_risk: RiskAssessment | dict | None = None,
    ) -> ActionPlan:
        """综合各方会诊意见，生成后续行动计划。

        Args:
            consultation_notes: 各专科 Agent 的会诊笔记。
            event_data: 原始事件数据（可选）。
            patient_context: 患者上下文（可选）。
            clinical_risk: 规则引擎权威风险等级（可选）。

        Returns:
            ActionPlan。LLM 不可用时返回由会诊建议聚合而成的降级计划。
        """
        self._reset_counters()

        notes_plain = [self._to_plain(n) for n in (consultation_notes or [])]

        user_content = (
            "以下是团队各成员的会诊意见，请综合形成一份后续行动计划。\n\n"
            f"【患者信息】\n{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【原始事件】\n{self._dumps(event_data or '无')}\n\n"
            f"【规则引擎风险评估（权威）】\n"
            f"{self._dumps(self._to_plain(clinical_risk) or '未提供')}\n\n"
            f"【团队会诊意见】\n{self._dumps(notes_plain)}\n\n"
            "【输出格式】严格输出如下结构的 JSON（actions[].type 取 followup/monitoring/"
            "medication_review/referral/education/alert；priority 取 low/medium/high）：\n"
            f"{_ACTION_PLAN_SCHEMA}"
        )

        data = await self._invoke_json(user_content, enable_thinking=True)
        if data is None:
            return self._degraded_plan(notes_plain)

        actions = self._parse_actions(data.get("actions", []))
        patient_communication = self._guard_patient_text(
            data.get("patient_communication", "") or ""
        )

        return ActionPlan(
            summary=data.get("summary", ""),
            clinical_assessment=data.get("clinical_assessment", ""),
            actions=actions,
            patient_communication=patient_communication,
            followup_plan=data.get("followup_plan", ""),
            reply=patient_communication or None,
        )

    def _parse_actions(self, raw_actions: list) -> list[ActionItem]:
        """解析并校验行动项，跳过非法条目。"""
        actions: list[ActionItem] = []
        for item in raw_actions or []:
            if not isinstance(item, dict):
                continue
            try:
                actions.append(
                    ActionItem(
                        type=str(item.get("type", "followup")),
                        description=str(item.get("description", "")),
                        assignee_role=item.get("assignee_role"),
                        priority=str(item.get("priority", "medium")),
                        deadline_hours=item.get("deadline_hours"),
                    )
                )
            except Exception as e:  # 单条非法不影响整体
                logger.warning(f"{self.display_name}: 行动项解析失败已跳过: {e}")
        return actions

    def _degraded_plan(self, notes_plain: list[dict]) -> ActionPlan:
        """LLM 不可用时，聚合会诊建议形成最小可执行计划。"""
        logger.warning(f"{self.display_name}: 综合决策降级，聚合会诊建议")
        recommendations: list[str] = []
        for note in notes_plain:
            recommendations.extend(note.get("recommendations", []) or [])

        actions = [
            ActionItem(
                type="followup",
                description=rec,
                assignee_role="assistant",
                priority="medium",
                deadline_hours=72,
            )
            for rec in recommendations[:5]
        ]
        return ActionPlan(
            summary="（模型不可用，已根据团队会诊建议生成降级行动计划）",
            clinical_assessment="",
            actions=actions,
            patient_communication="您的情况我们已记录，家庭医生团队会尽快与您联系。",
            followup_plan="由家医助理安排后续随访。",
        )

    # ────────────────────────────────────────────────────────
    # 基类通用入口
    # ────────────────────────────────────────────────────────

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs,
    ) -> AgentResult:
        """通用入口：分析事件并回包 AgentResult（含调度决策）。"""
        event_data = kwargs.get("event_data") or self._clinical_to_event(clinical_context)
        clinical_risk = kwargs.get("clinical_risk")

        decision = await self.analyze_event(event_data, patient_context, clinical_risk)

        return AgentResult(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=decision.event_summary or f"[{self.display_name}] 已完成事件分析与调度",
            findings=[f"严重程度: {decision.severity}", decision.reasoning]
            if decision.reasoning
            else [f"严重程度: {decision.severity}"],
            recommendations=decision.immediate_actions,
            data={"dispatch_decision": decision.model_dump(mode="json")},
        )

    @staticmethod
    def _clinical_to_event(clinical_context: ClinicalContext | None) -> dict:
        """将 ClinicalContext 转为事件数据 dict（供 execute 复用）。"""
        if clinical_context is None:
            return {}
        return {
            "measurements": clinical_context.model_dump(mode="json").get(
                "latest_measurements", []
            ),
            "symptoms": clinical_context.symptoms,
            "trends": clinical_context.model_dump(mode="json").get(
                "measurement_trends", []
            ),
        }
