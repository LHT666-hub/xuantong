"""营养师 Agent — 营养评估 / 膳食指导 / 慢病饮食管理。

模型：qwen-plus（显式声明 model_tier=SPECIALIST，路由到 specialist 层级）。
对外方法：consult() → ConsultationNote；execute() 为基类通用入口。

设计要点：
- 依据慢病类型给出循证膳食方案（高血压 DASH/低钠、糖尿病低 GI/碳水计数、
  痛风低嘌呤、高血脂低饱和脂肪、CKD 优质低蛋白限磷钾等）；
- 输出膳食评估、餐次建议、营养素补充与体重管理方案；
- 严守边界：不替代药物治疗，特殊人群（CKD/孕期）需个体化并提示专业复核。
"""

import logging

from app.schemas.agent import AgentResult, ConsultationNote
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent
from app.xuantong.llm.provider import ModelTier

logger = logging.getLogger(__name__)

_CONSULT_SCHEMA = """{
  "dietary_assessment": "当前饮食偏咸、蔬果摄入不足，饱和脂肪偏高，与高血压/糖尿病控制目标不符",
  "disease_diet_principle": "高血压合并糖尿病：DASH 饮食 + 低钠(<5g/天) + 低 GI + 碳水计数",
  "meal_plan_suggestions": [
    "主食粗细搭配，每日全谷物占 1/3，控制总碳水并均匀分配至三餐",
    "每日蔬菜 500g（深色占半）、水果 200g（选低 GI 如苹果/柚子，两餐间食用）",
    "优质蛋白：鱼禽蛋奶豆，减少肥肉与加工肉；烹调油 25-30g/天",
    "限盐<5g/天（含酱油/腌制品隐形钠），增加富钾食物（如菠菜、香蕉，肾功能正常时）"
  ],
  "nutrient_supplements": ["如无日晒不足可评估维生素D", "膳食纤维不足时可酌情补充"],
  "weight_management": "如超重，建议每周减重 0.5kg，能量缺口 300-500kcal/天，配合运动",
  "observation": "患者高血压合并2型糖尿病，饮食结构存在高钠、精制碳水偏多问题",
  "assessment": "饮食干预是血压与血糖控制的基础，当前结构需系统调整",
  "recommendations": [
    "推行 DASH 饮食并严格限钠<5g/天",
    "采用低 GI 主食与碳水计数，规律三餐、定时定量",
    "记录饮食日记，2-4 周复评体重、血压、血糖变化"
  ],
  "red_flags": [],
  "confidence": 0.8
}"""


class NutritionAgent(BaseAgent):
    """营养师角色。

    职责：营养评估、膳食指导、慢病饮食管理、体重管理。
    """

    role = "nutrition"
    display_name = "营养师"
    description = "营养评估/膳食指导/慢病饮食管理"
    implemented = True
    model_tier = ModelTier.SPECIALIST

    SYSTEM_PROMPT = """你是一位临床营养师（注册营养师），专注于社区慢病患者的营养评估与膳食管理。

你的职责：
1. 评估患者当前膳食结构（钠、脂肪、碳水、蛋白、蔬果、总能量等）
2. 依据慢病类型制定循证饮食方案
3. 给出餐次搭配、营养素补充与体重管理建议

慢病饮食原则（务必对因施膳）：
- 高血压：DASH 饮食、低钠(<5g/天，注意酱油/腌制品隐形钠)、高钾高钙高镁、限酒（肾功能正常者适度富钾）
- 糖尿病：低 GI/GL、碳水计数、主食粗细搭配、三餐定时定量、膳食纤维 25-30g/天
- 高尿酸/痛风：低嘌呤（限动物内脏、浓肉汤、部分海鲜）、严格限酒（尤其啤酒）、多饮水(>2000ml/天)
- 高血脂：低饱和脂肪与反式脂肪、增加可溶性纤维与植物固醇、适量深海鱼（Omega-3）
- 慢性肾病(CKD)：优质低蛋白(依分期 0.6-0.8g/kg)、限磷、限钾、限钠，须个体化并提示肾内科/营养师复核

重要原则：
- 饮食是慢病管理基础，但不替代药物治疗；不擅自建议停药或调药
- 建议具体、可操作、贴合中国居民膳食习惯与《中国居民膳食指南》
- 特殊人群（CKD、孕期、老年消瘦、糖尿病肾病）需个体化，明确提示专业复核
- 富钾/高蛋白等建议在肾功能不全时可能有害，须结合患者情况谨慎并标注
- 不产生权威风险等级（那是规则引擎的工作）；如识别营养相关急症写入 red_flags

输出格式：严格按 JSON 格式输出，只输出一个 JSON 对象，不要包含 markdown 代码块或任何额外文字。
"""

    async def consult(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
    ) -> ConsultationNote:
        """从营养角度评估膳食并给出慢病饮食方案。"""
        self._reset_counters()

        user_content = (
            "请从临床营养角度评估以下患者的膳食结构，"
            "并结合其慢病类型给出饮食方案、餐次建议与营养补充建议。\n\n"
            f"【患者信息（含慢病/用药）】\n"
            f"{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【临床/事件数据】\n{self._dumps(event_data)}\n\n"
            f"【输出格式】严格输出如下结构的 JSON：\n{_CONSULT_SCHEMA}"
        )

        data = await self._invoke_json(user_content)
        if data is None:
            return self._degraded_note()

        observation = data.get("observation", "") or ""
        assessment = data.get("assessment", "") or ""
        dietary_assessment = data.get("dietary_assessment", "") or ""
        red_flags = [str(x) for x in data.get("red_flags", [])]
        recommendations = [str(x) for x in data.get("recommendations", [])]
        meal_plan_suggestions = [
            str(x) for x in data.get("meal_plan_suggestions", [])
        ]
        nutrient_supplements = [str(x) for x in data.get("nutrient_supplements", [])]

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
                "meal_plan_suggestions": meal_plan_suggestions,
                "nutrient_supplements": nutrient_supplements,
                "weight_management": data.get("weight_management"),
            },
        )

    def _degraded_note(self) -> ConsultationNote:
        """LLM 不可用时的降级营养意见（模板化建议）。"""
        logger.warning(f"{self.display_name}: 会诊降级，返回模板化建议")
        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary="（模型不可用，营养评估暂缺，请营养师个体化复核膳食方案）",
            recommendations=[
                "遵循《中国居民膳食指南》：食物多样、粗细搭配、少盐少油、限糖限酒",
                "结合慢病类型由注册营养师制定个体化膳食方案并定期复评",
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
        **kwargs,
    ) -> AgentResult:
        """通用入口：执行营养会诊并回包 AgentResult。"""
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
