from pydantic import BaseModel
from app.schemas.agent import AgentRole


class DispatchDecision(BaseModel):
    """FamilyDoctorAgent 的事件分析与调度决策。

    既保留既有的意图/技能路由字段，又扩展了事件分诊结构，
    以便 LLM 直接产出严重程度、团队成员选择与即时处置建议。
    """

    # ── 既有字段（意图 / 技能 / 工作流路由）───────────────────
    intent: str = ""
    selected_agents: list[AgentRole] = []  # 专业会诊团队（不含 Assistant）
    selected_skills: list[str] = []
    workflow: str | None = None
    reason: str = ""

    # ── 事件分诊结构（analyze_event 产出）─────────────────────
    event_summary: str = ""                # 事件摘要
    severity: str = "low"                  # low / moderate / high / emergency
    reasoning: str = ""                    # 决策理由
    immediate_actions: list[str] = []      # 即时处置建议
    requires_urgent_response: bool = False  # 是否需要紧急响应
