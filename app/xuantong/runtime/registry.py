"""Agent 和 Skill 注册表。

借鉴 fnos AI Task Registry 模式。
所有 Agent 统一注册，未实现的不允许调用。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentDefinition:
    """Agent 定义（不可变）。"""

    key: str                     # 稳定标识，如 "family_doctor"
    role: str                    # Agent 角色（对应 AgentRole 枚举值）
    display_name: str            # 中文名称
    description: str             # 职责描述
    phase: str = "consultation"  # "consultation" | "execution"
    implemented: bool = True     # 是否已实现（False = 骨架占位）
    capabilities: list[str] = field(default_factory=list)


class AgentRegistry:
    """Agent 注册表。所有 Agent 统一注册，集中管理。"""

    _agents: dict[str, AgentDefinition] = {}
    _instances: dict[str, Any] = {}

    @classmethod
    def register(cls, definition: AgentDefinition, instance: Any = None) -> None:
        """注册一个 Agent 定义及其可选实例。"""
        cls._agents[definition.key] = definition
        if instance is not None:
            cls._instances[definition.key] = instance

    @classmethod
    def get(cls, key: str) -> AgentDefinition | None:
        """按 key 获取 Agent 定义。"""
        return cls._agents.get(key)

    @classmethod
    def get_instance(cls, key: str) -> Any | None:
        """按 key 获取已注册的 Agent 实例。"""
        return cls._instances.get(key)

    @classmethod
    def list_all(cls) -> list[AgentDefinition]:
        """列出所有已注册 Agent。"""
        return list(cls._agents.values())

    @classmethod
    def list_implemented(cls) -> list[AgentDefinition]:
        """列出已实现（implemented=True）的 Agent。"""
        return [a for a in cls._agents.values() if a.implemented]

    @classmethod
    def list_by_phase(cls, phase: str) -> list[AgentDefinition]:
        """按阶段过滤 Agent。"""
        return [a for a in cls._agents.values() if a.phase == phase]

    @classmethod
    def clear(cls) -> None:
        """清除注册表（测试用）。"""
        cls._agents.clear()
        cls._instances.clear()


# ────────────────────────────────────────────────────────────
# Skill 注册表
# ────────────────────────────────────────────────────────────


class SkillDefinition:
    """Skill 定义。"""

    def __init__(
        self,
        name: str,
        description: str,
        allowed_agent_roles: list[str],
    ) -> None:
        self.name = name
        self.description = description
        self.allowed_agent_roles = allowed_agent_roles


class SkillRegistry:
    """Skill 注册表。"""

    _skills: dict[str, SkillDefinition] = {}

    @classmethod
    def register(cls, skill: SkillDefinition) -> None:
        cls._skills[skill.name] = skill

    @classmethod
    def filter_for_agent(cls, agent_role: str) -> list[SkillDefinition]:
        """返回某角色可使用的 Skill 列表。"""
        return [s for s in cls._skills.values() if agent_role in s.allowed_agent_roles]

    @classmethod
    def list_all(cls) -> list[SkillDefinition]:
        return list(cls._skills.values())

    @classmethod
    def clear(cls) -> None:
        cls._skills.clear()
