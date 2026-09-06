"""中医师 Agent — 中医辨证施治 / 体质辨识 / 中药方剂与适宜技术建议。

模型：qwen-plus（显式声明 model_tier=SPECIALIST，路由到 specialist 层级）。
对外方法：consult() → ConsultationNote；execute() 为基类通用入口。

设计要点：
- 以"辨证论治、整体观念"为核心，四诊合参归纳证型；
- 结合九种体质辨识，给出中药方剂、中医适宜技术（针灸/推拿/穴位贴敷等）建议；
- 严守安全边界：不替代急重症西医救治，警惕妊娠禁忌、有毒中药、十八反十九畏。
"""

import logging

from app.schemas.agent import AgentResult, ConsultationNote
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent
from app.xuantong.llm.provider import ModelTier

logger = logging.getLogger(__name__)

_CONSULT_SCHEMA = """{
  "tcm_diagnosis": "眩晕（肝阳上亢证）",
  "syndrome_type": "肝阳上亢",
  "constitution_type": "阴虚质偏阳亢",
  "four_examination": "望：面红目赤；闻：语声高亢；问：头晕胀痛、急躁易怒、少寐多梦；切：脉弦有力",
  "recommended_formula": "天麻钩藤饮加减",
  "formula_composition": ["天麻", "钩藤", "石决明", "栀子", "黄芩", "川牛膝", "杜仲", "益母草", "桑寄生", "夜交藤", "茯神"],
  "acupoints": ["太冲", "风池", "百会", "曲池", "太溪"],
  "tcm_therapy": ["针刺（泻法）", "耳穴压豆", "头部推拿"],
  "observation": "患者血压168/103伴头晕、面红、急躁，脉弦，符合肝阳上亢之象",
  "assessment": "本虚标实，肝肾阴虚为本、肝阳上亢为标，治宜平肝潜阳、滋养肝肾",
  "recommendations": [
    "以天麻钩藤饮平肝潜阳，需由执业中医师面诊后辨证加减",
    "配合针刺太冲、风池等穴平肝熄风",
    "调畅情志、低盐饮食、规律作息，忌辛辣动火之品"
  ],
  "red_flags": [],
  "confidence": 0.75
}"""


class TCMAgent(BaseAgent):
    """中医师角色。

    职责：中医辨证施治、体质辨识、中药方剂与中医适宜技术建议。
    """

    role = "tcm"
    display_name = "中医师"
    description = "中医辨证施治/体质辨识/中药方剂建议"
    implemented = True
    model_tier = ModelTier.SPECIALIST

    SYSTEM_PROMPT = """你是一位执业中医师，专注于社区慢病的中医辨证调治与养生指导。

你的职责：
1. 四诊合参（望闻问切），归纳中医证型（辨证分型）
2. 辨识患者体质（九种体质：平和质、气虚质、阳虚质、阴虚质、痰湿质、湿热质、血瘀质、气郁质、特禀质）
3. 给出治法与中药方剂建议（如天麻钩藤饮、补阳还五汤、六味地黄丸等）
4. 推荐中医适宜技术（针灸、推拿、拔罐、艾灸、穴位贴敷、耳穴压豆等）与调摄建议

核心理念：
- 辨证论治：同病异治、异病同治，紧扣证型而非仅病名
- 整体观念：脏腑、气血、阴阳平衡，人与自然统一
- 治未病：未病先防、既病防变、瘥后防复

常见证型参考：
- 高血压/眩晕：肝阳上亢（天麻钩藤饮）、痰湿中阻（半夏白术天麻汤）、肝肾阴虚（杞菊地黄丸）、瘀血阻窍（通窍活血汤）
- 中风后遗症/气虚血瘀：补阳还五汤
- 糖尿病/消渴：阴虚燥热（六味地黄丸、玉女煎）、气阴两虚（生脉散合增液汤）

重要安全原则：
- 你提供的是中医会诊建议，不替代面诊；方剂须由执业中医师四诊合参后辨证加减，不直接开具处方剂量
- 急危重症（如高血压急症、急性心梗、脑卒中急性期、大出血等）必须优先西医救治，中医为辅助，写入 red_flags 提醒
- 严守用药安全：妊娠禁忌药、有毒中药（如附子、乌头、马钱子等需炮制先煎）、十八反十九畏配伍禁忌
- 中西药联用注意相互作用，提醒与药师协同
- 不产生权威风险等级（那是规则引擎的工作）

输出格式：严格按 JSON 格式输出，只输出一个 JSON 对象，不要包含 markdown 代码块或任何额外文字。
"""

    async def consult(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
    ) -> ConsultationNote:
        """从中医角度辨证施治，输出会诊意见。"""
        self._reset_counters()

        user_content = (
            "请从中医角度对以下患者情况进行四诊合参与辨证论治，"
            "给出证型、体质、方剂与适宜技术建议。\n\n"
            f"【患者信息】\n{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【临床/事件数据】\n{self._dumps(event_data)}\n\n"
            f"【输出格式】严格输出如下结构的 JSON：\n{_CONSULT_SCHEMA}"
        )

        data = await self._invoke_json(user_content)
        if data is None:
            return self._degraded_note()

        observation = data.get("observation", "") or ""
        assessment = data.get("assessment", "") or ""
        tcm_diagnosis = data.get("tcm_diagnosis", "") or ""
        syndrome_type = data.get("syndrome_type", "") or ""
        red_flags = [str(x) for x in data.get("red_flags", [])]
        recommendations = [str(x) for x in data.get("recommendations", [])]
        acupoints = [str(x) for x in data.get("acupoints", [])]
        formula_composition = [str(x) for x in data.get("formula_composition", [])]
        tcm_therapy = [str(x) for x in data.get("tcm_therapy", [])]

        findings = [f for f in (tcm_diagnosis, syndrome_type) if f] + red_flags

        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=tcm_diagnosis or syndrome_type or observation or assessment,
            observation=observation or None,
            assessment=assessment or None,
            findings=findings,
            recommendations=recommendations,
            red_flags=red_flags,
            risk_observation=assessment or None,
            confidence=data.get("confidence"),
            data={
                "tcm_diagnosis": tcm_diagnosis or None,
                "syndrome_type": syndrome_type or None,
                "constitution_type": data.get("constitution_type"),
                "four_examination": data.get("four_examination"),
                "recommended_formula": data.get("recommended_formula"),
                "formula_composition": formula_composition,
                "acupoints": acupoints,
                "tcm_therapy": tcm_therapy,
            },
        )

    def _degraded_note(self) -> ConsultationNote:
        """LLM 不可用时的降级中医意见（模板化建议）。"""
        logger.warning(f"{self.display_name}: 会诊降级，返回模板化建议")
        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary="（模型不可用，中医辨证意见暂缺，请执业中医师面诊辨证）",
            recommendations=[
                "建议由执业中医师四诊合参、辨证论治后确定治法与方剂",
                "调畅情志、规律作息、清淡饮食，配合适度导引（如八段锦、太极）",
            ],
            data={
                "tcm_diagnosis": None,
                "syndrome_type": None,
                "recommended_formula": None,
                "acupoints": [],
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
        """通用入口：执行中医会诊并回包 AgentResult。"""
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
