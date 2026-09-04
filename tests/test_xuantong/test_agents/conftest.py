"""Agent 测试脚手架：可编程 Mock Provider 与样例 JSON 响应。"""

import pytest

from app.xuantong.llm import LLMRuntime
from app.xuantong.llm.provider import (
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    StreamChunk,
)


class ScriptedProvider:
    """按脚本返回内容的 Mock Provider。

    - default: 所有调用返回的默认内容（一段 JSON 字符串）。
    - by_role: 按 agent_role 覆盖返回内容。
    - sequence: 若提供，则按调用顺序依次返回（用于测试"重试后成功"）。
    """

    name = "scripted"

    def __init__(self, default="{}", by_role=None, sequence=None):
        self._default = default
        self._by_role = by_role or {}
        self._sequence = sequence
        self._idx = 0
        self.calls: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        if self._sequence is not None:
            content = self._sequence[min(self._idx, len(self._sequence) - 1)]
            self._idx += 1
        else:
            content = self._by_role.get(request.agent_role, self._default)
        return ModelResponse(
            content=content, provider="scripted", model="scripted-v1"
        )

    async def stream(self, request: ModelRequest):
        resp = await self.complete(request)
        yield StreamChunk(content=resp.content, finish_reason="stop")

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider="scripted", healthy=True)


def make_runtime(default="{}", by_role=None, sequence=None) -> LLMRuntime:
    """构建使用 ScriptedProvider 的 LLMRuntime。"""
    provider = ScriptedProvider(default=default, by_role=by_role, sequence=sequence)
    return LLMRuntime(provider, max_retries=0)


@pytest.fixture
def zhang_ayi_patient():
    from app.schemas.patient import MedicationInfo, PatientContext

    return PatientContext(
        patient_id="p-001",
        name="张阿姨",
        age=68,
        gender="女",
        chronic_diseases=["高血压", "2型糖尿病"],
        allergies=["青霉素"],
        current_medications=[
            MedicationInfo(drug_name="氨氯地平", dosage="5mg", frequency="qd")
        ],
        risk_level="yellow",
    )


@pytest.fixture
def bp_event():
    """张阿姨血压 168/103 + 头晕 事件。"""
    return {
        "event_type": "vital_sign_abnormal",
        "measurements": [
            {
                "type": "blood_pressure",
                "value": 168,
                "secondary_value": 103,
                "unit": "mmHg",
            }
        ],
        "symptoms": ["头晕"],
    }
