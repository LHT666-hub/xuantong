"""零依赖哈希向量器 — 字符 n-gram blake2b 哈希生成固定维度向量。

定位为 sentence-transformers 的轻量级降级方案：
- 优点：零外部依赖（纯 stdlib：hashlib + math）、确定性可复现、速度快
- 局限：基于字符而非语义，对同义词/近义词召回能力弱
- 升级路径：安装 sentence-transformers 后可切换为真实 embedding

移植自 medharness/mcp/vector-db/server.py 的哈希向量器实现。
"""

from __future__ import annotations

import hashlib
import math
import re


class HashingVectorizer:
    """字符 n-gram blake2b 哈希向量器。

    将任意文本映射为固定维度的 L2 归一化稠密向量：
    1. 归一化文本（折叠空白、转小写、保留 CJK）
    2. 切分为字符 n-gram
    3. 每个 n-gram 用 blake2b 哈希 → 落到某个维度桶并累加带符号计数
    4. L2 归一化

    相同输入永远得到相同输出（确定性），无需任何模型或训练。
    """

    def __init__(self, dim: int = 256, ngram: int = 3) -> None:
        """
        Args:
            dim: 输出向量维度。
            ngram: 字符 n-gram 的 n 值。
        """
        if dim <= 0:
            raise ValueError("dim 必须为正整数")
        if ngram <= 0:
            raise ValueError("ngram 必须为正整数")
        self.dim = dim
        self.ngram = ngram

    # ── 内部工具 ────────────────────────────────────────────────

    @staticmethod
    def _normalize_text(text: str) -> str:
        """折叠空白、统一小写；保留 CJK。"""
        return re.sub(r"\s+", " ", text.lower()).strip()

    def _ngrams(self, text: str) -> list[str]:
        """字符 n-gram 切分。文本短于 n 时返回整段。"""
        text = self._normalize_text(text)
        if not text:
            return []
        n = self.ngram
        if len(text) < n:
            return [text]
        return [text[i : i + n] for i in range(len(text) - n + 1)]

    # ── 公开接口 ────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """文本 → L2 归一化向量（长度 = self.dim）。"""
        vec = [0.0] * self.dim
        for gram in self._ngrams(text):
            h = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            # 用第 5 字节最低位决定 ±，降低哈希碰撞带来的系统性偏置
            sign = 1.0 if (h[4] & 1) == 0 else -1.0
            vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入 — 与逐条 embed 结果完全一致。"""
        return [self.embed(t) for t in texts]

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """余弦相似度。

        两向量若均已 L2 归一化，点积即余弦相似度；
        否则按定义做完整归一化，保证对任意输入都正确。
        """
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
