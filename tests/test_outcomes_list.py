"""GET /api/outcomes 全量查询测试（P1）。

此前 DB 模式下 patient_id 与 task_id 均缺省时恒返回空数组。本测试验证：
- 无过滤参数时返回全量结果 + 分页（page/size，默认 1/20），按 created_at 倒序；
- 响应结构 ``{"outcomes":[...], "total":int}`` 保留，并新增 page/size 字段；
- patient_id 过滤仍正常工作（未破坏既有能力）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database.base import Base
from app.main import app
from app.models.outcome import ServiceOutcome

OUTCOMES_URL = "/api/outcomes"


@pytest.fixture
async def mem_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    original = getattr(app.state, "session_factory", None)
    app.state.session_factory = factory
    try:
        yield factory
    finally:
        app.state.session_factory = original
        await engine.dispose()


async def _seed_outcomes(factory, n: int, patient_id=None):
    """插入 n 条 ServiceOutcome，created_at 递增以便验证倒序。"""
    base = datetime.now(timezone.utc) - timedelta(minutes=n)
    async with factory() as db:
        for i in range(n):
            db.add(
                ServiceOutcome(
                    id=uuid4(),
                    patient_id=patient_id or uuid4(),
                    event_id=uuid4(),
                    task_id=uuid4(),
                    outcome_type=f"type_{i}",
                    handled_by="tester",
                    summary=f"outcome {i}",
                    structured_result={},
                    occurred_at=base + timedelta(minutes=i),
                )
            )
        await db.commit()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_list_all_outcomes_no_filter(mem_db):
    await _seed_outcomes(mem_db, 5)
    async with _client() as client:
        resp = await client.get(OUTCOMES_URL)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5, body
    assert len(body["outcomes"]) == 5
    assert body["page"] == 1
    assert body["size"] == 20


async def test_list_all_outcomes_pagination(mem_db):
    await _seed_outcomes(mem_db, 5)
    async with _client() as client:
        p1 = await client.get(OUTCOMES_URL, params={"page": 1, "size": 2})
        b1 = p1.json()
        assert b1["total"] == 5
        assert len(b1["outcomes"]) == 2

        p3 = await client.get(OUTCOMES_URL, params={"page": 3, "size": 2})
        assert len(p3.json()["outcomes"]) == 1


async def test_list_all_outcomes_empty(mem_db):
    async with _client() as client:
        resp = await client.get(OUTCOMES_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["outcomes"] == []


async def test_filter_by_patient_still_works(mem_db):
    pid = uuid4()
    await _seed_outcomes(mem_db, 3, patient_id=pid)
    await _seed_outcomes(mem_db, 2, patient_id=uuid4())  # 其他患者
    async with _client() as client:
        resp = await client.get(OUTCOMES_URL, params={"patient_id": str(pid)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert len(body["outcomes"]) == 3
    assert all(o["patient_id"] == str(pid) for o in body["outcomes"])
