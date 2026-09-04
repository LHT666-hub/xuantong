"""BaseAgent 辅助方法（JSON 提取 / 序列化 / OutputGuard）测试。"""

from datetime import datetime

from app.schemas.patient import PatientContext
from app.xuantong.agents.base import BaseAgent
from app.xuantong.agents.nurse import NurseAgent


def test_extract_json_plain():
    assert BaseAgent._extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_code_fence():
    text = '```json\n{"a": 1}\n```'
    assert BaseAgent._extract_json(text) == {"a": 1}


def test_extract_json_embedded_in_prose():
    text = '好的，结果如下：\n{"severity": "high", "x": [1,2]}\n希望有帮助。'
    assert BaseAgent._extract_json(text) == {"severity": "high", "x": [1, 2]}


def test_extract_json_invalid_returns_none():
    assert BaseAgent._extract_json("完全不是 JSON") is None
    assert BaseAgent._extract_json("") is None


def test_extract_json_array_returns_none():
    # 仅接受 JSON 对象
    assert BaseAgent._extract_json("[1, 2, 3]") is None


def test_dumps_handles_pydantic_and_datetime():
    patient = PatientContext(patient_id="p1", name="张三", age=60, gender="男")
    text = BaseAgent._dumps({"patient": patient, "at": datetime(2026, 1, 1)})
    assert "张三" in text
    assert "2026" in text


def test_to_plain_converts_model():
    patient = PatientContext(patient_id="p1", name="张三", age=60, gender="男")
    plain = BaseAgent._to_plain(patient)
    assert isinstance(plain, dict)
    assert plain["name"] == "张三"


def test_to_plain_passthrough_dict():
    assert BaseAgent._to_plain({"a": 1}) == {"a": 1}


def test_guard_patient_text_rewrites_diagnostic():
    agent = NurseAgent(None)
    out = agent._guard_patient_text("你得了高血压，请注意休息。")
    assert "你得了" not in out


def test_guard_patient_text_blocks_hallucination():
    agent = NurseAgent(None)
    out = agent._guard_patient_text("我们有特效药可以根治高血压。")
    # 幻觉内容被阻断，替换为中性占位文本
    assert "特效药" not in out
    assert "家庭医生团队" in out


def test_guard_patient_text_passes_benign():
    agent = NurseAgent(None)
    text = "建议您低盐饮食并规律监测血压。"
    assert agent._guard_patient_text(text) == text


def test_guard_patient_text_empty():
    agent = NurseAgent(None)
    assert agent._guard_patient_text("") == ""
