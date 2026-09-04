"""动作安全守卫 (Action Guard)。

玄同 Safety 层的第三道闸门，在 Task 生成之前评估 AI 想要执行的动作风险。
本模块是**纯函数、无状态**的：不依赖 LLM，仅使用规则表判定。

四级风险：
- LOW：直接执行（信息查询、数据展示）。
- MEDIUM：自动执行但记录审计（预约、提醒、随访安排）。
- HIGH：需要人类确认后执行（转诊建议、用药调整建议）。
- CRITICAL：必须人类执行，AI 仅提供建议（紧急呼叫、停药、住院）。

当临床风险为 red 时，所有动作等级自动升一级（critical 封顶），
体现"宁严勿松"的安全策略。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.clinical import ActionRiskAssessment


class ActionGuardLevel(str, Enum):
    """AI 动作风险等级。"""

    LOW = "low"  # 直接执行（信息查询、数据展示）
    MEDIUM = "medium"  # 自动执行但记录审计（预约、提醒、随访安排）
    HIGH = "high"  # 需要人类确认后执行（转诊建议、用药调整建议）
    CRITICAL = "critical"  # 必须人类执行，AI 仅提供建议


# 等级排序，用于比较与升级
_LEVEL_ORDER: list[ActionGuardLevel] = [
    ActionGuardLevel.LOW,
    ActionGuardLevel.MEDIUM,
    ActionGuardLevel.HIGH,
    ActionGuardLevel.CRITICAL,
]
_LEVEL_RANK: dict[ActionGuardLevel, int] = {
    level: idx for idx, level in enumerate(_LEVEL_ORDER)
}

# 需要人类介入的等级
_HUMAN_REQUIRED_LEVELS = {ActionGuardLevel.HIGH, ActionGuardLevel.CRITICAL}


class ActionGuardResult(BaseModel):
    """动作守卫的评估结果。"""

    level: ActionGuardLevel
    requires_human: bool
    reasons: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)  # 可自动执行的动作
    blocked_actions: list[str] = Field(default_factory=list)  # 需人工的动作


class ActionGuard:
    """动作安全守卫 —— 评估 AI 动作风险，纯函数、无状态。"""

    # 动作分类规则：动作类型 → 风险等级
    ACTION_RULES: dict[str, str] = {
        # LOW: 信息查询类
        "query_patient_info": "low",
        "display_vital_signs": "low",
        "show_medication_list": "low",
        "generate_report": "low",
        # MEDIUM: 协调执行类（AssistantAgent 的日常工作）
        "send_reminder": "medium",
        "schedule_appointment": "medium",
        "notify_family_member": "medium",
        "schedule_followup": "medium",
        "send_health_education": "medium",
        # HIGH: 需确认类
        "suggest_referral": "high",
        "suggest_medication_change": "high",
        "escalate_to_specialist": "high",
        "modify_care_plan": "high",
        # CRITICAL: 仅建议类
        "emergency_call": "critical",
        "stop_medication": "critical",
        "hospitalization_recommendation": "critical",
    }

    # 未知动作的默认等级（宁严勿松）
    DEFAULT_LEVEL = ActionGuardLevel.HIGH

    def check(
        self,
        actions: list[str],
        clinical_risk_level: str = "green",
        patient_context: dict | None = None,
    ) -> ActionGuardResult:
        """评估一组动作的风险等级。

        Args:
            actions: 待执行的动作类型列表。
            clinical_risk_level: 患者当前临床风险（green / yellow / red）。
                为 red 时，所有动作等级自动升一级。
            patient_context: 可选患者上下文（预留扩展）。

        Returns:
            ActionGuardResult: 整体等级、是否需人工、原因及动作分组。
        """
        escalate_all = (clinical_risk_level or "").lower() == "red"

        reasons: list[str] = []
        allowed_actions: list[str] = []
        blocked_actions: list[str] = []
        overall = ActionGuardLevel.LOW
        has_action = False

        for action in actions or []:
            has_action = True
            base_level = self._lookup_level(action, reasons)
            final_level = self._escalate(base_level) if escalate_all else base_level

            if escalate_all and final_level != base_level:
                reasons.append(
                    f"临床风险为 red，动作 '{action}' 等级由 "
                    f"{base_level.value} 升级为 {final_level.value}"
                )

            if final_level in _HUMAN_REQUIRED_LEVELS:
                blocked_actions.append(action)
            else:
                allowed_actions.append(action)

            if _LEVEL_RANK[final_level] > _LEVEL_RANK[overall]:
                overall = final_level

        if not has_action:
            reasons.append("无待评估动作，默认为最低风险")

        requires_human = overall in _HUMAN_REQUIRED_LEVELS
        return ActionGuardResult(
            level=overall,
            requires_human=requires_human,
            reasons=reasons,
            allowed_actions=allowed_actions,
            blocked_actions=blocked_actions,
        )

    def _lookup_level(self, action: str, reasons: list[str]) -> ActionGuardLevel:
        """查规则表确定单个动作的基础等级；未知动作按 DEFAULT_LEVEL 处理。"""
        raw = self.ACTION_RULES.get(action)
        if raw is None:
            reasons.append(f"未知动作 '{action}'，按最高谨慎等级处理")
            return self.DEFAULT_LEVEL
        return ActionGuardLevel(raw)

    @staticmethod
    def _escalate(level: ActionGuardLevel) -> ActionGuardLevel:
        """将等级升一级，critical 封顶。"""
        rank = _LEVEL_RANK[level]
        return _LEVEL_ORDER[min(rank + 1, len(_LEVEL_ORDER) - 1)]

    def to_action_risk_assessment(
        self, result: ActionGuardResult
    ) -> ActionRiskAssessment:
        """转换为 Pydantic schema（与 state 中的 action_risk 字段对接）。"""
        return ActionRiskAssessment(
            level=result.level.value,
            reasons=list(result.reasons),
            requires_human=result.requires_human,
        )
