"""药师 Agent — 用药安全分析 / 药物相互作用（DDI）检查。

模型：qwen-plus（由 LLMRuntime 依据 agent_role="pharmacist" 路由到 specialist 层级）。
对外方法：consult() → ConsultationNote；execute() 为基类通用入口。
"""

import logging

from app.schemas.agent import AgentResult, ConsultationNote
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent

logger = logging.getLogger(__name__)

_CONSULT_SCHEMA = """{
  "observation": "患者当前服用氨氯地平5mg qd，本次血压168/103控制不佳",
  "medication_review": "降压方案单药控制不佳，需评估依从性与剂量 adequacy",
  "ddi_findings": ["如需联用，注意避免与强效CYP3A4抑制剂合用"],
  "assessment": "血压未达标，首先排查用药依从性，其次评估方案强度",
  "recommendations": [
    "核实患者近一周是否规律服药、有无漏服",
    "提示氨氯地平常见踝部水肿等不良反应",
    "建议医生评估是否需要联合用药（药师不直接调药）"
  ],
  "red_flags": [],
  "confidence": 0.8
}"""


class PharmacistAgent(BaseAgent):
    """药师角色。

    职责：用药安全分析、药物相互作用检查。
    """

    role = "pharmacist"
    display_name = "药师"
    description = "用药安全分析"

    SYSTEM_PROMPT = """你是一位临床药师，专注于社区慢病用药安全管理。

你的职责：
1. 审查患者当前用药方案的安全性
2. 检查药物相互作用（DDI）
3. 评估用药依从性问题
4. 提供用药教育建议

重要原则：
- 不直接建议调药（那是医生的权限），而是提供药学分析
- 关注常见降压药的副作用和相互作用
- 用药依从性是血压控制不佳的首要原因
- 如发现严重DDI或不良反应，标记为紧急（写入 red_flags）

输出格式：严格按 JSON 格式输出，只输出一个 JSON 对象，不要包含 markdown 代码块或任何额外文字。
"""

    async def consult(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
    ) -> ConsultationNote:
        """审查用药安全、检查 DDI、评估依从性。"""
        self._reset_counters()

        user_content = (
            "请从临床药学角度审查以下患者的用药安全，检查药物相互作用并评估依从性。\n\n"
            f"【患者信息（含当前用药）】\n"
            f"{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【临床/事件数据】\n{self._dumps(event_data)}\n\n"
            f"【输出格式】严格输出如下结构的 JSON：\n{_CONSULT_SCHEMA}"
        )

        data = await self._invoke_json(user_content)
        if data is None:
            return self._degraded_note()

        observation = data.get("observation", "") or ""
        assessment = data.get("assessment", "") or ""
        red_flags = [str(x) for x in data.get("red_flags", [])]
        ddi_findings = [str(x) for x in data.get("ddi_findings", [])]
        recommendations = [str(x) for x in data.get("recommendations", [])]

        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=observation or assessment,
            observation=observation or None,
            assessment=assessment or None,
            medication_review=data.get("medication_review"),
            ddi_findings=ddi_findings,
            findings=ddi_findings + red_flags,
            recommendations=recommendations,
            red_flags=red_flags,
            risk_observation=assessment or None,
            confidence=data.get("confidence"),
        )

    def _degraded_note(self) -> ConsultationNote:
        """LLM 不可用时的降级药学意见。"""
        logger.warning(f"{self.display_name}: 会诊降级，返回空观察")
        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary="（模型不可用，用药安全分析暂缺，请人工复核用药方案）",
            recommendations=["建议人工复核患者当前用药方案与药物相互作用"],
        )

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs,
    ) -> AgentResult:
        """通用入口：执行用药安全会诊并回包 AgentResult。"""
        event_data = kwargs.get("event_data") or (
            clinical_context.model_dump(mode="json") if clinical_context else {}
        )
        note = await self.consult(event_data, patient_context)
        return AgentResult(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=note.summary,
            findings=note.findings,
            recommendations=note.recommendations,
            risk_observation=note.risk_observation,
            data=note.model_dump(mode="json"),
        )
