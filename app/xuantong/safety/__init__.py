"""玄同 Safety Guard 独立解耦层。

本层完全独立于 Agent 逻辑，作为纯函数存在（HITLService 除外，它管理
待审核队列，是唯一有状态的组件）。四层 Guard 分别在 workflow 的不同
阶段被调用：

- InputGuard  : LangGraph workflow 入口，过滤危机 / 注入 / 超长输入。
- OutputGuard : 每个 Agent 输出后，4 态处置（pass/rewrite/block/escalate）。
- ActionGuard : Task 生成前，评估 AI 动作风险等级。
- HITLService : ActionGuard 判定需人工时触发，暂停 workflow 等待审核。
"""

from app.xuantong.safety.action_guard import (
    ActionGuard,
    ActionGuardLevel,
    ActionGuardResult,
)
from app.xuantong.safety.hitl import HITLDecision, HITLService
from app.xuantong.safety.input_guard import (
    InputGuard,
    InputGuardAction,
    InputGuardResult,
)
from app.xuantong.safety.output_guard import (
    OutputGuard,
    OutputGuardAction,
    OutputGuardResult,
)

__all__ = [
    # Input Guard
    "InputGuard",
    "InputGuardAction",
    "InputGuardResult",
    # Output Guard
    "OutputGuard",
    "OutputGuardAction",
    "OutputGuardResult",
    # Action Guard
    "ActionGuard",
    "ActionGuardLevel",
    "ActionGuardResult",
    # HITL
    "HITLDecision",
    "HITLService",
]
