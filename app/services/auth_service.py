"""认证服务 —— 密码哈希与 JWT 令牌签发/校验。

手写最小 JWT 认证体系（不引入 fastapi-users，避免改动 User 模型）：
- 密码哈希：passlib + bcrypt
- 令牌：python-jose 签发 HS256 JWT，携带 sub（用户 ID）与 exp（过期时间）

所有函数均为纯函数，密钥/算法/过期时长从 app.config.Settings 读取。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import Settings

# bcrypt 密码哈希上下文（deprecated='auto' 支持后续无缝升级算法）
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 令牌类型标识，写入 JWT 的 type 字段，便于将来区分 access/refresh token
_TOKEN_TYPE = "access"


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 哈希。"""
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。哈希非法时返回 False 而非抛异常。"""
    try:
        return _pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """签发 JWT access token。

    Args:
        data: 需要写入 payload 的字段（通常包含 sub=用户 ID、role 等）。
        expires_delta: 自定义有效期；缺省时使用 settings.jwt_expire_minutes。

    Returns:
        编码后的 JWT 字符串。
    """
    settings = Settings()
    to_encode = dict(data)

    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.jwt_expire_minutes)
    )
    to_encode.update({"exp": expire, "iat": now, "type": _TOKEN_TYPE})

    return jwt.encode(
        to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


def decode_token(token: str) -> dict[str, Any] | None:
    """解码并校验 JWT。

    过期、签名无效或格式错误均返回 None（由上层依赖转换为 401）。
    """
    settings = Settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
    return payload


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_token",
]
