"""结构化 JSON 日志 + PHI 脱敏（从 careflow 移植，去除 GCP 专有字段）。

设计意图
--------
每条 ``logging`` 调用都会被格式化为**一行 JSON** 输出到 stdout，包含以下核心字段::

    {"severity": "INFO", "time": "2026-04-28T12:34:56.789Z",
     "message": "...", "logger": "app.api.routes.events",
     "trace_id": "<32-hex>",          # 可选：有则输出，无则省略
     "event_type": "hitl_pause", "risk_level": "HIGH", ...}

与 careflow 原版的差异：
  - **去掉了 GCP 专有字段**（``GOOGLE_CLOUD_PROJECT`` 的
    ``projects/<proj>/traces/<id>`` trace 格式）。
  - ``trace_id`` 保留为**可选**字段：当 OpenTelemetry context 可用、或调用方
    通过 ``extra={"trace_id": ...}`` 显式传入时才输出，否则完全省略。

PHI 安全 / 患者信息保护
-----------------------
原始 ``patient_id`` 绝不写入日志。``hash_patient_id()`` 用 blake2b 生成
固定长度的伪匿名标识（同输入同输出，可用于跨日志关联，但不泄露原始 PHI）。
格式化器作为**防御性兜底**：一旦在 ``extra=`` 中发现 ``patient_id`` /
``phone`` / ``email`` / ``name`` / ``address`` 等敏感键，一律替换为
``[REDACTED]``，以防调用方误传原始 PHI。

纯标准库实现（json / logging / hashlib / datetime），无第三方依赖。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
from typing import Any

# =============================================================================
# 常量
# =============================================================================

# Python logging level → severity 词汇映射。
# Python 的 WARN -> WARNING、FATAL -> CRITICAL。
_LEVEL_TO_SEVERITY: dict[int, str] = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

# 标准 LogRecord 属性 —— 用于区分 ``extra=`` 传入的用户自定义字段。
_RESERVED_RECORD_ATTRS: frozenset[str] = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)

# 绝不允许以原始形式出现在日志中的键 —— 防御性脱敏。
# 覆盖 email / phone / name / address 等常见 PHI 字段。
_PHI_REDACT_KEYS: frozenset[str] = frozenset(
    {
        "patient_id", "raw_patient_id", "ssn", "aadhaar",
        "phone", "phone_number", "mobile", "email", "email_address",
        "name", "patient_name", "full_name", "address", "home_address",
        "id_card", "id_number", "national_id",
    }
)

_REDACTED_PLACEHOLDER = "[REDACTED]"


# =============================================================================
# 公共辅助函数
# =============================================================================

def hash_patient_id(patient_id: str | None) -> str | None:
    """返回用于安全记录的 12 位 blake2b 伪匿名标识。

    任何患者标识符在写入日志前都应经过此函数。结果是固定长度的伪匿名标签，
    相同输入产生相同 hash（可用于跨日志关联追踪），但绝不暴露原始 PHI。

    当输入为 None / 空时返回 None，调用方可无条件透传而无需 ``if`` 保护。
    """
    if not patient_id:
        return None
    digest = hashlib.blake2b(
        str(patient_id).encode("utf-8"), digest_size=6
    ).hexdigest()
    return digest[:12]


# =============================================================================
# 格式化器
# =============================================================================

class PHIRedactingJSONFormatter(logging.Formatter):
    """产出单行 JSON、并对 PHI 字段自动脱敏的日志格式化器。

    输出形态::

        {
          "severity": "INFO",
          "time":     "2026-04-28T12:34:56.789Z",
          "message":  "hitl_paused",
          "logger":   "app.xuantong.safety.plugin",
          "trace_id": "<32-hex>",        # 可选：仅在 OTel context 有效时出现
          "event_type": "hitl_pause",    # 来自 extra=
          "risk_level": "HIGH"           # 来自 extra=
        }

    PHI 脱敏：``extra=`` 中若含 ``patient_id`` / ``phone`` / ``email`` 等原始
    PHI 键，其值一律改写为 ``[REDACTED]``。调用方应始终使用
    ``hash_patient_id()`` 产出的 ``patient_id_hash``，此处仅为防御性兜底。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": _LEVEL_TO_SEVERITY.get(record.levelno, record.levelname),
            "time": _format_time(record.created),
            "message": record.getMessage(),
            "logger": record.name,
        }

        # 异常信息 —— traceback 单独放入 ``exception`` 字段。
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # 可选 trace_id：仅在 OpenTelemetry context 有效时注入。
        # 无则完全省略该字段（去除 careflow 的 GCP projects/traces 格式）。
        trace_id = self._otel_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id

        # 追加 ``extra=`` 传入的用户字段，并执行 PHI 脱敏。
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            if key in payload:
                # 不覆盖 severity/time/message/logger/trace_id 等已生成字段。
                continue
            if key in _PHI_REDACT_KEYS:
                payload[key] = _REDACTED_PLACEHOLDER
            else:
                payload[key] = _safe_jsonable(value)

        return json.dumps(payload, ensure_ascii=False, default=str)

    # ---- helpers ------------------------------------------------------------

    @staticmethod
    def _otel_trace_id() -> str | None:
        """从当前 OpenTelemetry context 提取 trace_id（若可用）。

        未安装 opentelemetry 或无有效 span 时返回 None，字段随即被省略。
        """
        try:
            from opentelemetry import trace as _otel_trace
        except ImportError:  # pragma: no cover — 防御性：未安装 OTel 时静默降级
            return None

        span = _otel_trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if not ctx or not getattr(ctx, "is_valid", False):
            return None

        return format(ctx.trace_id, "032x")


# =============================================================================
# 配置入口
# =============================================================================

def configure_structured_logging(
    level: str | int = "INFO",
    *,
    force: bool = True,
) -> None:
    """在根 logger 上安装 :class:`PHIRedactingJSONFormatter`。

    调用后，所有 ``logging`` 输出都会以单行 JSON 形式流向 stdout。

    Args:
        level: 日志级别（名称字符串或整数）。
        force: 为 True 时移除既有 handler 后重新安装（保证幂等，
               并避免与 uvicorn 默认 handler 产生重复输出）。
    """
    root = logging.getLogger()
    if force:
        # 清空既有 handler —— 保证幂等 + 防止与 uvicorn 默认 handler 重复输出。
        for handler in list(root.handlers):
            root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(PHIRedactingJSONFormatter())
    root.addHandler(handler)
    root.setLevel(level)


# =============================================================================
# 内部辅助函数
# =============================================================================

def _format_time(epoch_seconds: float) -> str:
    """RFC 3339 / ISO-8601，毫秒精度，带结尾 Z（UTC）。"""
    dt = _dt.datetime.fromtimestamp(epoch_seconds, tz=_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def _safe_jsonable(value: Any) -> Any:
    """将任意值强制转换为 ``json.dumps`` 可安全处理的形式。

    JSON 序列化安全网 —— 把对象、集合、字节等统一转为可序列化结构。
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_safe_jsonable(v) for v in value]
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover — 防御性
            return repr(value)
    return str(value)
