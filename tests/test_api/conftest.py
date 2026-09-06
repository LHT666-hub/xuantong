"""test_api 共享 fixture：为需要真实数据库的路由提供内存 SQLite。

patients / care_teams / health_records 路由通过 ``get_db_session`` 依赖读取
``app.state.session_factory``。此处在测试期注入基于 StaticPool 的内存 SQLite
（共享同一连接），并在用例结束后恢复原值，避免影响其他内存模式测试。
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 —— 确保所有模型注册到 Base.metadata
from app.database.base import Base
from app.main import app


@pytest.fixture
async def db_factory():
    """创建内存数据库并注入 app.state.session_factory。"""
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


@pytest.fixture
async def client(db_factory):
    """绑定到主 app 的异步测试客户端（已注入内存数据库）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
