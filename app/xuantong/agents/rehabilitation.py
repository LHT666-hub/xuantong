"""康复师 Agent — 功能评估 / 运动处方 / 康复训练指导。

模型：qwen-plus（显式声明 model_tier=SPECIALIST，路由到 specialist 层级）。
对外方法：consult() → ConsultationNote；execute() 为基类通用入口。

设计要点：
- 依据 FITT 原则（频率/强度/时间/类型）制定个体化运动处方；
- 覆盖慢病康复（高血压、糖尿病、脑卒中后、COPD、骨质疏松等）；
- 强调功能评估（ADL/平衡/肌力/心肺耐力）、居家康复与运动安全禁忌。
"""

import logging

from app.schemas.agent import AgentResult, ConsultationNote
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent
from app.xuantong.llm.provider import ModelTier

logger = logging.getLogger(__name__)

_CONSULT_SCHEMA = """{
  "functional_assessment": "建议评估 ADL（Barthel 指数）、平衡（Berg/TUG）、肌力（MMT）、心肺耐力（6分钟步行）",
  "exercise_prescription": {
    "frequency": "每周 5-7 天有氧，抗阻 2-3 天（隔天）",
    "intensity": "中等强度（RPE 12-13，或心率储备 40-60%），可言语测试监测",
    "time": "每次有氧 30 分钟（可分 3×10 分钟），抗阻每组 8-12 次×2-3 组",
    "type": "快走/太极/游泳等有氧 + 弹力带/自重抗阻 + 柔韧与平衡训练"
  },
  "home_program": [
    "每日快走 30 分钟，循序渐进",
    "弹力带上肢/下肢抗阻训练，隔天一次",
    "每日平衡训练（单脚站立、脚跟对脚尖行走）防跌倒"
  ],
  "safety_precautions": [
    "血压未控制(≥180/110)或急性期暂停运动，先就医",
    "避免屏气用力的等长/大重量运动（防血压骤升）",
    "运动前后监测血压/血糖，随身携带急救与含糖食品，出现胸闷头晕立即停止"
  ],
  "contraindications": ["不稳定心绞痛、未控制的严重高血压、急性感染发热期为运动禁忌"],
  "observation": "患者高血压合并糖尿病，缺乏规律运动，心肺耐力与肌力待评估",
  "assessment": "规律有氧结合抗阻有助于降压控糖，需在安全阈值内个体化处方",
  "recommendations": [
    "从低-中等强度有氧起步，逐步达到每周 150 分钟",
    "结合抗阻与平衡训练，兼顾控糖与防跌倒",
    "运动前评估心血管风险，制定监护与随访计划"
  ],
  "red_flags": [],
  "confidence": 0.8
}"""


class RehabilitationAgent(BaseAgent):
    """康复师角色。

    职责：功能评估、运动处方（FITT）、慢病康复与居家训练指导。
    """

    role = "rehabilitation"
    display_name = "康复师"
    description = "功能评估/运动处方/康复训练指导"
    implemented = True
    model_tier = ModelTier.SPECIALIST

    SYSTEM_PROMPT = """你是一位康复治疗师（物理治疗/运动康复方向），专注于社区慢病与功能障碍患者的康复评估与运动处方。

你的职责：
1. 建议功能评估（ADL/Barthel、平衡/Berg/TUG、肌力/MMT、心肺耐力/6分钟步行、疼痛等）
2. 依据 FITT 原则制定个体化运动处方（Frequency 频率 / Intensity 强度 / Time 时间 / Type 类型）
3. 给出居家康复训练方案与运动安全注意事项、禁忌

慢病康复要点（务必对因施策）：
- 高血压：以有氧运动为主（快走/太极/游泳/骑车），中等强度；避免屏气发力的等长运动与大重量抗阻；血压≥180/110 或急性期暂停运动
- 糖尿病：餐后 1 小时运动更佳，有氧+抗阻组合；运动前后监测血糖，防低血糖（随身含糖食品），注意足部保护
- 脑卒中后：良肢位摆放、肢体功能训练（Bobath/运动再学习）、平衡与步态训练、ADL 训练，必要时语言/吞咽康复；循序渐进、防跌倒防误吸
- COPD：缩唇呼吸、腹式呼吸、呼吸操，肺康复（有氧+吸气肌训练），排痰体位引流
- 骨质疏松：负重运动与抗阻训练增骨量，平衡训练防跌倒；避免脊柱过度屈曲/旋转与高冲击运动

重要原则：
- 运动处方须个体化、循序渐进，明确强度监测方法（RPE、心率储备、言语测试）
- 运动前评估心血管风险，列出运动禁忌与安全注意事项（写入 safety_precautions / contraindications）
- 康复是辅助手段，不替代药物与急重症救治；如识别危险信号写入 red_flags
- 建议具体可操作，便于居家执行与家属协助
- 不产生权威风险等级（那是规则引擎的工作）

输出格式：严格按 JSON 格式输出，只输出一个 JSON 对象，不要包含 markdown 代码块或任何额外文字。
其中 exercise_prescription 为一个包含 frequency/intensity/time/type 四个字段的 JSON 对象。
"""

    async def consult(
        self,
        event_data: dict,
        patient_context: PatientContext | dict | None = None,
    ) -> ConsultationNote:
        """从康复角度评估功能并给出运动处方与居家康复方案。"""
        self._reset_counters()

        user_content = (
            "请从康复医学角度评估以下患者的功能状况，"
            "结合其慢病/障碍类型给出 FITT 运动处方、居家康复方案与安全注意事项。\n\n"
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
        functional_assessment = data.get("functional_assessment", "") or ""
        red_flags = [str(x) for x in data.get("red_flags", [])]
        recommendations = [str(x) for x in data.get("recommendations", [])]
        home_program = [str(x) for x in data.get("home_program", [])]
        safety_precautions = [str(x) for x in data.get("safety_precautions", [])]
        contraindications = [str(x) for x in data.get("contraindications", [])]

        exercise_prescription = data.get("exercise_prescription")
        if not isinstance(exercise_prescription, dict):
            exercise_prescription = (
                {"description": str(exercise_prescription)}
                if exercise_prescription
                else {}
            )

        findings = (
            ([functional_assessment] if functional_assessment else [])
            + red_flags
            + contraindications
        )

        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=functional_assessment or observation or assessment,
            observation=observation or None,
            assessment=assessment or None,
            findings=findings,
            recommendations=recommendations,
            red_flags=red_flags,
            risk_observation=assessment or None,
            confidence=data.get("confidence"),
            data={
                "functional_assessment": functional_assessment or None,
                "exercise_prescription": exercise_prescription,
                "home_program": home_program,
                "safety_precautions": safety_precautions,
                "contraindications": contraindications,
            },
        )

    def _degraded_note(self) -> ConsultationNote:
        """LLM 不可用时的降级康复意见（模板化建议）。"""
        logger.warning(f"{self.display_name}: 会诊降级，返回模板化建议")
        return ConsultationNote(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary="（模型不可用，康复评估暂缺，请康复治疗师个体化评估后制定运动处方）",
            recommendations=[
                "由康复治疗师评估功能状况后，依 FITT 原则制定个体化运动处方",
                "遵循循序渐进、量力而行，运动前评估心血管风险并注意运动禁忌",
            ],
            data={
                "functional_assessment": None,
                "exercise_prescription": {},
                "home_program": [],
                "safety_precautions": [],
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
        """通用入口：执行康复会诊并回包 AgentResult。"""
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
