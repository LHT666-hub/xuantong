"""会话 / 消息管理端点测试（changxi 前端历史会话）。

覆盖路由（prefix=/api/v1）：
- POST   /chat/sessions                     创建会话（201）
- GET    /chat/sessions?patient_id=         列出患者会话
- POST   /chat/sessions/{id}/messages       追加消息（201 / 404）
- GET    /chat/sessions/{id}/messages       列出会话消息（时间升序）
- DELETE /chat/sessions/{id}                删除会话（404 if 不存在）

内存模式（conftest 未设置 app.state.session_factory），无需数据库。
每个用例前后重置内存对话存储以保证隔离。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.chat_service import reset_chat_service

SESSIONS_URL = "/api/v1/chat/sessions"


@pytest.fixture(autouse=True)
def _reset_chat_store():
    reset_chat_service()
    yield
    reset_chat_service()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_create_chat_session():
    async with _client() as client:
        resp = await client.post(SESSIONS_URL, json={"patient_id": "patient-zhang-001"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"]
    # patient_id 归一化为确定性 UUID
    assert body["patient_id"] == str(uuid.UUID(body["patient_id"]))
    assert body["message_count"] == 0
    assert body["last_message_at"] is None
    assert body["created_at"]


@pytest.mark.asyncio
async def test_create_session_requires_patient_id():
    async with _client() as client:
        resp = await client.post(SESSIONS_URL, json={})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_add_and_list_messages():
    async with _client() as client:
        session = (await client.post(SESSIONS_URL, json={"patient_id": "p-002"})).json()
        sid = session["id"]

        r1 = await client.post(
            f"{SESSIONS_URL}/{sid}/messages",
            json={"role": "user", "content": "我头晕"},
        )
        assert r1.status_code == 201, r1.text
        assert r1.json()["role"] == "user"
        assert r1.json()["session_id"] == sid

        r2 = await client.post(
            f"{SESSIONS_URL}/{sid}/messages",
            json={"role": "assistant", "content": "建议测量血压并休息"},
        )
        assert r2.status_code == 201, r2.text

        listing = await client.get(f"{SESSIONS_URL}/{sid}/messages")
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["session_id"] == sid
        assert body["count"] == 2
        # 时间升序：先 user 后 assistant
        roles = [m["role"] for m in body["messages"]]
        assert roles == ["user", "assistant"]

        # 会话消息计数已更新
        sessions = (await client.get(SESSIONS_URL, params={"patient_id": "p-002"})).json()
        target = next(s for s in sessions["sessions"] if s["id"] == sid)
        assert target["message_count"] == 2
        assert target["last_message_at"] is not None


@pytest.mark.asyncio
async def test_list_messages_limit():
    async with _client() as client:
        sid = (await client.post(SESSIONS_URL, json={"patient_id": "p-003"})).json()["id"]
        for i in range(5):
            await client.post(
                f"{SESSIONS_URL}/{sid}/messages",
                json={"role": "user", "content": f"消息 {i}"},
            )
        resp = await client.get(f"{SESSIONS_URL}/{sid}/messages", params={"limit": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    # 返回最近 2 条（时间升序）
    assert [m["content"] for m in body["messages"]] == ["消息 3", "消息 4"]


@pytest.mark.asyncio
async def test_list_sessions():
    async with _client() as client:
        await client.post(SESSIONS_URL, json={"patient_id": "p-004"})
        await client.post(SESSIONS_URL, json={"patient_id": "p-004"})
        # 另一名患者的会话不应混入
        await client.post(SESSIONS_URL, json={"patient_id": "p-other"})

        resp = await client.get(SESSIONS_URL, params={"patient_id": "p-004"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["patient_id"] == "p-004"
    assert body["count"] == 2
    assert len(body["sessions"]) == 2


@pytest.mark.asyncio
async def test_list_sessions_requires_patient_id():
    async with _client() as client:
        resp = await client.get(SESSIONS_URL)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_delete_session():
    async with _client() as client:
        sid = (await client.post(SESSIONS_URL, json={"patient_id": "p-005"})).json()["id"]
        await client.post(
            f"{SESSIONS_URL}/{sid}/messages",
            json={"role": "user", "content": "待删除消息"},
        )

        deleted = await client.delete(f"{SESSIONS_URL}/{sid}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": True, "session_id": sid}

        # 删除后消息不可再列出（会话已不存在 → 404）
        gone = await client.get(f"{SESSIONS_URL}/{sid}/messages")
        assert gone.status_code == 404, gone.text

        # 会话列表中不再出现
        listing = (await client.get(SESSIONS_URL, params={"patient_id": "p-005"})).json()
        assert listing["count"] == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_session():
    async with _client() as client:
        resp = await client.delete(f"{SESSIONS_URL}/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_add_message_to_nonexistent_session():
    async with _client() as client:
        resp = await client.post(
            f"{SESSIONS_URL}/{uuid.uuid4()}/messages",
            json={"role": "user", "content": "孤儿消息"},
        )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_messages_nonexistent_session():
    async with _client() as client:
        resp = await client.get(f"{SESSIONS_URL}/{uuid.uuid4()}/messages")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_add_message_invalid_role():
    async with _client() as client:
        sid = (await client.post(SESSIONS_URL, json={"patient_id": "p-006"})).json()["id"]
        resp = await client.post(
            f"{SESSIONS_URL}/{sid}/messages",
            json={"role": "alien", "content": "非法角色"},
        )
    assert resp.status_code == 422, resp.text
