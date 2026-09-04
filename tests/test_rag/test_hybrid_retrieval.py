"""混合检索 + 重排测试。

测试 BM25 检索、RRF 融合、规则重排器、检索+重排完整流程。
"""

import pytest

from app.xuantong.rag.knowledge_base import KnowledgeBase
from app.xuantong.rag.models import RetrievalResult
from app.xuantong.rag.reranker import RuleBasedReranker
from app.xuantong.rag.retriever import RAGRetriever


class TestBM25Search:
    """BM25 检索基本功能。"""

    @pytest.fixture
    def kb_with_docs(self) -> KnowledgeBase:
        """含文档的知识库。"""
        kb = KnowledgeBase()
        return kb

    @pytest.mark.asyncio
    async def test_bm25_search(self, kb_with_docs: KnowledgeBase):
        """BM25 检索基本功能 — 能找到包含查询关键词的文档。"""
        await kb_with_docs.add_document(
            "高血压患者需要长期服用降压药物，常用的降压药包括 ACEI、ARB、CCB 等。",
            metadata={"source": "hypertension.md"},
        )
        await kb_with_docs.add_document(
            "糖尿病患者需要控制饮食和运动，定期监测血糖。",
            metadata={"source": "diabetes.md"},
        )
        await kb_with_docs.add_document(
            "感冒是一种常见的呼吸道疾病，症状包括咳嗽、流涕、发热等。",
            metadata={"source": "cold.md"},
        )

        results = await kb_with_docs.hybrid_search("高血压 降压")

        assert len(results) >= 1
        assert any("高血压" in r.content for r in results)
        assert results[0].bm25_score != 0.0

    @pytest.mark.asyncio
    async def test_bm25_character_tokenization(self, kb_with_docs: KnowledgeBase):
        """BM25 使用字符级分词，中文单字也能匹配。"""
        await kb_with_docs.add_document("黄帝内经素问记载：上古之人，春秋皆度百岁")

        results = await kb_with_docs.hybrid_search("黄帝")
        assert len(results) >= 1
        assert "黄帝" in results[0].content


class TestHybridSearch:
    """混合检索（BM25-only 模式）测试。"""

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_results(self):
        """hybrid_search 在 BM25-only 模式下正常返回。"""
        kb = KnowledgeBase()
        await kb.add_document("高血压治疗方案包括药物治疗和非药物治疗")
        await kb.add_document("糖尿病饮食指南：控制碳水化合物摄入")

        results = await kb.hybrid_search("高血压治疗")
        assert len(results) >= 1
        assert any("高血压" in r.content for r in results)

    @pytest.mark.asyncio
    async def test_hybrid_search_score_normalized(self):
        """hybrid_search 返回的 score 在 0-1 范围内。"""
        kb = KnowledgeBase()
        await kb.add_document("高血压高血压高血压")  # 高频词
        await kb.add_document("普通文档内容")

        results = await kb.hybrid_search("高血压")
        for r in results:
            assert 0.0 <= r.score <= 1.0

    @pytest.mark.asyncio
    async def test_hybrid_search_empty_query(self):
        """空查询返回空结果。"""
        kb = KnowledgeBase()
        await kb.add_document("测试文档")

        results = await kb.hybrid_search("")
        assert results == []

    @pytest.mark.asyncio
    async def test_hybrid_search_empty_kb(self):
        """空知识库返回空结果。"""
        kb = KnowledgeBase()
        results = await kb.hybrid_search("测试")
        assert results == []


class TestRRFFusion:
    """RRF 融合分数计算测试。"""

    def test_rrf_fusion_single_source(self):
        """单路排名时 RRF 分数正确计算。"""
        from app.xuantong.rag.chroma_retriever import ChromaRAGClient

        # 模拟：只有 BM25 结果
        bm25_results = [
            ("文档A", {"source": "a.md"}, 0.9),
            ("文档B", {"source": "b.md"}, 0.7),
            ("文档C", {"source": "c.md"}, 0.5),
        ]

        fused = ChromaRAGClient._rrf_fuse(
            vector_results=[],
            bm25_results=bm25_results,
            n_results=3,
            k=60,
        )

        assert len(fused) == 3
        # 排名越高 RRF 分数越高
        assert fused[0].score >= fused[1].score >= fused[2].score
        # 第一个文档的 RRF 原始分 = 1/(60+1) = 0.01639...
        # 归一化 = 0.01639 / (2/(60+1)) = 0.01639 / 0.03279 ≈ 0.5
        assert fused[0].score > 0

    def test_rrf_fusion_two_sources(self):
        """两路排名时 RRF 融合正确。"""
        from app.xuantong.rag.chroma_retriever import ChromaRAGClient

        vector_results = [
            RetrievalResult(content="文档A", source="a.md", score=0.9, vector_score=0.9),
            RetrievalResult(content="文档B", source="b.md", score=0.7, vector_score=0.7),
        ]
        bm25_results = [
            ("文档B", {"source": "b.md"}, 0.95),  # BM25 排第一
            ("文档A", {"source": "a.md"}, 0.8),   # BM25 排第二
        ]

        fused = ChromaRAGClient._rrf_fuse(
            vector_results=vector_results,
            bm25_results=bm25_results,
            n_results=2,
            k=60,
        )

        assert len(fused) == 2
        # 文档B: 向量 rank=2 → 1/(60+2), BM25 rank=1 → 1/(60+1)
        # 文档A: 向量 rank=1 → 1/(60+1), BM25 rank=2 → 1/(60+2)
        # 两者 RRF 原始分相同 → 归一化后也相同
        assert abs(fused[0].score - fused[1].score) < 0.01

    def test_rrf_fusion_dedup(self):
        """RRF 融合自动去重。"""
        from app.xuantong.rag.chroma_retriever import ChromaRAGClient

        vector_results = [
            RetrievalResult(content="相同文档", source="a.md", score=0.9, vector_score=0.9),
        ]
        bm25_results = [
            ("相同文档", {"source": "a.md"}, 0.8),
        ]

        fused = ChromaRAGClient._rrf_fuse(
            vector_results=vector_results,
            bm25_results=bm25_results,
            n_results=5,
        )

        # 相同文档只出现一次
        assert len(fused) == 1
        assert fused[0].content == "相同文档"


class TestRuleBasedReranker:
    """规则重排器测试。"""

    @pytest.mark.asyncio
    async def test_rule_based_reranker_basic(self):
        """规则重排器按关键词重叠度排序。"""
        reranker = RuleBasedReranker()
        docs = [
            RetrievalResult(content="完全不相关的文档内容"),
            RetrievalResult(content="高血压患者需要降压治疗"),
            RetrievalResult(content="一些普通内容"),
        ]

        results = await reranker.rerank("高血压 降压", docs, top_k=2)

        assert len(results) == 2
        # 包含"高血压"和"降压"的文档应排在前面
        assert "高血压" in results[0].content

    @pytest.mark.asyncio
    async def test_rule_based_reranker_empty(self):
        """空文档列表返回空。"""
        reranker = RuleBasedReranker()
        results = await reranker.rerank("测试", [], top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_rule_based_reranker_sets_score(self):
        """重排器设置 rerank_score。"""
        reranker = RuleBasedReranker()
        docs = [
            RetrievalResult(content="高血压治疗指南"),
        ]

        results = await reranker.rerank("高血压", docs, top_k=1)
        assert results[0].rerank_score > 0


class TestRetrieverWithRerank:
    """检索 + 重排完整流程测试。"""

    @pytest.mark.asyncio
    async def test_retriever_with_rerank(self):
        """RAGRetriever 集成重排器完整流程。"""
        kb = KnowledgeBase()
        await kb.add_document("高血压患者需要长期服用降压药物")
        await kb.add_document("糖尿病饮食控制指南")
        await kb.add_document("高血压降压药包括ACEI和ARB")

        retriever = RAGRetriever(knowledge_base=kb)
        results = await retriever.retrieve("高血压 降压", top_k=2, use_rerank=True)

        assert len(results) <= 2
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_retriever_without_rerank(self):
        """RAGRetriever 关闭重排也能工作。"""
        kb = KnowledgeBase()
        await kb.add_document("高血压患者需要长期服用降压药物")

        retriever = RAGRetriever(knowledge_base=kb)
        results = await retriever.retrieve("高血压", top_k=5, use_rerank=False)

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_hybrid_retrieve(self):
        """hybrid_retrieve 方法正常工作。"""
        kb = KnowledgeBase()
        await kb.add_document("高血压治疗方案")
        await kb.add_document("糖尿病饮食指南")

        retriever = RAGRetriever(knowledge_base=kb)
        results = await retriever.hybrid_retrieve("高血压", top_k=3)

        assert len(results) >= 1


class TestEdgeCases:
    """边界情况测试。"""

    @pytest.mark.asyncio
    async def test_empty_query(self):
        """空查询不崩溃。"""
        kb = KnowledgeBase()
        await kb.add_document("测试文档")
        results = await kb.hybrid_search("   ")
        assert results == []

    @pytest.mark.asyncio
    async def test_no_documents(self):
        """无文档时不崩溃。"""
        kb = KnowledgeBase()
        results = await kb.hybrid_search("测试查询")
        assert results == []

    @pytest.mark.asyncio
    async def test_single_char_query(self):
        """单字查询能工作。"""
        kb = KnowledgeBase()
        await kb.add_document("高血压是一种常见的慢性病")
        results = await kb.hybrid_search("高")
        assert len(results) >= 1
