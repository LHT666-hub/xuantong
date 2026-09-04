"""药物相互作用（DDI）检测服务。

内置常见降压药 DDI 规则表，支持正向/反向查找。
"""

from pydantic import BaseModel
from enum import Enum


class DDISeverity(str, Enum):
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"


class DDIPair(BaseModel):
    drug_a: str
    drug_b: str
    severity: DDISeverity
    description: str
    recommendation: str


class DDIResult(BaseModel):
    severity: DDISeverity
    pairs: list[DDIPair] = []
    recommendations: list[str] = []
    safe: bool = True


class DrugInteractionService:
    """药物相互作用检测服务"""

    # 常见降压药 DDI 规则表（20 对）
    DDI_RULES: dict[tuple[str, str], tuple] = {
        ("氨氯地平", "地尔硫卓"): (
            DDISeverity.MODERATE,
            "钙通道阻滞剂联用可能增加低血压风险",
            "监测血压，考虑调整剂量",
        ),
        ("氨氯地平", "辛伐他汀"): (
            DDISeverity.MODERATE,
            "氨氯地平可增加辛伐他汀血药浓度",
            "辛伐他汀日剂量不超过20mg",
        ),
        ("依那普利", "螺内酯"): (
            DDISeverity.MODERATE,
            "ACEI+保钾利尿剂可能增加高钾血症风险",
            "监测血钾水平",
        ),
        ("依那普利", "氯化钾"): (
            DDISeverity.MODERATE,
            "ACEI+钾补充剂可能增加高钾血症风险",
            "监测血钾，谨慎补钾",
        ),
        ("氯沙坦", "螺内酯"): (
            DDISeverity.MODERATE,
            "ARB+保钾利尿剂可能增加高钾血症风险",
            "监测血钾水平",
        ),
        ("氢氯噻嗪", "地高辛"): (
            DDISeverity.SEVERE,
            "噻嗪类利尿剂可引起低钾，增加地高辛毒性风险",
            "监测血钾和地高辛血药浓度",
        ),
        ("氢氯噻嗪", "锂盐"): (
            DDISeverity.SEVERE,
            "噻嗪类利尿剂减少锂排泄，增加锂中毒风险",
            "避免联用，或密切监测锂血药浓度",
        ),
        ("美托洛尔", "维拉帕米"): (
            DDISeverity.SEVERE,
            "β受体阻滞剂+非二氢吡啶类CCB可能引起严重心动过缓",
            "避免联用，或密切监测心率和血压",
        ),
        ("美托洛尔", "地尔硫卓"): (
            DDISeverity.SEVERE,
            "β受体阻滞剂+非二氢吡啶类CCB可能引起严重心动过缓",
            "避免联用，或密切监测心率和血压",
        ),
        ("硝苯地平", "利福平"): (
            DDISeverity.MODERATE,
            "利福平诱导CYP3A4，降低硝苯地平血药浓度",
            "监测血压，可能需要增加硝苯地平剂量",
        ),
        ("缬沙坦", "NSAIDs"): (
            DDISeverity.MODERATE,
            "NSAIDs可能减弱ARB的降压效果，增加肾损害风险",
            "监测血压和肾功能",
        ),
        ("培哚普利", "别嘌醇"): (
            DDISeverity.MINOR,
            "ACEI可能增加别嘌醇过敏反应风险",
            "监测皮疹等过敏症状",
        ),
        ("吲达帕胺", "地高辛"): (
            DDISeverity.SEVERE,
            "袢利尿剂可引起低钾，增加地高辛毒性风险",
            "监测血钾和地高辛血药浓度",
        ),
        ("卡托普利", "环孢素"): (
            DDISeverity.MODERATE,
            "ACEI+环孢素可能增加肾功能损害风险",
            "密切监测肾功能",
        ),
        ("氨氯地平", "环孢素"): (
            DDISeverity.MODERATE,
            "CCB可能增加环孢素血药浓度",
            "监测环孢素血药浓度和肾功能",
        ),
        ("氯沙坦", "氟康唑"): (
            DDISeverity.MINOR,
            "氟康唑可能增加氯沙坦血药浓度",
            "监测血压",
        ),
        ("厄贝沙坦", "钾补充剂"): (
            DDISeverity.MODERATE,
            "ARB+钾补充剂可能增加高钾血症风险",
            "监测血钾",
        ),
        ("比索洛尔", "胰岛素"): (
            DDISeverity.MINOR,
            "β受体阻滞剂可能掩盖低血糖症状",
            "教育患者识别低血糖的非心率症状",
        ),
        ("特拉唑嗪", "西地那非"): (
            DDISeverity.MODERATE,
            "α受体阻滞剂+PDE5抑制剂可能引起低血压",
            "从低剂量开始，监测血压",
        ),
        ("多沙唑嗪", "西地那非"): (
            DDISeverity.MODERATE,
            "α受体阻滞剂+PDE5抑制剂可能引起低血压",
            "从低剂量开始，监测血压",
        ),
    }

    def check_ddi(self, medications: list[str]) -> DDIResult:
        """检查药物列表的相互作用"""
        pairs: list[DDIPair] = []
        recommendations: list[str] = []
        max_severity = DDISeverity.NONE

        for i, drug_a in enumerate(medications):
            for drug_b in medications[i + 1:]:
                # 正向查找
                key = (drug_a, drug_b)
                rule = self.DDI_RULES.get(key)
                if rule is None:
                    # 反向查找
                    key = (drug_b, drug_a)
                    rule = self.DDI_RULES.get(key)
                if rule is not None:
                    severity, desc, rec = rule
                    pairs.append(DDIPair(
                        drug_a=drug_a,
                        drug_b=drug_b,
                        severity=severity,
                        description=desc,
                        recommendation=rec,
                    ))
                    recommendations.append(rec)
                    if self._severity_rank(severity) > self._severity_rank(max_severity):
                        max_severity = severity

        return DDIResult(
            severity=max_severity,
            pairs=pairs,
            recommendations=recommendations,
            safe=max_severity in (DDISeverity.NONE, DDISeverity.MINOR),
        )

    @staticmethod
    def _severity_rank(severity: DDISeverity) -> int:
        return {
            DDISeverity.NONE: 0,
            DDISeverity.MINOR: 1,
            DDISeverity.MODERATE: 2,
            DDISeverity.SEVERE: 3,
        }[severity]
