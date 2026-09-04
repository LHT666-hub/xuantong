"""AI 输出校验器。
确保 AI 生成的数据在写入数据库前经过校验。
借鉴 fnos: AI 输出不得未经校验直接写入核心业务数据。
"""


class HealthDataValidator:
    """健康数据校验器骨架。V0.1 先建立接口。"""

    @staticmethod
    def validate_bp(systolic: float, diastolic: float) -> tuple[bool, str]:
        """校验血压值合理性"""
        if systolic < 60 or systolic > 260:
            return False, f"收缩压 {systolic} 超出合理范围 (60-260)"
        if diastolic < 30 or diastolic > 160:
            return False, f"舒张压 {diastolic} 超出合理范围 (30-160)"
        if systolic <= diastolic:
            return False, "收缩压应高于舒张压"
        return True, ""

    @staticmethod
    def validate_glucose(value: float) -> tuple[bool, str]:
        """校验血糖值合理性"""
        if value < 1.0 or value > 40.0:
            return False, f"血糖值 {value} 超出合理范围 (1.0-40.0)"
        return True, ""
