"""知识库管理 — 文档加载、索引与搜索。

当前阶段使用内存关键词索引；后续可接入 pgvector 做向量检索。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.xuantong.rag.models import RetrievalResult

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """内存知识库 — 支持从目录加载 Markdown 文档并按关键词检索。"""

    def __init__(self) -> None:
        self._documents: list[dict[str, Any]] = []

    # ── 文档管理 ─────────────────────────────────────────────

    async def add_document(self, content: str, metadata: dict | None = None) -> None:
        """添加单条文档。"""
        self._documents.append({
            "content": content,
            "metadata": metadata or {},
        })
        logger.info("知识库: 添加文档 (metadata=%s)", metadata)

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

    # ── 检索 ──────────────────────────────────────────────────

    async def search(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        """基于关键词匹配的简单检索。

        将 query 拆分为词元（按空格/标点），统计每篇文档命中词元数，
        以命中率作为 score 排序返回。
        """
        if not self._documents or not query.strip():
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self._documents:
            content_lower = doc["content"].lower()
            hits = sum(1 for t in tokens if t in content_lower)
            if hits > 0:
                score = hits / len(tokens)
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[RetrievalResult] = []
        for score, doc in scored[:top_k]:
            results.append(
                RetrievalResult(
                    content=doc["content"],
                    source=doc.get("metadata", {}).get("source", ""),
                    score=round(score, 4),
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
