"""输入安全守卫 (Input Guard)。

玄同 Safety 层的第一道闸门，在 LangGraph workflow 入口处被调用。
本模块是**纯函数、无状态**的：不依赖 LLM，仅使用正则规则做匹配，
可被独立单元测试。

职责：
1. 危机检测（最高优先级）——自杀/自残、急性心血管、急性脑血管、
   严重过敏、急性呼吸困难等，命中后返回 EMERGENCY，跳过常规流程，
   交由 EmergencyRuleEngine / 人工处理。
2. 注入攻击检测——识别 prompt injection 常见模式，命中后 BLOCK。
3. 输入长度验证——超长输入直接 BLOCK。
4. 其余情况 PASS，并返回清理后的 sanitized_input。

设计原则：危机检测**宁严勿松**（宁可误报也不能漏报）。
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel


class InputGuardAction(str, Enum):
    """输入守卫的处置动作。"""

    PASS = "pass"
    BLOCK = "block"
    EMERGENCY = "emergency"  # 检测到危机，跳过常规流程


class InputGuardResult(BaseModel):
    """输入守卫的检查结果。"""

    action: InputGuardAction
    reason: str = ""
    emergency_type: str | None = None  # suicide_risk / acute_cardiac / ...
    sanitized_input: str | None = None  # 清理后的输入


class InputGuard:
    """输入安全守卫 —— 纯函数，无状态。"""

    # 最大输入长度（字符）
    MAX_INPUT_LENGTH = 10000

    # 危机关键词模式：(正则, 危机类型)
    # 宁严勿松：命中任意一条即触发 EMERGENCY。
    CRISIS_PATTERNS: list[tuple[str, str]] = [
        # 自杀 / 自残
        (r"(想死|不想活|自杀|活着没意思|结束生命|割腕|跳楼)", "suicide_risk"),
        # 急性心血管（宁严勿松：胸痛/胸口/胸闷 + 压迫/压榨/放射 均触发）
        (r"(胸[痛口闷].*(?:压迫|压榨|放射)|胸口.*(?:剧烈|撕裂).*痛)", "acute_cardiac"),
        # 急性脑血管
        (r"(突然.*(?:说不出话|口角歪斜|一侧.*无力|意识不清))", "acute_stroke"),
        # 严重过敏
        (r"(全身.*(?:红肿|荨麻疹).*(?:呼吸|喉).*(?:困难|紧))", "anaphylaxis"),
        # 急性呼吸困难
        (r"(喘不上气|呼吸.*困难.*(?:严重|加重)|窒息)", "respiratory_emergency"),
    ]

    # 注入攻击模式（英文 prompt injection 常见特征）
    INJECTION_PATTERNS: list[str] = [
        r"(ignore|forget|disregard).*(previous|above|all).*(instructions|rules|prompts)",
        r"system\s*:\s*",
        r"<\|.*?\|>",
        r"\[INST\]",
    ]

    def __init__(self) -> None:
        # 预编译正则，提升重复调用性能（编译结果不改变纯函数语义）。
        self._crisis_compiled = [
            (re.compile(pattern), crisis_type)
            for pattern, crisis_type in self.CRISIS_PATTERNS
        ]
        self._injection_compiled = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.INJECTION_PATTERNS
        ]

    def check(self, text: str, metadata: dict | None = None) -> InputGuardResult:
        """检查输入安全性。

        Args:
            text: 患者/用户原始输入文本。
            metadata: 可选上下文元数据（预留扩展，当前不参与判定）。

        Returns:
            InputGuardResult: 包含处置动作、原因、危机类型或清理后的输入。
        """
        if text is None:
            return InputGuardResult(
                action=InputGuardAction.BLOCK,
                reason="输入为空",
            )

        # 1. 危机检测（最高优先级）—— 宁严勿松，优先于注入/长度判断。
        for regex, crisis_type in self._crisis_compiled:
            if regex.search(text):
                return InputGuardResult(
                    action=InputGuardAction.EMERGENCY,
                    reason=f"检测到危机信号：{crisis_type}",
                    emergency_type=crisis_type,
                )

        # 2. 注入攻击检测
        for regex in self._injection_compiled:
            if regex.search(text):
                return InputGuardResult(
                    action=InputGuardAction.BLOCK,
                    reason="检测到疑似提示词注入攻击",
                )

        # 3. 输入长度验证
        if len(text) > self.MAX_INPUT_LENGTH:
            return InputGuardResult(
                action=InputGuardAction.BLOCK,
                reason=f"输入超长（>{self.MAX_INPUT_LENGTH} 字符）",
            )

        # 4. 通过 —— 返回清理后的输入
        return InputGuardResult(
            action=InputGuardAction.PASS,
            reason="",
            sanitized_input=self._sanitize(text),
        )

    @staticmethod
    def _sanitize(text: str) -> str:
        """清理输入：去除首尾空白并折叠多余空行。

        保持纯函数语义，不改变原始语义内容。
        """
        cleaned = re.sub(r"[ \t]+", " ", text)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
