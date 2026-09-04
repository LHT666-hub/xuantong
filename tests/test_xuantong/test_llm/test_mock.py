import pytest
from app.xuantong.llm import LLMRuntime, MockProvider


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
