"""玄同工作流引擎 —— LangGraph StateGraph 编排。

将 8-Agent 团队的协作流程编排为一张有向图：

    START
      → multimodal_detection 多模态检测（图片/音频/文本）
      → [条件] image_analysis / speech_transcription / input_guard
      → input_guard        输入安全（危机 / 注入 / 超长）
      → [条件] emergency → END
      → analyze            FamilyDoctor 分析事件 → DispatchDecision
      → dispatch           调度归一化（不重复调用 LLM）
      → [Send 并行] consult 扇出到选中的会诊 Agent
      → synthesis          FamilyDoctor 综合会诊意见 → ActionPlan
      → risk_assessment    RiskRuleService 产生权威 clinical_risk
      → output_guard       患者可见文本 4 态安检
      → action_guard       评估动作风险 → 是否需人工
      → [条件] hitl → task_generation
      → task_generation    ActionPlan.actions → 任务清单
      → execution          AssistantAgent 拆解执行
      → timeline           汇总审计
      → END

对外入口：XuantongWorkflow.run(event_data, patient_context, thread_id)。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.schemas.patient import PatientContext
from app.xuantong.runtime.state import XuantongState
from app.xuantong.workflow.checkpoint import get_checkpointer
from app.xuantong.workflow.nodes import WorkflowNodes

logger = logging.getLogger(__name__)


class XuantongWorkflow(WorkflowNodes):
    """玄同工作流引擎 —— 编排 Agent 协作。

    节点逻辑继承自 WorkflowNodes；本类负责依赖注入、图构建与执行入口。
    """

    def __init__(
        self,
        llm_runtime: Any = None,
        agent_registry: Any = None,
        risk_service: Any = None,
        input_guard: Any = None,
        output_guard: Any = None,
        action_guard: Any = None,
        hitl_service: Any = None,
        checkpointer: Any = None,
        rag_loop: Any = None,
        rag_enabled: bool = True,
    ) -> None:
        self.llm_runtime = llm_runtime
        self.agent_registry = agent_registry
        self.risk_service = risk_service
        self.input_guard = input_guard
        self.output_guard = output_guard
        self.action_guard = action_guard
        self.hitl_service = hitl_service
        self._checkpointer = checkpointer or get_checkpointer()
        self.rag_loop = rag_loop
        self.rag_enabled = rag_enabled
        self._graph = self._build_graph()

    # ────────────────────────────────────────────────────────
    # 图构建
    # ────────────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        """构建并编译 StateGraph。"""
        graph = StateGraph(XuantongState)

        # ── 节点 ──
        graph.add_node("multimodal_detection", self._multimodal_detection_node)
        graph.add_node("image_analysis", self._image_analysis_node)
        graph.add_node("speech_transcription", self._speech_transcription_node)
        graph.add_node("input_guard", self._input_guard_node)
        graph.add_node("emergency", self._emergency_node)
        graph.add_node("rag_retrieval", self._rag_retrieval_node)
        graph.add_node("analyze", self._analyze_node)
        graph.add_node("dispatch", self._dispatch_node)
        graph.add_node("consult", self._consult_node)
        graph.add_node("synthesis", self._synthesis_node)
        graph.add_node("risk_assessment", self._risk_node)
        graph.add_node("output_guard", self._output_guard_node)
        graph.add_node("action_guard", self._action_guard_node)
        graph.add_node("hitl", self._hitl_node)
        graph.add_node("task_generation", self._task_gen_node)
        graph.add_node("execution", self._execute_node)
        graph.add_node("timeline", self._timeline_node)

        # ── 边 ──
        graph.add_edge(START, "multimodal_detection")
        graph.add_conditional_edges(
            "multimodal_detection",
            self._route_after_multimodal,
            {
                "image": "image_analysis",
                "audio": "speech_transcription",
                "text": "input_guard",
            },
        )
        graph.add_edge("image_analysis", "input_guard")
        graph.add_edge("speech_transcription", "input_guard")
        graph.add_conditional_edges(
            "input_guard",
            self._route_after_input_guard,
            {"emergency": "emergency", "analyze": "analyze", "rag_retrieval": "rag_retrieval"},
        )
        graph.add_edge("emergency", END)
        graph.add_edge("rag_retrieval", "analyze")
        graph.add_edge("analyze", "dispatch")
        # dispatch → 动态并行扇出到 consult（或直接 synthesis）
        graph.add_conditional_edges("dispatch", self._route_to_consult, ["consult", "synthesis"])
        graph.add_edge("consult", "synthesis")
        graph.add_edge("synthesis", "risk_assessment")
        graph.add_edge("risk_assessment", "output_guard")
        graph.add_edge("output_guard", "action_guard")
        graph.add_conditional_edges(
            "action_guard",
            self._route_after_action_guard,
            {"hitl": "hitl", "task_generation": "task_generation"},
        )
        graph.add_edge("hitl", "task_generation")
        graph.add_edge("task_generation", "execution")
        graph.add_edge("execution", "timeline")
        graph.add_edge("timeline", END)

        return graph.compile(checkpointer=self._checkpointer)

    # ────────────────────────────────────────────────────────
    # 执行入口
    # ────────────────────────────────────────────────────────

    async def run(
        self,
        event_data: dict[str, Any],
        patient_context: PatientContext | dict | None = None,
        thread_id: str | None = None,
    ) -> XuantongState:
        """执行完整工作流，返回最终 State。

        Args:
            event_data: 健康事件数据（指标、症状、来源等）。
            patient_context: 患者上下文（可选）。
            thread_id: 会话线程 ID；缺省则新建（保证 checkpointer 状态隔离）。

        Returns:
            最终 XuantongState（含 dispatch_decision / consultation_notes /
            action_plan / clinical_risk / execution_result / flow_log 等）。
        """
        thread_id = thread_id or uuid4().hex

        initial: dict[str, Any] = {
            "event_data": event_data or {},
            "thread_id": thread_id,
            "messages": [],
            "consultation_notes": [],
            "flow_log": [],
        }
        if patient_context is not None:
            initial["patient_context"] = patient_context

        config = {"configurable": {"thread_id": thread_id}}
        logger.info(f"workflow: 启动 thread_id={thread_id}")
        final_state = await self._graph.ainvoke(initial, config=config)
        logger.info(
            f"workflow: 完成 thread_id={thread_id}, "
            f"steps={len(final_state.get('flow_log') or [])}"
        )
        return final_state


__all__ = ["XuantongWorkflow"]
