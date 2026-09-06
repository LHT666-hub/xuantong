"""DbChatService（数据库实现）回归测试。

直接使用内存 SQLite（StaticPool 保证单连接共享同一 DB）验证生产持久化路径：
- 消息按时间升序稳定返回（回归：SQLite CURRENT_TIMESTAMP 秒级精度导致的排序不稳定）
- 会话统计派生、列表聚合、删除级联

路由层在 ``app.state.session_factory`` 存在时使用本实现；这些测试不经过 HTTP，
直接调用服务，避免影响 conftest 的全局 app.state。
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import ChatMessage, Organization, Patient, User  # noqa: F401
from app.services.db import DbChatService


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_add_and_list_messages_chronological(db_session):
    svc = DbChatService(db_session)
    session = await svc.create_session("p-db-001")
    sid = session["id"]

    await svc.add_message(sid, session["patient_id"], "user", "第一条")
    await svc.add_message(sid, session["patient_id"], "assistant", "第二条")
    await svc.add_message(sid, session["patient_id"], "user", "第三条")

    msgs = await svc.list_messages(sid)
    assert [m["content"] for m in msgs] == ["第一条", "第二条", "第三条"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_messages_limit_keeps_recent_chronological(db_session):
    svc = DbChatService(db_session)
    sid = (await svc.create_session("p-db-002"))["id"]
    pid = (await svc.get_session(sid))["patient_id"] or "p-db-002"
    for i in range(5):
        await svc.add_message(sid, pid, "user", f"m{i}")

    msgs = await svc.list_messages(sid, limit=2)
    # 取最近 2 条，仍按时间升序返回
    assert [m["content"] for m in msgs] == ["m3", "m4"]
    await db_session.commit()


@pytest.mark.asyncio
async def test_session_stats_and_list(db_session):
    svc = DbChatService(db_session)
    session = await svc.create_session("p-db-003")
    sid = session["id"]
    await svc.add_message(sid, session["patient_id"], "user", "hi")
    await svc.add_message(sid, session["patient_id"], "assistant", "hello")

    got = await svc.get_session(sid)
    assert got["message_count"] == 2
    assert got["last_message_at"] is not None

    sessions = await svc.list_sessions("p-db-003")
    assert len(sessions) == 1
    assert sessions[0]["id"] == sid
    assert sessions[0]["message_count"] == 2
    await db_session.commit()


@pytest.mark.asyncio
async def test_delete_session_removes_messages(db_session):
    svc = DbChatService(db_session)
    session = await svc.create_session("p-db-004")
    sid = session["id"]
    await svc.add_message(sid, session["patient_id"], "user", "to be deleted")

    assert await svc.delete_session(sid) is True
    assert await svc.list_messages(sid) == []
    assert await svc.list_sessions("p-db-004") == []
    await db_session.commit()


@pytest.mark.asyncio
async def test_delete_nonexistent_session_returns_false(db_session):
    import uuid

    svc = DbChatService(db_session)
    assert await svc.delete_session(str(uuid.uuid4())) is False
    await db_session.commit()
