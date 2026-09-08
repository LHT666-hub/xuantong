"""LLM Runtime — 统一模型调用入口（多模型分层路由 + 超时 + 指数退避重试）"""
import asyncio
import time
import logging
from typing import AsyncIterator

from app.xuantong.llm.provider import (
    ModelProvider, ModelRequest, ModelResponse, StreamChunk, ModelTier,
)

logger = logging.getLogger(__name__)


class LLMRuntime:
    """统一模型调用入口。

    职责：
    - 根据 agent_role 自动路由到对应模型层级
    - 超时控制（asyncio.wait_for）
    - 指数退避重试
    - 调用审计与 token 统计
    - 多模态调用（视觉 / 语音）

    不理解医疗业务，纯编排层。
    """

    def __init__(
        self,
        provider: ModelProvider,
        max_retries: int = 3,
        timeout_seconds: float = 60.0,
        retry_base_delay: float = 1.0,
        settings=None,
        medical_provider: ModelProvider | None = None,
    ):
        self.provider = provider
        self.medical_provider = medical_provider  # Novita Ling 3.0（可选）
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.retry_base_delay = retry_base_delay
        self._settings = settings  # 可选的 Settings 实例，用于模型路由
        self._call_count = 0
        self._total_tokens = 0
        self._medical_call_count = 0

    def _resolve_model(self, agent_role: str, model_id: str = "", model_tier: ModelTier | None = None) -> str:
        """解析最终使用的模型名称。

        优先级：model_id > model_tier > agent_role 映射 > settings 默认
        """
        if model_id:
            return model_id

        if model_tier and self._settings:
            return self._settings.get_model_for_tier(model_tier.value)

        if agent_role and self._settings:
            return self._settings.get_model_for_agent(agent_role)

        # fallback: 使用 provider 默认模型
        return ""

    def _select_provider(self, agent_role: str) -> "ModelProvider":
        """根据 agent_role 选择 provider：医疗 Agent 优先走 Novita，其他走 Qwen。"""
        if (
            self.medical_provider is not None
            and self._settings
            and self._settings.use_medical_model
            and self._settings.is_medical_agent(agent_role)
        ):
            return self.medical_provider
        return self.provider

    async def invoke(
        self,
        agent_role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        model_id: str = "",
        model_tier: ModelTier | None = None,
        extra_body: dict | None = None,
        **kwargs,
    ) -> ModelResponse:
        """调用模型，含自动路由、超时、指数退避重试和审计。

        Args:
            agent_role: Agent 角色标识，用于自动选择模型
            messages: 对话消息列表
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            model_id: 直接指定模型（跳过路由）
            model_tier: 指定模型层级（跳过 agent_role 路由）
            extra_body: Qwen 私有参数，如 {"enable_thinking": True}
            **kwargs: 附加元数据
        """
        resolved_model = self._resolve_model(agent_role, model_id, model_tier)

        request = ModelRequest(
            model_id=resolved_model,
            model_tier=model_tier,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body or {},
            agent_role=agent_role,
            metadata=kwargs,
        )

        selected = self._select_provider(agent_role)
        try:
            return await self._execute_with_retry(request, agent_role, provider=selected)
        except Exception:
            # 医疗 Provider 失败时回退到主 Provider（Qwen）
            if selected is self.medical_provider:
                logger.warning(
                    "Novita 医疗模型调用失败，回退到 Qwen: agent=%s", agent_role
                )
                return await self._execute_with_retry(request, agent_role, provider=self.provider)
            raise

    async def invoke_with_vision(
        self,
        agent_role: str,
        prompt: str,
        image_data: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int | None = None,
        model_id: str = "",
        **kwargs,
    ) -> ModelResponse:
        """视觉理解调用（图片 + 文本）。

        Args:
            agent_role: Agent 角色
            prompt: 文本提示
            image_data: 图片数据（base64 或 URL）
            system_prompt: 系统提示
            temperature: 采样温度（视觉任务建议低温度）
            max_tokens: 最大生成 token
            model_id: 直接指定模型，默认使用 vision 层级
        """
        # 构建多模态消息
        content_parts = []
        if image_data.startswith("http://") or image_data.startswith("https://"):
            image_url = image_data
        else:
            # 假设是 base64 编码
            image_url = f"data:image/jpeg;base64,{image_data}"

        content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
        content_parts.append({"type": "text", "text": prompt})

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content_parts})

        resolved_model = model_id
        if not resolved_model and self._settings:
            resolved_model = self._settings.get_model_for_tier("vision")

        request = ModelRequest(
            model_id=resolved_model,
            model_tier=ModelTier.VISION,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            agent_role=agent_role,
            metadata=kwargs,
        )

        return await self._execute_with_retry(request, agent_role, provider=self.provider)

    async def invoke_with_speech(
        self,
        audio_url: str,
        language_hints: list[str] | None = None,
        model_id: str = "",
        **kwargs,
    ) -> ModelResponse:
        """语音识别调用。

        Args:
            audio_url: 音频文件 URL 或 base64 数据
            language_hints: 语言提示，如 ["zh", "yue"]
            model_id: 直接指定模型，默认使用 asr 层级
        """
        resolved_model = model_id
        if not resolved_model and self._settings:
            resolved_model = self._settings.get_model_for_tier("asr")

        # 构建语音消息（OpenAI 兼容格式）
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_url},
                    }
                ],
            }
        ]

        extra_body = {}
        if language_hints:
            extra_body["asr_options"] = {"language_hints": language_hints}

        request = ModelRequest(
            model_id=resolved_model,
            model_tier=ModelTier.ASR,
            messages=messages,
            temperature=0.0,
            extra_body=extra_body,
            agent_role="asr",
            metadata=kwargs,
        )

        return await self._execute_with_retry(request, agent_role, provider=self.provider)

    async def stream(
        self,
        agent_role: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        model_id: str = "",
        model_tier: ModelTier | None = None,
        extra_body: dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用模型"""
        resolved_model = self._resolve_model(agent_role, model_id, model_tier)

        request = ModelRequest(
            model_id=resolved_model,
            model_tier=model_tier,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body or {},
            agent_role=agent_role,
            metadata=kwargs,
        )

        active_provider = self._select_provider(agent_role)
        async for chunk in active_provider.stream(request):
            yield chunk

    def _resolve_timeout(self, request: ModelRequest) -> float:
        """根据请求的模型层级解析超时时间，优先分层配置，fallback 到全局 timeout_seconds。"""
        if request.model_tier and self._settings:
            return float(self._settings.get_timeout_for_tier(request.model_tier.value))
        # 尝试通过 agent_role 推断层级
        if request.agent_role and self._settings:
            tier = self._settings.llm_agent_model_map.get(request.agent_role)
            if tier:
                return float(self._settings.get_timeout_for_tier(tier))
        return self.timeout_seconds

    async def _execute_with_retry(self, request: ModelRequest, agent_role: str, provider: "ModelProvider | None" = None) -> ModelResponse:
        """带超时和指数退避重试的执行逻辑"""
        if provider is None:
            provider = self.provider
        last_error = None
        timeout = self._resolve_timeout(request)

        for attempt in range(self.max_retries + 1):
            try:
                start = time.monotonic()

                # 超时控制（按模型层级动态调整）
                response = await asyncio.wait_for(
                    provider.complete(request),
                    timeout=timeout,
                )

                elapsed = int((time.monotonic() - start) * 1000)
                response.elapsed_ms = elapsed

                self._call_count += 1
                if provider is self.medical_provider:
                    self._medical_call_count += 1
                self._total_tokens += response.prompt_tokens + response.completion_tokens

                logger.info(
                    f"LLM call #{self._call_count} | agent={agent_role} "
                    f"| provider={response.provider} model={response.model} "
                    f"| tokens={response.prompt_tokens}+{response.completion_tokens} "
                    f"| elapsed={elapsed}ms"
                )
                return response

            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(
                    f"LLM call attempt {attempt + 1}/{self.max_retries + 1} "
                    f"timeout ({timeout}s): agent={agent_role}"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"LLM call attempt {attempt + 1}/{self.max_retries + 1} "
                    f"failed: agent={agent_role}, error={e}"
                )

            # 指数退避
            if attempt < self.max_retries:
                delay = self.retry_base_delay * (2 ** attempt)
                logger.info(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"LLM call failed after {self.max_retries + 1} attempts: {last_error}"
        )

    async def health(self) -> dict:
        """检查 Provider 健康状态（含 Novita 医疗模型）"""
        h = await self.provider.health()
        result = {
            "provider": h.provider,
            "healthy": h.healthy,
            "message": h.message,
            "total_calls": self._call_count,
            "total_tokens": self._total_tokens,
        }
        # Novita 医疗模型健康状态
        if self.medical_provider is not None:
            mh = await self.medical_provider.health()
            result["medical_provider"] = {
                "provider": mh.provider,
                "healthy": mh.healthy,
                "message": mh.message,
                "medical_calls": self._medical_call_count,
            }
        return result
