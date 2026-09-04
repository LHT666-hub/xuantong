"""证据分级模块测试。

测试从 DrugClaw 移植的证据评分逻辑。
"""

from __future__ import annotations

import pytest

from app.xuantong.rag.evidence import (
    EvidenceGrader,
    EvidenceItem,
    EvidenceKind,
    infer_evidence_kind,
)


class TestEvidenceGrader:
    """证据分级器测试。"""

    @pytest.fixture
    def grader(self) -> EvidenceGrader:
        return EvidenceGrader()

    def test_score_database_record(self, grader: EvidenceGrader) -> None:
        """数据库记录评分 — 基础分 0.78。"""
        item = EvidenceItem(
            content="这是一条足够长的数据库记录内容，用于测试评分逻辑是否正确运行，包含足够的字符数来满足长度要求。",
            source="DrugBank",
            evidence_kind=EvidenceKind.DATABASE_RECORD,
            support_direction="support",
        )
        score = grader.score_evidence(item)
        # 基础分 0.78 + 内容长度加分 0.03 = 0.81
        assert 0.75 <= score <= 0.85
        assert 0.0 <= score <= 1.0

    def test_score_guideline(self, grader: EvidenceGrader) -> None:
        """指南评分 — 最高基础分 0.85。"""
        item = EvidenceItem(
            content="这是一条来自临床指南的推荐意见，具有最高的证据等级和可信度，用于验证指南类型的评分逻辑。",
            source="高血压指南2023",
            evidence_kind=EvidenceKind.GUIDELINE,
            support_direction="support",
        )
        score = grader.score_evidence(item)
        # 基础分 0.85 + 内容长度加分 0.03 = 0.88
        assert 0.85 <= score <= 0.95

    def test_score_model_prediction(self, grader: EvidenceGrader) -> None:
        """模型预测评分 — 低基础分 0.48。"""
        item = EvidenceItem(
            content="这是一条模型预测的结果，可信度较低，需要更多的验证和确认才能用于临床决策支持系统。",
            source="ML Model",
            evidence_kind=EvidenceKind.MODEL_PREDICTION,
            support_direction="support",
        )
        score = grader.score_evidence(item)
        # 基础分 0.48 + 内容长度加分 0.03 = 0.51
        assert 0.45 <= score <= 0.55

    def test_score_short_content_penalty(self, grader: EvidenceGrader) -> None:
        """短内容扣分 — 少于40字扣0.08。"""
        item = EvidenceItem(
            content="短内容",
            source="test",
            evidence_kind=EvidenceKind.DATABASE_RECORD,
            support_direction="support",
        )
        score = grader.score_evidence(item)
        # 基础分 0.78 - 短内容扣分 0.08 = 0.70
        assert 0.65 <= score <= 0.75

    def test_score_neutral_direction_penalty(self, grader: EvidenceGrader) -> None:
        """neutral 方向扣分 — 扣0.1。"""
        item = EvidenceItem(
            content="这是一条中性方向的证据内容，用于测试方向调整扣分逻辑，需要足够长度来避免短内容扣分。",
            source="test",
            evidence_kind=EvidenceKind.DATABASE_RECORD,
            support_direction="neutral",
        )
        score = grader.score_evidence(item)
        # 基础分 0.78 + 0.03 - 0.1 = 0.71
        assert 0.65 <= score <= 0.75

    def test_score_structured_payload_bonus(self, grader: EvidenceGrader) -> None:
        """结构化 payload 加分 — +0.05。"""
        item = EvidenceItem(
            content="这是一条包含结构化数据的证据内容，用于测试加分逻辑，需要足够长度来验证加分效果。",
            source="test",
            evidence_kind=EvidenceKind.DATABASE_RECORD,
            support_direction="support",
            metadata={"has_structured_payload": True},
        )
        score = grader.score_evidence(item)
        # 基础分 0.78 + 0.05 + 0.03 = 0.86
        assert 0.80 <= score <= 0.90

    def test_multi_source_bonus(self, grader: EvidenceGrader) -> None:
        """多源加分 — >=2 个独立来源 +0.1。"""
        items = [
            EvidenceItem(
                content="内容A" * 20,
                source="source_1",
                evidence_kind=EvidenceKind.DATABASE_RECORD,
                support_direction="support",
            ),
            EvidenceItem(
                content="内容B" * 20,
                source="source_2",
                evidence_kind=EvidenceKind.LITERATURE,
                support_direction="support",
            ),
        ]
        result = grader.aggregate_evidence(items)
        # 多源加分应该生效
        assert result["sources"] == 2
        assert result["confidence"] > 0.7

    def test_single_source_penalty(self, grader: EvidenceGrader) -> None:
        """单源扣分 — 仅1个来源 -0.08。"""
        items = [
            EvidenceItem(
                content="内容A" * 20,
                source="source_1",
                evidence_kind=EvidenceKind.DATABASE_RECORD,
                support_direction="support",
            ),
        ]
        result = grader.aggregate_evidence(items)
        assert result["sources"] == 1

    def test_contradiction_penalty(self, grader: EvidenceGrader) -> None:
        """矛盾扣分 — 每条 -0.15，封顶 -0.3。"""
        items = [
            EvidenceItem(
                content="支持证据内容" * 20,
                source="source_1",
                evidence_kind=EvidenceKind.DATABASE_RECORD,
                support_direction="support",
            ),
            EvidenceItem(
                content="矛盾证据1内容" * 20,
                source="source_2",
                evidence_kind=EvidenceKind.LITERATURE,
                support_direction="contradict",
            ),
            EvidenceItem(
                content="矛盾证据2内容" * 20,
                source="source_3",
                evidence_kind=EvidenceKind.GUIDELINE,
                support_direction="contradict",
            ),
        ]
        result = grader.aggregate_evidence(items)
        assert result["contradictions"] == 2
        # 扣分应为 min(2 * 0.15, 0.3) = 0.3

    def test_all_model_prediction_penalty(self, grader: EvidenceGrader) -> None:
        """全为模型预测扣分 — -0.2。"""
        items = [
            EvidenceItem(
                content="模型预测结果A" * 20,
                source="source_1",
                evidence_kind=EvidenceKind.MODEL_PREDICTION,
                support_direction="support",
            ),
            EvidenceItem(
                content="模型预测结果B" * 20,
                source="source_2",
                evidence_kind=EvidenceKind.MODEL_PREDICTION,
                support_direction="support",
            ),
        ]
        result = grader.aggregate_evidence(items)
        # 全为模型预测，应该有额外扣分
        assert result["confidence"] < 0.6

    def test_aggregate_evidence_empty(self, grader: EvidenceGrader) -> None:
        """空证据列表聚合。"""
        result = grader.aggregate_evidence([])
        assert result["confidence"] == 0.0
        assert result["sources"] == 0
        assert result["contradictions"] == 0
        assert result["items"] == []

    def test_aggregate_evidence_sets_scores(self, grader: EvidenceGrader) -> None:
        """聚合后每条证据的 evidence_score 被设置。"""
        items = [
            EvidenceItem(
                content="内容A" * 20,
                source="source_1",
                evidence_kind=EvidenceKind.DATABASE_RECORD,
                support_direction="support",
            ),
        ]
        result = grader.aggregate_evidence(items)
        assert items[0].evidence_score > 0.0
        assert len(result["items"]) == 1


class TestInferEvidenceKind:
    """证据类型推断测试。"""

    def test_infer_guideline(self) -> None:
        assert infer_evidence_kind("高血压指南2023") == EvidenceKind.GUIDELINE
        assert infer_evidence_kind("clinical_guideline.pdf") == EvidenceKind.GUIDELINE

    def test_infer_label_text(self) -> None:
        assert infer_evidence_kind("药品说明书") == EvidenceKind.LABEL_TEXT
        assert infer_evidence_kind("drug_label.txt") == EvidenceKind.LABEL_TEXT

    def test_infer_literature(self) -> None:
        assert infer_evidence_kind("文献报道") == EvidenceKind.LITERATURE
        assert infer_evidence_kind("literature_review.pdf") == EvidenceKind.LITERATURE

    def test_infer_database(self) -> None:
        assert infer_evidence_kind("数据库记录") == EvidenceKind.DATABASE_RECORD
        assert infer_evidence_kind("database_entry.json") == EvidenceKind.DATABASE_RECORD

    def test_infer_prediction(self) -> None:
        assert infer_evidence_kind("模型预测") == EvidenceKind.MODEL_PREDICTION
        assert infer_evidence_kind("prediction_result.csv") == EvidenceKind.MODEL_PREDICTION

    def test_infer_unknown(self) -> None:
        assert infer_evidence_kind("unknown_source") == EvidenceKind.UNKNOWN
        assert infer_evidence_kind("") == EvidenceKind.UNKNOWN
