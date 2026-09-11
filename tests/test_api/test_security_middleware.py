from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.middleware.security import APIAuthenticationMiddleware, RateLimitMiddleware
from app.services.auth_service import create_access_token


@pytest.mark.asyncio
async def test_auth_guard_keeps_health_public_and_protects_health_records():
    guarded = FastAPI()
    guarded.add_middleware(APIAuthenticationMiddleware, enabled=True)

    @guarded.get("/api/health")
    async def health():
        return {"status": "ok"}

    @guarded.get("/api/health-records")
    async def records():
        return []

    async with AsyncClient(
        transport=ASGITransport(app=guarded), base_url="http://test"
    ) as client:
        assert (await client.get("/api/health")).status_code == 200
        response = await client.get("/api/health-records")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_auth_guard_accepts_signed_access_token(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-signing")
    guarded = FastAPI()
    guarded.add_middleware(APIAuthenticationMiddleware, enabled=True)

    @guarded.get("/api/private")
    async def private():
        return {"ok": True}

    token = create_access_token({"sub": "00000000-0000-0000-0000-000000000001"})
    async with AsyncClient(
        transport=ASGITransport(app=guarded), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/private", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_limiter_returns_retry_after():
    limited = FastAPI()
    limited.add_middleware(
        RateLimitMiddleware,
        enabled=True,
        requests_per_minute=1,
        auth_requests_per_minute=1,
    )

    @limited.get("/api/example")
    async def example():
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=limited), base_url="http://test"
    ) as client:
        assert (await client.get("/api/example")).status_code == 200
        response = await client.get("/api/example")
        assert response.status_code == 429
        assert response.headers["retry-after"]
