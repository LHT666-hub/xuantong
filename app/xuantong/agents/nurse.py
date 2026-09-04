"""护士 Agent — 指标解释 / 趋势分析 / 专业观察。

模型：qwen-plus（由 LLMRuntime 依据 agent_role="nurse" 路由到 specialist 层级）。
对外方法：consult() → ConsultationNote；execute() 为基类通用入口。
"""

import logging

from app.schemas.agent import AgentResult, ConsultationNote
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent

logger = logging.getLogger(__name__)

_CONSULT_SCHEMA = """{
  "observation": "收缩压168mmHg，舒张压103mmHg，均明显高于目标值（<140/90）",
  "assessment": "血压控制不佳，伴头晕症状提示可能存在靶器官影响",
  "trend_analysis": "需要对比历史数据确认是急性升高还是持续控制不佳",
  "recommendations": [
    "建议患者安静休息后复测血压",
    "确认近期是否规律服药",
    "如复测仍≥160/100，建议尽快就诊"
  ],
  "red_flags": ["头晕伴血压明显升高需警惕高血压急症"],
  "confidence": 0.85
}"""


class NurseAgent(BaseAgent):
    """护士角色。

    职责：指标解释、趋势分析、专业观察。
    """

    role = "nurse"
    display_name = "护士"
    description = "指标解释/趋势分析/专业观察"

    SYSTEM_PROMPT = """你是一位社区护理护士，专注于慢病管理患者的日常健康监测。

你的职责：
1. 分析患者生命体征数据（血压、血糖、心率等）
2. 识别异常趋势和变化模式
3. 提供护理观察意见和健康教育建议

重要原则：
- 你提供的是护理观察，不是医学诊断
- 关注趋势变化比单次数值更重要
- 用药依从性是常见问题，需特别关注
- 不要产生权威风险等级（那是规则引擎的工作）
- 如观察到危险信号，明确指出并建议紧急处理

输出格式：严格按 JSON 格式输出，只输出一个 JSON 对象，不要包含 markdown 代码块或任何额外文字。
"""

    async def consult(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
    ) -> ConsultationNote:
        """接收临床数据，输出专业护理观察。"""
        self._reset_counters()

        user_content = (
            "请从护理角度分析以下患者数据，给出专业观察意见。\n\n"
            f"【患者信息】\n{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【临床/事件数据】\n{self._dumps(event_data)}\n\n"
            f"【输出格式】严格输出如下结构的 JSON：\n{_CONSULT_SCHEMA}"
        )

        data = await self._invoke_json(user_content)
        if data is None:
            return self._degraded_note()

        observation = data.get("observation", "") or ""
        assessment = data.get("assessment", "") or ""
        red_flags = [str(x) for x in data.get("red_flags", [])]
        recommendations = [str(x) for x in data.get("recommendations", [])]

        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=observation or assessment,
            observation=observation or None,
            assessment=assessment or None,
            trend_analysis=data.get("trend_analysis"),
            findings=red_flags,
            recommendations=recommendations,
            red_flags=red_flags,
            risk_observation=assessment or None,
            confidence=data.get("confidence"),
        )

    def _degraded_note(self) -> ConsultationNote:
        """LLM 不可用时的降级护理观察。"""
        logger.warning(f"{self.display_name}: 会诊降级，返回空观察")
        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary="（模型不可用，护理观察暂缺，请人工复核生命体征）",
            recommendations=["建议人工复核患者生命体征与用药依从性"],
        )

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs,
    ) -> AgentResult:
        """通用入口：执行护理会诊并回包 AgentResult。"""
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
