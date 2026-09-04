"""检索结果评分器 — LLM 判断文档与查询的相关性。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.xuantong.rag.models import GradeResult

logger = logging.getLogger(__name__)

# 评分 Prompt
_GRADE_SYSTEM = (
    "你是一位医疗知识检索评估专家。你的任务是判断检索到的文档是否包含回答查询所需的信息。"
)

_GRADE_USER_TEMPLATE = (
    "请评估以下文档与查询的相关性。\n\n"
    "【查询】\n{query}\n\n"
    "【文档】\n{document}\n\n"
    "评分标准：\n"
    "- 0.8-1.0：文档直接包含回答问题所需的核心信息\n"
    "- 0.6-0.8：文档部分相关，包含一些有用信息\n"
    "- 0.0-0.6：文档与查询关联较弱或无关\n\n"
    "请以 JSON 格式输出：\n"
    '{{"relevant": true/false, "score": 0.0-1.0, "reason": "评分理由"}}'
)


class RetrievalGrader:
    """检索结果评分器 — 使用 LLM 判断文档与查询的相关性。"""

    def __init__(self, llm_runtime: Any = None) -> None:
        """
        Args:
            llm_runtime: LLMRuntime 实例；为 None 时使用规则降级。
        """
        self.runtime = llm_runtime

    async def grade(self, query: str, document: str) -> GradeResult:
        """评估单个文档与查询的相关性。

        Args:
            query: 原始查询。
            document: 待评估文档内容。

        Returns:
            GradeResult
        """
        if not document.strip():
            return GradeResult(relevant=False, score=0.0, reason="文档为空")

        if self.runtime is None:
            return self._rule_based_grade(query, document)

        messages = [
            {"role": "system", "content": _GRADE_SYSTEM},
            {"role": "user", "content": _GRADE_USER_TEMPLATE.format(
                query=query, document=document[:2000]
            )},
        ]

        try:
            response = await self.runtime.invoke(
                agent_role="rag_grader",
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
            return self._parse_response(response.content)
        except Exception as e:
            logger.warning("评分 LLM 调用失败，降级为规则评分: %s", e)
            return self._rule_based_grade(query, document)

    async def grade_batch(
        self, query: str, documents: list[str]
    ) -> list[GradeResult]:
        """批量评分。

        逐个调用 grade()；后续可优化为并发调用。
        """
        results: list[GradeResult] = []
        for doc in documents:
            result = await self.grade(query, doc)
            results.append(result)
        return results

    # ── 内部 ──────────────────────────────────────────────────

    @staticmethod
    def _parse_response(content: str) -> GradeResult:
        """解析 LLM 返回的 JSON。"""
        # 尝试直接解析
        try:
            data = json.loads(content)
            return GradeResult(
                relevant=bool(data.get("relevant", False)),
                score=float(data.get("score", 0.0)),
                reason=str(data.get("reason", "")),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # 尝试从文本中提取 JSON 块
        match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return GradeResult(
                    relevant=bool(data.get("relevant", False)),
                    score=float(data.get("score", 0.0)),
                    reason=str(data.get("reason", "")),
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        logger.warning("无法解析评分响应: %s", content[:200])
        return GradeResult(relevant=False, score=0.0, reason="解析失败")

    @staticmethod
    def _rule_based_grade(query: str, document: str) -> GradeResult:
        """规则降级评分 — 基于关键词重叠率。"""
        query_tokens = set(re.split(r"[\s,，。、；：！？]+", query.lower()))
        query_tokens = {t for t in query_tokens if len(t) >= 2}
        if not query_tokens:
            return GradeResult(relevant=False, score=0.0, reason="查询过短")

        doc_lower = document.lower()
        hits = sum(1 for t in query_tokens if t in doc_lower)
        ratio = hits / len(query_tokens)

        return GradeResult(
            relevant=ratio >= 0.3,
            score=round(ratio, 4),
            reason=f"关键词命中率: {hits}/{len(query_tokens)}",
        )
