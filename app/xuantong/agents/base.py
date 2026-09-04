"""Agent 基类。

不锁死 LLM 调用次数：
- AssistantAgent 发预约提醒可能 0 次 LLM
- FamilyDoctorAgent 可能需要多次

通过 max_steps / max_llm_calls / timeout 控制上限。

除执行入口 execute() 外，基类统一提供：
- _invoke_json(): 结构化 JSON 调用（含解析失败重试）
- _extract_json(): 从模型输出中稳健提取 JSON 对象
- _guard_patient_text(): 患者可见文本经 OutputGuard 安全处置
- _dumps(): 输入数据序列化

设计原则：LLM 调用失败 / 超时 / 输出非法时**不抛异常中断流程**，
而是记录日志并返回 None，由各 Agent 决定降级默认响应。
"""

import json
import logging
import re
from typing import Any

from app.schemas.agent import AgentResult
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext

logger = logging.getLogger(__name__)


class BaseAgent:
    """Agent 抽象基类。子类覆写 execute() 并定义 SYSTEM_PROMPT。"""

    role: str = ""
    display_name: str = ""
    description: str = ""

    # 子类的系统提示词（角色定位 + 边界 + 输出格式约束）
    SYSTEM_PROMPT: str = ""

    # 结构化输出的默认采样温度（低温以提升 JSON 稳定性）
    json_temperature: float = 0.3

    # 上限控制（子类可覆盖）
    max_llm_calls: int = 3
    max_steps: int = 5
    timeout_seconds: int = 30

    def __init__(self, llm_runtime: Any = None) -> None:
        self.llm_runtime = llm_runtime
        self._llm_call_count: int = 0
        self._output_guard = None  # 懒加载，避免无谓导入

    # ────────────────────────────────────────────────────────
    # 子类覆写点
    # ────────────────────────────────────────────────────────

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        """执行 Agent 逻辑。子类必须覆写。

        内部自行决定 0..N 次 LLM 调用（受 max_llm_calls 约束）。
        """
        raise NotImplementedError

    # ────────────────────────────────────────────────────────
    # LLM 调用（带计数）
    # ────────────────────────────────────────────────────────

    async def _call_llm(self, messages: list[dict], **kwargs: Any) -> str:
        """调用 LLM，自动计数并检查上限。"""
        if self.llm_runtime is None:
            raise RuntimeError(f"{self.display_name}: LLM Runtime not configured")

        self._llm_call_count += 1
        if self._llm_call_count > self.max_llm_calls:
            raise RuntimeError(
                f"{self.display_name}: Exceeded max LLM calls ({self.max_llm_calls})"
            )

        response = await self.llm_runtime.invoke(
            agent_role=self.role,
            messages=messages,
            **kwargs,
        )
        return response.content

    async def _invoke_json(
        self,
        user_content: str,
        *,
        enable_thinking: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int = 1,
    ) -> dict | None:
        """发起一次结构化 JSON 调用。

        流程：system(SYSTEM_PROMPT) + user(user_content) → LLM → 提取 JSON。
        若解析失败，追加一轮"请严格输出 JSON"的纠正对话后重试。

        Args:
            user_content: 用户消息（含事件数据与输出格式要求）。
            enable_thinking: 是否开启 Qwen 思考模式（通过 extra_body 传入）。
            temperature: 采样温度，默认使用 self.json_temperature。
            max_tokens: 最大生成 token。
            retries: 解析失败后的额外重试次数（默认 1，即最多 2 次调用）。

        Returns:
            解析出的 JSON dict；全部失败或 LLM 不可用时返回 None（不抛异常）。
        """
        if not self.SYSTEM_PROMPT:
            logger.warning(f"{self.display_name}: SYSTEM_PROMPT 未定义")

        extra_body = {"enable_thinking": True} if enable_thinking else None
        temp = self.json_temperature if temperature is None else temperature

        messages: list[dict] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        for attempt in range(retries + 1):
            try:
                content = await self._call_llm(
                    messages,
                    temperature=temp,
                    max_tokens=max_tokens,
                    extra_body=extra_body,
                )
            except Exception as e:  # LLM 不可用 / 超时 / 超出调用上限
                logger.error(f"{self.display_name}: LLM 调用失败: {e}")
                return None

            data = self._extract_json(content)
            if data is not None:
                return data

            logger.warning(
                f"{self.display_name}: 第 {attempt + 1} 次输出非法 JSON，"
                f"内容前 120 字: {content[:120]!r}"
            )
            # 追加纠正对话，进入下一轮重试
            messages = messages + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "你上一次的输出不是合法 JSON。请严格只输出一个 JSON 对象，"
                        "不要包含 markdown 代码块、注释或任何额外说明文字。"
                    ),
                },
            ]

        logger.error(f"{self.display_name}: JSON 解析在 {retries + 1} 次尝试后仍失败")
        return None

    # ────────────────────────────────────────────────────────
    # 内部工具
    # ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """从模型输出中稳健提取 JSON 对象。

        依次尝试：直接解析 → 去除 ```json 代码围栏 → 截取首个 { 到末个 }。
        仅接受 JSON 对象（dict）；数组或非法内容返回 None。
        """
        if not text:
            return None

        s = text.strip()

        # 去除 markdown 代码围栏 ```json ... ```
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
            s = re.sub(r"\s*```$", "", s).strip()

        for candidate in (s, None):
            if candidate is None:
                start, end = s.find("{"), s.rfind("}")
                if start == -1 or end == -1 or end <= start:
                    break
                candidate = s[start : end + 1]
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
            return None

        return None

    @staticmethod
    def _dumps(obj: Any) -> str:
        """将输入数据序列化为紧凑 JSON 文本（保留中文）。

        自动处理 Pydantic 模型（model_dump）与 datetime 等类型。
        """
        def _default(o: Any) -> Any:
            model_dump = getattr(o, "model_dump", None)
            if callable(model_dump):
                return model_dump(mode="json")
            return str(o)

        try:
            return json.dumps(obj, ensure_ascii=False, default=_default)
        except (TypeError, ValueError):
            return str(obj)

    @classmethod
    def _to_plain(cls, obj: Any) -> Any:
        """将 Pydantic 模型转为普通 dict，其余原样返回。"""
        model_dump = getattr(obj, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json")
        return obj

    def _guard_patient_text(self, text: str) -> str:
        """对患者可见文本执行 OutputGuard 安全处置。

        - PASS: 原样返回
        - REWRITE: 返回改写后的安全文本
        - BLOCK: 返回中性占位文本（疑似幻觉，绝不下发）
        - ESCALATE: 保留原文但记录日志（需人类医生审核）

        OutputGuard 为纯函数、不依赖 LLM，失败时降级为原样返回。
        """
        if not text:
            return text
        try:
            if self._output_guard is None:
                from app.xuantong.safety import OutputGuard

                self._output_guard = OutputGuard()
            result = self._output_guard.check(text, self.role)
        except Exception as e:  # 安全层异常不应阻断主流程
            logger.warning(f"{self.display_name}: OutputGuard 检查异常，跳过: {e}")
            return text

        action = getattr(result.action, "value", str(result.action))
        if action == "rewrite" and result.rewritten_content:
            logger.info(f"{self.display_name}: 患者文本已改写（{result.reason}）")
            return result.rewritten_content
        if action == "block":
            logger.warning(f"{self.display_name}: 患者文本被阻断（{result.reason}）")
            return "您的情况我们已记录，家庭医生团队会尽快与您联系，请留意后续通知。"
        if action == "escalate":
            logger.warning(f"{self.display_name}: 患者文本需人工审核（{result.reason}）")
        return text

    def _reset_counters(self) -> None:
        """每次 execute 开始前重置计数器。"""
        self._llm_call_count = 0
