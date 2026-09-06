"""请求追踪中间件 —— 为每个 HTTP 请求生成 request_id 并输出结构化日志。

功能：
  - 为每个请求生成唯一 ``request_id``（uuid4），并回写到响应头 ``X-Request-ID``。
  - 记录 ``request_start`` / ``request_end`` 两个结构化事件，字段包含：
    request_id、method、path、status_code、duration_ms、client_ip。
  - 依赖根 logger 上的 :class:`PHIRedactingJSONFormatter`（由
    ``configure_structured_logging`` 安装），日志以单行 JSON 输出。

纯标准库实现（uuid / time / logging），无第三方依赖。
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.request")

# 响应头名称 —— 客户端可据此关联同一次请求的服务端日志。
REQUEST_ID_HEADER = "X-Request-ID"


def _client_ip(request: Request) -> str | None:
    """提取客户端 IP。

    优先取反向代理透传的 ``X-Forwarded-For`` 首个地址，否则回退到
    socket 对端地址。取不到时返回 None。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录请求生命周期并注入 ``X-Request-ID`` 响应头的中间件。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex
        client_ip = _client_ip(request)
        method = request.method
        path = request.url.path

        # 将 request_id 挂到 request.state，便于下游 handler / 异常处理器取用。
        request.state.request_id = request_id

        logger.info(
            "request_start",
            extra={
                "event_type": "request_start",
                "request_id": request_id,
                "method": method,
                "path": path,
                "client_ip": client_ip,
            },
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 未捕获异常也要留下 request_end（含耗时），再向上抛给异常处理器。
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.exception(
                "request_error",
                extra={
                    "event_type": "request_error",
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "client_ip": client_ip,
                    "duration_ms": round(duration_ms, 3),
                },
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000.0
        status_code = response.status_code
        log_fn = logger.warning if status_code >= 400 else logger.info
        log_fn(
            "request_end",
            extra={
                "event_type": "request_end",
                "request_id": request_id,
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 3),
                "client_ip": client_ip,
            },
        )

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
