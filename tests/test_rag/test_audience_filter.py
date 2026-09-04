"""受众分层过滤器测试。"""

import pytest

from app.xuantong.rag.audience_filter import (
    ROLE_TO_AUDIENCE,
    Audience,
    AudienceFilter,
)
from app.xuantong.rag.models import RetrievalResult


class TestAudienceFilter:
    """测试受众分层过滤器。"""

    @pytest.fixture
    def af(self):
        return AudienceFilter()

    @pytest.fixture
    def sample_docs(self):
        """构造不同 audience 的文档列表。"""
        return [
            RetrievalResult(
                content="高血压诊断标准与治疗指南",
                source="guidelines.md",
                score=0.9,
                metadata={"audience": "doctor"},
            ),
            RetrievalResult(
                content="患者饮食与运动注意事项",
                source="patient_guide.md",
                score=0.8,
                metadata={"audience": "patient"},
            ),
            RetrievalResult(
                content="通用健康管理知识",
                source="general.md",
                score=0.7,
                metadata={"audience": "shared"},
            ),
            RetrievalResult(
                content="药物相互作用与不良反应",
                source="pharm.md",
                score=0.85,
                metadata={"audience": "pharmacist"},
            ),
            RetrievalResult(
                content="公共卫生随访服务规范",
                source="ph.md",
                score=0.75,
                metadata={"audience": "public_health"},
            ),
        ]

    # -- 按角色过滤 --

    def test_doctor_audience(self, af: AudienceFilter, sample_docs):
        """医生角色看到 doctor + shared。"""
        result = af.filter_by_role(sample_docs, "family_doctor")

        audiences = {d.metadata["audience"] for d in result}
        assert "doctor" in audiences
        assert "shared" in audiences
        assert "patient" not in audiences
        assert "pharmacist" not in audiences

    def test_patient_audience(self, af: AudienceFilter, sample_docs):
        """助手角色（面向患者）看到 patient + shared。"""
        result = af.filter_by_role(sample_docs, "assistant")

        audiences = {d.metadata["audience"] for d in result}
        assert "patient" in audiences
        assert "shared" in audiences
        assert "doctor" not in audiences

    def test_pharmacist_audience(self, af: AudienceFilter, sample_docs):
        """药师角色看到 pharmacist + doctor + shared。"""
        result = af.filter_by_role(sample_docs, "pharmacist")

        audiences = {d.metadata["audience"] for d in result}
        assert "pharmacist" in audiences
        assert "doctor" in audiences
        assert "shared" in audiences
        assert "patient" not in audiences

    def test_public_health_audience(self, af: AudienceFilter, sample_docs):
        """公卫角色看到 public_health + shared。"""
        result = af.filter_by_role(sample_docs, "public_health")

        audiences = {d.metadata["audience"] for d in result}
        assert "public_health" in audiences
        assert "shared" in audiences
        assert "doctor" not in audiences

    def test_unknown_role_gets_shared_only(self, af: AudienceFilter, sample_docs):
        """未知角色只看到 shared。"""
        result = af.filter_by_role(sample_docs, "unknown_role")

        audiences = {d.metadata["audience"] for d in result}
        assert audiences == {"shared"}

    def test_filter_empty_list(self, af: AudienceFilter):
        """空列表过滤。"""
        result = af.filter_by_role([], "family_doctor")
        assert result == []

    # -- 内容推断受众 --

    def test_infer_audience_doctor(self, af: AudienceFilter):
        """推断医生向内容。"""
        assert af.infer_audience("根据最新指南，诊断标准为...") == Audience.DOCTOR

    def test_infer_audience_pharmacist(self, af: AudienceFilter):
        """推断药师向内容。"""
        assert af.infer_audience("该药物剂量及不良反应如下...") == Audience.PHARMACIST

    def test_infer_audience_public_health(self, af: AudienceFilter):
        """推断公卫向内容。"""
        assert af.infer_audience("公共卫生随访服务规范...") == Audience.PUBLIC_HEALTH

    def test_infer_audience_patient(self, af: AudienceFilter):
        """推断患者向内容。"""
        assert af.infer_audience("患者日常注意事项及自我管理...") == Audience.PATIENT

    def test_infer_audience_shared(self, af: AudienceFilter):
        """无法推断时返回 shared。"""
        assert af.infer_audience("这是一段普通文本") == Audience.SHARED

    # -- 枚举值 --

    def test_audience_enum_values(self):
        """Audience 枚举值正确。"""
        assert Audience.PATIENT.value == "patient"
        assert Audience.DOCTOR.value == "doctor"
        assert Audience.SHARED.value == "shared"

    def test_role_mapping_completeness(self):
        """核心角色均有映射。"""
        expected_roles = {"family_doctor", "nurse", "public_health", "pharmacist", "assistant"}
        assert expected_roles == set(ROLE_TO_AUDIENCE.keys())
