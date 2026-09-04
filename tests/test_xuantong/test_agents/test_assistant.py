"""AssistantAgent（执行阶段）智能逻辑测试。"""

import json

import pytest

from app.schemas.action import ActionItem, ActionPlan, ExecutionResult
from app.xuantong.agents.assistant import AssistantAgent
from tests.test_xuantong.test_agents.conftest import make_runtime

ASSISTANT_JSON = json.dumps(
    {
        "tasks": [
            {
                "title": "电话随访张阿姨血压情况",
                "description": "联系患者确认今日血压复测结果，询问头晕是否缓解",
                "assignee_type": "agent",
                "assignee_role": "assistant",
                "priority": "high",
                "deadline_hours": 24,
                "status": "pending",
            },
            {
                "title": "发送血压监测提醒",
                "description": "提醒张阿姨明早测量血压并上传",
                "assignee_type": "agent",
                "assignee_role": "assistant",
                "priority": "medium",
                "deadline_hours": 12,
                "status": "pending",
            },
        ],
        "patient_message": "张阿姨您好，我是您的家庭医生团队助理，提醒您明早复测血压。",
        "family_notification": None,
    },
    ensure_ascii=False,
)


@pytest.fixture
def sample_action_plan():
    return ActionPlan(
        summary="血压控制不佳",
        actions=[
            ActionItem(
                type="followup",
                description="安排3天内复诊测血压",
                assignee_role="assistant",
                priority="high",
                deadline_hours=72,
            ),
            ActionItem(
                type="medication_review",
                description="评估降压方案",
                assignee_role="human_doctor",
                priority="high",
                deadline_hours=72,
            ),
        ],
        patient_communication="张阿姨您好，您的血压有些偏高。",
    )


@pytest.mark.asyncio
async def test_execute_plan_returns_execution_result(sample_action_plan, zhang_ayi_patient):
    agent = AssistantAgent(make_runtime(default=ASSISTANT_JSON))
    result = await agent.execute_plan(sample_action_plan, zhang_ayi_patient)

    assert isinstance(result, ExecutionResult)
    assert len(result.tasks) == 2
    assert result.tasks[0].priority == "high"
    assert result.tasks[0].deadline_hours == 24
    assert result.patient_message
    assert result.family_notification is None


@pytest.mark.asyncio
async def test_execute_plan_skips_malformed_tasks(zhang_ayi_patient):
    payload = json.dumps(
        {"tasks": ["非法字符串", {"title": "有效任务"}], "patient_message": "您好"},
        ensure_ascii=False,
    )
    agent = AssistantAgent(make_runtime(default=payload))
    result = await agent.execute_plan(ActionPlan(), zhang_ayi_patient)
    assert len(result.tasks) == 1
    assert result.tasks[0].title == "有效任务"


@pytest.mark.asyncio
async def test_patient_message_passes_output_guard():
    """患者消息含诊断性语言时应被 OutputGuard 改写。"""
    payload = json.dumps(
        {"tasks": [], "patient_message": "你得了高血压，要注意休息。"},
        ensure_ascii=False,
    )
    agent = AssistantAgent(make_runtime(default=payload))
    result = await agent.execute_plan(ActionPlan())
    assert "你得了" not in result.patient_message


@pytest.mark.asyncio
async def test_execute_plan_degrades_mapping_actions(sample_action_plan):
    """无 runtime 时降级：直接把行动项映射为任务。"""
    agent = AssistantAgent(None)
    result = await agent.execute_plan(sample_action_plan)
    assert isinstance(result, ExecutionResult)
    assert len(result.tasks) == 2
    # human_doctor 行动项应标记为 human 执行
    human_tasks = [t for t in result.tasks if t.assignee_type == "human"]
    assert len(human_tasks) == 1


@pytest.mark.asyncio
async def test_generate_communication_returns_text(sample_action_plan):
    payload = json.dumps({"patient_message": "张阿姨您好，记得明早测血压哦。"}, ensure_ascii=False)
    agent = AssistantAgent(make_runtime(default=payload))
    text = await agent.generate_communication(sample_action_plan, purpose="血压监测提醒")
    assert isinstance(text, str)
    assert "血压" in text


@pytest.mark.asyncio
async def test_generate_communication_degrades_without_runtime():
    agent = AssistantAgent(None)
    text = await agent.generate_communication()
    assert isinstance(text, str) and text


@pytest.mark.asyncio
async def test_execute_returns_agent_result(sample_action_plan):
    agent = AssistantAgent(make_runtime(default=ASSISTANT_JSON))
    result = await agent.execute(action_plan=sample_action_plan)
    assert result.agent_role == "assistant"
    assert "已拆解 2 项执行任务" in result.summary
    assert result.data["patient_message"]
