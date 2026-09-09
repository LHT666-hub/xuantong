"""RAG 环路接入工作流的集成测试。

验证：当 XuantongWorkflow 注入了真实的 RAGEvaluationLoop 后，
提交健康事件时 `rag_retrieval` 节点被真正触发（不再 skipped=True），
并把检索到的知识写入 State.rag_context。

同时保留一条回归基线：未注入 rag_loop 时节点仍应优雅跳过。
"""

import json

import pytest

from app.domain.rules.risk_classification import RiskRuleService
from app.xuantong.agents import register_all_agents
from app.xuantong.llm import LLMRuntime, MockProvider
from app.xuantong.rag import (
    AudienceFilter,
    EntityResolver,
    EvidenceGrader,
    KnowledgeBase,
    QueryRewriter,
    RAGEvaluationLoop,
    RAGRetriever,
    RAGSafetyFilter,
    RetrievalGrader,
    RuleBasedReranker,
)
from app.xuantong.runtime.registry import AgentRegistry
from app.xuantong.safety import (
    ActionGuard,
    HITLService,
    InputGuard,
    OutputGuard,
)
from app.xuantong.workflow import XuantongWorkflow
from app.api.routes.events import _summarize_workflow
from tests.test_workflow.conftest import HAPPY_RESPONSES


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# 检索评分器（rag_grader）的响应 —— 命中其提示词稳定前缀
GRADE_RELEVANT_JSON = _j({"relevant": True, "score": 0.9, "reason": "文档直接覆盖查询"})

RAG_RESPONSES: dict[str, str] = {
    **HAPPY_RESPONSES,
    "请评估以下文档与查询的相关性": GRADE_RELEVANT_JSON,
}


async def _make_rag_loop(llm_runtime: LLMRuntime) -> RAGEvaluationLoop:
    """构建一个装载了高血压知识的内存 RAG 评估环路。"""
    kb = KnowledgeBase()
    await kb.add_document(
        "高血压患者血压升高（如 168/103mmHg）伴头晕时，应让其安静休息后复测血压，"
        "并核实近期降压药服药依从性；若持续升高需考虑转诊。",
        metadata={"source": "hypertension_guidelines.md"},
    )
    retriever = RAGRetriever(
        knowledge_base=kb,
        reranker=RuleBasedReranker(),
        safety_filter=RAGSafetyFilter(),
        audience_filter=AudienceFilter(),
    )
    return RAGEvaluationLoop(
        retriever=retriever,
        grader=RetrievalGrader(llm_runtime=llm_runtime),
        rewriter=QueryRewriter(llm_runtime=llm_runtime),
        max_retries=3,
        relevance_threshold=0.5,
        entity_resolver=EntityResolver(llm_runtime=llm_runtime),
        evidence_grader=EvidenceGrader(),
    )


def _make_workflow(llm_runtime: LLMRuntime, rag_loop, rag_enabled: bool) -> XuantongWorkflow:
    AgentRegistry.clear()
    register_all_agents(llm_runtime)
    return XuantongWorkflow(
        llm_runtime=llm_runtime,
        agent_registry=AgentRegistry,
        risk_service=RiskRuleService(),
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        action_guard=ActionGuard(),
        hitl_service=HITLService(),
        rag_loop=rag_loop,
        rag_enabled=rag_enabled,
    )


@pytest.fixture
def bp_event_with_complaint():
    """张阿姨血压 168/103 + 头晕 + 主诉 事件。"""
    return {
        "event_type": "vital_sign_abnormal",
        "patient_id": "p-001",
        "chief_complaint": "血压升高伴头晕",
        "measurements": [
            {
                "type": "blood_pressure",
                "value": 168,
                "secondary_value": 103,
                "unit": "mmHg",
            }
        ],
        "symptoms": ["头晕"],
    }


async def test_rag_retrieval_node_triggered(bp_event_with_complaint):
    """注入 rag_loop 后，rag_retrieval 节点应被触发并写入 rag_context。"""
    llm = LLMRuntime(MockProvider(responses=dict(RAG_RESPONSES)))
    rag_loop = await _make_rag_loop(llm)
    wf = _make_workflow(llm, rag_loop=rag_loop, rag_enabled=True)

    state = await wf.run(bp_event_with_complaint, thread_id="t-rag-on")

    rag_entries = [e for e in state["flow_log"] if e["node"] == "rag_retrieval"]
    assert rag_entries, f"rag_retrieval 节点未出现在 flow_log: {[e['node'] for e in state['flow_log']]}"

    entry = rag_entries[0]
    # 关键断言：节点不再被跳过
    assert entry.get("skipped") is not True
    assert entry.get("success") is True
    assert entry.get("doc_count", 0) >= 1

    # 检索到的知识应写入 State.rag_context，供下游 Agent 使用
    rag_context = state.get("rag_context")
    assert rag_context is not None
    assert len(rag_context.retrieved_docs) >= 1
    assert any("高血压" in doc for doc in rag_context.retrieved_docs)

    references = _summarize_workflow(state)["references"]
    assert len(references) >= 1
    assert references[0]["title"] == "高血压健康管理指南"
    assert "高血压" in references[0]["excerpt"]
    assert references[0]["kind"] == "local_knowledge_base"

    AgentRegistry.clear()


async def test_rag_retrieval_precedes_analyze(bp_event_with_complaint):
    """rag_retrieval 应在 analyze 之前执行（图拓扑顺序）。"""
    llm = LLMRuntime(MockProvider(responses=dict(RAG_RESPONSES)))
    rag_loop = await _make_rag_loop(llm)
    wf = _make_workflow(llm, rag_loop=rag_loop, rag_enabled=True)

    state = await wf.run(bp_event_with_complaint, thread_id="t-rag-order")

    nodes = [e["node"] for e in state["flow_log"]]
    assert "rag_retrieval" in nodes
    assert "analyze" in nodes
    assert nodes.index("rag_retrieval") < nodes.index("analyze")

    AgentRegistry.clear()


async def test_rag_retrieval_skipped_without_loop(bp_event_with_complaint):
    """回归基线：未注入 rag_loop 时节点应优雅跳过（skipped=True）。"""
    llm = LLMRuntime(MockProvider(responses=dict(RAG_RESPONSES)))
    wf = _make_workflow(llm, rag_loop=None, rag_enabled=False)

    state = await wf.run(bp_event_with_complaint, thread_id="t-rag-off")

    rag_entries = [e for e in state["flow_log"] if e["node"] == "rag_retrieval"]
    # 未启用 RAG 时，路由绕过检索节点，或节点以 skipped 记录
    if rag_entries:
        assert rag_entries[0].get("skipped") is True
    assert state.get("rag_context") is None

    AgentRegistry.clear()


async def test_route_after_input_guard_selects_rag(bp_event_with_complaint):
    """启用 RAG 时，输入安检后的路由应指向 rag_retrieval。"""
    llm = LLMRuntime(MockProvider(responses=dict(RAG_RESPONSES)))
    rag_loop = await _make_rag_loop(llm)
    wf = _make_workflow(llm, rag_loop=rag_loop, rag_enabled=True)

    # 非危机、无 safety_decision → 应路由到 rag_retrieval
    route = wf._route_after_input_guard({"event_data": bp_event_with_complaint})
    assert route == "rag_retrieval"

    AgentRegistry.clear()
