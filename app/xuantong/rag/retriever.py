"""RAG 检索器 — 封装知识库检索与混合检索策略。"""

from __future__ import annotations

import logging
from typing import Any

from app.xuantong.rag.knowledge_base import KnowledgeBase
from app.xuantong.rag.models import RetrievalResult

logger = logging.getLogger(__name__)


class RAGRetriever:
    """RAG 检索器 — 支持多种检索策略。

    当前阶段：基于 KnowledgeBase 的关键词检索。
    后续阶段：接入 pgvector 做向量检索，实现真正的混合检索。
    """

    def __init__(self, knowledge_base: KnowledgeBase | None = None) -> None:
        self.kb = knowledge_base or KnowledgeBase()

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """检索相关文档。

        Args:
            query: 查询文本。
            top_k: 返回条数。
            filters: 过滤条件（预留，当前未使用）。

        Returns:
            RetrievalResult 列表，按相关性降序。
        """
        if not query.strip():
            return []

        results = await self.kb.search(query, top_k=top_k)

        # 应用过滤（预留接口）
        if filters:
            results = self._apply_filters(results, filters)

        logger.info("RAGRetriever: query=%r → %d 条结果", query[:60], len(results))
        return results

    async def hybrid_retrieve(
        self, query: str, top_k: int = 5
    ) -> list[RetrievalResult]:
        """混合检索（关键词 + 向量）。

        当前阶段向量部分未实现，退化为纯关键词检索。
        后续接入 pgvector 后，合并两路结果并按 score 排序。
        """
        keyword_results = await self.retrieve(query, top_k=top_k)
        # TODO: 向量检索部分（pgvector）
        vector_results: list[RetrievalResult] = []

        # 合并去重（以 content 前 100 字符为 key）
        seen: set[str] = set()
        merged: list[RetrievalResult] = []
        for r in keyword_results + vector_results:
            key = r.content[:100]
            if key not in seen:
                seen.add(key)
                merged.append(r)

        merged.sort(key=lambda x: x.score, reverse=True)
        return merged[:top_k]

    @staticmethod
    def _apply_filters(
        results: list[RetrievalResult], filters: dict[str, Any]
    ) -> list[RetrievalResult]:
        """按 metadata 字段过滤结果。"""
        filtered = []
        for r in results:
            match = True
            for k, v in filters.items():
                if r.metadata.get(k) != v:
                    match = False
                    break
            if match:
                filtered.append(r)
        return filtered
