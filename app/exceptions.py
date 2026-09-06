"""统一异常层次 — 玄同系统所有业务异常的基类与子类。

设计原则:
- 所有业务异常继承 XuantongError，便于统一捕获
- 每个异常自带业务 code 与 HTTP status_code，FastAPI 层通过
  @app.exception_handler(XuantongError) 统一映射为 JSON 错误响应
- Agent / 服务层抛出 XuantongError 子类，由调用方决定如何处理
- 统一响应格式:
    {"error": {"code": "...", "message": "...", "detail": ...}}

参考 LingYi 项目 lingyi/exceptions.py 的层次设计，并适配玄同
数字化家庭医生团队的医疗业务场景（LLM 调用、安全护栏、RAG 检索、
存储、认证鉴权、业务校验等）。
"""
from typing import Any


class XuantongError(Exception):
    """玄同系统所有业务异常的基类。

    属性:
        message: 面向调用方的错误描述
        code: 稳定的业务错误码（大写下划线风格），供前端/日志分类
        status_code: 映射到 HTTP 的状态码
        detail: 可选的结构化上下文（如校验字段、上游返回等），会被序列化进响应
    """

    #: 子类可覆盖的默认错误码与状态码
    default_code: str = "INTERNAL_ERROR"
    default_status_code: int = 500

    def __init__(
        self,
        message: str = "服务器内部错误",
        code: str | None = None,
        status_code: int | None = None,
        *,
        detail: Any = None,
    ):
        self.message = message
        self.code = code or self.default_code
        self.status_code = status_code or self.default_status_code
        self.detail = detail
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """序列化为统一错误响应体（不含 HTTP 状态码）。

        采取**兼容叠加**策略，同时输出：
        - 顶层 ``detail``（人读消息字符串），供仅读 detail 的老客户端使用；
        - 顶层 ``error`` 结构，内含 ``code`` / ``message``，并统一同时给出
          ``detail``（单数场景）与 ``details``（恒为数组），避免客户端猜键名。
        """
        details: list[Any]
        if self.detail is None:
            details = []
        elif isinstance(self.detail, list):
            details = self.detail
        else:
            details = [self.detail]

        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "detail": self.detail if self.detail is not None else self.message,
            "details": details,
        }
        return {"detail": self.message, "error": error}

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"{self.__class__.__name__}(code={self.code!r}, "
            f"status_code={self.status_code!r}, message={self.message!r})"
        )


class ConfigError(XuantongError):
    """配置错误 — 缺少必要的环境变量或配置值无效。"""

    default_code = "CONFIG_ERROR"
    default_status_code = 500


class ModelCallError(XuantongError):
    """模型调用失败 — LLM API 超时、限流或返回异常。"""

    default_code = "MODEL_CALL_ERROR"
    # 上游依赖失败，语义上更接近 502 Bad Gateway
    default_status_code = 502

    def __init__(
        self,
        message: str = "模型调用失败",
        code: str | None = None,
        status_code: int | None = None,
        *,
        detail: Any = None,
        provider: str = "",
        model: str = "",
        upstream_status: int | None = None,
    ):
        super().__init__(message, code, status_code, detail=detail)
        self.provider = provider
        self.model = model
        self.upstream_status = upstream_status
        if self.detail is None:
            ctx = {
                k: v
                for k, v in (
                    ("provider", provider),
                    ("model", model),
                    ("upstream_status", upstream_status),
                )
                if v
            }
            if ctx:
                self.detail = ctx


class SafetyViolationError(XuantongError):
    """安全层拦截 — 输入/输出/动作护栏或 HITL 触发的安全违规。"""

    default_code = "SAFETY_VIOLATION"
    default_status_code = 400

    def __init__(
        self,
        message: str = "内容未通过安全校验",
        code: str | None = None,
        status_code: int | None = None,
        *,
        detail: Any = None,
        violations: list[str] | None = None,
        guard: str = "",
    ):
        super().__init__(message, code, status_code, detail=detail)
        self.violations = violations or []
        self.guard = guard
        if self.detail is None:
            ctx = {}
            if self.violations:
                ctx["violations"] = self.violations
            if guard:
                ctx["guard"] = guard
            if ctx:
                self.detail = ctx


class RAGSearchError(XuantongError):
    """RAG 检索失败 — 向量/关键词检索异常或知识库连接失败。"""

    default_code = "RAG_SEARCH_ERROR"
    default_status_code = 502


class ParseError(XuantongError):
    """解析错误 — LLM 输出的 JSON / 结构化结果不符合预期。"""

    default_code = "PARSE_ERROR"
    default_status_code = 500


class StorageError(XuantongError):
    """存储/数据库错误 — 持久化操作失败。"""

    default_code = "STORAGE_ERROR"
    default_status_code = 500


class AuthenticationError(XuantongError):
    """认证失败 — 身份凭证缺失、无效或已过期。"""

    default_code = "AUTHENTICATION_ERROR"
    default_status_code = 401


class AuthorizationError(XuantongError):
    """权限不足 — 已通过认证但无权执行该操作。"""

    default_code = "AUTHORIZATION_ERROR"
    default_status_code = 403


class ValidationError(XuantongError):
    """业务校验失败 — 请求数据在业务规则层面不合法。"""

    default_code = "VALIDATION_ERROR"
    default_status_code = 422


__all__ = [
    "XuantongError",
    "ConfigError",
    "ModelCallError",
    "SafetyViolationError",
    "RAGSearchError",
    "ParseError",
    "StorageError",
    "AuthenticationError",
    "AuthorizationError",
    "ValidationError",
]
