"""危机信号检测规则。
用于 Input Guard 阶段，在 FamilyDoctorAgent 之前直接拦截。
只有明确的危机才会拦截，否则放行给 FamilyDoctorAgent。
"""
import re


class EmergencyRuleEngine:
    """确定性危机信号检测。

    只拦截明确危机（如胸痛+呼吸困难+意识模糊）。
    药物相关关键词不拦截，而是作为路由信号传递给 FamilyDoctorAgent。
    """

    # 危机信号模式（必须非常明确才拦截）
    CRITICAL_PATTERNS = [
        r"胸痛.*呼吸困难",
        r"呼吸困难.*意识模糊",
        r"昏迷",
        r"意识丧失",
        r"大出血",
        r"呼吸骤停",
        r"心跳停止",
    ]

    # 紧急信号（提升风险等级，但不直接拦截）
    URGENT_PATTERNS = [
        r"剧烈胸痛",
        r"严重呼吸困难",
        r"意识不清",
        r"抽搐.*持续",
    ]

    @classmethod
    def is_emergency(cls, text: str) -> tuple[bool, str]:
        """检测是否为明确危机。
        返回 (is_emergency, reason)
        """
        for pattern in cls.CRITICAL_PATTERNS:
            if re.search(pattern, text):
                return True, f"检测到危机信号: 匹配模式 '{pattern}'"
        return False, ""

    @classmethod
    def is_urgent(cls, text: str) -> tuple[bool, str]:
        """检测是否为紧急信号（不拦截，但提升风险）。"""
        for pattern in cls.URGENT_PATTERNS:
            if re.search(pattern, text):
                return True, f"检测到紧急信号: 匹配模式 '{pattern}'"
        return False, ""
