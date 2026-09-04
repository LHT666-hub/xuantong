"""ChromaDB 混合检索 — BM25 + 向量 + RRF 融合。

从 LingYi 移植，适配玄同接口规范。
核心流程：
1. BM25 关键词检索（字符级分词，适配中文）
2. 向量检索（ChromaDB cosine，可选，需要 embedding 模型）
3. RRF 融合两路排名（k=60）
4. 无 embedding 时自动回退 BM25-only
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

from app.xuantong.rag.base import BaseRAGClient
from app.xuantong.rag.models import RetrievalResult

logger = logging.getLogger(__name__)

# RRF 平滑参数 k（标准值 60）
_RRF_K = 60


class ChromaRAGClient(BaseRAGClient):
    """ChromaDB 混合检索客户端 — BM25 + 向量 + RRF 融合。

    通过构造函数注入 embedding 模型，支持 mock/real 切换。
    混合检索流程：
    1. 向量检索：用 embedding 模型嵌入查询，ChromaDB cosine 检索
    2. BM25 检索：对集合中的文档做字符级 BM25 关键词检索
    3. RRF 融合：对两路排名做 Reciprocal Rank Fusion (k=60)

    无 embedding 模型时回退到 BM25-only。
    """

    def __init__(
        self,
        chroma_db_dir: str,
        embedding_model: Any = None,
        collection_name: str = "xuantong_kb",
    ):
        """
        Args:
            chroma_db_dir: ChromaDB 持久化目录
            embedding_model: BaseEmbedding 实例（用于查询向量化）
            collection_name: 集合名称
        """
        self._chroma_db_dir = chroma_db_dir
        self._embedding_model = embedding_model
        self._collection_name = collection_name
        self._client = None
        self._collection = None

        # BM25 索引缓存（懒加载，add_documents 后失效）
        self._bm25_index = None
        self._bm25_corpus: list[dict[str, Any]] = []

        logger.info(
            "ChromaRAGClient 初始化: dir=%s, collection=%s",
            chroma_db_dir, collection_name,
        )

    def _ensure_client(self) -> None:
        """延迟初始化 ChromaDB 客户端。"""
        if self._client is not None:
            return

        import chromadb

        self._client = chromadb.PersistentClient(path=self._chroma_db_dir)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB 连接完成: %s", self._collection_name)

    # ── BM25 索引管理 ──────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """字符级分词 — 适用于中文文本。

        将文本拆分为单个字符（过滤空白），不依赖 jieba。
        """
        return [ch for ch in text if ch.strip()]

    def _ensure_bm25_index(self) -> None:
        """延迟构建 BM25 索引。

        从 ChromaDB collection.get() 拉取全部文档，按字符分词后构建 BM25Okapi。
        索引缓存在 self._bm25_index，add_documents 后置 None 触发重建。
        """
        if self._bm25_index is not None:
            return

        from rank_bm25 import BM25Okapi

        try:
            all_data = self._collection.get()
        except Exception as e:
            logger.error("BM25 索引构建失败（无法读取集合）: %s", e)
            self._bm25_index = None
            self._bm25_corpus = []
            return

        ids = all_data.get("ids", [])
        documents = all_data.get("documents", [])
        metadatas = all_data.get("metadatas", [])

        if not documents:
            self._bm25_index = None
            self._bm25_corpus = []
            return

        tokenized_corpus = [self._tokenize(doc) for doc in documents]
        self._bm25_corpus = [
            {"id": _id, "content": doc, "metadata": meta or {}}
            for _id, doc, meta in zip(ids, documents, metadatas)
        ]
        self._bm25_index = BM25Okapi(tokenized_corpus)
        logger.info("BM25 索引构建完成: %d 条文档", len(self._bm25_corpus))

    def _bm25_search(
        self, query: str, n_results: int
    ) -> list[tuple[str, dict[str, Any], float]]:
        """BM25 关键词检索（同步，在线程池中运行）。

        Returns:
            [(content, metadata, normalized_score), ...] 按相关性降序
        """
        self._ensure_bm25_index()
        if self._bm25_index is None or not self._bm25_corpus:
            return []

        tokenized_query = self._tokenize(query)
        if not tokenized_query:
            return []

        scores = self._bm25_index.get_scores(tokenized_query)

        ranked_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )

        max_score = float(max(scores)) if len(scores) > 0 else 0.0
        results: list[tuple[str, dict[str, Any], float]] = []
        for idx in ranked_indices:
            if scores[idx] <= 0:
                break
            entry = self._bm25_corpus[idx]
            norm_score = float(scores[idx]) / max_score if max_score > 0 else 0.0
            results.append((entry["content"], entry["metadata"], norm_score))
            if len(results) >= n_results:
                break

        return results

    # ── 向量检索 ────────────────────────────────────────────────

    def _query_chroma(
        self,
        query: str,
        query_embedding: list[float] | None,
        n_results: int,
    ) -> list[RetrievalResult]:
        """同步执行 ChromaDB 向量查询（在线程池中运行）。"""
        try:
            kwargs: dict[str, Any] = {"n_results": n_results}

            if query_embedding:
                kwargs["query_embeddings"] = [query_embedding]
            else:
                kwargs["query_texts"] = [query]

            results = self._collection.query(**kwargs)

            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            parsed: list[RetrievalResult] = []
            for doc, meta, dist in zip(documents, metadatas, distances):
                score = max(0.0, 1 - dist) if dist is not None else 0.0
                parsed.append(
                    RetrievalResult(
                        content=doc,
                        source=meta.get("source", "") if meta else "",
                        score=score,
                        vector_score=score,
                        metadata=meta or {},
                    )
                )

            return parsed

        except Exception as e:
            logger.error("ChromaDB 查询失败: %s", e)
            return []

    # ── RRF 融合 ────────────────────────────────────────────────

    @staticmethod
    def _rrf_fuse(
        vector_results: list[RetrievalResult],
        bm25_results: list[tuple[str, dict[str, Any], float]],
        n_results: int,
        k: int = _RRF_K,
    ) -> list[RetrievalResult]:
        """Reciprocal Rank Fusion — 融合向量与 BM25 排名。

        rrf_score(d) = sum(1 / (k + rank_i(d)))
        分数归一化：除以理论最大值 num_rankings/(k+1)
        """
        rrf_scores: dict[str, float] = {}
        meta_map: dict[str, tuple[str, dict[str, Any]]] = {}
        bm25_score_map: dict[str, float] = {}
        vector_score_map: dict[str, float] = {}

        # 向量排名
        for rank, result in enumerate(vector_results, start=1):
            rrf_scores[result.content] = rrf_scores.get(result.content, 0.0) + 1.0 / (k + rank)
            vector_score_map[result.content] = result.vector_score
            if result.content not in meta_map:
                meta_map[result.content] = (result.source, result.metadata)

        # BM25 排名
        for rank, (content, metadata, score) in enumerate(bm25_results, start=1):
            rrf_scores[content] = rrf_scores.get(content, 0.0) + 1.0 / (k + rank)
            bm25_score_map[content] = score
            if content not in meta_map:
                meta_map[content] = (metadata.get("source", ""), metadata)

        sorted_contents = sorted(rrf_scores.keys(), key=lambda c: rrf_scores[c], reverse=True)

        # 归一化：理论最大值 = 2/(k+1)（两个系统均排第一）
        max_possible = 2.0 / (k + 1)

        fused: list[RetrievalResult] = []
        for content in sorted_contents[:n_results]:
            source, metadata = meta_map[content]
            normalized_score = rrf_scores[content] / max_possible
            fused.append(
                RetrievalResult(
                    content=content,
                    source=source,
                    score=normalized_score,
                    metadata=metadata,
                    bm25_score=bm25_score_map.get(content, 0.0),
                    vector_score=vector_score_map.get(content, 0.0),
                )
            )

        return fused

    # ── 公开检索接口 ─────────────────────────────────────────────

    def _hybrid_search_sync(
        self,
        query: str,
        query_embedding: list[float] | None,
        n_results: int,
    ) -> list[RetrievalResult]:
        """同步混合检索（在线程池中运行）。"""
        candidate_k = max(n_results * 3, n_results)

        bm25_results = self._bm25_search(query, candidate_k)

        # 无 embedding 模型：BM25-only
        if query_embedding is None:
            results = [
                RetrievalResult(
                    content=content,
                    source=metadata.get("source", ""),
                    score=score,
                    bm25_score=score,
                    metadata=metadata,
                )
                for content, metadata, score in bm25_results[:n_results]
            ]
            return results

        # 向量检索
        vector_results = self._query_chroma(query, query_embedding, candidate_k)

        if not vector_results and not bm25_results:
            return []

        if not bm25_results:
            return vector_results[:n_results]
        if not vector_results:
            return [
                RetrievalResult(
                    content=content,
                    source=metadata.get("source", ""),
                    score=score,
                    bm25_score=score,
                    metadata=metadata,
                )
                for content, metadata, score in bm25_results[:n_results]
            ]

        return self._rrf_fuse(vector_results, bm25_results, n_results)

    async def search(self, query: str, top_k: int = 3) -> list[RetrievalResult]:
        """执行混合检索（语义等同 hybrid_search，仅截取 top_k）。"""
        return await self.hybrid_search(query, n_results=top_k)

    async def hybrid_search(self, query: str, n_results: int = 10) -> list[RetrievalResult]:
        """执行混合检索（BM25 + 向量，RRF 融合）。

        无 embedding 模型时回退到 BM25-only。
        """
        self._ensure_client()

        if self._embedding_model:
            query_embedding = await self._embedding_model.aembed_query(query)
        else:
            query_embedding = None

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: self._hybrid_search_sync(query, query_embedding, n_results),
        )

        return results

    # ── 文档入库 ────────────────────────────────────────────────

    async def existing_ids(self) -> set[str]:
        """返回集合中已存在的全部文档 ID（md5(content)）。"""
        self._ensure_client()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: self._collection.get(include=[])
        )
        return set(result.get("ids", []))

    async def add_documents(self, documents: list[dict[str, Any]]) -> int:
        """添加文档到 ChromaDB。添加后使 BM25 索引缓存失效。"""
        self._ensure_client()

        if not documents:
            return 0

        contents = [doc.get("content", "") for doc in documents]

        embeddings: list[list[float]] | None = None
        if self._embedding_model:
            embeddings = await self._embedding_model.aembed_documents(contents)
        else:
            logger.warning("未注入 embedding 模型，回退 ChromaDB 默认嵌入")

        loop = asyncio.get_running_loop()
        count = await loop.run_in_executor(
            None,
            lambda: self._batch_add(documents, embeddings),
        )

        if count > 0:
            self._bm25_index = None
            self._bm25_corpus = []

        logger.info("ChromaDB 添加 %d 条文档", count)
        return count

    def _batch_add(
        self,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]] | None = None,
    ) -> int:
        """批量添加文档（在线程池中运行）。"""
        ids = []
        contents = []
        metadatas = []

        for doc in documents:
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            doc_id = hashlib.md5(content.encode()).hexdigest()
            ids.append(doc_id)
            contents.append(content)
            metadatas.append(metadata)

        try:
            kwargs: dict[str, Any] = {
                "ids": ids,
                "documents": contents,
                "metadatas": metadatas,
            }
            if embeddings is not None:
                kwargs["embeddings"] = embeddings
            self._collection.upsert(**kwargs)
            return len(documents)
        except Exception as e:
            logger.error("ChromaDB 批量添加失败: %s", e)
            return 0
