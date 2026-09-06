"""RAG 检索质量评估测试。

使用 ground truth 数据集验证检索系统的基本质量（纯检索层，不依赖 LLM）：
- recall@5：前 5 个结果中命中期望文档的比例
- keyword_hit_rate：前 5 个结果内容中期望关键词的平均命中率
- precision@5：前 5 个结果中属于期望文档的比例
- MRR：第一个命中期望文档的倒数排名均值
- audience_filter_accuracy：命中文档受众与期望受众一致的比例

评估数据集：app/xuantong/rag/data/evaluation/ground_truth.json
被测系统：KnowledgeBase.hybrid_search（BM25 + 哈希向量 RRF 融合）。

约定：
- expected_docs 中的每个标识为文档来源路径（source）的子串，命中即算匹配；
- source 路径在 Windows 下使用反斜杠，统一归一化为正斜杠后再做子串匹配。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.xuantong.rag.knowledge_base import KnowledgeBase

# data 目录与 ground truth 路径（相对本文件定位，跨平台）
DATA_DIR = Path(__file__).resolve().parents[2] / "app" / "xuantong" / "rag" / "data"
GT_PATH = DATA_DIR / "evaluation" / "ground_truth.json"

# doc_type → source 路径标记（归一化后子串匹配）
DOC_TYPE_MARKERS = {
    "guidelines": ["guideline"],
    "drugs": ["drugs/", "medication"],
    "policies": ["policies/", "public_health"],
}

TOP_K = 5


# ── 匹配工具 ────────────────────────────────────────────────────

def _norm(source: str) -> str:
    """归一化 source 路径分隔符（Windows 反斜杠 → 正斜杠）。"""
    return (source or "").replace("\\", "/")


def _is_match(source: str, expected_docs: list[str]) -> bool:
    """source 是否命中任一 expected_docs 标识。"""
    norm = _norm(source)
    return any(ed in norm for ed in expected_docs)


def _recall_hit(results, expected_docs: list[str]) -> bool:
    """前 K 结果中是否存在命中期望文档的结果。"""
    return any(_is_match(r.source, expected_docs) for r in results)


def _precision(results, expected_docs: list[str]) -> float:
    """前 K 结果中命中期望文档的比例。"""
    if not results:
        return 0.0
    hits = sum(1 for r in results if _is_match(r.source, expected_docs))
    return hits / len(results)


def _keyword_rate(results, keywords: list[str]) -> float:
    """期望关键词在前 K 结果合并内容中的命中比例。"""
    if not keywords:
        return 0.0
    text = "\n".join(r.content for r in results)
    hits = sum(1 for kw in keywords if kw in text)
    return hits / len(keywords)


def _first_match_rank(results, expected_docs: list[str]) -> int | None:
    """第一个命中期望文档的排名（1-based），未命中返回 None。"""
    for i, r in enumerate(results, start=1):
        if _is_match(r.source, expected_docs):
            return i
    return None


# ── fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def knowledge_base() -> KnowledgeBase:
    """加载完整知识库（data/ 下全部 .md，向量检索开启）。"""
    kb = KnowledgeBase(vector_enabled=True)
    loaded = asyncio.run(kb.load_from_directory(str(DATA_DIR)))
    assert loaded >= 16, f"知识库文档数不足: {loaded}"
    return kb


@pytest.fixture(scope="module")
def ground_truth() -> list[dict]:
    """加载评估数据集。"""
    assert GT_PATH.exists(), f"ground truth 不存在: {GT_PATH}"
    return json.loads(GT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def search_results(knowledge_base, ground_truth) -> dict[str, list]:
    """对每个问题预计算 top-K 检索结果（模块级缓存，仅检索一次）。"""

    async def _run() -> dict[str, list]:
        out: dict[str, list] = {}
        for item in ground_truth:
            out[item["id"]] = await knowledge_base.hybrid_search(
                item["question"], top_k=TOP_K
            )
        return out

    return asyncio.run(_run())


# ── 测试 ────────────────────────────────────────────────────────

class TestRetrievalQuality:
    """检索质量评估（不需要 LLM，纯检索层测试）。"""

    def test_dataset_structure(self, ground_truth):
        """数据集结构完整、字段齐全、id 唯一。"""
        assert len(ground_truth) >= 30, "评估问题应不少于 30 个"
        ids = set()
        for item in ground_truth:
            for field in (
                "id", "question", "expected_keywords",
                "expected_docs", "audience", "difficulty",
                "category", "doc_type",
            ):
                assert field in item, f"{item.get('id')} 缺少字段 {field}"
            assert item["expected_keywords"], f"{item['id']} expected_keywords 为空"
            assert item["expected_docs"], f"{item['id']} expected_docs 为空"
            assert item["id"] not in ids, f"重复 id: {item['id']}"
            ids.add(item["id"])

    def test_knowledge_base_loaded(self, knowledge_base):
        """知识库应加载全部 16 篇文档，且未误加载 evaluation/ 下的 json。"""
        assert knowledge_base.document_count == 16

    def test_recall_at_5(self, ground_truth, search_results):
        """recall@5 应 > 0.6。"""
        hits = sum(
            1 for item in ground_truth
            if _recall_hit(search_results[item["id"]], item["expected_docs"])
        )
        recall = hits / len(ground_truth)
        assert recall > 0.6, f"recall@5={recall:.2f} ({hits}/{len(ground_truth)}), expected > 0.6"

    def test_keyword_hit_rate(self, ground_truth, search_results):
        """关键词平均命中率应 > 0.5。"""
        rates = [
            _keyword_rate(search_results[item["id"]], item["expected_keywords"])
            for item in ground_truth
        ]
        hit_rate = sum(rates) / len(rates)
        assert hit_rate > 0.5, f"keyword_hit_rate={hit_rate:.2f}, expected > 0.5"

    def test_precision_at_5(self, ground_truth, search_results):
        """precision@5 应 > 0.2（top5 中期望文档占比）。"""
        precs = [
            _precision(search_results[item["id"]], item["expected_docs"])
            for item in ground_truth
        ]
        precision = sum(precs) / len(precs)
        assert precision > 0.2, f"precision@5={precision:.2f}, expected > 0.2"

    def test_mrr(self, ground_truth, search_results):
        """MRR（平均倒数排名）应 > 0.4。"""
        rr = []
        for item in ground_truth:
            rank = _first_match_rank(search_results[item["id"]], item["expected_docs"])
            rr.append(1.0 / rank if rank else 0.0)
        mrr = sum(rr) / len(rr)
        assert mrr > 0.4, f"MRR={mrr:.2f}, expected > 0.4"

    def test_audience_filter_accuracy(self, ground_truth, search_results):
        """命中文档受众与期望受众一致的比例应 > 0.5。

        对每个问题：在前 K 结果里筛出命中 expected_docs 的文档，
        若其中存在 audience == 期望 audience 的文档，则计为正确。
        """
        correct = 0
        for item in ground_truth:
            matched = [
                r for r in search_results[item["id"]]
                if _is_match(r.source, item["expected_docs"])
            ]
            if any(r.metadata.get("audience") == item["audience"] for r in matched):
                correct += 1
        accuracy = correct / len(ground_truth)
        assert accuracy > 0.5, f"audience_filter_accuracy={accuracy:.2f}, expected > 0.5"

    def test_policy_questions_hit_policy_docs(self, ground_truth, search_results):
        """政策类问题应命中政策文档（doc_type=policies 分组 recall > 0.6）。"""
        self._assert_doc_type_recall(ground_truth, search_results, "policies")

    def test_guideline_questions_hit_guideline_docs(self, ground_truth, search_results):
        """指南类问题应命中指南文档（doc_type=guidelines 分组 recall > 0.6）。"""
        self._assert_doc_type_recall(ground_truth, search_results, "guidelines")

    def test_drug_questions_hit_drug_docs(self, ground_truth, search_results):
        """药物类问题应命中药物文档（doc_type=drugs 分组 recall > 0.6）。"""
        self._assert_doc_type_recall(ground_truth, search_results, "drugs")

    # ── 内部：分组 recall 校验 ──

    @staticmethod
    def _assert_doc_type_recall(ground_truth, search_results, doc_type: str) -> None:
        """校验某 doc_type 分组：问题应命中该类型标记的文档。"""
        markers = DOC_TYPE_MARKERS[doc_type]
        items = [it for it in ground_truth if it["doc_type"] == doc_type]
        assert items, f"doc_type={doc_type} 无评估问题"

        hits = 0
        for item in items:
            results = search_results[item["id"]]
            # 命中标准：前 K 结果中存在属于该 doc_type 的文档
            if any(any(m in _norm(r.source) for m in markers) for r in results):
                hits += 1
        recall = hits / len(items)
        assert recall > 0.6, (
            f"doc_type={doc_type} 命中类型文档比例={recall:.2f} "
            f"({hits}/{len(items)}), expected > 0.6"
        )
