from pydantic import BaseModel
from datetime import datetime
from typing import Any


class EventCreate(BaseModel):
    """创建事件的请求"""
    patient_id: str
    event_type: str
    channel: str  # changxi / doctor_workbench / admin_console / wecom / voice / system
    source: str = ""
    payload: dict[str, Any] = {}
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = {}


class EventResponse(BaseModel):
    """事件响应"""
    id: str
    patient_id: str
    event_type: str
    channel: str
    source: str
    payload: dict[str, Any]
    occurred_at: datetime
    received_at: datetime
