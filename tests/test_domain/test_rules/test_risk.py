import pytest
from app.domain.rules import RiskRuleService, EmergencyRuleEngine
from app.schemas.clinical import ClinicalContext, Measurement
from datetime import datetime


def test_bp_emergency():
    level, score, trigger = RiskRuleService.evaluate_bp(180, 120)
    assert level == "red"
    assert score >= 0.9


def test_bp_normal():
    level, score, trigger = RiskRuleService.evaluate_bp(115, 75)
    assert level == "green"


def test_evaluate_comprehensive():
    ctx = ClinicalContext(
        latest_measurements=[
            Measurement(type="blood_pressure", value=180, secondary_value=120, unit="mmHg", measured_at=datetime.now()),
        ],
        symptoms=["头晕"],
    )
    result = RiskRuleService.evaluate(ctx)
    assert result.level == "red"
    assert result.rule_version == "v0.1"


def test_emergency_detection():
    is_emerg, reason = EmergencyRuleEngine.is_emergency("胸痛而且呼吸困难")
    assert is_emerg == True


def test_no_false_emergency():
    is_emerg, reason = EmergencyRuleEngine.is_emergency("我今天忘记吃降压药了")
    assert is_emerg == False  # 药物相关不拦截
