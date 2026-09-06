"""知识库管理 — 文档加载、索引与搜索。

支持 BM25 检索（字符级分词，适配中文）与零依赖哈希向量检索（HashingVectorizer）；
两路结果按 RRF（Reciprocal Rank Fusion）融合。向量检索可通过配置开关，
关闭或无向量时优雅降级到纯 BM25。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from app.config import Settings
from app.xuantong.rag.audience_filter import AudienceFilter
from app.xuantong.rag.hashing_vectorizer import HashingVectorizer
from app.xuantong.rag.models import RetrievalResult

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """内存知识库 — 支持从目录加载文档并按 BM25 + 向量混合检索。"""

    def __init__(
        self,
        data_dir: str | None = None,
        vector_enabled: bool | None = None,
        vector_dim: int | None = None,
        vector_ngram: int | None = None,
        rrf_k: int | None = None,
    ) -> None:
        settings = Settings()
        self._documents: list[dict[str, Any]] = []
        self._bm25_index = None
        self.data_dir = data_dir

        # 向量检索配置（构造参数优先，否则读配置）
        self._vector_enabled = (
            vector_enabled if vector_enabled is not None else settings.rag_vector_enabled
        )
        dim = vector_dim if vector_dim is not None else settings.rag_vector_dim
        ngram = vector_ngram if vector_ngram is not None else settings.rag_vector_ngram
        self._rrf_k = rrf_k if rrf_k is not None else settings.rag_rrf_k
        self._vectorizer = HashingVectorizer(dim=dim, ngram=ngram) if self._vector_enabled else None
        # 与 self._documents 一一对齐的文档向量（未启用向量时为空）
        self._vectors: list[list[float]] = []

    # ── 文档管理 ─────────────────────────────────────────────

    async def add_document(self, content: str, metadata: dict | None = None) -> None:
        """添加单条文档。

        若 metadata 中未指定 audience，自动从内容推断。
        """
        meta = dict(metadata or {})

        # 自动推断受众
        if "audience" not in meta:
            meta["audience"] = AudienceFilter.infer_audience(
                content, meta.get("source", "")
            ).value

        self._documents.append({
            "content": content,
            "metadata": meta,
        })
        # 同步计算并存储文档向量（与 _documents 索引一一对齐）
        if self._vectorizer is not None:
            self._vectors.append(self._vectorizer.embed(content))
        # 使 BM25 索引失效，下次检索时懒重建
        self._bm25_index = None
        logger.info("知识库: 添加文档 (metadata=%s)", meta)

    async def load_from_directory(self, directory: str) -> int:
        """从目录递归加载所有 .md 文件。

        Returns:
            成功加载的文档数量。
        """
        path = Path(directory)
        if not path.exists():
            logger.warning("知识库目录不存在: %s", directory)
            return 0

        count = 0
        for md_file in sorted(path.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                if text.strip():
                    await self.add_document(
                        text,
                        metadata={"source": str(md_file.relative_to(path)), "file": md_file.name},
                    )
                    count += 1
            except Exception as e:
                logger.warning("加载文档失败 %s: %s", md_file, e)

        logger.info("知识库: 从 %s 加载 %d 篇文档", directory, count)
        return count

    # ── BM25 索引 ─────────────────────────────────────────────

    def _build_bm25_index(self) -> None:
        """构建 BM25 索引（字符级分词，适配中文）。"""
        from rank_bm25 import BM25Okapi

        if not self._documents:
            self._bm25_index = None
            return

        corpus = [doc["content"] for doc in self._documents]
        tokenized = [self._tokenize_chars(doc) for doc in corpus]
        self._bm25_index = BM25Okapi(tokenized)
        logger.info("BM25 索引构建完成: %d 条文档", len(self._documents))

    @staticmethod
    def _tokenize_chars(text: str) -> list[str]:
        """字符级分词 — 过滤空白。"""
        return [ch for ch in text if ch.strip()]

    # ── 检索 ──────────────────────────────────────────────────

    async def search(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        """基于 BM25 的检索（字符级分词，适配中文）。"""
        return await self.hybrid_search(query, top_k=top_k)

    async def hybrid_search(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        """混合检索（BM25 + 零依赖哈希向量，RRF 融合）。

        流程：
        1. BM25 字符级检索（字符分词，适配中文）
        2. 向量检索（启用且已有文档向量时）：查询向量 vs 文档向量余弦相似度
        3. RRF 融合两路排名：score = sum(1 / (k + rank_i))

        向量未启用或无向量（0 文档）时优雅降级到纯 BM25。
        """
        if not self._documents or not query.strip():
            return []

        # 懒构建 BM25 索引
        if self._bm25_index is None:
            self._build_bm25_index()
        if self._bm25_index is None:
            return []

        tokenized_query = self._tokenize_chars(query)
        if not tokenized_query:
            return []

        scores = self._bm25_index.get_scores(tokenized_query)

        # 向量检索是否可用（启用 + 向量与文档数量对齐 + 非空）
        vector_active = (
            self._vectorizer is not None
            and len(self._vectors) == len(self._documents)
            and len(self._documents) > 0
        )

        if vector_active:
            return self._hybrid_rrf(query, scores, top_k)
        return self._bm25_only(scores, top_k)

    def _bm25_only(self, scores: Any, top_k: int) -> list[RetrievalResult]:
        """纯 BM25 检索 — 保留小语料 min-max 归一化逻辑（不过滤 score<=0）。"""
        # 取 top_k * 3 候选（为后续重排留余量）
        candidate_k = min(top_k * 3, len(self._documents))
        top_indices = np.argsort(scores)[::-1][:candidate_k]

        # min-max 归一化（BM25 分数可能为负，小语料场景常见）
        max_score = float(max(scores)) if len(scores) > 0 else 0.0
        min_score = float(min(scores)) if len(scores) > 0 else 0.0
        score_range = max_score - min_score

        results: list[RetrievalResult] = []
        for idx in top_indices:
            # 跳过完全无匹配（分数等于全局最小值且为负）
            if score_range > 0 and scores[idx] == min_score and min_score < 0:
                continue
            doc = self._documents[idx]
            # 归一化到 0-1
            if score_range > 0:
                norm_score = (float(scores[idx]) - min_score) / score_range
            elif max_score > 0:
                norm_score = 1.0
            else:
                norm_score = 0.0
            results.append(
                RetrievalResult(
                    content=doc["content"],
                    source=doc.get("metadata", {}).get("source", ""),
                    score=round(norm_score, 4),
                    bm25_score=float(scores[idx]),
                    metadata=doc.get("metadata", {}),
                )
            )

        return results[:top_k]

    def _hybrid_rrf(self, query: str, bm25_scores: Any, top_k: int) -> list[RetrievalResult]:
        """BM25 + 向量两路排名做 RRF 融合。

        rrf_score(d) = sum(1 / (k + rank_i(d)))，归一化除以理论最大值 2/(k+1)。
        """
        n_docs = len(self._documents)
        candidate_k = min(max(top_k * 3, top_k), n_docs)
        k = self._rrf_k

        # ── BM25 排名（降序）──
        bm25_order = np.argsort(bm25_scores)[::-1][:candidate_k]
        # ── 向量排名：查询向量 vs 所有文档向量的余弦相似度（降序）──
        assert self._vectorizer is not None
        query_vec = self._vectorizer.embed(query)
        cos_scores = [
            self._vectorizer.cosine_similarity(query_vec, self._vectors[i])
            for i in range(n_docs)
        ]
        vector_order = sorted(range(n_docs), key=lambda i: cos_scores[i], reverse=True)[:candidate_k]

        # ── RRF 累加（rank 从 1 开始）──
        rrf: dict[int, float] = {}
        for rank, idx in enumerate((int(i) for i in bm25_order), start=1):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (k + rank)
        for rank, idx in enumerate(vector_order, start=1):
            rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (k + rank)

        # 归一化：理论最大值 = 2/(k+1)（两路均排第一）
        max_possible = 2.0 / (k + 1)
        sorted_indices = sorted(rrf.keys(), key=lambda i: rrf[i], reverse=True)

        results: list[RetrievalResult] = []
        for idx in sorted_indices[:top_k]:
            doc = self._documents[idx]
            results.append(
                RetrievalResult(
                    content=doc["content"],
                    source=doc.get("metadata", {}).get("source", ""),
                    score=round(rrf[idx] / max_possible, 4),
                    bm25_score=float(bm25_scores[idx]),
                    vector_score=round(float(cos_scores[idx]), 4),
                    metadata=doc.get("metadata", {}),
                )
            )

        return results

    # ── 内部 ──────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简易分词：按空格和标点拆分，过滤空串，转小写。"""
        parts = re.split(r"[\s,，。、；：！？]+", text)
        return [p.strip().lower() for p in parts if p and len(p.strip()) >= 1]

    @property
    def document_count(self) -> int:
        return len(self._documents)
