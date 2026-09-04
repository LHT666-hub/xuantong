"""QueryRewriter 测试。"""

import pytest

from app.xuantong.rag.query_rewriter import QueryRewriter
from app.xuantong.rag.models import RetrievalResult


class TestQueryRewriter:
    """测试查询重写器。"""

    @pytest.fixture
    def rewriter(self):
        """无 LLM 的重写器（使用规则降级）。"""
        return QueryRewriter(llm_runtime=None)

    @pytest.mark.asyncio
    async def test_rewrite_improves_query(self, rewriter: QueryRewriter):
        """重写后查询更具体。"""
        original = "血压高怎么办"
        failed_results = [
            RetrievalResult(content="今天天气很好", source="weather.md", score=0.1),
        ]

        rewritten = await rewriter.rewrite(original, failed_results)

        assert rewritten != original
        assert len(rewritten) > 0
        # 规则降级会扩展同义词
        assert "高血压" in rewritten or "血压" in rewritten

    @pytest.mark.asyncio
    async def test_rewrite_preserves_intent(self, rewriter: QueryRewriter):
        """重写保留原始意图。"""
        original = "高血压 降压"
        failed_results = []

        rewritten = await rewriter.rewrite(original, failed_results)

        # 重写后应该包含原始关键词或相关扩展
        assert "高血压" in rewritten or "降压" in rewritten or "血压" in rewritten

    @pytest.mark.asyncio
    async def test_rewrite_empty_query(self, rewriter: QueryRewriter):
        """空查询不重写。"""
        original = ""
        failed_results = []

        rewritten = await rewriter.rewrite(original, failed_results)

        assert rewritten == original

    @pytest.mark.asyncio
    async def test_rule_based_rewrite_with_synonyms(self, rewriter: QueryRewriter):
        """规则重写扩展同义词。"""
        query = "糖尿病血糖高"
        rewritten = rewriter._rule_based_rewrite(query)

        # 应包含糖尿病相关扩展词
        assert "糖尿病" in rewritten or "血糖" in rewritten

    @pytest.mark.asyncio
    async def test_rule_based_rewrite_default(self, rewriter: QueryRewriter):
        """规则重写默认追加管理指导词。"""
        query = "头痛"
        rewritten = rewriter._rule_based_rewrite(query)

        # 应包含同义词扩展或默认后缀
        assert len(rewritten) >= len(query)
