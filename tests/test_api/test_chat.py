"""POST /api/v1/chat 轻量对话端点测试。

覆盖：
- test_chat_basic：发送消息收到非空回复，格式匹配前端期望 {reply}
- test_chat_empty_message：空消息返回 422
- test_chat_with_mock_provider：MockProvider 下正常工作（无需真实 API Key）
- 附加：携带历史上下文 / patient_id、危机输入的安全兜底
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.chat_service import reset_chat_service

CHAT_URL = "/api/v1/chat"


@pytest.fixture(autouse=True)
def _reset_chat_store():
    """每个用例前后重置内存对话存储，保证会话/消息隔离。"""
    reset_chat_service()
    yield
    reset_chat_service()


@pytest.mark.asyncio
async def test_chat_basic():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(CHAT_URL, json={"message": "我最近血压有点高，需要注意什么？"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 前端强依赖的字段
    assert "reply" in body
    assert isinstance(body["reply"], str) and body["reply"].strip()
    assert body["agent_role"] == "family_doctor"
    # 未显式传 session_id 时应自动新建会话并回传
    assert body.get("session_id")


@pytest.mark.asyncio
async def test_chat_empty_message():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(CHAT_URL, json={"message": ""})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_chat_with_mock_provider():
    """MockProvider 下应返回模拟回复（回显用户消息 + [MockProvider] 标记）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(CHAT_URL, json={"message": "你好，家庭药箱常备药有哪些"})
    assert resp.status_code == 200, resp.text
    reply = resp.json()["reply"]
    assert reply.strip()
    # MockProvider 默认回显标记；OutputGuard 不应误伤该文本
    assert "MockProvider" in reply


@pytest.mark.asyncio
async def test_chat_with_context_and_patient_id():
    transport = ASGITransport(app=app)
    payload = {
        "message": "那我该怎么调整饮食？",
        "patient_id": "patient-zhang-001",
        "context": [
            {"role": "user", "content": "我血压偏高"},
            {"role": "assistant", "content": "建议低盐饮食并规律监测。"},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(CHAT_URL, json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["reply"].strip()


@pytest.mark.asyncio
async def test_chat_crisis_returns_safety_guidance():
    """危机输入应触发 InputGuard，返回紧急引导而非普通对话。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(CHAT_URL, json={"message": "我不想活了，想自杀"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"].strip()
    # 危机路径不调用 LLM，metadata 标记 guard=emergency
    assert (body.get("metadata") or {}).get("guard") == "emergency"
