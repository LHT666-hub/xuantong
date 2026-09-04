"""RAG 评估环路 — 检索 → 评分 → 重写 → 重新检索。

参考 LingYi 的 RAG 评估环路设计，实现自适应检索：
1. 执行检索
2. LLM 评估检索质量
3. 质量不达标 → 重写查询 → 重新检索
4. 达标或重试耗尽 → 返回结果
"""

from __future__ import annotations

import logging
from typing import Any

from app.xuantong.rag.grader import RetrievalGrader
from app.xuantong.rag.models import RAGResult, RetrievalResult
from app.xuantong.rag.query_rewriter import QueryRewriter
from app.xuantong.rag.retriever import RAGRetriever

logger = logging.getLogger(__name__)


class RAGEvaluationLoop:
    """RAG 评估环路 — 检索 → 评分 → 重写 → 重新检索。"""

    def __init__(
        self,
        retriever: RAGRetriever,
        grader: RetrievalGrader,
        rewriter: QueryRewriter,
        max_retries: int = 3,
        relevance_threshold: float = 0.5,
    ) -> None:
        """
        Args:
            retriever: 检索器实例。
            grader: 评分器实例。
            rewriter: 查询重写器实例。
            max_retries: 最大重试次数。
            relevance_threshold: 相关性阈值（score >= 此值视为相关）。
        """
        self.retriever = retriever
        self.grader = grader
        self.rewriter = rewriter
        self.max_retries = max_retries
        self.threshold = relevance_threshold

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

        for attempt in range(self.max_retries):
            logger.info(
                "RAG 环路: attempt=%d/%d query=%r",
                attempt + 1, self.max_retries, current_query[:60],
            )

            # 1. 检索
            results = await self.retriever.retrieve(current_query)

            if not results:
                # 无结果，直接重写
                if attempt < self.max_retries - 1:
                    current_query = await self.rewriter.rewrite(current_query, [])
                    continue
                break

            # 2. 评分
            grades = await self.grader.grade_batch(
                query, [r.content for r in results]
            )

            # 3. 筛选达标结果
            relevant_results = [
                r for r, g in zip(results, grades)
                if g.relevant or g.score >= self.threshold
            ]

            if relevant_results:
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

            # 4. 不达标 → 重写查询
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
