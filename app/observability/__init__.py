"""可观测性模块 —— 结构化 JSON 日志与 PHI 脱敏。"""

from app.observability.logging import (
    PHIRedactingJSONFormatter,
    configure_structured_logging,
    hash_patient_id,
    _safe_jsonable,
)
from app.observability.tracing import setup_tracing

__all__ = [
    "PHIRedactingJSONFormatter",
    "configure_structured_logging",
    "hash_patient_id",
    "_safe_jsonable",
    "setup_tracing",
]
