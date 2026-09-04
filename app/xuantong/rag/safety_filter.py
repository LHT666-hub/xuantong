"""RAG 安全过滤器 — PHI 脱敏 + 注入攻击检测。

从 MedHarness 移植，适配中国医疗场景。
fail-closed 策略：检测到 PHI 即脱敏，检测到注入即拦截。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class SafetyFilterResult(BaseModel):
    """安全过滤结果。"""

    passed: bool = Field(description="是否通过安全检查")
    reason: str = Field(default="", description="未通过原因")
    sanitized_content: str = Field(default="", description="脱敏后的内容")


class RAGSafetyFilter:
    """RAG 安全过滤器 — PHI 脱敏 + 注入检测。"""

    # PHI 模式（中国医疗场景）
    PHI_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("id_card", re.compile(r"\d{17}[\dXx]")),
        ("id_card_full", re.compile(
            r"\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]"
        )),
        ("phone", re.compile(r"1[3-9]\d{9}")),
        ("email", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
    ]

    # 注入攻击模式
    INJECTION_PATTERNS: list[re.Pattern[str]] = [
        re.compile(
            r"(ignore|forget|disregard).*(previous|above|all).*(instructions|rules)",
            re.IGNORECASE,
        ),
        re.compile(r"system\s*:\s*", re.IGNORECASE),
        re.compile(r"<\|.*?\|>"),
    ]

    def filter_content(self, content: str) -> SafetyFilterResult:
        """过滤单条检索结果内容。

        检查顺序：PHI → 注入 → 通过。
        """
        if not content:
            return SafetyFilterResult(passed=True, sanitized_content="")

        # 1. PHI 检测（fail-closed：检测到即脱敏）
        for _name, pattern in self.PHI_PATTERNS:
            if pattern.search(content):
                sanitized = pattern.sub("[已脱敏]", content)
                return SafetyFilterResult(
                    passed=False,
                    reason="phi_detected",
                    sanitized_content=sanitized,
                )

        # 2. 注入检测
        for pattern in self.INJECTION_PATTERNS:
            if pattern.search(content):
                return SafetyFilterResult(
                    passed=False,
                    reason="injection_detected",
                    sanitized_content="",
                )

        # 3. 通过
        return SafetyFilterResult(passed=True, sanitized_content=content)

    def filter_batch(self, contents: list[str]) -> list[SafetyFilterResult]:
        """批量过滤。"""
        return [self.filter_content(c) for c in contents]
