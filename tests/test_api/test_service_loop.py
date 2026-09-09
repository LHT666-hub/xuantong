"""Event → Task → Outcome → Timeline 服务闭环端到端集成测试。

覆盖验收场景（张阿姨血压异常）：
1. POST /api/events → 201，返回 event_id + workflow_summary + task_ids
2. GET /api/tasks?patient_id=... → 返回生成的任务列表
3. POST /api/tasks/{task_id}/complete → 200，返回 task + outcome
4. GET /api/patients/{patient_id}/timeline → 完整时间线（≥5 条）
5. GET /api/events/{event_id}/status → 处理完成状态
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.rules.risk_classification import RiskRuleService
from app.main import app
from app.services import reset_store
from app.utils import normalize_patient_id
from app.xuantong.agents import register_all_agents
from app.xuantong.llm import LLMRuntime, MockProvider
from app.xuantong.runtime.registry import AgentRegistry
from app.xuantong.safety import ActionGuard, HITLService, InputGuard, OutputGuard
from app.xuantong.workflow import XuantongWorkflow
from tests.test_workflow.conftest import HAPPY_RESPONSES

PATIENT_ID = "patient-zhang-001"
NORMALIZED_PATIENT_ID = normalize_patient_id(PATIENT_ID)


def _build_scripted_workflow() -> XuantongWorkflow:
    """构建使用可编程 Mock（HAPPY_RESPONSES）的 workflow，稳定产出任务。"""
    llm = LLMRuntime(MockProvider(responses=dict(HAPPY_RESPONSES)))
    AgentRegistry.clear()
    register_all_agents(llm)
    return XuantongWorkflow(
        llm_runtime=llm,
        agent_registry=AgentRegistry,
        risk_service=RiskRuleService(),
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        action_guard=ActionGuard(),
        hitl_service=HITLService(),
    )


@pytest.fixture
def scripted_workflow():
    """替换 app.state.workflow 为可编程 Mock 版本，并隔离内存存储。"""
    reset_store()
    original = getattr(app.state, "workflow", None)
    app.state.workflow = _build_scripted_workflow()
    yield app.state.workflow
    app.state.workflow = original
    reset_store()


def _bp_event_payload() -> dict:
    return {
        "patient_id": PATIENT_ID,
        "event_type": "vital_sign_abnormal",
        "channel": "changxi",
        "source": "home_monitor",
        "payload": {
            "measurements": [
                {
                    "type": "blood_pressure",
                    "value": 168,
                    "secondary_value": 103,
                    "unit": "mmHg",
                }
            ],
            "symptoms": ["头晕"],
        },
    }


@pytest.mark.asyncio
async def test_full_service_loop(scripted_workflow):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1) 创建事件 → 触发 workflow → 生成任务
        resp = await client.post("/api/events", json=_bp_event_payload())
        assert resp.status_code == 201, resp.text
        body = resp.json()
        event_id = body["event"]["id"]
        # red 风险（168/103）会触发 ActionGuard → 需人工审核，属正常终态
        assert body["workflow"]["status"] in {"completed", "pending_human"}
        assert body["workflow"]["clinical_risk"] == "red"
        task_ids = body["task_ids"]
        assert len(task_ids) >= 1
        assert [task["id"] for task in body["tasks"]] == task_ids
        assert all(task["title"] for task in body["tasks"])

        # 2) 查询患者任务列表
        resp = await client.get("/api/tasks", params={"patient_id": PATIENT_ID})
        assert resp.status_code == 200
        tasks_body = resp.json()
        assert tasks_body["total"] == len(task_ids)
        assert all(t["patient_id"] == NORMALIZED_PATIENT_ID for t in tasks_body["tasks"])

        # 3) 完成一个任务 → 记录 outcome
        target_task = task_ids[0]
        resp = await client.post(
            f"/api/tasks/{target_task}/complete",
            json={
                "outcome_type": "resolved",
                "notes": "已电话随访，患者复测血压回落至 150/95，头晕缓解。",
                "completed_by": "nurse",
            },
        )
        assert resp.status_code == 200, resp.text
        done = resp.json()
        assert done["task"]["status"] == "completed"
        assert done["task"]["completed_at"] is not None
        assert done["outcome"]["outcome_type"] == "resolved"
        assert done["outcome"]["measured_by"] == "nurse"

        # 4) 患者时间线（≥5 条：event_received/risk_assessed/consultation/
        #    action_planned/tasks_created/execution_started + task_completed/outcome）
        resp = await client.get(f"/api/patients/{PATIENT_ID}/timeline")
        assert resp.status_code == 200
        timeline = resp.json()
        assert timeline["patient_id"] == NORMALIZED_PATIENT_ID
        assert timeline["total"] >= 5
        types = {e["entry_type"] for e in timeline["timeline"]}
        assert "event_received" in types
        assert "risk_assessed" in types
        assert "tasks_created" in types
        assert "task_completed" in types
        assert "outcome_recorded" in types

        # 5) 事件处理状态
        resp = await client.get(f"/api/events/{event_id}/status")
        assert resp.status_code == 200
        status = resp.json()
        assert status["status"] in {"completed", "pending_human"}
        assert status["task_ids"] == task_ids


@pytest.mark.asyncio
async def test_task_filters_and_pagination(scripted_workflow):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/events", json=_bp_event_payload())

        # 分页 size=1 只返回一条，但 total 为全部
        resp = await client.get(
            "/api/tasks", params={"patient_id": PATIENT_ID, "page": 1, "size": 1}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["tasks"]) == 1
        assert body["total"] >= 2
        assert body["page"] == 1 and body["size"] == 1

        # 按状态过滤
        resp = await client.get(
            "/api/tasks", params={"patient_id": PATIENT_ID, "status": "pending"}
        )
        assert resp.status_code == 200
        assert all(t["status"] == "pending" for t in resp.json()["tasks"])


@pytest.mark.asyncio
async def test_get_nonexistent_returns_404(scripted_workflow):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/tasks/nope")).status_code == 404
        assert (await client.get("/api/events/nope")).status_code == 404
        assert (
            await client.post("/api/tasks/nope/complete", json={"outcome_type": "resolved"})
        ).status_code == 404
