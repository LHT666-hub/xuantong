"""知识库管理 — 文档加载、索引与搜索。

支持 BM25 检索（字符级分词，适配中文）；
后续可接入 pgvector 做向量检索，实现真正的混合检索。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from app.xuantong.rag.audience_filter import AudienceFilter
from app.xuantong.rag.models import RetrievalResult

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """内存知识库 — 支持从目录加载文档并按 BM25 检索。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self._documents: list[dict[str, Any]] = []
        self._bm25_index = None
        self.data_dir = data_dir

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
        """BM25 混合检索（字符级分词）。

        当前阶段仅用 BM25；后续接入向量检索后，
        在此合并两路结果并按 RRF 融合。
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

    # ── 内部 ──────────────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简易分词：按空格和标点拆分，过滤空串，转小写。"""
        parts = re.split(r"[\s,，。、；：！？]+", text)
        return [p.strip().lower() for p in parts if p and len(p.strip()) >= 1]

    @property
    def document_count(self) -> int:
        return len(self._documents)
