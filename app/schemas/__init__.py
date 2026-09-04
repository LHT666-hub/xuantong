"""
app/schemas — 玄同 V0.1 Pydantic v2 强类型契约

所有跨模块数据传递必须使用这些 BaseModel，不允许用 dict 代替。
"""

# message
from app.schemas.message import ChatMessage, add_chat_messages

# patient
from app.schemas.patient import MedicationInfo, PatientContext

# clinical
from app.schemas.clinical import (
    Measurement,
    TrendAnalysis,
    ClinicalContext,
    RiskAssessment,
    ActionRiskAssessment,
)

# agent
from app.schemas.agent import (
    AgentRole,
    AgentRequest,
    AgentResult,
    ConsultationNote,
    consultation_notes_reducer,
)

# dispatch
from app.schemas.dispatch import DispatchDecision

# action
from app.schemas.action import (
    TaskSpec,
    FollowupSpec,
    NotificationSpec,
    ActionItem,
    ActionPlan,
    ExecutionTask,
    ExecutionResult,
    SafetyDecision,
)

# event
from app.schemas.event import EventCreate, EventResponse

# task
from app.schemas.task import (
    TaskResponse,
    TaskListResponse,
    TaskCompleteRequest,
    TaskCompleteResponse,
    OutcomeRecordResponse,
)

# outcome
from app.schemas.outcome import OutcomeResponse

# workflow
from app.schemas.workflow import WorkflowResult

# timeline
from app.schemas.timeline import (
    TimelineEntry,
    TimelineEntryResponse,
    TimelineResponse,
)

# common
from app.schemas.common import ErrorDetail, ErrorResponse, HealthResponse

__all__ = [
    # message
    "ChatMessage",
    "add_chat_messages",
    # patient
    "MedicationInfo",
    "PatientContext",
    # clinical
    "Measurement",
    "TrendAnalysis",
    "ClinicalContext",
    "RiskAssessment",
    "ActionRiskAssessment",
    # agent
    "AgentRole",
    "AgentRequest",
    "AgentResult",
    "ConsultationNote",
    "consultation_notes_reducer",
    # dispatch
    "DispatchDecision",
    # action
    "TaskSpec",
    "FollowupSpec",
    "NotificationSpec",
    "ActionItem",
    "ActionPlan",
    "ExecutionTask",
    "ExecutionResult",
    "SafetyDecision",
    # event
    "EventCreate",
    "EventResponse",
    # task
    "TaskResponse",
    "TaskListResponse",
    "TaskCompleteRequest",
    "TaskCompleteResponse",
    "OutcomeRecordResponse",
    # outcome
    "OutcomeResponse",
    # workflow
    "WorkflowResult",
    # timeline
    "TimelineEntry",
    "TimelineEntryResponse",
    "TimelineResponse",
    # common
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
]
