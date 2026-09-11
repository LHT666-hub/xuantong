"""公网 API 的认证边界与单实例速率限制。"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.services.auth_service import decode_token


def _error(status: int, code: str, message: str, **headers: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        headers=headers or None,
        content={
            "detail": message,
            "error": {
                "code": code,
                "message": message,
                "detail": message,
                "details": [],
            },
        },
    )


class APIAuthenticationMiddleware(BaseHTTPMiddleware):
    """生产开关开启后，除健康检查和认证端点外均要求 Bearer JWT。"""

    _PUBLIC_PATHS = {
        "/api/health",
        "/api/health/detail",
        "/api/auth/register",
        "/api/auth/login",
        "/openapi.json",
    }
    _PUBLIC_PREFIXES = (
        "/docs",
        "/redoc",
    )

    def __init__(self, app, *, enabled: bool) -> None:
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if (
            not self.enabled
            or request.method == "OPTIONS"
            or not path.startswith("/api/")
            or path in self._PUBLIC_PATHS
            or any(path.startswith(prefix) for prefix in self._PUBLIC_PREFIXES)
        ):
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return _error(
                401,
                "AUTH_REQUIRED",
                "请先登录后再访问玄同服务",
                **{"WWW-Authenticate": "Bearer"},
            )

        claims = decode_token(token)
        if claims is None or claims.get("type") != "access" or not claims.get("sub"):
            return _error(
                401,
                "INVALID_TOKEN",
                "登录状态已失效，请重新登录",
                **{"WWW-Authenticate": "Bearer"},
            )
        request.state.auth_claims = claims
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """按客户端 IP 的滑动窗口限制；适用于当前单 worker ECS 部署。"""

    def __init__(
        self,
        app,
        *,
        enabled: bool,
        requests_per_minute: int,
        auth_requests_per_minute: int,
    ) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.default_limit = max(1, requests_per_minute)
        self.auth_limit = max(1, auth_requests_per_minute)
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    @staticmethod
    def _client_key(request: Request) -> str:
        # 生产端口只绑定 127.0.0.1，由 Nginx 独占入口，因此可接受其 XFF。
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or request.method == "OPTIONS" or not request.url.path.startswith("/api/"):
            return await call_next(request)

        is_auth = request.url.path.startswith("/api/auth/")
        limit = self.auth_limit if is_auth else self.default_limit
        bucket_key = f"{'auth' if is_auth else 'api'}:{self._client_key(request)}"
        now = time.monotonic()
        cutoff = now - 60.0

        async with self._lock:
            bucket = self._requests[bucket_key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(60 - (now - bucket[0])))
                return _error(
                    429,
                    "RATE_LIMITED",
                    "请求过于频繁，请稍后再试",
                    **{"Retry-After": str(retry_after)},
                )
            bucket.append(now)

            # 防止长期运行时被随机 IP 撑大；清理空的旧桶。
            if len(self._requests) > 10_000:
                stale = [key for key, values in self._requests.items() if not values or values[-1] <= cutoff]
                for key in stale:
                    self._requests.pop(key, None)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        return response
