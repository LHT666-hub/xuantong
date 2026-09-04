"""输出安全守卫 (Output Guard)。

玄同 Safety 层的第二道闸门，在每个 Agent 产出内容、下发给患者之前调用。
本模块是**4 态纯函数、无状态**的：不依赖 LLM，仅使用正则规则匹配，
可被独立单元测试。

4 种处置动作：
- PASS：直接通过。
- REWRITE：改写后通过（去掉诊断性语言、超范围承诺等）。
- BLOCK：完全阻断，不输出给患者（疑似幻觉内容）。
- ESCALATE：升级给人类医生审核（用药建议越权）。

严重度优先级：BLOCK > ESCALATE > REWRITE > PASS。
当内容命中多类违规时，取最严重的处置动作，并把全部违规记入 violations。
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field


class OutputGuardAction(str, Enum):
    """输出守卫的处置动作（4 态）。"""

    PASS = "pass"  # 直接通过
    REWRITE = "rewrite"  # 改写后通过（去掉诊断性语言等）
    BLOCK = "block"  # 完全阻断，不输出给患者
    ESCALATE = "escalate"  # 升级给人类医生审核


class OutputGuardResult(BaseModel):
    """输出守卫的检查结果。"""

    action: OutputGuardAction
    reason: str = ""
    rewritten_content: str | None = None  # action=rewrite 时的改写内容
    violations: list[str] = Field(default_factory=list)  # 违反的规则列表


class OutputGuard:
    """输出安全守卫 —— 4 态纯函数。"""

    # 诊断性语言模式（AI 不应直接下诊断）
    DIAGNOSTIC_PATTERNS: list[str] = [
        r"你(得了|患有|确诊了|已经被诊断为)",
        r"(你的诊断是|诊断为|确诊为)",
        r"(一定是|肯定是|无疑是).*(病|症|癌)",
    ]

    # 用药建议越权（AI 不应直接建议用药方案）
    MEDICATION_OVERRIDE_PATTERNS: list[str] = [
        r"(建议你|你应该|你需要)(开始|停止|换用|加量|减量)(服用|吃|用)",
        r"(处方|开药).*(改为|换成|调整为)",
        r"(每天|每日)(服用|吃)\d+.*(片|粒|mg|毫克)",
    ]

    # 超范围承诺
    OVERCOMMITMENT_PATTERNS: list[str] = [
        r"(保证|确保|一定)(能|会)(治好|康复|痊愈|根治)",
        r"(不需要|不用)(去医院|看医生|就医)",
        r"(没有|不会有)(任何|一切)(风险|副作用|问题)",
    ]

    # 幻觉检测关键词（不存在的药品名等 —— 基础版）
    HALLUCINATION_INDICATORS: list[str] = [
        # 常见幻觉模式：编造药品名
        r"(特效药|神药|万能药)",
    ]

    def __init__(self) -> None:
        self._diagnostic_compiled = [re.compile(p) for p in self.DIAGNOSTIC_PATTERNS]
        self._medication_compiled = [
            re.compile(p) for p in self.MEDICATION_OVERRIDE_PATTERNS
        ]
        self._overcommitment_compiled = [
            re.compile(p) for p in self.OVERCOMMITMENT_PATTERNS
        ]
        self._hallucination_compiled = [
            re.compile(p) for p in self.HALLUCINATION_INDICATORS
        ]

    def check(
        self, content: str, agent_role: str, context: dict | None = None
    ) -> OutputGuardResult:
        """4 态检查输出安全性。

        Args:
            content: Agent 产出的、准备下发给患者的文本。
            agent_role: 产出该内容的 Agent 角色（预留差异化策略）。
            context: 可选上下文（预留扩展）。

        Returns:
            OutputGuardResult: 处置动作、原因、改写内容与违规列表。
        """
        if not content:
            return OutputGuardResult(action=OutputGuardAction.PASS)

        violations: list[str] = []
        hit_diagnostic = any(r.search(content) for r in self._diagnostic_compiled)
        hit_medication = any(r.search(content) for r in self._medication_compiled)
        hit_overcommitment = any(
            r.search(content) for r in self._overcommitment_compiled
        )
        hit_hallucination = any(
            r.search(content) for r in self._hallucination_compiled
        )

        if hit_hallucination:
            violations.append("疑似幻觉内容")
        if hit_medication:
            violations.append("用药建议越权")
        if hit_diagnostic:
            violations.append("诊断性语言")
        if hit_overcommitment:
            violations.append("超范围承诺")

        # 1. 幻觉指标 → BLOCK（最严重，绝不输出给患者）
        if hit_hallucination:
            return OutputGuardResult(
                action=OutputGuardAction.BLOCK,
                reason="输出包含疑似幻觉内容（如编造的药品/疗效），已阻断",
                violations=violations,
            )

        # 2. 用药越权 → ESCALATE（需人类医生确认）
        if hit_medication:
            return OutputGuardResult(
                action=OutputGuardAction.ESCALATE,
                reason="输出包含用药方案调整建议，需人类医生审核确认",
                violations=violations,
            )

        # 3. 诊断性语言 / 超范围承诺 → REWRITE（改为建议性语言）
        if hit_diagnostic or hit_overcommitment:
            rewritten = content
            if hit_diagnostic:
                rewritten = self._rewrite_diagnostic(rewritten)
            if hit_overcommitment:
                rewritten = self._rewrite_overcommitment(rewritten)
            reasons = [v for v in ("诊断性语言", "超范围承诺") if v in violations]
            return OutputGuardResult(
                action=OutputGuardAction.REWRITE,
                reason=f"输出包含{'、'.join(reasons)}，已改写为建议性语言",
                rewritten_content=rewritten,
                violations=violations,
            )

        # 4. 全部通过 → PASS
        return OutputGuardResult(
            action=OutputGuardAction.PASS,
            reason="",
            violations=violations,
        )

    def _rewrite_diagnostic(self, content: str) -> str:
        """将诊断性语言改写为建议性语言。

        例："你得了高血压" → "您可能存在高血压，建议与医生确认是否需要进一步评估。"
        """
        rewritten = content
        rewritten = re.sub(
            r"你(得了|患有|确诊了|已经被诊断为)", "您可能存在", rewritten
        )
        rewritten = re.sub(
            r"(你的诊断是|诊断为|确诊为)", "初步评估提示可能为", rewritten
        )
        rewritten = re.sub(
            r"(一定是|肯定是|无疑是)", "可能需要进一步评估是否为", rewritten
        )
        if rewritten != content:
            rewritten = rewritten.rstrip("。！!") + "，建议与医生确认是否需要进一步评估。"
        return rewritten

    def _rewrite_overcommitment(self, content: str) -> str:
        """改写超范围承诺。

        例："保证能治好" → "有助于改善，具体请遵循医生指导。"
        """
        rewritten = content
        rewritten = re.sub(
            r"(保证|确保|一定)(能|会)(治好|康复|痊愈|根治)", "有助于改善", rewritten
        )
        rewritten = re.sub(
            r"(不需要|不用)(去医院|看医生|就医)", "仍建议适时就医", rewritten
        )
        rewritten = re.sub(
            r"(没有|不会有)(任何|一切)(风险|副作用|问题)",
            "仍需留意可能存在的风险",
            rewritten,
        )
        if rewritten != content:
            rewritten = rewritten.rstrip("。！!") + "，具体请遵循医生指导。"
        return rewritten
