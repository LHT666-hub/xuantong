"""家医助理 Agent — 连接性劳动（后置服务协调/执行角色）。

定位：不是聊天机器人，而是连接性劳动的执行者。
职责：联系患者 / 提醒 / 预约协调 / 任务催办 / 随访跟进 / 家属协调 / 群管理。
阶段：execution（后置执行阶段，非会诊阶段）。
模型：qwen-flash（由 LLMRuntime 依据 agent_role="assistant" 路由到 execution 层级）。

对外方法：
- execute_plan():            接收 ActionPlan，拆解为可执行任务清单 → ExecutionResult。
- generate_communication():  生成患者沟通文本。
- execute():                 基类通用入口，路由到 execute_plan 并回包 AgentResult。
"""

import logging

from app.schemas.action import ActionPlan, ExecutionResult, ExecutionTask
from app.schemas.agent import AgentResult
from app.schemas.clinical import ClinicalContext
from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent

logger = logging.getLogger(__name__)

_EXECUTE_SCHEMA = """{
  "tasks": [
    {
      "title": "电话随访张阿姨血压情况",
      "description": "联系患者确认今日血压复测结果，询问头晕是否缓解",
      "assignee_type": "agent",
      "assignee_role": "assistant",
      "priority": "high",
      "deadline_hours": 24,
      "status": "pending"
    }
  ],
  "patient_message": "张阿姨您好，我是您的家庭医生团队助理……",
  "family_notification": null
}"""


class AssistantAgent(BaseAgent):
    """家医助理角色。

    连接性劳动：协调、提醒、跟进——而非临床决策。
    属于 execution 阶段，在会诊完成后执行服务协调。
    """

    role = "assistant"
    display_name = "家医助理"
    description = (
        "连接性劳动：联系患者/提醒/预约协调/任务催办/随访跟进/家属协调/群管理。"
        "定位为后置服务协调/执行角色。"
    )
    max_llm_calls = 2  # 协调类任务通常不需要大量 LLM 调用

    SYSTEM_PROMPT = """你是家庭医生团队的助理，负责执行协调工作。

你的职责：
1. 将医生的行动计划拆解为具体可执行的任务
2. 联系患者传达医嘱和健康提醒
3. 协调预约、安排随访、催办任务
4. 与家属沟通、管理健康群

重要原则：
- 你不做临床判断，只负责协调执行
- 沟通语气要温和、易懂、尊重患者
- 任务描述要具体、可操作、有时限
- 如果患者有疑问，引导其咨询医生而非自行回答

输出格式：严格按 JSON 格式输出，只输出一个 JSON 对象，不要包含 markdown 代码块或任何额外文字。
"""

    # ────────────────────────────────────────────────────────
    # 执行阶段：拆解行动计划
    # ────────────────────────────────────────────────────────

    async def execute_plan(
        self,
        action_plan: ActionPlan | dict,
        patient_context: PatientContext | dict | None = None,
    ) -> ExecutionResult:
        """接收行动计划，拆解为具体可执行任务清单，并生成沟通文本。"""
        self._reset_counters()

        user_content = (
            "以下是家庭医生制定的行动计划，请拆解为具体可执行的任务，"
            "并撰写一条温和易懂的患者沟通消息。\n\n"
            f"【患者信息】\n{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【行动计划】\n{self._dumps(self._to_plain(action_plan))}\n\n"
            "【输出格式】严格输出如下结构的 JSON（priority 取 low/medium/high；"
            "assignee_type 取 agent/human；无需家属通知时 family_notification 置为 null）：\n"
            f"{_EXECUTE_SCHEMA}"
        )

        data = await self._invoke_json(user_content)
        if data is None:
            return self._degraded_result(action_plan)

        tasks = self._parse_tasks(data.get("tasks", []))
        patient_message = self._guard_patient_text(data.get("patient_message", "") or "")
        family_raw = data.get("family_notification")
        family_notification = (
            self._guard_patient_text(str(family_raw)) if family_raw else None
        )

        return ExecutionResult(
            tasks=tasks,
            patient_message=patient_message,
            family_notification=family_notification,
        )

    def _parse_tasks(self, raw_tasks: list) -> list[ExecutionTask]:
        """解析并校验任务项，跳过非法条目。"""
        tasks: list[ExecutionTask] = []
        for item in raw_tasks or []:
            if not isinstance(item, dict):
                continue
            try:
                tasks.append(
                    ExecutionTask(
                        title=str(item.get("title", "")),
                        description=str(item.get("description", "")),
                        assignee_type=str(item.get("assignee_type", "agent")),
                        assignee_role=item.get("assignee_role"),
                        priority=str(item.get("priority", "medium")),
                        deadline_hours=item.get("deadline_hours"),
                        status=str(item.get("status", "pending")),
                    )
                )
            except Exception as e:  # 单条非法不影响整体
                logger.warning(f"{self.display_name}: 任务解析失败已跳过: {e}")
        return tasks

    def _degraded_result(self, action_plan: ActionPlan | dict) -> ExecutionResult:
        """LLM 不可用时，直接依据行动计划行动项生成最小任务清单。"""
        logger.warning(f"{self.display_name}: 执行拆解降级，直接映射行动项")
        plan = self._to_plain(action_plan) or {}
        actions = plan.get("actions", []) if isinstance(plan, dict) else []
        tasks = [
            ExecutionTask(
                title=str(a.get("description", "跟进任务"))[:40],
                description=str(a.get("description", "")),
                assignee_type="human" if a.get("assignee_role") == "human_doctor" else "agent",
                assignee_role=a.get("assignee_role") or "assistant",
                priority=str(a.get("priority", "medium")),
                deadline_hours=a.get("deadline_hours"),
                status="pending",
            )
            for a in actions
            if isinstance(a, dict)
        ]
        patient_message = self._guard_patient_text(
            plan.get("patient_communication", "") if isinstance(plan, dict) else ""
        ) or "您的情况我们已记录，家庭医生团队会尽快与您联系，请留意后续通知。"
        return ExecutionResult(tasks=tasks, patient_message=patient_message)

    # ────────────────────────────────────────────────────────
    # 患者沟通文本生成
    # ────────────────────────────────────────────────────────

    async def generate_communication(
        self,
        action_plan: ActionPlan | dict | None = None,
        patient_context: PatientContext | dict | None = None,
        purpose: str = "健康提醒与随访协调",
    ) -> str:
        """生成一段面向患者的沟通文本（温和、易懂、尊重）。"""
        self._reset_counters()

        user_content = (
            f"请撰写一条面向患者的沟通消息，目的：{purpose}。\n\n"
            f"【患者信息】\n{self._dumps(self._to_plain(patient_context) or '无')}\n\n"
            f"【行动计划（如有）】\n{self._dumps(self._to_plain(action_plan) or '无')}\n\n"
            '【输出格式】严格输出如下结构的 JSON：\n{"patient_message": "……"}'
        )

        data = await self._invoke_json(user_content)
        if data is None:
            logger.warning(f"{self.display_name}: 沟通文本生成降级")
            return "您好，我是您的家庭医生团队助理，稍后会与您联系沟通后续安排。"
        return self._guard_patient_text(data.get("patient_message", "") or "")

    # ────────────────────────────────────────────────────────
    # 基类通用入口
    # ────────────────────────────────────────────────────────

    async def execute(
        self,
        patient_context: PatientContext | None = None,
        clinical_context: ClinicalContext | None = None,
        messages: list | None = None,
        task_description: str | None = None,
        **kwargs,
    ) -> AgentResult:
        """通用入口：拆解行动计划并回包 AgentResult。"""
        action_plan = kwargs.get("action_plan") or ActionPlan(
            summary=task_description or ""
        )
        result = await self.execute_plan(action_plan, patient_context)
        return AgentResult(
            agent_role=self.role,
            agent_display_name=self.display_name,
            summary=f"[{self.display_name}] 已拆解 {len(result.tasks)} 项执行任务",
            findings=[t.title for t in result.tasks],
            recommendations=[result.patient_message] if result.patient_message else [],
            data=result.model_dump(mode="json"),
        )
