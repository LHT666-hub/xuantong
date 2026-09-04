from app.xuantong.llm.provider import (
    ModelProvider, ModelRequest, ModelResponse, StreamChunk, ProviderHealth
)


class MockProvider:
    """Mock LLM Provider。用于测试，无需真实 API Key。

    支持配置预设响应模板。默认返回基于输入的结构化响应。
    """
    name = "mock"

    def __init__(self, responses: dict[str, str] | None = None):
        """
        Args:
            responses: 可选的预设响应模板。
                       key 为匹配关键词（在用户消息中），value 为响应内容。
        """
        self._responses = responses or {}
        self._call_count = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self._call_count += 1

        # 尝试匹配预设响应
        user_content = ""
        for msg in request.messages:
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        response_content = None
        for keyword, response in self._responses.items():
            if keyword in user_content:
                response_content = response
                break

        if response_content is None:
            # 默认响应：回显最后一条用户消息 + 标记为 mock
            response_content = f"[MockProvider] 收到消息: {user_content[:100]}"

        total_input = sum(len(m.get("content", "")) for m in request.messages)

        return ModelResponse(
            content=response_content,
            provider="mock",
            model="mock-v1",
            finish_reason="stop",
            prompt_tokens=max(1, total_input // 4),
            completion_tokens=len(response_content) // 4,
        )

    async def stream(self, request: ModelRequest):
        response = await self.complete(request)
        yield StreamChunk(content=response.content, finish_reason="stop")

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="mock",
            healthy=True,
            message=f"MockProvider OK (calls={self._call_count})",
        )
