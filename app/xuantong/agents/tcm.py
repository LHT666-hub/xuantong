"""中医师 Agent — 中医辨证（Phase 3 实现）。"""

from app.schemas.agent import AgentResult
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent


class TCMAgent(BaseAgent):
    """中医师角色。

    职责：中医辨证论治。
    状态：Phase 3 实现，当前为骨架占位。
    """

    role = "tcm"
    display_name = "中医师"
    description = "中医辨证"
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
            recommendations=["等待 Phase 3 实现中医辨证逻辑"],
        )
