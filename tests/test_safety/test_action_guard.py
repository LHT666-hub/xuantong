"""ActionGuard 单元测试。"""

from app.schemas.clinical import ActionRiskAssessment
from app.xuantong.safety.action_guard import (
    ActionGuard,
    ActionGuardLevel,
)


def test_low_risk_query():
    guard = ActionGuard()
    result = guard.check(["query_patient_info"])
    assert result.level == ActionGuardLevel.LOW
    assert result.requires_human is False
    assert "query_patient_info" in result.allowed_actions


def test_medium_risk_reminder():
    guard = ActionGuard()
    result = guard.check(["send_reminder"])
    assert result.level == ActionGuardLevel.MEDIUM
    assert result.requires_human is False
    assert "send_reminder" in result.allowed_actions


def test_high_risk_referral():
    guard = ActionGuard()
    result = guard.check(["suggest_referral"])
    assert result.level == ActionGuardLevel.HIGH
    assert result.requires_human is True
    assert "suggest_referral" in result.blocked_actions


def test_critical_risk_emergency():
    guard = ActionGuard()
    result = guard.check(["emergency_call"])
    assert result.level == ActionGuardLevel.CRITICAL
    assert result.requires_human is True
    assert "emergency_call" in result.blocked_actions


def test_red_clinical_risk_escalates():
    """clinical_risk=red 时所有级别自动升一级。"""
    guard = ActionGuard()
    # low -> medium
    low = guard.check(["query_patient_info"], clinical_risk_level="red")
    assert low.level == ActionGuardLevel.MEDIUM
    # medium -> high（升级为需人工）
    medium = guard.check(["send_reminder"], clinical_risk_level="red")
    assert medium.level == ActionGuardLevel.HIGH
    assert medium.requires_human is True


def test_multiple_actions_take_highest_level():
    guard = ActionGuard()
    result = guard.check(["query_patient_info", "suggest_referral"])
    assert result.level == ActionGuardLevel.HIGH
    assert result.requires_human is True


def test_to_action_risk_assessment():
    guard = ActionGuard()
    result = guard.check(["suggest_referral"])
    assessment = guard.to_action_risk_assessment(result)
    assert isinstance(assessment, ActionRiskAssessment)
    assert assessment.level == "high"
    assert assessment.requires_human is True
