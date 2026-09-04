"""RetrievalGrader 测试。"""

import pytest

from app.xuantong.rag.grader import RetrievalGrader
from app.xuantong.rag.models import GradeResult


class TestRetrievalGrader:
    """测试检索结果评分器。"""

    @pytest.fixture
    def grader(self):
        """无 LLM 的评分器（使用规则降级）。"""
        return RetrievalGrader(llm_runtime=None)

    @pytest.mark.asyncio
    async def test_relevant_document(self, grader: RetrievalGrader):
        """相关文档评分为 relevant。"""
        query = "高血压 降压治疗"
        document = "高血压患者需要长期服用降压药物，常用的降压药包括 ACEI、ARB、CCB 等。"

        result = await grader.grade(query, document)

        assert isinstance(result, GradeResult)
        assert result.relevant is True
        assert result.score > 0.3

    @pytest.mark.asyncio
    async def test_irrelevant_document(self, grader: RetrievalGrader):
        """不相关文档评分为 not relevant。"""
        query = "高血压 降压治疗"
        document = "今天天气很好，适合出去散步。"

        result = await grader.grade(query, document)

        assert isinstance(result, GradeResult)
        assert result.relevant is False
        assert result.score < 0.3

    @pytest.mark.asyncio
    async def test_empty_document(self, grader: RetrievalGrader):
        """空文档评分为 not relevant。"""
        query = "高血压"
        document = ""

        result = await grader.grade(query, document)

        assert result.relevant is False
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_batch_grading(self, grader: RetrievalGrader):
        """批量评分。"""
        query = "糖尿病 血糖控制"
        documents = [
            "糖尿病患者需要定期监测血糖，控制饮食。",
            "高血压的治疗方法是服用降压药。",
            "二甲双胍是治疗糖尿病的一线用药。",
        ]

        results = await grader.grade_batch(query, documents)

        assert len(results) == 3
        assert all(isinstance(r, GradeResult) for r in results)
        # 第一个和第三个文档应该更相关
        assert results[0].score > results[1].score or results[2].score > results[1].score

    @pytest.mark.asyncio
    async def test_rule_based_grade(self, grader: RetrievalGrader):
        """规则降级评分。"""
        query = "高血压 降压"
        document = "高血压患者需要降压治疗，常用药物有氨氯地平。"

        result = grader._rule_based_grade(query, document)

        assert result.relevant is True
        assert result.score > 0.3
        assert "命中率" in result.reason
