"""Human-in-the-Loop 人工审核服务 (HITL)。

玄同 Safety 层的第四道闸门。当 Action Guard 判定 requires_human=True
（HIGH / CRITICAL 级动作）时触发：暂停 workflow，生成待审批任务，
等待人类医生做出决策后再继续。

与三层 Guard 不同，HITLService 是 Safety 层中**唯一有状态**的组件，
负责管理待审核队列。当前实现使用进程内字典存储，生产环境可替换为
持久化后端（数据库 / 消息队列），接口保持不变。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel


def _utcnow() -> datetime:
    """统一的时区感知当前时间，便于超时计算与测试。"""
    return datetime.now(timezone.utc)


class HITLDecision(BaseModel):
    """Human-in-the-Loop 决策记录。"""

    task_id: str
    action_description: str
    risk_level: str
    requested_at: datetime
    decided_at: datetime | None = None
    decision: str | None = None  # approved / rejected / modified
    decided_by: str | None = None  # human doctor ID
    modification_notes: str | None = None
    timeout_hours: int = 24  # 超时自动升级
    escalated: bool = False


class HITLService:
    """人工审核服务 —— 管理待审核队列（有状态）。"""

    VALID_DECISIONS = {"approved", "rejected", "modified"}

    def __init__(self) -> None:
        self._pending: dict[str, HITLDecision] = {}

    async def request_review(
        self,
        task_id: str,
        action_description: str,
        risk_level: str,
        timeout_hours: int = 24,
    ) -> HITLDecision:
        """请求人工审核，暂停 workflow。

        Args:
            task_id: 关联的任务 ID（唯一标识本次审核）。
            action_description: 需要人工确认的动作描述。
            risk_level: 动作风险等级（high / critical 等）。
            timeout_hours: 超时小时数，超时后自动升级。

        Returns:
            HITLDecision: 新建的待审核记录。
        """
        record = HITLDecision(
            task_id=task_id,
            action_description=action_description,
            risk_level=risk_level,
            requested_at=_utcnow(),
            timeout_hours=timeout_hours,
        )
        self._pending[task_id] = record
        return record

    async def submit_decision(
        self,
        task_id: str,
        decision: str,
        decided_by: str,
        notes: str = "",
    ) -> HITLDecision:
        """提交审核决定。

        Args:
            task_id: 待审核任务 ID。
            decision: 决策结果（approved / rejected / modified）。
            decided_by: 做出决策的人类医生 ID。
            notes: 决策备注 / 修改说明。

        Returns:
            HITLDecision: 更新后的记录。

        Raises:
            KeyError: task_id 不存在。
            ValueError: decision 非法。
        """
        record = self._pending.get(task_id)
        if record is None:
            raise KeyError(f"未找到待审核任务: {task_id}")
        if decision not in self.VALID_DECISIONS:
            raise ValueError(
                f"非法决策 '{decision}'，应为 {sorted(self.VALID_DECISIONS)} 之一"
            )

        record.decision = decision
        record.decided_by = decided_by
        record.decided_at = _utcnow()
        record.modification_notes = notes or None
        return record

    async def check_timeout(self, task_id: str) -> bool:
        """检查是否超时，超时则自动升级。

        Returns:
            bool: True 表示已超时并被标记为升级；False 表示未超时或已决策。
        """
        record = self._pending.get(task_id)
        if record is None:
            return False
        # 已决策的任务不再判超时
        if record.decision is not None:
            return False

        deadline = record.requested_at + timedelta(hours=record.timeout_hours)
        if _utcnow() >= deadline:
            record.escalated = True
            return True
        return False

    def get_pending_reviews(self) -> list[HITLDecision]:
        """获取所有待审核项（尚未做出决策的记录）。"""
        return [r for r in self._pending.values() if r.decision is None]

    def get(self, task_id: str) -> HITLDecision | None:
        """按 task_id 获取审核记录（含已决策）。"""
        return self._pending.get(task_id)
