from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


class TaskResponse(BaseModel):
    """任务响应"""
    id: str
    patient_id: str
    event_id: str | None = None
    title: str = ""
    description: str = ""
    task_type: str = ""
    status: str
    priority: str = "medium"
    assignee_type: str | None = None
    assignee_role: str | None = None
    assignee_id: str | None = None
    human_owner_id: str | None = None
    team_id: str | None = None
    result: dict[str, Any] | None = None
    deadline: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class TaskListResponse(BaseModel):
    """任务列表响应（分页）"""
    tasks: list[TaskResponse]
    total: int
    page: int
    size: int


class TaskCompleteRequest(BaseModel):
    """完成任务的请求。

    outcome_type: resolved / escalated / pending / cancelled。
    保留 result / outcome_summary 作为向后兼容的可选附加字段。
    """
    outcome_type: str = "resolved"
    notes: str = ""
    completed_by: str = ""
    # ── 向后兼容（旧契约）──
    result: dict[str, Any] = Field(default_factory=dict)
    outcome_summary: str = ""


class OutcomeRecordResponse(BaseModel):
    """服务结果记录响应（内存存储契约）"""
    id: str
    task_id: str
    patient_id: str
    event_id: str | None = None
    outcome_type: str
    notes: str = ""
    measured_by: str = ""
    measured_at: datetime


class TaskCompleteResponse(BaseModel):
    """完成任务后的响应：任务 + 结果"""
    task: TaskResponse
    outcome: OutcomeRecordResponse
