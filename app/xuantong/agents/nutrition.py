"""营养师 Agent — 为常曦食养提供安全、结构化的菜谱排序。"""

import logging
from typing import Any

from app.schemas.agent import AgentResult
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent


logger = logging.getLogger(__name__)

_RECOMMENDATION_SCHEMA = """{
  "recipe_ids": ["recipe-id-1", "recipe-id-2", "recipe-id-3"],
  "summary": "一句面向居民、说明本次排序依据的话",
  "notices": ["只写确实需要提醒的过敏、用药或慢病饮食注意事项"]
}"""


class NutritionAgent(BaseAgent):
    """根据已授权资料和本地候选菜谱排序，不凭空生成医疗结论。"""

    role = "nutrition"
    display_name = "营养师"
    description = "个性化食养与菜谱排序"
    implemented = True
    max_llm_calls = 2

    SYSTEM_PROMPT = """你是社区家庭医生团队中的营养师，为居民提供日常食养参考。

你的任务是从调用方给出的候选菜谱中排序，不能编造候选列表以外的 recipe_id。
优先级依次为：明确过敏和忌口、用药相关风险、已确认健康需求、现有食材、可用时间、口味与地域习惯。
不要诊断疾病、调整处方、承诺食物疗效，也不要把中医食养描述成治疗。
资料不足时保持保守，并在 notices 中说明需要居民确认的事项。
严格只输出 JSON 对象，不要包含 markdown 或额外文字。
"""

    async def recommend(self, payload: dict[str, Any]) -> AgentResult:
        self._reset_counters()
        candidates = payload.get("candidate_recipes") or []
        candidate_ids = [
            str(item.get("id"))
            for item in candidates
            if isinstance(item, dict) and item.get("id")
        ]
        fallback_ids = candidate_ids[:3]

        user_content = (
            "请依据以下已授权信息，为本次食养候选菜谱排序。"
            "只能返回 candidate_recipes 中存在的 id。\n\n"
            f"【食养上下文】\n{self._dumps(payload)}\n\n"
            f"【输出格式】\n{_RECOMMENDATION_SCHEMA}"
        )
        data = await self._invoke_json(user_content, temperature=0.2, max_tokens=900)
        if data is None:
            logger.warning("营养师模型不可用，保留本地安全排序")
            return self._result(
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
        ranked = ranked[:3]

        summary = self._guard_patient_text(str(data.get("summary") or "已结合你的饭桌重新排序。"))
        notices = [
            self._guard_patient_text(str(item))
            for item in data.get("notices", [])
            if str(item).strip()
        ][:3]
        return self._result(ranked, summary, notices, degraded=False)

    def _result(
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

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        payload = kwargs.get("nutrition_payload") or {}
        if patient_context is not None:
            payload.setdefault("patient_context", self._to_plain(patient_context))
        return await self.recommend(payload)
