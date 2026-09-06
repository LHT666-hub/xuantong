"""事件持久化测试（P1 回归）。

针对 Bug：``DbEventService.update_event_status`` 曾对 JSON 列 ``metadata_`` 做
**原地 mutation**（取出同一 dict 引用改 key 后赋回），SQLAlchemy 普通 JSON 列用
``==`` 比对新旧值 → 判定「无变化」→ 不发 UPDATE，导致 workflow 结果
（status / workflow / thread_id / task_ids / updated_at）**从未真正落库**。

现有事件测试全走内存 store 分支（不注入 session_factory），DB 持久化路径是盲区，
故 340 个测试全过却没抓到该 Bug。本文件用**真实 DB session**（基于文件的临时
SQLite，参考 tests/test_documents_persistence.py）覆盖。

关键复现条件：Bug 仅在事件**已有非空 metadata** 时触发 —— 因为 ``event.metadata_ or {}``
在 metadata_ 为空 ``{}`` 时会短路返回一个**新** ``{}``（空 dict 为 falsy），意外掩盖了
问题；只有当既有 metadata 非空（truthy）时才返回**同一**已加载对象，原地改 key 后
赋回 → SQLAlchemy ``==`` 判定无变化 → 不发 UPDATE。故本文件所有用例都带非空初始 metadata。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 —— 确保所有模型注册到 Base.metadata
from app.database.base import Base
from app.main import app
from app.models.event import Event
from app.services.db import DbEventService
from app.services.progress_hub import progress_hub

EVENTS_URL = "/api/events"


def _make_engine_and_factory(url: str):
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


class _FileDbHandle:
    """封装基于文件的临时 SQLite，并提供 ``restart`` 模拟进程重启。"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = None
        self.factory = None

    async def startup(self) -> None:
        self.engine, self.factory = _make_engine_and_factory(self.url)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        app.state.session_factory = self.factory

    async def restart(self) -> None:
        """模拟重启：释放旧引擎、清空进程内进度频道，用同一 DB 文件重建引擎。"""
        if self.engine is not None:
            await self.engine.dispose()
        # 进程重启后 progress_hub 的内存频道必然消失
        progress_hub.reset()
        self.engine, self.factory = _make_engine_and_factory(self.url)
        app.state.session_factory = self.factory

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


@pytest.fixture
async def file_db(tmp_path):
    db_path = (tmp_path / "events.db").as_posix()
    handle = _FileDbHandle(f"sqlite+aiosqlite:///{db_path}")
    original = getattr(app.state, "session_factory", None)
    progress_hub.reset()
    await handle.startup()
    try:
        yield handle
    finally:
        await handle.shutdown()
        progress_hub.reset()
        app.state.session_factory = original


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── 服务层：直接命中 Bug 的精确回归 ──────────────────────────────────────────


async def test_update_event_status_persists_metadata(file_db):
    """update_event_status 写入的键必须真正落库（重开 session 仍能读到）。"""
    event_id = str(uuid.uuid4())
    workflow_result = {
        "status": "completed",
        "thread_id": "thread-abc-123",
        "steps": ["intake", "triage", "dispatch"],
    }
    task_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    # 创建 + 更新（第一个 session，提交后关闭）
    async with file_db.factory() as db:
        svc = DbEventService(db)
        await svc.create_event(
            {
                "id": event_id,
                "patient_id": "p-svc",
                "event_type": "bp_reading",
                "channel": "changxi",
                "payload": {"systolic": 168, "diastolic": 103},
                # 非空初始 metadata —— 复现 Bug 的必要条件
                "metadata": {"device": "changxi-ios", "tz": "Asia/Shanghai"},
            }
        )
        await db.commit()

    async with file_db.factory() as db:
        svc = DbEventService(db)
        updated = await svc.update_event_status(
            event_id=event_id,
            status="completed",
            workflow_result=workflow_result,
            task_ids=task_ids,
        )
        await db.commit()
        assert updated is not None
        assert updated["status"] == "completed"

    # 全新 session 从磁盘重读 —— 若 UPDATE 未发出，这里会读回旧值
    async with file_db.factory() as db:
        row = (
            await db.execute(select(Event).where(Event.id == uuid.UUID(event_id)))
        ).scalar_one()
        meta = row.metadata_ or {}
        assert meta.get("status") == "completed", f"status 未落库: {meta}"
        assert meta.get("workflow") == workflow_result, f"workflow 未落库: {meta}"
        assert meta.get("thread_id") == "thread-abc-123"
        assert meta.get("task_ids") == task_ids
        assert meta.get("updated_at"), "updated_at 未落库"
        # 原有 metadata 键必须保留（合并而非覆盖）
        assert meta.get("device") == "changxi-ios", f"原 metadata 丢失: {meta}"

        fetched = await DbEventService(db).get_event(event_id)
        assert fetched["status"] == "completed"
        assert fetched["workflow"] == workflow_result
        assert fetched["thread_id"] == "thread-abc-123"
        assert fetched["task_ids"] == task_ids


async def test_update_event_status_survives_engine_restart(file_db):
    """模拟进程重启（重建 engine）后，workflow 结果仍在。"""
    event_id = str(uuid.uuid4())
    async with file_db.factory() as db:
        svc = DbEventService(db)
        await svc.create_event(
            {"id": event_id, "patient_id": "p-restart", "event_type": "bp_reading",
             "channel": "changxi", "payload": {"systolic": 150, "diastolic": 95},
             "metadata": {"device": "changxi-ios"}}
        )
        await svc.update_event_status(
            event_id=event_id,
            status="completed",
            workflow_result={"status": "completed", "thread_id": "t-1", "steps": ["intake"]},
            task_ids=["task-1"],
        )
        await db.commit()

    await file_db.restart()

    async with file_db.factory() as db:
        fetched = await DbEventService(db).get_event(event_id)
        assert fetched is not None
        assert fetched["status"] == "completed"
        assert fetched["workflow"]["thread_id"] == "t-1"
        assert fetched["task_ids"] == ["task-1"]


# ── 端到端：HTTP 契约 + 重启存活 ─────────────────────────────────────────────


async def test_post_event_then_get_reads_workflow_and_survives_restart(file_db):
    """POST /api/events → GET 读到 workflow；重启后仍在。"""
    async with _client() as client:
        resp = await client.post(
            EVENTS_URL,
            json={
                "patient_id": "p-http",
                "event_type": "bp_reading",
                "channel": "changxi",
                "payload": {"systolic": 168, "diastolic": 103},
                "metadata": {"device": "changxi-ios"},
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        event_id = body["event"]["id"]

        # 同步返回已带 workflow
        assert body["workflow"] is not None

        got = await client.get(f"{EVENTS_URL}/{event_id}")
        assert got.status_code == 200, got.text
        record = got.json()["event"]
        assert record["workflow"] is not None, "GET 读不到 workflow（未落库）"
        assert record["status"] != "received", "status 仍为 received（未落库）"

        status_resp = await client.get(f"{EVENTS_URL}/{event_id}/status")
        assert status_resp.status_code == 200, status_resp.text
        sbody = status_resp.json()
        assert sbody["workflow"] is not None
        assert sbody["status"] == record["status"]

    # 模拟进程重启
    await file_db.restart()

    async with _client() as client:
        got2 = await client.get(f"{EVENTS_URL}/{event_id}")
        assert got2.status_code == 200, got2.text
        rec2 = got2.json()["event"]
        assert rec2["workflow"] is not None, "重启后 workflow 丢失"
        assert rec2["status"] == record["status"]

        s2 = await client.get(f"{EVENTS_URL}/{event_id}/status")
        assert s2.json()["workflow"] is not None


async def test_stream_replays_steps_after_restart(file_db):
    """重启后 SSE 流应从持久化 workflow.steps 回放并发出 event: complete。"""
    async with _client() as client:
        resp = await client.post(
            EVENTS_URL,
            json={
                "patient_id": "p-stream",
                "event_type": "bp_reading",
                "channel": "changxi",
                "payload": {"systolic": 168, "diastolic": 103},
                "metadata": {"device": "changxi-ios"},
            },
        )
        assert resp.status_code == 201, resp.text
        event_id = resp.json()["event"]["id"]

    # 重启：清空内存频道，迫使 SSE 走持久化回放路径
    await file_db.restart()

    collected: list[str] = []
    async with _client() as client:
        async with client.stream("GET", f"/api/v1/events/{event_id}/stream") as stream:
            assert stream.status_code == 200
            async for line in stream.aiter_lines():
                collected.append(line)
                # 收到终态即停止，避免空闲超时拖慢测试
                if line.startswith("event: complete") or line.startswith("event: timeout"):
                    # 再读一行 data 便于断言
                    break

    text = "\n".join(collected)
    assert "event: complete" in text, f"未回放 complete，实际流：\n{text}"
    assert "event: timeout" not in text, f"不应超时，实际流：\n{text}"
