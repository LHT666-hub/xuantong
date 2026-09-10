"""8 个 Agent 全部注册到 AgentRegistry。

V0.1 Phase 1：骨架全注册，能力逐步实现。
"""

from app.xuantong.agents.assistant import AssistantAgent
from app.xuantong.agents.family_doctor import FamilyDoctorAgent
from app.xuantong.agents.nurse import NurseAgent
from app.xuantong.agents.nutrition import NutritionAgent
from app.xuantong.agents.pharmacist import PharmacistAgent
from app.xuantong.agents.public_health import PublicHealthAgent
from app.xuantong.agents.rehabilitation import RehabilitationAgent
from app.xuantong.agents.tcm import TCMAgent
from app.xuantong.runtime.registry import AgentDefinition, AgentRegistry


def register_all_agents(llm_runtime=None) -> None:
    """注册所有 8 个 Agent 到 AgentRegistry。

    Parameters
    ----------
    llm_runtime : LLMRuntime | None
        可选的 LLM 运行时实例，注入到每个 Agent。
    """

    agents: list[tuple[AgentDefinition, object]] = [
        # ── 会诊阶段（consultation）─────────────────────────
        (
            AgentDefinition(
                key="family_doctor",
                role="family_doctor",
                display_name="家庭医生",
                description="团队负责人/统一入口：分析事件，选择团队成员，综合决策",
                phase="consultation",
                capabilities=["event_analysis", "team_dispatch", "synthesis"],
            ),
            FamilyDoctorAgent(llm_runtime),
        ),
        (
            AgentDefinition(
                key="nurse",
                role="nurse",
                display_name="护士",
                description="指标解释/趋势分析/专业观察",
                phase="consultation",
                capabilities=["vital_signs_analysis", "trend_analysis"],
            ),
            NurseAgent(llm_runtime),
        ),
        (
            AgentDefinition(
                key="public_health",
                role="public_health",
                display_name="公卫医师",
                description="公卫随访管理/公卫规范",
                phase="consultation",
                capabilities=["followup_management", "public_health_guidelines"],
            ),
            PublicHealthAgent(llm_runtime),
        ),
        (
            AgentDefinition(
                key="pharmacist",
                role="pharmacist",
                display_name="药师",
                description="用药安全分析",
                phase="consultation",
                capabilities=["medication_safety", "ddi_check"],
            ),
            PharmacistAgent(llm_runtime),
        ),
        (
            AgentDefinition(
                key="tcm",
                role="tcm",
                display_name="中医师",
                description="中医辨证",
                phase="consultation",
                implemented=False,  # Phase 3 实现
            ),
            TCMAgent(llm_runtime),
        ),
        (
            AgentDefinition(
                key="nutrition",
                role="nutrition",
                display_name="营养师",
                description="个性化食养与菜谱排序",
                phase="consultation",
                implemented=True,
                capabilities=["meal_ranking", "dietary_safety", "pantry_matching"],
            ),
            NutritionAgent(llm_runtime),
        ),
        (
            AgentDefinition(
                key="rehabilitation",
                role="rehabilitation",
                display_name="康复师",
                description="康复指导",
                phase="consultation",
                implemented=False,  # Phase 3 实现
            ),
            RehabilitationAgent(llm_runtime),
        ),
        # ── 执行阶段（execution）────────────────────────────
        (
            AgentDefinition(
                key="assistant",
                role="assistant",
                display_name="家医助理",
                description=(
                    "连接性劳动：联系患者/提醒/预约协调/任务催办/随访跟进/"
                    "家属协调/群管理"
                ),
                phase="execution",  # 后置执行阶段，非会诊阶段
                capabilities=[
                    "care_coordination",
                    "appointment",
                    "reminder",
                    "followup_tracking",
                ],
            ),
            AssistantAgent(llm_runtime),
        ),
    ]

    for definition, instance in agents:
        AgentRegistry.register(definition, instance)


__all__ = [
    "register_all_agents",
    "FamilyDoctorAgent",
    "NurseAgent",
    "PublicHealthAgent",
    "AssistantAgent",
    "PharmacistAgent",
    "TCMAgent",
    "NutritionAgent",
    "RehabilitationAgent",
]
