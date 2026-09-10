"""营养师 Agent：临床营养会诊与常曦食养菜谱排序。"""

import logging
from typing import Any

from app.schemas.agent import AgentResult, ConsultationNote
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent
from app.xuantong.llm.provider import ModelTier

logger = logging.getLogger(__name__)

_CONSULT_SCHEMA = """{
  "dietary_assessment": "当前饮食结构的简要评估",
  "disease_diet_principle": "结合慢病的循证饮食原则",
  "meal_plan_suggestions": ["具体、可执行的餐次建议"],
  "nutrient_supplements": ["确有依据时才给出的补充建议"],
  "weight_management": "体重管理建议",
  "observation": "营养观察",
  "assessment": "营养评估",
  "recommendations": ["后续建议"],
  "red_flags": [],
  "confidence": 0.8
}"""

_RECOMMENDATION_SCHEMA = """{
  "recipe_ids": ["recipe-id-1", "recipe-id-2", "recipe-id-3"],
  "summary": "一句面向居民、说明本次排序依据的话",
  "notices": ["只写确实需要提醒的过敏、用药或慢病饮食注意事项"]
}"""


class NutritionAgent(BaseAgent):
    """同时支持工作流会诊和食养候选菜谱排序。"""

    role = "nutrition"
    display_name = "营养师"
    description = "营养评估、慢病膳食指导与个性化食养排序"
    implemented = True
    model_tier = ModelTier.SPECIALIST
    max_llm_calls = 2

    SYSTEM_PROMPT = """你是社区家庭医生团队中的临床营养师，负责营养评估、慢病膳食指导和日常食养参考。

慢病原则：
- 高血压：DASH、低钠，提醒酱油和腌制品中的隐形钠；富钾建议必须先考虑肾功能。
- 糖尿病：低 GI/GL、碳水计数、粗细搭配、三餐定时定量。
- 高尿酸/痛风：低嘌呤、限酒，并结合心肾功能给出饮水建议。
- 高血脂：减少饱和脂肪和反式脂肪，增加可溶性纤维。
- 慢性肾病：蛋白质、钾、磷、钠必须个体化，并提示专科复核。

安全边界：
- 饮食建议不能替代诊断和药物治疗，不能建议擅自停药或调药。
- 特殊人群及资料不足时保持保守，明确指出需居民确认或专业复核的事项。
- 菜谱排序只能返回调用方候选列表中的 recipe_id，不得编造菜谱。
- 患者可见内容应清楚、克制、可执行，不承诺疗效。
- 严格只输出调用方要求的 JSON 对象，不要包含 markdown 或额外文字。
"""

    async def consult(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
    ) -> ConsultationNote:
        """从临床营养角度参与玄同会诊。"""
        self._reset_counters()
        user_content = (
            "请从临床营养角度评估以下患者资料，并给出安全、可执行的膳食建议。\n\n"
            f"【患者信息】\n{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【临床/事件数据】\n{self._dumps(event_data)}\n\n"
            f"【输出格式】\n{_CONSULT_SCHEMA}"
        )
        data = await self._invoke_json(user_content)
        if data is None:
            return self._degraded_note()

        observation = str(data.get("observation") or "")
        assessment = str(data.get("assessment") or "")
        dietary_assessment = str(data.get("dietary_assessment") or "")
        red_flags = [str(value) for value in data.get("red_flags", [])]
        recommendations = [str(value) for value in data.get("recommendations", [])]
        meal_suggestions = [str(value) for value in data.get("meal_plan_suggestions", [])]
        supplements = [str(value) for value in data.get("nutrient_supplements", [])]
        findings = ([dietary_assessment] if dietary_assessment else []) + red_flags

        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=dietary_assessment or observation or assessment,
            observation=observation or None,
            assessment=assessment or None,
            findings=findings,
            recommendations=recommendations,
            red_flags=red_flags,
            risk_observation=assessment or None,
            confidence=data.get("confidence"),
            data={
                "dietary_assessment": dietary_assessment or None,
                "disease_diet_principle": data.get("disease_diet_principle"),
                "meal_plan_suggestions": meal_suggestions,
                "nutrient_supplements": supplements,
                "weight_management": data.get("weight_management"),
            },
        )

    async def recommend(self, payload: dict[str, Any]) -> AgentResult:
        """按安全限制和居民偏好排序调用方提供的候选菜谱。"""
        self._reset_counters()
        candidates = payload.get("candidate_recipes") or []
        candidate_ids = [
            str(item.get("id"))
            for item in candidates
            if isinstance(item, dict) and item.get("id")
        ]
        fallback_ids = candidate_ids[:3]
        user_content = (
            "请依据以下已授权信息排序食养候选菜谱。"
            "优先考虑过敏和忌口、用药风险、已确认健康需求、现有食材、时间和口味。"
            "只能返回 candidate_recipes 中存在的 id。\n\n"
            f"【食养上下文】\n{self._dumps(payload)}\n\n"
            f"【输出格式】\n{_RECOMMENDATION_SCHEMA}"
        )
        data = await self._invoke_json(user_content, temperature=0.2, max_tokens=900)
        if data is None:
            logger.warning("营养师模型不可用，保留本地安全排序")
            return self._recommendation_result(
                fallback_ids,
                "已按现有食材、用餐时间和安全限制完成本地排序。",
                ["智能食养暂时不可用，本次结果来自本地规则。"],
                degraded=True,
            )

        allowed = set(candidate_ids)
        ranked: list[str] = []
        for value in data.get("recipe_ids", []):
            recipe_id = str(value)
            if recipe_id in allowed and recipe_id not in ranked:
                ranked.append(recipe_id)
        for recipe_id in fallback_ids:
            if recipe_id not in ranked:
                ranked.append(recipe_id)

        summary = self._guard_patient_text(
            str(data.get("summary") or "已结合你的饭桌重新排序。")
        )
        notices = [
            self._guard_patient_text(str(item))
            for item in data.get("notices", [])
            if str(item).strip()
        ][:3]
        return self._recommendation_result(ranked[:3], summary, notices, degraded=False)

    def _recommendation_result(
        self,
        recipe_ids: list[str],
        summary: str,
        notices: list[str],
        *,
        degraded: bool,
    ) -> AgentResult:
        return AgentResult(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=summary,
            recommendations=notices,
            data={
                "recipe_ids": recipe_ids,
                "summary": summary,
                "notices": notices,
                "degraded": degraded,
            },
        )

    def _degraded_note(self) -> ConsultationNote:
        logger.warning("%s: 会诊降级，返回模板化建议", self.display_name)
        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary="模型暂时不可用，营养方案需要营养师结合个人情况复核。",
            recommendations=[
                "保持食物多样、粗细搭配、少盐少油，并记录实际饮食。",
                "结合慢病、用药和肾功能，由专业人员制定个体化方案。",
            ],
            data={
                "dietary_assessment": None,
                "meal_plan_suggestions": [],
                "nutrient_supplements": [],
                "degraded": True,
            },
        )

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        """食养请求走 recommend；玄同工作流事件继续走临床会诊。"""
        if "nutrition_payload" in kwargs:
            payload = dict(kwargs.get("nutrition_payload") or {})
            if patient_context is not None:
                payload.setdefault("patient_context", self._to_plain(patient_context))
            return await self.recommend(payload)

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
