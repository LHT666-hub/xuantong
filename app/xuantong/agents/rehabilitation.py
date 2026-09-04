"""康复师 Agent — 康复指导（Phase 3 实现）。"""

from app.schemas.agent import AgentResult
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent


class RehabilitationAgent(BaseAgent):
    """康复师角色。

    职责：康复指导、运动处方。
    状态：Phase 3 实现，当前为骨架占位。
    """

    role = "rehabilitation"
    display_name = "康复师"
    description = "康复指导"
    implemented = False  # Phase 3

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs,
    ) -> AgentResult:
        self._reset_counters()
        return AgentResult(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=f"[{self.display_name}] 骨架模式：Phase 3 待实现",
            findings=["Phase 3 骨架"],
            recommendations=["等待 Phase 3 实现康复指导逻辑"],
        )
