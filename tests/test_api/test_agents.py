import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_list_agents():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/agents")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 8
    roles = [a["role"] for a in data["agents"]]
    assert "family_doctor" in roles
    assert "nurse" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_assistant_is_execution_phase():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/agents")
    data = response.json()
    assistant = next(a for a in data["agents"] if a["role"] == "assistant")
    assert assistant["phase"] == "execution"
