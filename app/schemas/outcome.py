from pydantic import BaseModel
from datetime import datetime
from typing import Any


class OutcomeResponse(BaseModel):
    """服务结果响应"""
    id: str
    patient_id: str
    event_id: str
    task_id: str
    outcome_type: str
    handled_by: str
    summary: str
    structured_result: dict[str, Any]
    next_action: str | None = None
    followup_required: bool
    occurred_at: datetime
