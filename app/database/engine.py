"""数据库引擎与会话管理。

支持两种模式：
- 开发模式：SQLite（本地文件 xuantong.db，使用 aiosqlite）
- 生产模式：PostgreSQL/Supabase（使用 asyncpg）

通过 DATABASE_URL 环境变量切换，默认使用 SQLite。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_db_engine(settings: Settings):
    """创建异步数据库引擎。

    SQLite 使用 aiosqlite，PostgreSQL 使用 asyncpg。
    """
    # 根据数据库类型设置连接参数
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        connect_args=connect_args,
    )
    return engine


def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    """创建异步会话工厂。"""
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的依赖注入函数（用于 FastAPI Depends）。

    使用方式：
        async def endpoint(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话的上下文管理器（用于服务层）。

    使用方式：
        async with get_db_context(session_factory) as db:
            # 使用 db 进行数据库操作
            ...
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
