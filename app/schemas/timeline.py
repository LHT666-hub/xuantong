from pydantic import BaseModel
from datetime import datetime
from typing import Any


class TimelineEntry(BaseModel):
    """患者时间线条目（旧契约，聚合视图用）"""
    timestamp: datetime
    entry_type: str  # event / task / outcome / agent_run
    title: str
    summary: str
    related_ids: dict[str, str] = {}  # event_id, task_id, etc.
    channel: str | None = None


class TimelineEntryResponse(BaseModel):
    """时间线条目响应（内存存储契约）"""
    id: str
    patient_id: str
    entry_type: str
    title: str
    description: str = ""
    related_id: str | None = None
    metadata: dict[str, Any] = {}
    created_at: datetime


class TimelineResponse(BaseModel):
    """患者时间线响应（分页）"""
    timeline: list[TimelineEntryResponse]
    patient_id: str
    total: int
    page: int
    size: int
