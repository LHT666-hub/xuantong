import pytest
from app.xuantong.llm import LLMRuntime, MockProvider
from app.config import Settings
from app.xuantong.llm.provider import ModelResponse, ProviderHealth, StreamChunk
from app.xuantong.llm.vision import VisionService
from app.xuantong.llm.speech import SpeechService


class RecordingProvider:
    def __init__(self, name: str):
        self.name = name
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return ModelResponse(content="ok", provider=self.name, model=request.model_id)

    async def stream(self, request):
        self.requests.append(request)
        yield StreamChunk(content="ok")

    async def health(self):
        return ProviderHealth(provider=self.name, healthy=True)


@pytest.mark.asyncio
async def test_mock_provider_complete():
    provider = MockProvider()
    from app.xuantong.llm.provider import ModelRequest
    request = ModelRequest(messages=[{"role": "user", "content": "你好"}])
    response = await provider.complete(request)
    assert response.provider == "mock"
    assert len(response.content) > 0


@pytest.mark.asyncio
async def test_mock_provider_with_template():
    provider = MockProvider(responses={"血压": "您的血压偏高，建议复测"})
    from app.xuantong.llm.provider import ModelRequest
    request = ModelRequest(messages=[{"role": "user", "content": "我血压160"}])
    response = await provider.complete(request)
    assert "血压" in response.content


@pytest.mark.asyncio
async def test_llm_runtime_invoke():
    runtime = LLMRuntime(MockProvider())
    result = await runtime.invoke("test_agent", [{"role": "user", "content": "测试"}])
    assert result.provider == "mock"


@pytest.mark.asyncio
async def test_llm_runtime_health():
    runtime = LLMRuntime(MockProvider())
    health = await runtime.health()
    assert health["healthy"] == True


@pytest.mark.asyncio
async def test_medical_agent_uses_medical_provider_model_for_invoke_and_stream():
    primary = RecordingProvider("qwen")
    medical = RecordingProvider("novita")
    settings = Settings(
        use_medical_model=True,
        medical_model_id="medical-test-model",
    )
    runtime = LLMRuntime(
        primary,
        medical_provider=medical,
        settings=settings,
        max_retries=0,
    )

    result = await runtime.invoke(
        "family_doctor", [{"role": "user", "content": "test"}]
    )
    chunks = [
        chunk.content
        async for chunk in runtime.stream(
            "family_doctor", [{"role": "user", "content": "test"}]
        )
    ]

    assert result.provider == "novita"
    assert chunks == ["ok"]
    assert [request.model_id for request in medical.requests] == [
        "medical-test-model",
        "medical-test-model",
    ]
    assert primary.requests == []


@pytest.mark.asyncio
async def test_multimodal_services_resolve_vision_ocr_and_asr_models():
    primary = RecordingProvider("qwen")
    settings = Settings(
        llm_model_vision="vision-test-model",
        llm_model_ocr="ocr-test-model",
        llm_model_asr="asr-test-model",
        use_medical_model=False,
    )
    runtime = LLMRuntime(primary, settings=settings, max_retries=0)
    vision = VisionService(runtime)
    speech = SpeechService(runtime)

    await vision.analyze_image("data:image/jpeg;base64,AA==", "describe")
    await vision.ocr_medical_document("data:image/jpeg;base64,AA==")
    await speech.transcribe("data:audio/wav;base64,AA==", ["zh", "yue"])

    assert [request.model_id for request in primary.requests] == [
        "vision-test-model",
        "ocr-test-model",
        "asr-test-model",
    ]
