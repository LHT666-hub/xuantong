from pydantic import BaseModel


class TaskSpec(BaseModel):
    """要创建的任务规格"""
    task_type: str
    priority: str = "normal"
    assignee_role: str | None = None
    description: str
    due_within_minutes: int | None = None


class FollowupSpec(BaseModel):
    """随访规格"""
    followup_type: str
    description: str
    due_within_minutes: int | None = None


class NotificationSpec(BaseModel):
    """通知规格"""
    notification_type: str  # reminder / alert / info
    target: str  # patient / doctor / family
    channel: str | None = None
    message: str


class ActionItem(BaseModel):
    """行动计划中的单条行动项（FamilyDoctorAgent.synthesize 产出）。"""
    type: str                             # followup / monitoring / medication_review / referral / education / alert
    description: str
    assignee_role: str | None = None      # assistant / human_doctor / nurse / ...
    priority: str = "medium"              # low / medium / high
    deadline_hours: int | None = None


class ActionPlan(BaseModel):
    """FamilyDoctorAgent 综合后的行动计划。

    保留既有的任务/随访/通知规格字段（供 workflow 直接落地），
    并扩展 LLM 综合产出的结构化字段（摘要、评估、行动项、患者沟通）。
    """
    # ── 既有字段（可直接落地为任务/随访/通知）──────────────────
    reply: str | None = None
    tasks_to_create: list[TaskSpec] = []
    followups: list[FollowupSpec] = []
    notifications: list[NotificationSpec] = []

    # ── LLM 综合产出（synthesize）──────────────────────────────
    summary: str = ""
    clinical_assessment: str = ""
    actions: list[ActionItem] = []
    patient_communication: str = ""
    followup_plan: str = ""


class ExecutionTask(BaseModel):
    """AssistantAgent 拆解出的可执行任务。"""
    title: str
    description: str = ""
    assignee_type: str = "agent"          # agent / human
    assignee_role: str | None = None
    priority: str = "medium"              # low / medium / high
    deadline_hours: int | None = None
    status: str = "pending"


class ExecutionResult(BaseModel):
    """AssistantAgent 执行阶段的产出：任务清单 + 沟通文本。"""
    tasks: list[ExecutionTask] = []
    patient_message: str = ""
    family_notification: str | None = None


class SafetyDecision(BaseModel):
    """Safety Layer 决策"""
    input_ok: bool = True
    output_action: str = "pass"  # pass / rewrite / reject / emergency
    rewritten_text: str | None = None
    action_guard_result: str = "allow"  # allow / block / require_human
    reasons: list[str] = []
