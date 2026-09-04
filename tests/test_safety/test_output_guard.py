"""OutputGuard 单元测试。"""

from app.xuantong.safety.output_guard import (
    OutputGuard,
    OutputGuardAction,
)

ROLE = "family_doctor"


def test_safe_output_passes():
    guard = OutputGuard()
    result = guard.check("建议每天规律监测血压，保持清淡饮食。", ROLE)
    assert result.action == OutputGuardAction.PASS
    assert result.violations == []


def test_diagnostic_rewritten():
    guard = OutputGuard()
    result = guard.check("你得了高血压", ROLE)
    assert result.action == OutputGuardAction.REWRITE
    assert result.rewritten_content is not None
    assert "诊断性语言" in result.violations
    # 改写后不应再出现直接诊断的措辞
    assert "你得了" not in result.rewritten_content


def test_medication_escalated():
    guard = OutputGuard()
    result = guard.check("建议你停止服用降压药", ROLE)
    assert result.action == OutputGuardAction.ESCALATE
    assert "用药建议越权" in result.violations


def test_overcommitment_rewritten():
    guard = OutputGuard()
    result = guard.check("保证能治好", ROLE)
    assert result.action == OutputGuardAction.REWRITE
    assert result.rewritten_content is not None
    assert "超范围承诺" in result.violations


def test_hallucination_blocked():
    guard = OutputGuard()
    result = guard.check("我们这里有治疗糖尿病的特效药", ROLE)
    assert result.action == OutputGuardAction.BLOCK
    assert "疑似幻觉内容" in result.violations
