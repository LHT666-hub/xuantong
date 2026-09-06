"""FastAPI 依赖注入"""
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.auth_service import decode_token
from app.xuantong.llm.runtime import LLMRuntime

# tokenUrl 指向登录端点，供 OpenAPI 文档的 "Authorize" 按钮使用
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# 401 未认证时统一返回的挑战头
_AUTHENTICATE = {"WWW-Authenticate": "Bearer"}


async def get_llm_runtime(request: Request) -> LLMRuntime:
    """获取 LLM Runtime 实例"""
    return request.app.state.llm_runtime


async def get_db_session(request: Request) -> AsyncSession:
    """获取数据库 session（每次请求一个独立 session）"""
    async with request.app.state.session_factory() as session:
        yield session


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db_session: AsyncSession = Depends(get_db_session),
) -> User:
    """解析 JWT 获取当前用户。

    令牌无效 / 过期 / 用户不存在 / 用户被禁用均抛 401。
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers=_AUTHENTICATE,
    )

    payload = decode_token(token)
    if payload is None:
        raise credentials_error

    sub = payload.get("sub")
    if not sub:
        raise credentials_error

    try:
        user_id = UUID(sub)
    except (ValueError, TypeError):
        raise credentials_error

    result = await db_session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_error
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers=_AUTHENTICATE,
        )
    return user


def require_role(*roles: str):
    """角色门控依赖工厂。

    用法：
        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
        或
        async def endpoint(user = Depends(require_role("doctor", "admin"))): ...
    """

    async def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return role_checker
