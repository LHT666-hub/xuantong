"""HITLService 单元测试。"""

import pytest

from app.xuantong.safety.hitl import HITLService


@pytest.mark.asyncio
async def test_request_review():
    service = HITLService()
    record = await service.request_review(
        task_id="task-1",
        action_description="建议转诊至心内科",
        risk_level="high",
    )
    assert record.task_id == "task-1"
    assert record.decision is None
    assert record.escalated is False
    # 待审核队列应包含该记录
    pending = service.get_pending_reviews()
    assert len(pending) == 1
    assert pending[0].task_id == "task-1"


@pytest.mark.asyncio
async def test_submit_decision():
    service = HITLService()
    await service.request_review("task-2", "调整用药方案", "high")
    record = await service.submit_decision(
        task_id="task-2",
        decision="approved",
        decided_by="doctor-007",
        notes="同意转诊",
    )
    assert record.decision == "approved"
    assert record.decided_by == "doctor-007"
    assert record.decided_at is not None
    assert record.modification_notes == "同意转诊"
    # 决策后不再处于待审核队列
    assert service.get_pending_reviews() == []


@pytest.mark.asyncio
async def test_submit_invalid_decision_raises():
    service = HITLService()
    await service.request_review("task-3", "住院建议", "critical")
    with pytest.raises(ValueError):
        await service.submit_decision("task-3", "maybe", "doctor-007")


@pytest.mark.asyncio
async def test_timeout_detection():
    service = HITLService()
    # timeout_hours=0 表示立即到期
    await service.request_review("task-4", "紧急呼叫", "critical", timeout_hours=0)
    timed_out = await service.check_timeout("task-4")
    assert timed_out is True
    assert service.get("task-4").escalated is True


@pytest.mark.asyncio
async def test_no_timeout_within_window():
    service = HITLService()
    await service.request_review("task-5", "转诊建议", "high", timeout_hours=24)
    timed_out = await service.check_timeout("task-5")
    assert timed_out is False
    assert service.get("task-5").escalated is False
