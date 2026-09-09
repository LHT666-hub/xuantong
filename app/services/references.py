"""Patient-safe reference presentation helpers for RAG-backed responses."""

from __future__ import annotations

import re
from typing import Any, Iterable

_SOURCE_TITLES = {
    "hypertension_guidelines.md": "高血压健康管理指南",
    "guidelines/hypertension_grassroots_2025.md": "基层高血压防治指南（2025）",
    "diabetes_guidelines.md": "糖尿病健康管理指南",
    "guidelines/diabetes_grassroots_2025.md": "基层糖尿病防治指南（2025）",
    "guidelines/copd_grassroots_2025.md": "基层慢阻肺防治指南（2025）",
    "guidelines/stroke_grassroots_2021.md": "基层脑卒中防治指南（2021）",
    "medication_safety.md": "家庭用药安全手册",
    "drugs/antihypertensive_medications.md": "常用降压药物资料",
    "drugs/antidiabetic_medications.md": "常用降糖药物资料",
    "drugs/essential_drug_list_common.md": "国家基本药物常用目录",
    "public_health_services.md": "国家基本公共卫生服务资料",
    "policies/national/basic_public_health_service.md": "国家基本公共卫生服务规范",
    "policies/national/family_doctor_contracting.md": "家庭医生签约服务政策",
    "policies/shanghai/chronic_disease_management_2025.md": "上海市慢性病健康管理资料（2025）",
    "policies/shanghai/family_doctor_111.md": "上海家庭医生 1+1+1 服务资料",
    "policies/fengxian/family_doctor_service.md": "奉贤区家庭医生服务资料",
}


def source_title(source: str) -> str:
    if source in _SOURCE_TITLES:
        return _SOURCE_TITLES[source]
    stem = source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return stem.replace("_", " ").strip().title() or "玄同医学知识库"


def reference_excerpt(document: str, limit: int = 260) -> str:
    text = re.sub(r"```.*?```", " ", document, flags=re.DOTALL)
    text = re.sub(r"[#>*_`|\[\]()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，。；; ") + "…"


def build_references(
    sources: Iterable[str], documents: Iterable[str], confidence: float = 0.0
) -> list[dict[str, Any]]:
    source_list = list(sources)
    document_list = list(documents)
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, source in enumerate(source_list):
        if not source or source in seen:
            continue
        seen.add(source)
        excerpt = document_list[index] if index < len(document_list) else ""
        references.append(
            {
                "id": f"ref-{len(references) + 1}",
                "title": source_title(source),
                "source": source,
                "excerpt": reference_excerpt(excerpt),
                "evidence_score": round(float(confidence or 0.0), 3),
                "kind": "local_knowledge_base",
            }
        )
    return references


__all__ = ["build_references", "reference_excerpt", "source_title"]
