"""XuantongWorkflow 图级集成测试。

使用可编程 Mock Provider 驱动完整 LangGraph 流程，覆盖：
- 图编译
- 正常血压事件走完全流程
- 危机输入短路到 emergency
- 多 Agent 并行会诊（Send 扇出）
- 高风险动作触发 HITL
"""

import pytest

from tests.test_workflow.conftest import (
    ACTION_PLAN_REFERRAL_JSON,
    HAPPY_RESPONSES,
)


def test_workflow_compiles(make_workflow):
    """graph.compile() 成功，产出可调用对象。"""
    wf = make_workflow(HAPPY_RESPONSES)
    assert wf._graph is not None
    # 编译后的图应具备异步调用入口
    assert hasattr(wf._graph, "ainvoke")


async def test_normal_bp_flow(make_workflow, bp_event, zhang_ayi_patient):
    """正常血压事件应走完 input_guard → ... → timeline 全流程。"""
    wf = make_workflow(HAPPY_RESPONSES)
    state = await wf.run(bp_event, patient_context=zhang_ayi_patient, thread_id="t-normal")

    nodes = [e["node"] for e in state["flow_log"]]
    # 关键节点均被执行
    for expected in (
        "input_guard",
        "analyze",
        "dispatch",
        "consult",
        "synthesis",
        "risk_assessment",
        "output_guard",
        "action_guard",
        "task_generation",
        "execution",
        "timeline",
    ):
        assert expected in nodes, f"缺少节点 {expected}，实际 {nodes}"

    # 未走 emergency
    assert "emergency" not in nodes
    # 权威临床风险由规则引擎产出（168/103 → red）
    assert state["clinical_risk"] is not None
    assert state["clinical_risk"].level == "red"
    # 综合产出行动计划 + 执行拆解
    assert state["action_plan"] is not None
    assert state["action_plan"].patient_communication
    assert state["execution_result"] is not None
    assert len(state["execution_result"].tasks) >= 1
    # 任务生成
    assert len(state["generated_tasks"]) >= 1


async def test_emergency_input_shortcut(make_workflow):
    """危机输入应短路到 emergency 节点并直接结束，不走常规会诊。"""
    wf = make_workflow(HAPPY_RESPONSES)
    state = await wf.run({"text": "我最近很难受，我不想活了"}, thread_id="t-emergency")

    nodes = [e["node"] for e in state["flow_log"]]
    # 多模态检测是第一个节点，然后进入 input_guard
    assert nodes[0] == "multimodal_detection"
    assert "input_guard" in nodes
    assert "emergency" in nodes
    # 短路：不进入分析/会诊/综合
    assert "analyze" not in nodes
    assert "consult" not in nodes
    assert "synthesis" not in nodes
    # 危机 → 需人工
    assert state["human_required"] is True
    assert state["action_plan"] is not None
    # 安全决策标记为 emergency
    assert state["safety_decision"].output_action == "emergency"


async def test_parallel_consult(make_workflow, bp_event, zhang_ayi_patient):
    """DispatchDecision 选中多个 Agent 时应并行产生多条 ConsultationNote。"""
    wf = make_workflow(HAPPY_RESPONSES)
    state = await wf.run(bp_event, patient_context=zhang_ayi_patient, thread_id="t-parallel")

    notes = state["consultation_notes"]
    roles = {n.agent_role for n in notes}
    # HAPPY_RESPONSES 的调度选中 nurse / public_health / pharmacist
    assert roles == {"nurse", "public_health", "pharmacist"}
    assert len(notes) == 3
    # 每条会诊笔记都有实质观察内容（来自 scripted JSON，非降级）
    for note in notes:
        assert note.summary or note.observation


async def test_action_guard_triggers_hitl(make_workflow, bp_event, zhang_ayi_patient):
    """含转诊（HIGH 级）动作时 ActionGuard 应触发 HITL 分支。"""
    responses = dict(HAPPY_RESPONSES)
    responses["以下是团队各成员的会诊意见"] = ACTION_PLAN_REFERRAL_JSON
    wf = make_workflow(responses)

    state = await wf.run(bp_event, patient_context=zhang_ayi_patient, thread_id="t-hitl")

    nodes = [e["node"] for e in state["flow_log"]]
    assert "action_guard" in nodes
    assert "hitl" in nodes
    assert state["human_required"] is True
    assert state["action_risk"] is not None
    assert state["action_risk"].requires_human is True
    # HITL 之后仍继续生成任务
    assert "task_generation" in nodes
    # 生成的任务标记为待人工
    assert any(t["status"] == "pending_human" for t in state["generated_tasks"])
    # HITL 服务已登记待审记录
    assert len(wf.hitl_service.get_pending_reviews()) >= 1


async def test_no_selected_agents_skips_consult(make_workflow, bp_event):
    """调度未选中任何可会诊 Agent 时应跳过 consult 直达 synthesis。"""
    responses = dict(HAPPY_RESPONSES)
    # 调度仅选中 assistant（执行阶段，不参与会诊）
    responses["请分析以下健康事件"] = (
        '{"event_summary":"轻微波动","severity":"low",'
        '"selected_agents":["assistant"],"reasoning":"仅需助理跟进",'
        '"immediate_actions":[],"requires_urgent_response":false}'
    )
    wf = make_workflow(responses)
    state = await wf.run(bp_event, thread_id="t-noconsult")

    nodes = [e["node"] for e in state["flow_log"]]
    assert "consult" not in nodes
    assert "synthesis" in nodes
    assert state["consultation_notes"] == []
