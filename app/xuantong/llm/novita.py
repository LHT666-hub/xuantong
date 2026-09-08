"""Novita AI Provider — Ling 3.0 Flash Santé 医疗模型（OpenAI 兼容模式）"""
import time
import logging
from typing import AsyncIterator

from app.xuantong.llm.provider import (
    ModelRequest, ModelResponse, StreamChunk, ProviderHealth,
)

logger = logging.getLogger(__name__)


class NovitaProvider:
    """Novita AI 医疗模型 Provider（OpenAI 兼容模式）。

    支持：
    - 文本对话（Ling 3.0 Flash Santé 医疗专用模型）
    - 流式输出
    - 健康检查
    """
    name = "novita"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "inclusional/ling-3.0-flash-sante",
    ):
        self._api_key = api_key
        self._base_url = base_url or "https://api.novita.ai/openai"
        self._default_model = default_model
        self._client = None

    @property
    def client(self):
        """延迟初始化 AsyncOpenAI 客户端"""
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "NovitaProvider requires API key. Set NOVITA_API_KEY in .env"
                )
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """非流式调用 Novita 医疗模型"""
        model = request.model_id or self._default_model
        start = time.monotonic()

        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens

        logger.debug(
            f"NovitaProvider.complete: model={model}, messages={len(request.messages)}"
        )

        response = await self.client.chat.completions.create(**kwargs)

        elapsed = int((time.monotonic() - start) * 1000)
        choice = response.choices[0] if response.choices else None

        content = ""
        finish_reason = "stop"
        if choice:
            content = choice.message.content or ""
            finish_reason = choice.finish_reason or "stop"

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        return ModelResponse(
            content=content,
            provider="novita",
            model=model,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=elapsed,
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        """流式调用 Novita 医疗模型"""
        model = request.model_id or self._default_model

        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens

        stream = await self.client.chat.completions.create(**kwargs)

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield StreamChunk(
                    content=chunk.choices[0].delta.content,
                    finish_reason=chunk.choices[0].finish_reason,
                )

    async def health(self) -> ProviderHealth:
        """检查 Novita Provider 健康状态"""
        if not self._api_key:
            return ProviderHealth(
                provider="novita",
                healthy=False,
                message="API key not configured",
            )

        try:
            response = await self.client.chat.completions.create(
                model=self._default_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            return ProviderHealth(
                provider="novita",
                healthy=True,
                message=f"Novita API OK (model={self._default_model})",
            )
        except Exception as e:
            return ProviderHealth(
                provider="novita",
                healthy=False,
                message=f"Novita API error: {str(e)[:200]}",
            )
