"""RAG 抽象基类 — 定义统一的检索与重排接口。

从 LingYi 移植，适配玄同接口规范。
支持多种实现：
- MockRAGClient: 从文件加载预设结果，用于开发和测试
- ChromaRAGClient: 真实混合检索（BM25 + 向量 + RRF），用于生产环境
- RuleBasedReranker / CrossEncoderReranker: 重排器实现
"""

from abc import ABC, abstractmethod
from typing import Any

from app.xuantong.rag.models import RetrievalResult


class BaseRAGClient(ABC):
    """RAG 检索客户端抽象基类。

    所有 RAG 实现（Mock、ChromaDB 等）都继承此类。
    统一约定：search 与 hybrid_search 均返回 list[RetrievalResult]。
    """

    @abstractmethod
    async def search(self, query: str, top_k: int = 3) -> list[RetrievalResult]:
        """简单向量检索。

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            RetrievalResult 列表（按相关性降序）
        """

    @abstractmethod
    async def hybrid_search(self, query: str, n_results: int = 10) -> list[RetrievalResult]:
        """混合检索（向量 + 关键词）。

        Args:
            query: 查询文本
            n_results: 返回结果数量

        Returns:
            RetrievalResult 列表（按相关性降序）
        """

    async def add_documents(self, documents: list[dict[str, Any]]) -> int:
        """添加文档到向量库（可选实现）。

        Args:
            documents: [{"content": "...", "metadata": {...}}]

        Returns:
            成功添加的文档数量
        """
        return 0


class BaseReranker(ABC):
    """重排器抽象基类。

    对检索到的文档进行重新排序，提升相关文档的排名。
    """

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[RetrievalResult],
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """异步重排文档。

        Args:
            query: 查询文本
            documents: 待重排的 RetrievalResult 列表
            top_k: 返回前 K 个文档

        Returns:
            重排后的 RetrievalResult 列表（按相关性降序）
        """
