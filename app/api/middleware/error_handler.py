"""全局异常处理

统一错误响应格式：
{
    "error": {
        "code": "...",
        "message": "...",
        "details": ...  # 可选
    }
}
"""
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.exceptions import XuantongError

logger = logging.getLogger(__name__)


async def xuantong_exception_handler(
    request: Request, exc: XuantongError
) -> JSONResponse:
    """处理玄同系统业务异常。

    将 XuantongError 及其子类映射为统一 JSON 错误响应，
    HTTP 状态码与业务 code 由异常自身携带。
    """
    logger.warning(
        f"业务异常: {request.method} {request.url.path} -> "
        f"[{exc.code}] {exc.message}"
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """处理请求参数校验异常 (422)"""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请求参数校验失败",
                "details": exc.errors(),
            }
        },
    )


async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """处理未捕获的异常 (500)"""
    logger.exception(f"未处理异常: {request.method} {request.url.path} -> {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
            }
        },
    )
