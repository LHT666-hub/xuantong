"""RAG 检索质量独立评估脚本。

加载 app/xuantong/rag/data/ 下的全部 .md 文档，运行 ground truth 中的所有问题，
计算检索质量指标并按类别分组输出格式化报告。不依赖 LLM，仅评估检索层。

指标：
- recall@5     ：前 5 结果中命中期望文档的问题比例
- precision@5  ：前 5 结果中期望文档占比的均值
- MRR          ：第一个命中期望文档的倒数排名均值
- keyword_hit  ：期望关键词在前 5 结果内容中的平均命中率
- audience_acc ：命中文档受众与期望受众一致的问题比例

用法：
    python scripts/evaluate_rag.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

# 将项目根目录加入 sys.path，使 `import app` 可用（脚本从根目录运行）
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.xuantong.rag.knowledge_base import KnowledgeBase  # noqa: E402

DATA_DIR = ROOT / "app" / "xuantong" / "rag" / "data"
GT_PATH = DATA_DIR / "evaluation" / "ground_truth.json"
TOP_K = 5


# ── 匹配工具 ────────────────────────────────────────────────────

def _norm(source: str) -> str:
    return (source or "").replace("\\", "/")


def _is_match(source: str, expected_docs: list[str]) -> bool:
    norm = _norm(source)
    return any(ed in norm for ed in expected_docs)


def _recall_hit(results, expected_docs: list[str]) -> bool:
    return any(_is_match(r.source, expected_docs) for r in results)


def _precision(results, expected_docs: list[str]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if _is_match(r.source, expected_docs)) / len(results)


def _keyword_rate(results, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    text = "\n".join(r.content for r in results)
    return sum(1 for kw in keywords if kw in text) / len(keywords)


def _first_match_rank(results, expected_docs: list[str]) -> int | None:
    for i, r in enumerate(results, start=1):
        if _is_match(r.source, expected_docs):
            return i
    return None


def _audience_ok(results, expected_docs: list[str], audience: str) -> bool:
    matched = [r for r in results if _is_match(r.source, expected_docs)]
    return any(r.metadata.get("audience") == audience for r in matched)


# ── 指标聚合 ────────────────────────────────────────────────────

class Metrics:
    """一组问题的指标累加器。"""

    def __init__(self) -> None:
        self.n = 0
        self.recall_hits = 0
        self.precision_sum = 0.0
        self.rr_sum = 0.0
        self.keyword_sum = 0.0
        self.audience_hits = 0

    def add(self, recall, precision, rr, keyword, audience_ok) -> None:
        self.n += 1
        self.recall_hits += int(recall)
        self.precision_sum += precision
        self.rr_sum += rr
        self.keyword_sum += keyword
        self.audience_hits += int(audience_ok)

    @property
    def recall(self) -> float:
        return self.recall_hits / self.n if self.n else 0.0

    @property
    def precision(self) -> float:
        return self.precision_sum / self.n if self.n else 0.0

    @property
    def mrr(self) -> float:
        return self.rr_sum / self.n if self.n else 0.0

    @property
    def keyword(self) -> float:
        return self.keyword_sum / self.n if self.n else 0.0

    @property
    def audience(self) -> float:
        return self.audience_hits / self.n if self.n else 0.0


# ── 主流程 ──────────────────────────────────────────────────────

async def evaluate() -> int:
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))

    kb = KnowledgeBase(vector_enabled=True)
    loaded = await kb.load_from_directory(str(DATA_DIR))

    overall = Metrics()
    by_doc_type: dict[str, Metrics] = defaultdict(Metrics)
    by_category: dict[str, Metrics] = defaultdict(Metrics)
    by_difficulty: dict[str, Metrics] = defaultdict(Metrics)
    failures: list[tuple[str, str, list[str]]] = []

    for item in gt:
        results = await kb.hybrid_search(item["question"], top_k=TOP_K)
        exp = item["expected_docs"]

        recall = _recall_hit(results, exp)
        precision = _precision(results, exp)
        rank = _first_match_rank(results, exp)
        rr = 1.0 / rank if rank else 0.0
        keyword = _keyword_rate(results, item["expected_keywords"])
        audience_ok = _audience_ok(results, exp, item["audience"])

        for acc in (overall, by_doc_type[item["doc_type"]],
                    by_category[item["category"]], by_difficulty[item["difficulty"]]):
            acc.add(recall, precision, rr, keyword, audience_ok)

        if not recall:
            got = [_norm(r.source) for r in results]
            failures.append((item["id"], item["question"], got))

    _print_report(loaded, overall, by_doc_type, by_category, by_difficulty, failures)

    # 退出码：核心指标达标返回 0，否则返回 1（便于 CI 集成）
    return 0 if overall.recall > 0.6 and overall.keyword > 0.5 else 1


def _row(label: str, m: Metrics) -> str:
    return (
        f"  {label:<20} n={m.n:<3} "
        f"recall@5={m.recall:.3f}  precision@5={m.precision:.3f}  "
        f"MRR={m.mrr:.3f}  keyword={m.keyword:.3f}  audience={m.audience:.3f}"
    )


def _print_report(loaded, overall, by_doc_type, by_category, by_difficulty, failures) -> None:
    line = "=" * 100
    print(line)
    print("RAG 检索质量评估报告")
    print(line)
    print(f"知识库文档数：{loaded}    评估问题数：{overall.n}    top_k={TOP_K}")
    print("检索方式：BM25(字符级) + 哈希向量(HashingVectorizer) → RRF 融合")
    print(line)

    print("【总体指标】")
    print(_row("OVERALL", overall))
    print()

    print("【按文档类型 doc_type】")
    for k in sorted(by_doc_type):
        print(_row(k, by_doc_type[k]))
    print()

    print("【按问题类别 category】")
    for k in sorted(by_category):
        print(_row(k, by_category[k]))
    print()

    print("【按难度 difficulty】")
    for k in sorted(by_difficulty):
        print(_row(k, by_difficulty[k]))
    print()

    print("【未命中期望文档的问题（recall miss）】")
    if not failures:
        print("  无")
    else:
        for qid, question, got in failures:
            print(f"  - {qid}: {question}")
            print(f"      实际 top{TOP_K}: {got}")
    print(line)

    verdict = "PASS" if overall.recall > 0.6 and overall.keyword > 0.5 else "FAIL"
    print(f"结论：{verdict}  (recall@5 阈值 0.6，keyword_hit 阈值 0.5)")
    print(line)


def main() -> None:
    exit_code = asyncio.run(evaluate())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
