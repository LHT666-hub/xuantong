"""RAGEvaluationLoop 测试。"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.xuantong.rag.models import GradeResult, RAGResult, RetrievalResult
from app.xuantong.rag.rag_loop import RAGEvaluationLoop
from app.xuantong.rag.retriever import RAGRetriever
from app.xuantong.rag.grader import RetrievalGrader
from app.xuantong.rag.query_rewriter import QueryRewriter


class TestRAGEvaluationLoop:
    """测试 RAG 评估环路。"""

    @pytest.fixture
    def mock_retriever(self):
        """Mock 检索器。"""
        retriever = MagicMock(spec=RAGRetriever)
        return retriever

    @pytest.fixture
    def mock_grader(self):
        """Mock 评分器。"""
        grader = MagicMock(spec=RetrievalGrader)
        return grader

    @pytest.fixture
    def mock_rewriter(self):
        """Mock 重写器。"""
        rewriter = MagicMock(spec=QueryRewriter)
        return rewriter

    @pytest.mark.asyncio
    async def test_first_attempt_success(
        self, mock_retriever, mock_grader, mock_rewriter
    ):
        """第一次检索就成功。"""
        # 设置 mock 返回
        mock_retriever.retrieve = AsyncMock(return_value=[
            RetrievalResult(content="高血压治疗指南", source="test.md", score=0.9),
        ])
        mock_grader.grade_batch = AsyncMock(return_value=[
            GradeResult(relevant=True, score=0.9, reason="直接相关"),
        ])

        loop = RAGEvaluationLoop(
            retriever=mock_retriever,
            grader=mock_grader,
            rewriter=mock_rewriter,
            max_retries=3,
        )

        result = await loop.run("高血压")

        assert result.success is True
        assert result.attempts == 1
        assert len(result.documents) == 1
        mock_rewriter.rewrite.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_then_success(
        self, mock_retriever, mock_grader, mock_rewriter
    ):
        """重试后成功。"""
        # 第一次返回不相关结果
        # 第二次返回相关结果
        mock_retriever.retrieve = AsyncMock(side_effect=[
            [RetrievalResult(content="天气很好", source="weather.md", score=0.1)],
            [RetrievalResult(content="高血压治疗指南", source="test.md", score=0.9)],
        ])
        mock_grader.grade_batch = AsyncMock(side_effect=[
            [GradeResult(relevant=False, score=0.1, reason="无关")],
            [GradeResult(relevant=True, score=0.9, reason="直接相关")],
        ])
        mock_rewriter.rewrite = AsyncMock(return_value="高血压 降压治疗")

        loop = RAGEvaluationLoop(
            retriever=mock_retriever,
            grader=mock_grader,
            rewriter=mock_rewriter,
            max_retries=3,
        )

        result = await loop.run("血压高")

        assert result.success is True
        assert result.attempts == 2
        mock_rewriter.rewrite.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(
        self, mock_retriever, mock_grader, mock_rewriter
    ):
        """达到最大重试次数。"""
        # 所有检索都返回不相关结果
        mock_retriever.retrieve = AsyncMock(return_value=[
            RetrievalResult(content="无关内容", source="test.md", score=0.1),
        ])
        mock_grader.grade_batch = AsyncMock(return_value=[
            GradeResult(relevant=False, score=0.1, reason="无关"),
        ])
        mock_rewriter.rewrite = AsyncMock(return_value="重写后的查询")

        loop = RAGEvaluationLoop(
            retriever=mock_retriever,
            grader=mock_grader,
            rewriter=mock_rewriter,
            max_retries=3,
        )

        result = await loop.run("测试查询")

        assert result.success is False
        assert result.attempts == 3
        assert len(result.documents) == 0

    @pytest.mark.asyncio
    async def test_empty_query(
        self, mock_retriever, mock_grader, mock_rewriter
    ):
        """空查询处理。"""
        loop = RAGEvaluationLoop(
            retriever=mock_retriever,
            grader=mock_grader,
            rewriter=mock_rewriter,
            max_retries=3,
        )

        result = await loop.run("")

        assert result.success is False
        assert result.attempts == 0
        assert len(result.documents) == 0
        mock_retriever.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_results_then_rewrite(
        self, mock_retriever, mock_grader, mock_rewriter
    ):
        """空检索结果触发重写。"""
        mock_retriever.retrieve = AsyncMock(side_effect=[
            [],  # 第一次空
            [RetrievalResult(content="高血压指南", source="test.md", score=0.8)],
        ])
        mock_grader.grade_batch = AsyncMock(return_value=[
            GradeResult(relevant=True, score=0.8, reason="相关"),
        ])
        mock_rewriter.rewrite = AsyncMock(return_value="高血压 降压")

        loop = RAGEvaluationLoop(
            retriever=mock_retriever,
            grader=mock_grader,
            rewriter=mock_rewriter,
            max_retries=3,
        )

        result = await loop.run("血压高")

        assert result.success is True
        assert result.attempts == 2
        mock_rewriter.rewrite.assert_called_once()
