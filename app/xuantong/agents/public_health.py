"""公卫医师 Agent — 公卫随访管理 / 公卫规范。

模型：qwen-plus（由 LLMRuntime 依据 agent_role="public_health" 路由到 specialist 层级）。
对外方法：consult() → ConsultationNote；execute() 为基类通用入口。
"""

import logging

from app.schemas.agent import AgentResult, ConsultationNote
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent

logger = logging.getLogger(__name__)

_CONSULT_SCHEMA = """{
  "observation": "患者血压168/103，属高血压2级范围，伴症状",
  "guideline_reference": "《国家基本公共卫生服务规范》高血压患者健康管理",
  "management_level": "二级管理（中危）",
  "followup_requirement": "每月至少1次随访，当前事件需48小时内电话随访",
  "recommendations": [
    "48小时内安排电话随访确认血压变化",
    "如复测仍≥160/100，建议转诊至上级医院",
    "纳入重点关注名单，缩短随访周期至每2周"
  ],
  "referral_needed": false,
  "referral_criteria": "如血压≥180/110或出现靶器官损害症状则需转诊",
  "confidence": 0.8
}"""


class PublicHealthAgent(BaseAgent):
    """公卫医师角色。

    职责：公卫随访管理、公卫规范指导。
    """

    role = "public_health"
    display_name = "公卫医师"
    description = "公卫随访管理/公卫规范"

    SYSTEM_PROMPT = """你是一位公共卫生医师，负责社区慢病管理和公共卫生服务。

你的职责：
1. 根据国家基本公共卫生服务规范判断随访要求
2. 评估患者慢病管理等级
3. 建议公卫服务干预方案

重要原则：
- 遵循《国家基本公共卫生服务规范（第三版）》
- 高血压患者分级管理：一级(低危)每3月随访，二级(中危)每月随访，三级(高危)每2周随访
- 血压≥180/110需转诊，≥160/100需加强管理
- 关注是否纳入慢病管理、随访是否规范、是否需要转诊

输出格式：严格按 JSON 格式输出，只输出一个 JSON 对象，不要包含 markdown 代码块或任何额外文字。
"""

    async def consult(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
    ) -> ConsultationNote:
        """从公卫规范角度提供随访管理与转诊意见。"""
        self._reset_counters()

        user_content = (
            "请从公共卫生与慢病管理规范角度分析以下患者情况，给出随访与转诊建议。\n\n"
            f"【患者信息】\n{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【临床/事件数据】\n{self._dumps(event_data)}\n\n"
            f"【输出格式】严格输出如下结构的 JSON：\n{_CONSULT_SCHEMA}"
        )

        data = await self._invoke_json(user_content)
        if data is None:
            return self._degraded_note()

        observation = data.get("observation", "") or ""
        recommendations = [str(x) for x in data.get("recommendations", [])]

        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=observation,
            observation=observation or None,
            guideline_reference=data.get("guideline_reference"),
            management_level=data.get("management_level"),
            followup_requirement=data.get("followup_requirement"),
            referral_needed=data.get("referral_needed"),
            referral_criteria=data.get("referral_criteria"),
            findings=[f"管理等级: {data['management_level']}"]
            if data.get("management_level")
            else [],
            recommendations=recommendations,
            confidence=data.get("confidence"),
        )

    def _degraded_note(self) -> ConsultationNote:
        """LLM 不可用时的降级公卫意见。"""
        logger.warning(f"{self.display_name}: 会诊降级，返回空观察")
        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary="（模型不可用，公卫随访意见暂缺，请按规范人工评估管理等级）",
            recommendations=["建议按《国家基本公共卫生服务规范》人工核定随访周期与转诊指征"],
        )

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs,
    ) -> AgentResult:
        """通用入口：执行公卫会诊并回包 AgentResult。"""
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
            data=note.model_dump(mode="json"),
        )
