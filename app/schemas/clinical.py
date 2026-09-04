from pydantic import BaseModel
from datetime import datetime


class Measurement(BaseModel):
    """单次测量值"""
    type: str  # blood_pressure / blood_glucose / heart_rate / weight / temperature
    value: float
    unit: str
    secondary_value: float | None = None  # e.g., diastolic BP
    measured_at: datetime


class TrendAnalysis(BaseModel):
    """趋势分析结果"""
    measurement_type: str
    direction: str  # increasing / decreasing / stable / fluctuating
    description: str
    data_points: int


class ClinicalContext(BaseModel):
    latest_measurements: list[Measurement] = []
    measurement_trends: list[TrendAnalysis] = []
    symptoms: list[str] = []
    duration_days: int | None = None


class RiskAssessment(BaseModel):
    """由 domain/rules/RiskRuleService 产生，是唯一权威临床风险来源"""
    level: str  # green / yellow / red
    score: float
    trigger_indicators: list[str] = []
    previous_level: str = "green"
    rule_version: str = "v0.1"


class ActionRiskAssessment(BaseModel):
    """由 Safety Layer 评估的 AI 动作风险"""
    level: str  # low / med / high / critical
    reasons: list[str] = []
    requires_human: bool = False
