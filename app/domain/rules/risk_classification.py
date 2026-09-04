"""确定性风险分级规则。
这是临床风险等级的唯一权威来源。
Agent 不得覆盖此结果，只能提供专业观察。
"""
import logging

from app.domain.rules.vital_sign_thresholds import VitalSignThresholds as VST
from app.schemas.clinical import ClinicalContext, Measurement, RiskAssessment

logger = logging.getLogger(__name__)


class RiskRuleService:
    """确定性风险分级服务。

    产生权威 clinical_risk_level。
    基于经验证的临床指南，V0.1 使用简化版本。

    原则：只升不降——确定性规则结果与 LLM 结果取 max。
    """

    RULE_VERSION = "v0.1"

    @classmethod
    def evaluate(
        cls,
        clinical_context: ClinicalContext,
        previous_risk_level: str = "green",
    ) -> RiskAssessment:
        """综合评估临床风险。

        检查所有最新测量值，返回最高风险等级。
        """
        worst_level = "green"
        worst_score = 0.0
        triggers: list[str] = []

        for measurement in clinical_context.latest_measurements:
            level, score, trigger = cls._evaluate_single(measurement)
            if cls._level_priority(level) > cls._level_priority(worst_level):
                worst_level = level
                worst_score = max(worst_score, score)
            if trigger:
                triggers.append(trigger)

        # 症状也会提升风险
        for symptom in clinical_context.symptoms:
            symptom_level = cls._evaluate_symptom(symptom)
            if cls._level_priority(symptom_level) > cls._level_priority(worst_level):
                worst_level = symptom_level
                triggers.append(f"症状: {symptom}")

        return RiskAssessment(
            level=worst_level,
            score=worst_score,
            trigger_indicators=triggers,
            previous_level=previous_risk_level,
            rule_version=cls.RULE_VERSION,
        )

    @classmethod
    def evaluate_bp(
        cls, systolic: float, diastolic: float
    ) -> tuple[str, float, str]:
        """评估血压风险。返回 (level, score, trigger_description)"""
        if (
            systolic >= VST.BP_SYSTOLIC_EMERGENCY
            or diastolic >= VST.BP_DIASTOLIC_EMERGENCY
        ):
            return "red", 0.95, f"高血压急症: BP {systolic}/{diastolic}"
        if (
            systolic >= VST.BP_SYSTOLIC_VERY_HIGH
            or diastolic >= VST.BP_DIASTOLIC_VERY_HIGH
        ):
            return "red", 0.8, f"高血压2级: BP {systolic}/{diastolic}"
        if systolic >= VST.BP_SYSTOLIC_HIGH or diastolic >= VST.BP_DIASTOLIC_HIGH:
            return "yellow", 0.5, f"高血压1级: BP {systolic}/{diastolic}"
        if (
            systolic >= VST.BP_SYSTOLIC_NORMAL_HIGH
            or diastolic >= VST.BP_DIASTOLIC_NORMAL_HIGH
        ):
            return "yellow", 0.3, f"血压偏高: BP {systolic}/{diastolic}"
        return "green", 0.1, ""

    @classmethod
    def _evaluate_single(cls, m: Measurement) -> tuple[str, float, str]:
        """评估单个测量值的风险"""
        if m.type == "blood_pressure":
            systolic = m.value
            diastolic = m.secondary_value or 0
            return cls.evaluate_bp(systolic, diastolic)

        elif m.type == "blood_glucose":
            if m.value <= VST.GLUCOSE_VERY_LOW:
                return "red", 0.9, f"严重低血糖: {m.value} mmol/L"
            if m.value <= VST.GLUCOSE_LOW:
                return "yellow", 0.6, f"低血糖: {m.value} mmol/L"
            if m.value >= VST.GLUCOSE_EMERGENCY_HIGH:
                return "red", 0.9, f"血糖急症: {m.value} mmol/L"
            if m.value >= VST.GLUCOSE_VERY_HIGH:
                return "red", 0.8, f"严重高血糖: {m.value} mmol/L"
            if m.value >= VST.GLUCOSE_FASTING_HIGH:
                return "yellow", 0.4, f"血糖偏高: {m.value} mmol/L"

        elif m.type == "heart_rate":
            if m.value <= VST.HR_VERY_LOW or m.value >= VST.HR_EMERGENCY:
                return "red", 0.9, f"心率危急: {m.value} bpm"
            if m.value <= VST.HR_LOW or m.value >= VST.HR_VERY_HIGH:
                return "red", 0.7, f"心率异常: {m.value} bpm"
            if m.value >= VST.HR_HIGH:
                return "yellow", 0.4, f"心率偏快: {m.value} bpm"

        elif m.type == "temperature":
            if m.value >= VST.TEMP_EMERGENCY:
                return "red", 0.8, f"高热急症: {m.value}°C"
            if m.value >= VST.TEMP_VERY_HIGH:
                return "yellow", 0.5, f"高热: {m.value}°C"
            if m.value >= VST.TEMP_HIGH:
                return "yellow", 0.3, f"低热: {m.value}°C"
            if m.value <= VST.TEMP_LOW:
                return "yellow", 0.5, f"体温过低: {m.value}°C"

        elif m.type == "blood_oxygen":
            spo2 = m.value
            if spo2 < VST.SPO2_EMERGENCY:
                return "red", 0.95, f"血氧{spo2}%，低于85%，急症"
            if spo2 < VST.SPO2_VERY_LOW:
                return "red", 0.8, f"血氧{spo2}%，低于90%"
            if spo2 < VST.SPO2_LOW:
                return "yellow", 0.5, f"血氧{spo2}%，低于95%"
            return "green", 0.1, ""

        return "green", 0.0, ""

    @classmethod
    def _evaluate_symptom(cls, symptom: str) -> str:
        """评估症状的风险等级"""
        emergency_symptoms = {"胸痛", "呼吸困难", "意识模糊", "昏迷", "大出血"}
        high_symptoms = {"头晕", "剧烈头痛", "持续呕吐", "胸闷"}

        for s in emergency_symptoms:
            if s in symptom:
                return "red"
        for s in high_symptoms:
            if s in symptom:
                return "yellow"
        return "green"

    @staticmethod
    def _level_priority(level: str) -> int:
        return {"green": 0, "yellow": 1, "red": 2}.get(level, 0)
