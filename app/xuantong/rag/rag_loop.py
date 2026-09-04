"""RAG 评估环路 — 检索 → 评分 → 重写 → 重新检索。

参考 LingYi 的 RAG 评估环路设计，实现自适应检索：
1. 实体解析（标准化查询中的医学术语）
2. 执行检索
3. LLM 评估检索质量
4. 证据分级（对检索结果评分）
5. 质量不达标 → 重写查询 → 重新检索
6. 达标或重试耗尽 → 返回结果
"""

from __future__ import annotations

import logging
from typing import Any

from app.xuantong.rag.evidence import (
    EvidenceGrader,
    EvidenceItem,
    infer_evidence_kind,
)
from app.xuantong.rag.entity_resolver import EntityResolver
from app.xuantong.rag.grader import RetrievalGrader
from app.xuantong.rag.models import RAGResult, RetrievalResult
from app.xuantong.rag.query_rewriter import QueryRewriter
from app.xuantong.rag.retriever import RAGRetriever

logger = logging.getLogger(__name__)


class RAGEvaluationLoop:
    """RAG 评估环路 — 检索 → 评分 → 重写 → 重新检索。

    支持可选的证据分级和实体解析增强。
    """

    def __init__(
        self,
        retriever: RAGRetriever,
        grader: RetrievalGrader,
        rewriter: QueryRewriter,
        max_retries: int = 3,
        relevance_threshold: float = 0.5,
        entity_resolver: EntityResolver | None = None,
        evidence_grader: EvidenceGrader | None = None,
    ) -> None:
        """
        Args:
            retriever: 检索器实例。
            grader: 评分器实例。
            rewriter: 查询重写器实例。
            max_retries: 最大重试次数。
            relevance_threshold: 相关性阈值（score >= 此值视为相关）。
            entity_resolver: 实体解析器实例（可选）。
            evidence_grader: 证据分级器实例（可选）。
        """
        self.retriever = retriever
        self.grader = grader
        self.rewriter = rewriter
        self.max_retries = max_retries
        self.threshold = relevance_threshold
        self.entity_resolver = entity_resolver
        self.evidence_grader = evidence_grader

    async def run(self, query: str, context: dict[str, Any] | None = None) -> RAGResult:
        """执行 RAG 评估环路。

        Args:
            query: 原始查询。
            context: 附加上下文（预留）。

        Returns:
            RAGResult
        """
        if not query.strip():
            return RAGResult(documents=[], query=query, attempts=0, success=False)

        current_query = query

        # 1. 实体解析（标准化查询中的医学术语）
        if self.entity_resolver:
            current_query = await self._resolve_entities(current_query)

        for attempt in range(self.max_retries):
            logger.info(
                "RAG 环路: attempt=%d/%d query=%r",
                attempt + 1, self.max_retries, current_query[:60],
            )

            # 2. 检索（内部已含重排）
            results = await self.retriever.retrieve(current_query, use_rerank=True)

            if not results:
                # 无结果，直接重写
                if attempt < self.max_retries - 1:
                    current_query = await self.rewriter.rewrite(current_query, [])
                    continue
                break

            # 3. 评分
            grades = await self.grader.grade_batch(
                query, [r.content for r in results]
            )

            # 4. 筛选达标结果
            relevant_results = [
                r for r, g in zip(results, grades)
                if g.relevant or g.score >= self.threshold
            ]

            if relevant_results:
                # 5. 证据分级（对检索结果评分）
                if self.evidence_grader:
                    relevant_results = self._apply_evidence_grading(relevant_results)

                logger.info(
                    "RAG 环路: 成功 attempt=%d, 相关文档=%d/%d",
                    attempt + 1, len(relevant_results), len(results),
                )
                return RAGResult(
                    documents=relevant_results,
                    query=current_query,
                    attempts=attempt + 1,
                    success=True,
                )

            # 6. 不达标 → 重写查询
            if attempt < self.max_retries - 1:
                current_query = await self.rewriter.rewrite(current_query, results)
                logger.info("RAG 环路: 重写查询 → %r", current_query[:60])

        # 所有重试都失败
        logger.warning("RAG 环路: %d 次尝试均未找到相关文档", self.max_retries)
        return RAGResult(
            documents=[],
            query=current_query,
            attempts=self.max_retries,
            success=False,
        )

    async def _resolve_entities(self, query: str) -> str:
        """解析查询中的医疗实体并标准化。

        目前简单实现：直接返回原查询。
        未来可从查询中提取实体并替换为标准名称。
        """
        # TODO: 实现实体提取和替换逻辑
        # 目前仅记录日志，不修改查询
        logger.debug("实体解析: query=%r", query[:60])
        return query

    def _apply_evidence_grading(
        self, results: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        """对检索结果应用证据分级。

        将证据评分注入到 RetrievalResult 的 metadata 中。

        Args:
            results: 检索结果列表

        Returns:
            注入证据评分后的结果列表
        """
        if not self.evidence_grader:
            return results

        # 构建证据条目
        evidence_items = [
            EvidenceItem(
                content=doc.content,
                source=doc.source,
                evidence_kind=infer_evidence_kind(doc.source),
                retrieval_score=doc.score,
                metadata=doc.metadata,
            )
            for doc in results
        ]

        # 聚合评分
        evidence_result = self.evidence_grader.aggregate_evidence(evidence_items)

        # 将证据评分注入结果
        for doc, item in zip(results, evidence_result["items"]):
            doc.metadata["evidence_score"] = item.evidence_score
            doc.metadata["evidence_kind"] = item.evidence_kind.value

        # 记录聚合结果
        logger.info(
            "证据分级: confidence=%.3f, sources=%d, contradictions=%d",
            evidence_result["confidence"],
            evidence_result["sources"],
            evidence_result["contradictions"],
        )

        return results
