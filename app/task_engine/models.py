from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


class AssigneeType(str, Enum):
    AGENT = "agent"
    HUMAN = "human"
    TEAM = "team"
    PATIENT = "patient"
    FAMILY = "family"
