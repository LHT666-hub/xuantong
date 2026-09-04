"""受众分层过滤器 — 按 Agent 角色过滤知识文档。

从 MAS-in-diabetes 移植，适配玄同 8 Agent 架构。
每篇文档标记 audience，检索时按 Agent 角色过滤可见范围。
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Audience(str, Enum):
    """文档受众分类。"""

    PATIENT = "patient"          # 面向患者
    DOCTOR = "doctor"            # 面向医生
    NURSE = "nurse"              # 面向护士
    PUBLIC_HEALTH = "public_health"  # 面向公卫
    PHARMACIST = "pharmacist"    # 面向药师
    SHARED = "shared"            # 通用


# Agent 角色 → 可见受众列表
ROLE_TO_AUDIENCE: dict[str, list[Audience]] = {
    "family_doctor": [Audience.DOCTOR, Audience.SHARED],
    "nurse": [Audience.NURSE, Audience.PATIENT, Audience.SHARED],
    "public_health": [Audience.PUBLIC_HEALTH, Audience.SHARED],
    "pharmacist": [Audience.PHARMACIST, Audience.DOCTOR, Audience.SHARED],
    "assistant": [Audience.PATIENT, Audience.SHARED],
}


class AudienceFilter:
    """受众过滤器 — 按 Agent 角色过滤文档。"""

    def filter_by_role(
        self, documents: list[Any], agent_role: str
    ) -> list[Any]:
        """按 Agent 角色过滤文档列表。

        Args:
            documents: 含 metadata["audience"] 的文档对象列表。
            agent_role: Agent 角色标识（如 "family_doctor"）。

        Returns:
            过滤后的文档列表。
        """
        allowed = set(ROLE_TO_AUDIENCE.get(agent_role, [Audience.SHARED]))

        filtered = []
        for doc in documents:
            raw = doc.metadata.get("audience", Audience.SHARED.value)
            if isinstance(raw, Audience):
                doc_aud = raw
            else:
                try:
                    doc_aud = Audience(str(raw))
                except ValueError:
                    doc_aud = Audience.SHARED

            if doc_aud in allowed:
                filtered.append(doc)

        logger.debug(
            "AudienceFilter: role=%s, %d/%d 文档通过",
            agent_role, len(filtered), len(documents),
        )
        return filtered

    @staticmethod
    def infer_audience(content: str, source: str = "") -> Audience:
        """从内容推断受众分类。

        基于关键词匹配，优先级：doctor > pharmacist > public_health > patient > shared。
        """
        content_lower = content.lower()

        doctor_kw = ["指南", "诊断标准", "用药方案", "临床路径", "hbA1c", "适应症"]
        pharm_kw = ["药物", "剂量", "相互作用", "不良反应", "药代动力学", "药理"]
        ph_kw = ["随访", "健康管理", "公共卫生", "慢病管理", "服务规范", "建档"]
        patient_kw = ["患者", "自我管理", "饮食", "运动", "注意事项", "日常护理"]

        if any(kw in content_lower for kw in doctor_kw):
            return Audience.DOCTOR
        if any(kw in content_lower for kw in pharm_kw):
            return Audience.PHARMACIST
        if any(kw in content_lower for kw in ph_kw):
            return Audience.PUBLIC_HEALTH
        if any(kw in content_lower for kw in patient_kw):
            return Audience.PATIENT
        return Audience.SHARED
