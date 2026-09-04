"""RAG 重排器 — 对检索结果进行重新排序。

从 LingYi 移植，适配玄同接口规范。
支持两种实现：
- RuleBasedReranker: 基于关键词重叠度排序（无模型依赖，用于测试/降级）
- CrossEncoderReranker: 使用 Cross-Encoder 模型重排（生产用）
"""

from __future__ import annotations

import asyncio
import logging

from app.xuantong.rag.base import BaseReranker
from app.xuantong.rag.models import RetrievalResult

logger = logging.getLogger(__name__)


class RuleBasedReranker(BaseReranker):
    """规则重排器 — 基于关键词重叠度排序，无模型依赖。

    用于测试和降级场景。
    """

    async def rerank(
        self, query: str, documents: list[RetrievalResult], top_k: int = 5
    ) -> list[RetrievalResult]:
        """按关键词重叠度重排文档。

        Args:
            query: 查询文本
            documents: 待重排的文档列表
            top_k: 返回前 K 个文档

        Returns:
            重排后的文档列表（按相关性降序）
        """
        if not documents:
            return []

        # 字符级分词（适配中文）
        query_chars = {ch for ch in query if ch.strip()}
        for doc in documents:
            doc_chars = {ch for ch in doc.content if ch.strip()}
            overlap = len(query_chars & doc_chars)
            doc.rerank_score = overlap / max(len(query_chars), 1)

        ranked = sorted(documents, key=lambda d: d.rerank_score, reverse=True)
        return ranked[:top_k]


class CrossEncoderReranker(BaseReranker):
    """Cross-Encoder 重排器。

    使用 sentence-transformers 的 CrossEncoder 模型对检索结果进行重排。
    延迟加载模型，避免启动时占用显存。
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        """
        Args:
            model_name: Cross-Encoder 模型名称
        """
        self._model_name = model_name
        self._model = None  # 延迟加载

    def _ensure_model(self) -> None:
        """延迟加载 CrossEncoder 模型。"""
        if self._model is not None:
            return

        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(self._model_name)
        logger.info("CrossEncoder 加载完成: %s", self._model_name)

    async def rerank(
        self, query: str, documents: list[RetrievalResult], top_k: int = 5
    ) -> list[RetrievalResult]:
        """异步重排文档。

        Args:
            query: 查询文本
            documents: 待重排的文档列表
            top_k: 返回前 K 个文档

        Returns:
            重排后的文档列表（按相关性降序）
        """
        if not documents:
            return []

        self._ensure_model()

        # 构造 query-doc 对
        pairs = [(query, doc.content) for doc in documents]

        # 在线程池中运行（避免阻塞事件循环）
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(None, self._model.predict, pairs)

        # 将分数赋值给文档并排序
        for doc, score in zip(documents, scores):
            doc.rerank_score = float(score)

        ranked = sorted(documents, key=lambda d: d.rerank_score, reverse=True)
        return ranked[:top_k]
