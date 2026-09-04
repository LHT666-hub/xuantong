"""DeepSeek Provider。V0.1 骨架，需要配置 LLM_API_KEY 和 LLM_BASE_URL 才能使用。"""
from app.xuantong.llm.provider import (
    ModelProvider, ModelRequest, ModelResponse, StreamChunk, ProviderHealth,
)


class DeepSeekProvider:
    """DeepSeek Provider。
    使用 OpenAI-compatible API。
    V0.1 骨架实现，实际调用需要配置 API Key。
    """
    name = "deepseek"

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "deepseek-chat"):
        self._api_key = api_key
        self._base_url = base_url or "https://api.deepseek.com/v1"
        self._model = model

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if not self._api_key:
            raise RuntimeError("DeepSeekProvider requires API key. Set LLM_API_KEY in .env")
        # TODO: 实现实际 API 调用
        raise NotImplementedError("DeepSeekProvider.complete() not yet implemented")

    async def stream(self, request: ModelRequest):
        raise NotImplementedError("DeepSeekProvider.stream() not yet implemented")

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider="deepseek",
            healthy=bool(self._api_key),
            message="Configured" if self._api_key else "API key not configured",
        )
