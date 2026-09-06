"""模型汇总 —— 确保 Alembic 能发现所有表。"""

from app.models.user import User
from app.models.organization import Organization
from app.models.team import Team
from app.models.patient import Patient
from app.models.care_team import CareTeam, CareTeamMember, PatientTeamAssignment
from app.models.health_record import HealthRecord
from app.models.measurement import Measurement
from app.models.medication import Medication
from app.models.event import Event
from app.models.task import Task
from app.models.outcome import ServiceOutcome
from app.models.followup import Followup
from app.models.timeline import TimelineEntry
from app.models.agent_run import AgentRun
from app.models.workflow_run import WorkflowRun
from app.models.audit_log import AuditLog
from app.models.chat_message import ChatMessage

__all__ = [
    "User",
    "Organization",
    "Team",
    "Patient",
    "CareTeam",
    "CareTeamMember",
    "PatientTeamAssignment",
    "HealthRecord",
    "Measurement",
    "Medication",
    "Event",
    "Task",
    "ServiceOutcome",
    "Followup",
    "TimelineEntry",
    "AgentRun",
    "WorkflowRun",
    "AuditLog",
    "ChatMessage",
]
