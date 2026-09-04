"""查询重写器 — 当检索结果不达标时重写查询以提高检索质量。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.xuantong.rag.models import RetrievalResult

logger = logging.getLogger(__name__)

_REWRITE_SYSTEM = (
    "你是一位医疗信息检索专家。当原始查询未能检索到相关文档时，"
    "你需要分析原因并重写查询，使其更精确、更专业、更容易匹配到相关知识。"
)

_REWRITE_USER_TEMPLATE = (
    "原始查询未能检索到相关文档。请分析原因并重写查询。\n\n"
    "【原始查询】\n{query}\n\n"
    "【检索到的无关文档摘要】\n{summaries}\n\n"
    "重写要求：\n"
    "1. 保留原始查询的核心意图\n"
    "2. 使用更专业的医疗术语\n"
    "3. 扩展同义词或相关概念\n"
    "4. 去除模糊或口语化的表达\n\n"
    "请直接输出重写后的查询文本，不要添加其他说明。"
)


class QueryRewriter:
    """查询重写器 — 使用 LLM 分析失败原因并生成改进的查询。"""

    def __init__(self, llm_runtime: Any = None) -> None:
        """
        Args:
            llm_runtime: LLMRuntime 实例；为 None 时使用规则降级。
        """
        self.runtime = llm_runtime

    async def rewrite(
        self,
        original_query: str,
        failed_results: list[RetrievalResult],
    ) -> str:
        """重写查询以提高检索质量。

        Args:
            original_query: 原始查询。
            failed_results: 未达标的检索结果。

        Returns:
            重写后的查询字符串。
        """
        if not original_query.strip():
            return original_query

        if self.runtime is None:
            return self._rule_based_rewrite(original_query)

        # 构造失败文档摘要
        summaries = []
        for i, r in enumerate(failed_results[:3], 1):
            snippet = r.content[:200].replace("\n", " ")
            summaries.append(f"{i}. {snippet}...")
        summary_text = "\n".join(summaries) if summaries else "（无检索结果）"

        messages = [
            {"role": "system", "content": _REWRITE_SYSTEM},
            {"role": "user", "content": _REWRITE_USER_TEMPLATE.format(
                query=original_query, summaries=summary_text
            )},
        ]

        try:
            response = await self.runtime.invoke(
                agent_role="rag_rewriter",
                messages=messages,
                temperature=0.3,
                max_tokens=200,
            )
            rewritten = response.content.strip()
            # 清理可能的引号包裹
            if rewritten.startswith('"') and rewritten.endswith('"'):
                rewritten = rewritten[1:-1]
            if rewritten:
                logger.info("查询重写: %r → %r", original_query[:60], rewritten[:60])
                return rewritten
        except Exception as e:
            logger.warning("查询重写 LLM 调用失败，降级为规则重写: %s", e)

        return self._rule_based_rewrite(original_query)

    # ── 内部 ──────────────────────────────────────────────────

    @staticmethod
    def _rule_based_rewrite(query: str) -> str:
        """规则降级重写 — 添加常见医疗同义词。"""
        # 简单的同义词扩展
        synonyms = {
            "高血压": "高血压 血压升高 降压 血压管理",
            "糖尿病": "糖尿病 血糖 降糖 血糖控制",
            "头痛": "头痛 偏头痛 头胀痛",
            "胸闷": "胸闷 胸痛 心前区不适",
            "血压高": "高血压 血压升高 降压治疗",
            "血糖高": "高血糖 糖尿病 血糖控制",
        }
        for keyword, expansion in synonyms.items():
            if keyword in query:
                return expansion

        # 默认：在查询后追加"管理 指导"
        return f"{query} 管理 指导"
