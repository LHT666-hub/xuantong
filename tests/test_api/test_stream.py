"""SSE 流式端点测试（Task #13）。

覆盖：
- test_sse_content_type：两个 SSE 端点的 Content-Type 为 text/event-stream
- test_sse_event_stream_connects：事件流可连接，未知事件返回 404
- test_sse_event_stream_replays_completed_workflow：已完成事件回放节点历史 + complete
- test_sse_event_stream_live_channel：progress_hub 实时频道推送（含迟到订阅回放）
- test_sse_chat_stream：对话流式端点逐块下发 + complete 终态含完整 reply
- test_sse_chat_stream_crisis：危机输入走 InputGuard 短路，仍正常流式下发
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.chat_service import reset_chat_service
from app.services.progress_hub import progress_hub
from app.services.store import get_store
from app.api.routes.stream import _references_used_in_reply
from app.services.ruomu import RuomuEvidence

EVENTS_URL = "/api/events"
CHAT_STREAM_URL = "/api/v1/chat/stream"

PATIENT_ID = "patient-stream-001"


def test_retrieved_references_are_exposed_with_honest_citation_state():
    references = [
        {"id": "ref-1", "title": "one"},
        {"id": "ref-2", "title": "two"},
        {"id": "ref-3", "title": "three"},
    ]
    marked = _references_used_in_reply("第一条[1]，第三条[3]。", references)
    assert [item["cited"] for item in marked] == [True, False, True]
    assert [item["title"] for item in marked] == ["one", "two", "three"]
    assert all(
        item["cited"] is False
        for item in _references_used_in_reply("没有实际引用。", references)
    )


def test_ruomu_only_runs_for_evidence_intent_without_sensitive_payload():
    from app.api.routes.stream import _should_use_ruomu

    assert _should_use_ruomu("请查一下最新高血压指南") is True
    assert _should_use_ruomu("我今天有一点头晕") is False
    assert _should_use_ruomu("请查最新资料，手机号13800138000") is False
    assert _should_use_ruomu("附件：检查报告全文") is False


def _event_stream_url(event_id: str) -> str:
    return f"/api/v1/events/{event_id}/stream"


def _bp_event_payload() -> dict:
    return {
        "patient_id": PATIENT_ID,
        "event_type": "bp_measurement",
        "channel": "changxi",
        "source": "home_monitor",
        "payload": {"systolic": 168, "diastolic": 103, "symptoms": ["头晕"]},
    }


def _parse_sse(text: str) -> tuple[list[dict], list[tuple[str, dict]]]:
    """解析 SSE 报文流。

    Returns:
        (data_messages, named_events)：前者为默认 message 事件的 JSON 列表，
        后者为 (event_name, payload) 具名事件列表；注释行（心跳）被忽略。
    """
    data_messages: list[dict] = []
    named_events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        event_name = None
        payload = None
        for line in lines:
            if line.startswith(":"):
                continue  # 心跳/注释行
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[len("data:"):].strip())
        if payload is None:
            continue
        if event_name:
            named_events.append((event_name, payload))
        else:
            data_messages.append(payload)
    return data_messages, named_events


@pytest.fixture(autouse=True)
def _reset_state():
    """每个用例前后重置内存事件存储 / 对话存储 / 进度频道，保证隔离。"""
    get_store().reset()
    reset_chat_service()
    progress_hub.reset()
    yield
    get_store().reset()
    reset_chat_service()
    progress_hub.reset()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_sse_content_type():
    """SSE 端点必须返回 text/event-stream。"""
    # 事件流：先创建事件（workflow 同步执行完毕）
    async with _client() as client:
        resp = await client.post(EVENTS_URL, json=_bp_event_payload())
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["event"]["id"]

        resp = await client.get(_event_stream_url(event_id))
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/event-stream")

        # 对话流
        resp = await client.post(CHAT_STREAM_URL, json={"message": "你好"})
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_sse_event_stream_connects():
    """SSE 事件流可连接并返回报文；未知事件返回 404。"""
    async with _client() as client:
        resp = await client.post(EVENTS_URL, json=_bp_event_payload())
        event_id = resp.json()["event"]["id"]

        resp = await client.get(_event_stream_url(event_id))
        assert resp.status_code == 200, resp.text
        assert resp.text.strip(), "SSE 流不应为空"
        # 首条报文是状态快照
        data_messages, _ = _parse_sse(resp.text)
        assert data_messages[0]["type"] == "status_snapshot"
        assert data_messages[0]["event_id"] == event_id

        # 未知事件（无记录且无进度频道）→ 404
        resp = await client.get(_event_stream_url("00000000-0000-0000-0000-000000000000"))
        assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_sse_event_stream_replays_completed_workflow():
    """已完成的事件：一次性回放节点历史并推送 event: complete。"""
    async with _client() as client:
        resp = await client.post(EVENTS_URL, json=_bp_event_payload())
        body = resp.json()
        event_id = body["event"]["id"]
        # POST 完成后频道被清理，模拟"事后连接"仅依赖持久化记录
        progress_hub.reset()

        resp = await client.get(_event_stream_url(event_id))
        assert resp.status_code == 200, resp.text
        data_messages, named_events = _parse_sse(resp.text)

        node_msgs = [m for m in data_messages if "node" in m]
        assert node_msgs, "应回放至少一个节点事件"
        assert all(m["status"] == "completed" for m in node_msgs)

        complete_events = [p for name, p in named_events if name == "complete"]
        assert complete_events, "应以 event: complete 收尾"
        assert complete_events[0]["final_status"] in {"completed", "pending_human"}


@pytest.mark.asyncio
async def test_sse_event_stream_live_channel():
    """progress_hub 实时频道：迟到订阅者可回放历史并收到 complete。"""
    event_id = "stream-live-001"
    channel = progress_hub.open(event_id)
    channel.publish({"node": "input_guard", "status": "completed"})
    channel.publish({"node": "risk_assessment", "status": "running"})
    channel.finish("completed")

    async with _client() as client:
        resp = await client.get(_event_stream_url(event_id))
        assert resp.status_code == 200, resp.text
        data_messages, named_events = _parse_sse(resp.text)

        nodes = [(m["node"], m["status"]) for m in data_messages if "node" in m]
        assert ("input_guard", "completed") in nodes
        assert ("risk_assessment", "running") in nodes
        # 每条节点事件带 timestamp
        assert all("timestamp" in m for m in data_messages if "node" in m)
        assert ("complete", {"final_status": "completed"}) in named_events


@pytest.mark.asyncio
async def test_sse_chat_stream():
    """对话流式端点：逐块下发 chunk，complete 终态携带完整 reply。"""
    async with _client() as client:
        resp = await client.post(CHAT_STREAM_URL, json={"message": "我最近血压有点高，需要注意什么？"})
        assert resp.status_code == 200, resp.text

        data_messages, named_events = _parse_sse(resp.text)
        chunks = [m for m in data_messages if m.get("done") is False]
        assert chunks, "应至少下发一个 chunk"
        assert all(m["chunk"] for m in chunks)

        complete_events = [p for name, p in named_events if name == "complete"]
        assert len(complete_events) == 1, "应恰好一个 complete 事件"
        final = complete_events[0]
        assert final["done"] is True
        assert final["chunk"] == ""
        # MockProvider 回复（可能经 OutputGuard），全文 = 各块拼接
        assert final["reply"].strip()
        assert "".join(m["chunk"] for m in chunks).strip() == final["reply"].strip()
        assert final["agent_role"] == "family_doctor"
        assert final["session_id"]


@pytest.mark.asyncio
async def test_sse_chat_uses_ruomu_as_evidence_not_final_speaker():
    class FakeRuomu:
        async def retrieve(self, prompt, history=None):
            assert prompt == "高血压最新健康教育资料"
            return RuomuEvidence(
                brief="若木检索摘要",
                request_id="ruomu-request-1",
                sources=[
                    {
                        "siteName": "WHO",
                        "title": "HEARTS 技术包",
                        "url": "https://www.who.int/example",
                    }
                ],
            )

    original = getattr(app.state, "ruomu_service", None)
    app.state.ruomu_service = FakeRuomu()
    try:
        async with _client() as client:
            resp = await client.post(
                CHAT_STREAM_URL, json={"message": "高血压最新健康教育资料"}
            )
    finally:
        app.state.ruomu_service = original

    _, named_events = _parse_sse(resp.text)
    final = [payload for name, payload in named_events if name == "complete"][0]
    assert final["agent_role"] == "family_doctor"
    assert final["metadata"]["ruomu_request_id"] == "ruomu-request-1"
    ruomu_reference = next(ref for ref in final["references"] if ref["source"] == "WHO")
    assert ruomu_reference["url"] == "https://www.who.int/example"


@pytest.mark.asyncio
async def test_sse_chat_stream_empty_message():
    """空消息应返回 422（与 POST /chat 校验一致）。"""
    async with _client() as client:
        resp = await client.post(CHAT_STREAM_URL, json={"message": ""})
        assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_sse_chat_stream_crisis():
    """危机输入：InputGuard 短路，不调用 LLM，仍以流式下发紧急引导。"""
    async with _client() as client:
        resp = await client.post(CHAT_STREAM_URL, json={"message": "我不想活了，想自杀"})
        assert resp.status_code == 200, resp.text

        data_messages, named_events = _parse_sse(resp.text)
        complete_events = [p for name, p in named_events if name == "complete"]
        assert complete_events, "危机路径也应正常收尾"
        final = complete_events[0]
        assert final["reply"].strip()
        assert (final.get("metadata") or {}).get("guard") == "emergency"
        # 下发的块拼接后与终态 reply 一致
        chunks = [m["chunk"] for m in data_messages if m.get("done") is False]
        assert "".join(chunks).strip() == final["reply"].strip()
