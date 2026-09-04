"""RAG 检索器 — 封装知识库检索、混合检索与重排策略。

集成安全过滤（PHI 脱敏 + 注入检测）、受众分层过滤与可选重排。
"""

from __future__ import annotations

import logging
from typing import Any

from app.xuantong.rag.audience_filter import AudienceFilter
from app.xuantong.rag.base import BaseReranker
from app.xuantong.rag.knowledge_base import KnowledgeBase
from app.xuantong.rag.models import RetrievalResult
from app.xuantong.rag.reranker import RuleBasedReranker
from app.xuantong.rag.safety_filter import RAGSafetyFilter

logger = logging.getLogger(__name__)


class RAGRetriever:
    """RAG 检索器 — 支持混合检索 + 可选重排。

    流程：检索 → 重排（可选） → 受众过滤 → 安全过滤
    """

    def __init__(
        self,
        knowledge_base: KnowledgeBase | None = None,
        safety_filter: RAGSafetyFilter | None = None,
        audience_filter: AudienceFilter | None = None,
        reranker: BaseReranker | None = None,
    ) -> None:
        self.kb = knowledge_base or KnowledgeBase()
        self.safety_filter = safety_filter if safety_filter is not None else RAGSafetyFilter()
        self.audience_filter = audience_filter if audience_filter is not None else AudienceFilter()
        self.reranker = reranker if reranker is not None else RuleBasedReranker()

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        agent_role: str | None = None,
        use_rerank: bool = True,
    ) -> list[RetrievalResult]:
        """检索相关文档（含可选重排）。

        Args:
            query: 查询文本。
            top_k: 返回条数。
            filters: 过滤条件（预留）。
            agent_role: Agent 角色，用于受众过滤。
            use_rerank: 是否启用重排（默认 True）。

        Returns:
            RetrievalResult 列表，按相关性降序。
        """
        if not query.strip():
            return []

        # 1. 粗排检索（多取一些用于重排）
        fetch_k = top_k * 3
        results = await self.kb.hybrid_search(query, top_k=fetch_k)

        # 2. 应用 metadata 过滤（预留接口）
        if filters:
            results = self._apply_filters(results, filters)

        # 3. 重排（可选）
        if use_rerank and results and self.reranker:
            results = await self.reranker.rerank(query, results, top_k=fetch_k)

        # 4. 受众过滤（可选）
        if agent_role and self.audience_filter:
            results = self.audience_filter.filter_by_role(results, agent_role)

        # 截断到 top_k
        results = results[:top_k]

        # 5. 安全过滤
        if self.safety_filter:
            results = self._apply_safety_filter(results)

        logger.info("RAGRetriever: query=%r → %d 条结果", query[:60], len(results))
        return results

    async def hybrid_retrieve(
        self, query: str, top_k: int = 5
    ) -> list[RetrievalResult]:
        """混合检索（BM25 + 向量 + 重排）。

        当前阶段使用 BM25 + RuleBasedReranker；
        后续接入向量检索和 CrossEncoder 后自动升级。
        """
        return await self.retrieve(query, top_k=top_k, use_rerank=True)

    def _apply_safety_filter(
        self, results: list[RetrievalResult]
    ) -> list[RetrievalResult]:
        """对检索结果执行安全过滤。"""
        safe: list[RetrievalResult] = []
        for doc in results:
            fr = self.safety_filter.filter_content(doc.content)
            if fr.passed:
                safe.append(doc)
            elif fr.sanitized_content:
                # 脱敏后保留
                doc.content = fr.sanitized_content
                doc.metadata["sanitized"] = True
                safe.append(doc)
            # else: 注入攻击 → 丢弃
        return safe

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
