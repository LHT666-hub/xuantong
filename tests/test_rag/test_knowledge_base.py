"""KnowledgeBase 测试。"""

import os
import tempfile
import pytest

from app.xuantong.rag.knowledge_base import KnowledgeBase
from app.xuantong.rag.models import RetrievalResult


class TestKnowledgeBase:
    """测试知识库管理。"""

    @pytest.fixture
    def kb(self):
        """空知识库。"""
        return KnowledgeBase()

    @pytest.mark.asyncio
    async def test_add_and_search(self, kb: KnowledgeBase):
        """添加文档后能搜索到。"""
        await kb.add_document(
            "高血压患者需要长期服用降压药物，常用的降压药包括 ACEI、ARB、CCB 等。",
            metadata={"source": "hypertension.md"},
        )
        await kb.add_document(
            "糖尿病患者需要控制饮食和运动，定期监测血糖。",
            metadata={"source": "diabetes.md"},
        )

        results = await kb.search("高血压 降压药")

        assert len(results) >= 1
        assert any("高血压" in r.content for r in results)
        assert results[0].score > 0

    @pytest.mark.asyncio
    async def test_search_empty_query(self, kb: KnowledgeBase):
        """空查询返回空结果。"""
        await kb.add_document("测试文档内容")

        results = await kb.search("")

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_empty_kb(self, kb: KnowledgeBase):
        """空知识库返回空结果。"""
        results = await kb.search("高血压")

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_load_from_directory(self, kb: KnowledgeBase):
        """从目录加载文档。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试文件
            test_file = os.path.join(tmpdir, "test.md")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("# 测试文档\n\n这是测试内容。")

            count = await kb.load_from_directory(tmpdir)

            assert count == 1
            assert kb.document_count == 1

    @pytest.mark.asyncio
    async def test_load_from_nonexistent_directory(self, kb: KnowledgeBase):
        """从不存在的目录加载返回 0。"""
        count = await kb.load_from_directory("/nonexistent/path")

        assert count == 0
        assert kb.document_count == 0

    @pytest.mark.asyncio
    async def test_search_with_top_k(self, kb: KnowledgeBase):
        """限制返回数量。"""
        for i in range(10):
            await kb.add_document(f"文档 {i}: 高血压相关内容")

        results = await kb.search("高血压", top_k=3)

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_relevance_ranking(self, kb: KnowledgeBase):
        """搜索结果按相关性排序。"""
        await kb.add_document("高血压 降压药 ACEI ARB")  # 高相关
        await kb.add_document("糖尿病 血糖控制")  # 低相关
        await kb.add_document("高血压 治疗 降压")  # 高相关

        results = await kb.search("高血压 降压")

        assert len(results) >= 2
        # 包含更多关键词的文档应该排在前面
        assert results[0].score >= results[-1].score

    @pytest.mark.asyncio
    async def test_document_count(self, kb: KnowledgeBase):
        """文档计数。"""
        assert kb.document_count == 0

        await kb.add_document("文档1")
        assert kb.document_count == 1

        await kb.add_document("文档2")
        assert kb.document_count == 2
