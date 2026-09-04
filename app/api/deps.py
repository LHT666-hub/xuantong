"""FastAPI 依赖注入"""
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.xuantong.llm.runtime import LLMRuntime


async def get_llm_runtime(request: Request) -> LLMRuntime:
    """获取 LLM Runtime 实例"""
    return request.app.state.llm_runtime


async def get_db_session(request: Request) -> AsyncSession:
    """获取数据库 session（每次请求一个独立 session）"""
    async with request.app.state.session_factory() as session:
        yield session
