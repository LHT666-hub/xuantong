from enum import Enum
from typing import Protocol, runtime_checkable
from pydantic import BaseModel
from typing import AsyncIterator


class ModelTier(str, Enum):
    """模型层级枚举 — 对应不同成本/能力的模型"""
    LEAD = "lead"              # 主智能体：最强推理（qwen3-max）
    SPECIALIST = "specialist"  # 专科Agent：1M上下文+FC（qwen-plus）
    EXECUTION = "execution"    # 执行Agent：低成本+FC（qwen-flash）
    VISION = "vision"          # 视觉识别（qwen3-vl-flash）
    OCR = "ocr"                # OCR（qwen3.5-ocr）
    ASR = "asr"                # 语音识别（qwen3-asr-flash）


class ModelRequest(BaseModel):
    """模型调用请求"""
    model_id: str = ""          # 具体模型名称，如 qwen-plus
    model_tier: ModelTier | None = None  # 模型层级，runtime 会自动解析为 model_id
    messages: list[dict]        # [{"role": "system/user/assistant", "content": "..." | list}]
    temperature: float = 0.7
    max_tokens: int | None = None
    # Qwen 私有参数（通过 extra_body 传入）
    extra_body: dict = {}       # 如 {"enable_thinking": True}
    # 合规元数据（借鉴 MedHarness）
    data_level: str = "L1"      # L1-L4
    agent_role: str = ""
    metadata: dict = {}


class ModelResponse(BaseModel):
    """模型调用响应"""
    content: str
    provider: str
    model: str
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: int = 0


class StreamChunk(BaseModel):
    """流式响应块"""
    content: str
    finish_reason: str | None = None


class ProviderHealth(BaseModel):
    """Provider 健康状态"""
    provider: str
    healthy: bool
    message: str = ""


@runtime_checkable
class ModelProvider(Protocol):
    """统一模型调用接口"""
    name: str

    async def complete(self, request: ModelRequest) -> ModelResponse: ...
    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]: ...
    async def health(self) -> ProviderHealth: ...
