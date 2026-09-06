"""认证路由 —— 注册 / 登录 / 当前用户。

最小 JWT 认证体系：
- POST /register  创建用户（username/email/password/role），返回 201
- POST /login     OAuth2 密码模式登录，返回 {"access_token", "token_type"}
- GET  /me        返回当前登录用户信息（需认证）

路由本身不带前缀，由 main.py 以 prefix="/api/auth" 挂载。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(tags=["auth"])

# 允许注册的角色集合
_ALLOWED_ROLES = {"patient", "doctor", "nurse", "admin"}


# ── Schemas ────────────────────────────────────────────────────────────────
class UserRegister(BaseModel):
    """注册请求体。"""

    username: str = Field(min_length=3, max_length=60)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(default="patient")


class UserOut(BaseModel):
    """对外暴露的用户信息（绝不含 hashed_password）。"""

    id: UUID
    username: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """登录成功返回的令牌。"""

    access_token: str
    token_type: str = "bearer"


def _validate_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid role. Must be one of: {', '.join(sorted(_ALLOWED_ROLES))}",
        )
    return role


# ── Routes ─────────────────────────────────────────────────────────────────
@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: UserRegister,
    db_session: AsyncSession = Depends(get_db_session),
):
    """创建新用户。用户名或邮箱重复返回 409。"""
    role = _validate_role(payload.role)

    existing = await db_session.execute(
        select(User).where(
            or_(
                User.username == payload.username,
                User.email == payload.email,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",
        )

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db_session: AsyncSession = Depends(get_db_session),
):
    """OAuth2 密码模式登录。username 字段可填用户名或邮箱。

    凭据错误统一返回 401（不区分用户不存在 / 密码错误，避免枚举）。
    """
    identifier = form_data.username
    result = await db_session.execute(
        select(User).where(
            or_(User.username == identifier, User.email == identifier)
        )
    )
    user = result.scalar_one_or_none()

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise unauthorized
    if not user.is_active:
        raise unauthorized

    access_token = create_access_token(
        {"sub": str(user.id), "role": user.role, "username": user.username}
    )
    return TokenResponse(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserOut)
async def read_me(current_user: User = Depends(get_current_user)):
    """返回当前登录用户信息（需携带有效 Bearer Token）。"""
    return current_user
