"""通用工具函数。"""

from __future__ import annotations

import uuid


def normalize_patient_id(patient_id: str) -> str:
    """将任意 patient_id 转为确定性 UUID。

    如果 patient_id 已经是标准 UUID 格式，直接返回；
    否则基于 uuid5 生成确定性 UUID，保证同一 patient_id 始终映射到相同 UUID。
    """
    try:
        uuid.UUID(patient_id)
        return patient_id
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"patient:{patient_id}"))
