"""全局异常处理 —— 统一错误响应格式（兼容叠加策略）。

所有错误响应**同时**包含两个顶层键，实现新老客户端平滑过渡：

    {
        "detail": "<人读消息字符串>",          # 老客户端仅读 detail 仍可用
        "error": {
            "code": "...",                    # 稳定错误码，新客户端统一读取
            "message": "...",
            "detail": <单数场景的结构化上下文或消息>,
            "details": [...]                  # 恒为数组
        }
    }

覆盖三类来源：
- ``HTTPException``           → code = ``HTTP_<status>``
- ``RequestValidationError``  → code = ``VALIDATION_ERROR``（details 为字段错误数组）
- ``XuantongError``           → 由异常自身 ``to_dict()`` 产出（见 app/exceptions.py）
- 未捕获 ``Exception``        → code = ``INTERNAL_ERROR``
"""
import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import XuantongError

logger = logging.getLogger(__name__)


def _error_body(
    code: str,
    message: str,
    *,
    detail: Any = None,
    details: list[Any] | None = None,
) -> dict[str, Any]:
    """构建统一错误响应体：顶层含 ``detail`` 与 ``error``，error 内含 detail/details。

    - 顶层 ``detail`` 恒为人读消息字符串（老客户端契约）；
    - ``error.detail`` 取结构化上下文（缺省时回退为消息）；
    - ``error.details`` 恒为数组（缺省时为空数组）。
    """
    return {
        "detail": message,
        "error": {
            "code": code,
            "message": message,
            "detail": detail if detail is not None else message,
            "details": details if details is not None else [],
        },
    }


async def xuantong_exception_handler(
    request: Request, exc: XuantongError
) -> JSONResponse:
    """处理玄同系统业务异常。

    将 XuantongError 及其子类映射为统一 JSON 错误响应，
    HTTP 状态码与业务 code 由异常自身携带（见 ``XuantongError.to_dict``）。
    """
    logger.warning(
        f"业务异常: {request.method} {request.url.path} -> "
        f"[{exc.code}] {exc.message}"
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """处理 HTTPException（兼容 FastAPI HTTPException，其为 Starlette 版子类）。

    保留原始 ``detail``（老客户端仍读 body["detail"]），并叠加 ``error`` 结构，
    code 形如 ``HTTP_404``，message 取 detail 文本（detail 非字符串时用通用文案）。
    """
    raw_detail = exc.detail
    if isinstance(raw_detail, str):
        message = raw_detail
        details: list[Any] = [raw_detail]
    else:
        message = "请求处理失败"
        details = raw_detail if isinstance(raw_detail, list) else [raw_detail]

    content = _error_body(
        f"HTTP_{exc.status_code}",
        message,
        detail=raw_detail,
        details=details,
    )
    # 顶层 detail 逐字保留原始值（可能是字符串/字典/数组），确保老客户端兼容
    content["detail"] = raw_detail

    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=headers
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """处理请求参数校验异常 (422)。"""
    errors = exc.errors()
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "VALIDATION_ERROR",
            "请求参数校验失败",
            detail="请求参数校验失败",
            details=errors,
        ),
    )


async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """处理未捕获的异常 (500)。"""
    logger.exception(f"未处理异常: {request.method} {request.url.path} -> {exc}")
    return JSONResponse(
        status_code=500,
        content=_error_body("INTERNAL_ERROR", "服务器内部错误"),
    )
