"""任务确认接口测试。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import TaskService, reset_store


@pytest.fixture
def proposed_task():
    reset_store()
    service = TaskService()
    service.db.tasks["task-proposed"] = {
        "id": "task-proposed",
        "patient_id": "patient-001",
        "status": "proposed",
    }
    yield
    reset_store()


@pytest.mark.asyncio
async def test_patient_can_accept_proposed_task(proposed_task):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/tasks/task-proposed/accept")

    assert response.status_code == 200
    assert response.json()["task"]["status"] == "pending"


@pytest.mark.asyncio
async def test_only_proposed_task_can_be_accepted(proposed_task):
    TaskService().db.tasks["task-proposed"]["status"] = "pending"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/tasks/task-proposed/accept")

    assert response.status_code == 409

