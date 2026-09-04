"""Qwen Provider — 阿里云百炼 DashScope（OpenAI 兼容模式）"""
import time
import logging
from typing import AsyncIterator

from app.xuantong.llm.provider import (
    ModelRequest, ModelResponse, StreamChunk, ProviderHealth,
)

logger = logging.getLogger(__name__)


class QwenProvider:
    """阿里云百炼 Qwen 系列 Provider（OpenAI 兼容模式）。

    支持：
    - 文本对话（qwen3-max / qwen-plus / qwen-flash）
    - 视觉理解（qwen3-vl-flash）
    - OCR（qwen-vl-ocr）
    - 流式输出
    - Qwen 私有参数（enable_thinking 等）通过 extra_body 传入
    """
    name = "qwen"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "qwen-plus",
    ):
        self._api_key = api_key
        self._base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self._default_model = default_model
        self._client = None

    @property
    def client(self):
        """延迟初始化 AsyncOpenAI 客户端"""
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "QwenProvider requires API key. Set LLM_API_KEY in .env"
                )
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """非流式调用 Qwen 模型"""
        model = request.model_id or self._default_model
        start = time.monotonic()

        # 构建请求参数
        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens

        # Qwen 私有参数通过 extra_body 传入
        if request.extra_body:
            kwargs["extra_body"] = request.extra_body

        logger.debug(f"QwenProvider.complete: model={model}, messages={len(request.messages)}")

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
            provider="qwen",
            model=model,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=elapsed,
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        """流式调用 Qwen 模型"""
        model = request.model_id or self._default_model

        kwargs: dict = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        if request.extra_body:
            kwargs["extra_body"] = request.extra_body

        stream = await self.client.chat.completions.create(**kwargs)

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield StreamChunk(
                    content=chunk.choices[0].delta.content,
                    finish_reason=chunk.choices[0].finish_reason,
                )

    async def health(self) -> ProviderHealth:
        """检查 Provider 健康状态"""
        if not self._api_key:
            return ProviderHealth(
                provider="qwen",
                healthy=False,
                message="API key not configured",
            )

        # 轻量级健康检查：尝试列出模型或发送最小请求
        try:
            response = await self.client.chat.completions.create(
                model=self._default_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            return ProviderHealth(
                provider="qwen",
                healthy=True,
                message=f"Qwen API OK (model={self._default_model})",
            )
        except Exception as e:
            return ProviderHealth(
                provider="qwen",
                healthy=False,
                message=f"Qwen API error: {str(e)[:200]}",
            )
