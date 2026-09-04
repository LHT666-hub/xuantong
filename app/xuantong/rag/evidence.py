"""证据分级模块 — 基于规则的证据可信度评分。

从 DrugClaw 项目移植的证据评分逻辑，为 RAG 检索结果提供
证据可信度评估。纯规则实现，不依赖 LLM。

评分维度：
1. 基础可信度（按证据类型）
2. 结构化 payload 加分
3. 内容长度加分
4. 方向调整（neutral 扣分）
5. 多源交叉验证加分
6. 矛盾证据扣分
7. 全为模型预测扣分
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EvidenceKind(str, Enum):
    """证据类型枚举。"""

    DATABASE_RECORD = "database_record"      # 数据库记录（如 DrugBank）
    LABEL_TEXT = "label_text"                # 药品说明书
    LITERATURE = "literature"                # 文献报道
    GUIDELINE = "guideline"                  # 临床指南
    MODEL_PREDICTION = "model_prediction"    # 模型预测
    EXPERT_OPINION = "expert_opinion"        # 专家意见
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    """单条证据条目。"""

    content: str = Field(description="证据正文内容")
    source: str = Field(default="", description="来源标识")
    evidence_kind: EvidenceKind = Field(
        default=EvidenceKind.UNKNOWN, description="证据类型"
    )
    retrieval_score: float = Field(default=0.0, description="检索相关性得分")
    evidence_score: float = Field(default=0.0, description="证据可信度评分")
    support_direction: str = Field(
        default="neutral", description="支持方向: support/contradict/neutral"
    )
    confidence: float = Field(default=0.0, description="置信度")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class EvidenceGrader:
    """证据分级器 — 基于规则的评分逻辑。

    参考 DrugClaw 的 score_evidence_item / score_claim_confidence 实现。
    """

    # 基础可信度（按证据类型）
    BASE_SCORES: dict[EvidenceKind, float] = {
        EvidenceKind.DATABASE_RECORD: 0.78,
        EvidenceKind.LABEL_TEXT: 0.80,
        EvidenceKind.LITERATURE: 0.82,
        EvidenceKind.GUIDELINE: 0.85,
        EvidenceKind.MODEL_PREDICTION: 0.48,
        EvidenceKind.EXPERT_OPINION: 0.60,
        EvidenceKind.UNKNOWN: 0.50,
    }

    def score_evidence(self, item: EvidenceItem) -> float:
        """单条证据评分。

        评分规则：
        1. 基础分（按 evidence_kind）
        2. 结构化 payload 加分 (+0.05)
        3. 内容长度加分（>40字 +0.03，<40字 -0.08）
        4. 方向调整（neutral -0.1）

        Returns:
            评分值，范围 [0.0, 1.0]
        """
        # 1. 基础分
        score = self.BASE_SCORES.get(item.evidence_kind, 0.50)

        # 2. 结构化 payload 加分
        if item.metadata.get("has_structured_payload"):
            score += 0.05

        # 3. 内容长度加分
        if len(item.content) < 40:
            score -= 0.08
        else:
            score += 0.03

        # 4. 方向调整
        if item.support_direction == "neutral":
            score -= 0.1

        return _clamp(score)

    def aggregate_evidence(self, items: list[EvidenceItem]) -> dict[str, Any]:
        """多证据聚合评分。

        聚合规则：
        1. 计算各条证据评分的平均值
        2. 多源加分（>=2 个独立来源 +0.1，单源 -0.08）
        3. 矛盾扣分（每条 -0.15，封顶 -0.3）
        4. 全为模型预测扣分（-0.2）

        Returns:
            聚合结果字典，包含 confidence / sources / contradictions 等。
        """
        if not items:
            return {
                "confidence": 0.0,
                "sources": 0,
                "contradictions": 0,
                "avg_evidence_score": 0.0,
                "items": [],
            }

        # 评分每条证据
        for item in items:
            item.evidence_score = self.score_evidence(item)

        # 平均分
        scores = [item.evidence_score for item in items]
        avg_score = sum(scores) / len(scores)

        # 多源加分
        unique_sources = len({item.source for item in items})
        if unique_sources >= 2:
            multi_source_bonus = 0.1
        elif unique_sources == 1:
            multi_source_bonus = -0.08
        else:
            multi_source_bonus = 0.0

        # 矛盾扣分
        contradictions = sum(
            1 for item in items if item.support_direction == "contradict"
        )
        contradiction_penalty = min(contradictions * 0.15, 0.3)

        # 全为模型预测扣分
        all_predictions = all(
            item.evidence_kind == EvidenceKind.MODEL_PREDICTION for item in items
        )
        prediction_penalty = -0.2 if all_predictions else 0.0

        final_confidence = (
            avg_score + multi_source_bonus - contradiction_penalty + prediction_penalty
        )
        final_confidence = _clamp(final_confidence)

        return {
            "confidence": final_confidence,
            "sources": unique_sources,
            "contradictions": contradictions,
            "avg_evidence_score": avg_score,
            "items": items,
        }


def infer_evidence_kind(source: str) -> EvidenceKind:
    """从来源字符串推断证据类型。

    Args:
        source: 来源标识（文件名、URL 等）

    Returns:
        推断出的 EvidenceKind
    """
    source_lower = source.lower()
    if "guideline" in source_lower or "指南" in source:
        return EvidenceKind.GUIDELINE
    if "label" in source_lower or "说明书" in source:
        return EvidenceKind.LABEL_TEXT
    if "literature" in source_lower or "文献" in source:
        return EvidenceKind.LITERATURE
    if "database" in source_lower or "数据库" in source:
        return EvidenceKind.DATABASE_RECORD
    if "prediction" in source_lower or "预测" in source:
        return EvidenceKind.MODEL_PREDICTION
    return EvidenceKind.UNKNOWN


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """将值限制在 [low, high] 范围内。"""
    return max(low, min(high, value))
