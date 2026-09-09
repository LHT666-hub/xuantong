"""若木 D 模式客户端契约测试。"""

import httpx
import pytest

from app.services.ruomu import RuomuKnowledgeService


@pytest.mark.asyncio
async def test_ruomu_reads_streamed_brief_and_sources():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-access-key"] == "test-access-key"
        assert request.url.path == "/api/chat"
        body = request.read().decode()
        assert '"mode":"web_knowledge"' in body.replace(" ", "")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"type":"delta","text":"建议规律监测。"}\n\n'
                'data: {"type":"done","requestId":"req-1","sources":'
                '[{"siteName":"WHO","title":"HEARTS","url":"https://who.int/example"}]}\n\n'
            ),
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://ruomu.test"
    )
    service = RuomuKnowledgeService(
        "https://ruomu.test", "test-access-key", client=client
    )
    result = await service.retrieve("高血压怎么管理？")

    assert result.brief == "建议规律监测。"
    assert result.request_id == "req-1"
    assert result.sources[0]["siteName"] == "WHO"
    await client.aclose()


@pytest.mark.asyncio
async def test_ruomu_health_requires_ok_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = RuomuKnowledgeService("https://ruomu.test", "key", client=client)
    assert await service.health() is True
    await client.aclose()

