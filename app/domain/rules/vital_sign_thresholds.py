"""临床阈值常量。
基于常见临床指南（如 ADA 2024、ACC/AHA 2017），
但 V0.1 使用简化版本，后续必须用正式指南/本地规范验证。
"""


class VitalSignThresholds:
    """生命体征阈值常量。
    这些是确定性规则的"安全地板"——LLM 判断结果与这些规则取 max，保证安全底线。
    """

    # 血压阈值 (mmHg)
    BP_SYSTOLIC_NORMAL_HIGH = 120    # 正常高值
    BP_SYSTOLIC_HIGH = 140           # 高血压 1 级
    BP_SYSTOLIC_VERY_HIGH = 160      # 高血压 2 级
    BP_SYSTOLIC_EMERGENCY = 180      # 高血压急症
    BP_DIASTOLIC_NORMAL_HIGH = 80
    BP_DIASTOLIC_HIGH = 90
    BP_DIASTOLIC_VERY_HIGH = 100
    BP_DIASTOLIC_EMERGENCY = 120

    # 血糖阈值 (mmol/L)
    GLUCOSE_LOW = 3.9               # 低血糖
    GLUCOSE_VERY_LOW = 3.0          # 严重低血糖
    GLUCOSE_FASTING_HIGH = 7.0      # 空腹血糖高
    GLUCOSE_VERY_HIGH = 16.7        # 严重高血糖
    GLUCOSE_EMERGENCY_HIGH = 22.2   # 血糖急症

    # 心率阈值 (bpm)
    HR_LOW = 50
    HR_VERY_LOW = 40
    HR_HIGH = 100
    HR_VERY_HIGH = 130
    HR_EMERGENCY = 150

    # 体温阈值 (°C)
    TEMP_LOW = 35.0
    TEMP_HIGH = 37.3
    TEMP_VERY_HIGH = 38.5
    TEMP_EMERGENCY = 39.5

    # 血氧阈值 (%)
    SPO2_LOW = 95
    SPO2_VERY_LOW = 90
    SPO2_EMERGENCY = 85
