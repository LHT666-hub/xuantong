"""多模态 workflow 节点测试：图片分析 / 语音转写 / 路由。

使用 MockProvider 模拟 VisionService 和 SpeechService 的返回，
验证：
- multimodal_detection 节点正确检测输入类型
- image_analysis 节点调用 VisionService 并注入结构化数据
- speech_transcription 节点调用 SpeechService 并注入转写文本
- 条件路由正确分发到 image / audio / text 路径
- 多模态处理后进入常规 workflow 流程
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.rules.risk_classification import RiskRuleService
from app.xuantong.agents import register_all_agents
from app.xuantong.llm import LLMRuntime, MockProvider
from app.xuantong.llm.vision import BPReading, VisionService
from app.xuantong.llm.speech import SpeechService, TranscriptionResult
from app.xuantong.runtime.registry import AgentRegistry
from app.xuantong.safety import ActionGuard, HITLService, InputGuard, OutputGuard
from app.xuantong.workflow import XuantongWorkflow


# ── 测试用 Mock 响应 ──────────────────────────────────────────────

DISPATCH_JSON = json.dumps(
    {
        "intent": "health_event_triage",
        "event_summary": "血压计图片识别结果",
        "severity": "moderate",
        "selected_agents": ["nurse"],
        "reasoning": "血压偏高",
        "immediate_actions": [],
        "requires_urgent_response": False,
    },
    ensure_ascii=False,
)

ACTION_PLAN_JSON = json.dumps(
    {
        "summary": "血压偏高，建议复测",
        "clinical_assessment": "血压168/103",
        "actions": [
            {
                "type": "monitoring",
                "description": "复测血压",
                "assignee_role": "assistant",
                "priority": "high",
                "deadline_hours": 24,
            }
        ],
        "patient_communication": "您的血压有些偏高，建议安静休息后复测。",
        "followup_plan": "24小时后复测",
    },
    ensure_ascii=False,
)

NURSE_JSON = json.dumps(
    {
        "observation": "血压偏高",
        "assessment": "需关注",
        "trend_analysis": "待观察",
        "recommendations": ["复测血压"],
        "red_flags": [],
        "confidence": 0.8,
    },
    ensure_ascii=False,
)

ASSISTANT_JSON = json.dumps(
    {
        "tasks": [
            {
                "title": "提醒复测血压",
                "description": "联系患者复测血压",
                "assignee_type": "agent",
                "assignee_role": "assistant",
                "priority": "high",
                "deadline_hours": 24,
                "status": "pending",
            }
        ],
        "patient_message": "您好，请记得复测血压。",
        "family_notification": None,
    },
    ensure_ascii=False,
)

HAPPY_RESPONSES: dict[str, str] = {
    "请分析以下健康事件": DISPATCH_JSON,
    "以下是团队各成员的会诊意见": ACTION_PLAN_JSON,
    "请从护理角度": NURSE_JSON,
    "以下是家庭医生制定的行动计划": ASSISTANT_JSON,
}


@pytest.fixture
def make_workflow():
    """构建多模态测试用 workflow。"""

    def _make(responses: dict[str, str] | None = None) -> XuantongWorkflow:
        llm = LLMRuntime(MockProvider(responses=dict(responses or HAPPY_RESPONSES)))
        AgentRegistry.clear()
        register_all_agents(llm)
        return XuantongWorkflow(
            llm_runtime=llm,
            agent_registry=AgentRegistry,
            risk_service=RiskRuleService(),
            input_guard=InputGuard(),
            output_guard=OutputGuard(),
            action_guard=ActionGuard(),
            hitl_service=HITLService(),
        )

    yield _make
    AgentRegistry.clear()


# ── 测试：multimodal_detection 节点 ─────────────────────────────────


@pytest.mark.asyncio
async def test_multimodal_detection_with_image(make_workflow):
    """multimodal_detection 节点检测到图片输入。"""
    workflow = make_workflow()
    state = {
        "event_data": {
            "payload": {
                "image_data": "base64_encoded_image_data",
                "image_type": "bp_monitor",
            }
        },
        "flow_log": [],
    }
    result = await workflow._multimodal_detection_node(state)

    assert result["_has_image"] is True
    assert result["_has_audio"] is False
    assert result["image_data"] == "base64_encoded_image_data"
    assert result["image_type"] == "bp_monitor"


@pytest.mark.asyncio
async def test_multimodal_detection_with_audio(make_workflow):
    """multimodal_detection 节点检测到音频输入。"""
    workflow = make_workflow()
    state = {
        "event_data": {
            "payload": {
                "audio_data": "base64_encoded_audio_data",
                "audio_type": "voice_report",
            }
        },
        "flow_log": [],
    }
    result = await workflow._multimodal_detection_node(state)

    assert result["_has_image"] is False
    assert result["_has_audio"] is True
    assert result["audio_data"] == "base64_encoded_audio_data"


@pytest.mark.asyncio
async def test_multimodal_detection_text_only(make_workflow):
    """multimodal_detection 节点检测纯文本输入。"""
    workflow = make_workflow()
    state = {
        "event_data": {
            "payload": {"text": "我今天感觉头晕"}
        },
        "flow_log": [],
    }
    result = await workflow._multimodal_detection_node(state)

    assert result["_has_image"] is False
    assert result["_has_audio"] is False


# ── 测试：条件路由 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_after_multimodal_image(make_workflow):
    """路由到 image_analysis。"""
    workflow = make_workflow()
    state = {"_has_image": True, "_has_audio": False}
    assert workflow._route_after_multimodal(state) == "image"


@pytest.mark.asyncio
async def test_route_after_multimodal_audio(make_workflow):
    """路由到 speech_transcription。"""
    workflow = make_workflow()
    state = {"_has_image": False, "_has_audio": True}
    assert workflow._route_after_multimodal(state) == "audio"


@pytest.mark.asyncio
async def test_route_after_multimodal_text(make_workflow):
    """路由到 input_guard（纯文本）。"""
    workflow = make_workflow()
    state = {"_has_image": False, "_has_audio": False}
    assert workflow._route_after_multimodal(state) == "text"


# ── 测试：image_analysis 节点 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_image_analysis_bp_monitor(make_workflow):
    """image_analysis 节点识别血压计图片并注入结构化数据。"""
    workflow = make_workflow()

    # Mock VisionService
    mock_bp_reading = BPReading(
        systolic=168, diastolic=103, pulse=78, confidence=0.92
    )
    with patch.object(
        VisionService, "recognize_bp_monitor", new_callable=AsyncMock
    ) as mock_recognize:
        mock_recognize.return_value = mock_bp_reading

        state = {
            "event_data": {
                "payload": {
                    "image_data": "base64_image",
                    "image_type": "bp_monitor",
                }
            },
            "image_data": "base64_image",
            "image_type": "bp_monitor",
            "flow_log": [],
        }
        result = await workflow._image_analysis_node(state)

        assert result["vision_result"]["status"] == "success"
        payload = result["event_data"]["payload"]
        assert payload["systolic"] == 168
        assert payload["diastolic"] == 103
        assert payload["pulse"] == 78
        assert payload["source"] == "vision_recognition"


@pytest.mark.asyncio
async def test_image_analysis_medical_document(make_workflow):
    """image_analysis 节点 OCR 医疗文档。"""
    workflow = make_workflow()

    ocr_text = "检验报告\n白细胞: 6.5×10^9/L\n红细胞: 4.8×10^12/L"
    with patch.object(
        VisionService, "ocr_medical_document", new_callable=AsyncMock
    ) as mock_ocr:
        mock_ocr.return_value = ocr_text

        state = {
            "event_data": {
                "payload": {
                    "image_data": "base64_image",
                    "image_type": "medical_document",
                }
            },
            "image_data": "base64_image",
            "image_type": "medical_document",
            "flow_log": [],
        }
        result = await workflow._image_analysis_node(state)

        assert result["vision_result"]["status"] == "success"
        assert result["event_data"]["payload"]["text"] == ocr_text
        assert result["event_data"]["payload"]["source"] == "vision_ocr"


@pytest.mark.asyncio
async def test_image_analysis_other(make_workflow):
    """image_analysis 节点通用图片分析。"""
    workflow = make_workflow()

    with patch.object(
        VisionService, "analyze_image", new_callable=AsyncMock
    ) as mock_analyze:
        mock_analyze.return_value = "图片显示一位老人在家中"

        state = {
            "event_data": {"payload": {"image_data": "base64_image"}},
            "image_data": "base64_image",
            "image_type": "other",
            "flow_log": [],
        }
        result = await workflow._image_analysis_node(state)

        assert result["vision_result"]["status"] == "success"
        assert "image_description" in result["event_data"]["payload"]


# ── 测试：speech_transcription 节点 ─────────────────────────────────


@pytest.mark.asyncio
async def test_speech_transcription(make_workflow):
    """speech_transcription 节点转写音频并注入文本。"""
    workflow = make_workflow()

    mock_result = TranscriptionResult(
        text="我今天感觉头晕，血压可能偏高",
        language="zh",
        confidence=0.9,
    )
    with patch.object(
        SpeechService, "transcribe", new_callable=AsyncMock
    ) as mock_transcribe:
        mock_transcribe.return_value = mock_result

        state = {
            "event_data": {
                "payload": {
                    "audio_data": "base64_audio",
                    "audio_type": "voice_report",
                }
            },
            "audio_data": "base64_audio",
            "audio_type": "voice_report",
            "flow_log": [],
        }
        result = await workflow._speech_transcription_node(state)

        assert result["speech_text"] == "我今天感觉头晕，血压可能偏高"
        assert result["event_data"]["payload"]["text"] == "我今天感觉头晕，血压可能偏高"
        assert result["event_data"]["payload"]["source"] == "speech_transcription"


@pytest.mark.asyncio
async def test_speech_transcription_with_emotion(make_workflow):
    """speech_transcription 节点识别情绪。"""
    workflow = make_workflow()

    mock_result = TranscriptionResult(
        text="我很担心我的血压",
        language="zh",
        confidence=0.85,
        emotion="anxious",
    )
    with patch.object(
        SpeechService, "transcribe", new_callable=AsyncMock
    ) as mock_transcribe:
        mock_transcribe.return_value = mock_result

        state = {
            "event_data": {"payload": {"audio_data": "base64_audio"}},
            "audio_data": "base64_audio",
            "flow_log": [],
        }
        result = await workflow._speech_transcription_node(state)

        assert result["speech_text"] == "我很担心我的血压"
        assert result["event_data"]["payload"]["emotion"] == "anxious"


# ── 测试：完整 workflow 端到端（图片 → 常规流程）─────────────────────


@pytest.mark.asyncio
async def test_workflow_image_to_completion(make_workflow):
    """图片事件经 multimodal_detection → image_analysis → 常规流程完成。"""
    workflow = make_workflow()

    mock_bp_reading = BPReading(
        systolic=168, diastolic=103, pulse=78, confidence=0.92
    )

    with patch.object(
        VisionService, "recognize_bp_monitor", new_callable=AsyncMock
    ) as mock_recognize:
        mock_recognize.return_value = mock_bp_reading

        event_data = {
            "event_type": "image.uploaded",
            "patient_id": "p-001",
            "payload": {
                "image_data": "base64_image_data",
                "image_type": "bp_monitor",
            },
        }

        state = await workflow.run(event_data=event_data, thread_id="test-image-thread")

        # 验证流程经过了多模态节点
        flow_nodes = [e.get("node") for e in (state.get("flow_log") or [])]
        assert "multimodal_detection" in flow_nodes
        assert "image_analysis" in flow_nodes
        # 验证也经过了常规节点
        assert "input_guard" in flow_nodes

        # 验证 vision 结果
        assert state.get("vision_result", {}).get("status") == "success"


@pytest.mark.asyncio
async def test_workflow_audio_to_completion(make_workflow):
    """音频事件经 multimodal_detection → speech_transcription → 常规流程完成。"""
    workflow = make_workflow()

    mock_result = TranscriptionResult(
        text="我今天血压有点高，感觉头晕",
        language="zh",
        confidence=0.9,
    )

    with patch.object(
        SpeechService, "transcribe", new_callable=AsyncMock
    ) as mock_transcribe:
        mock_transcribe.return_value = mock_result

        event_data = {
            "event_type": "audio.uploaded",
            "patient_id": "p-001",
            "payload": {
                "audio_data": "base64_audio_data",
                "audio_type": "voice_report",
            },
        }

        state = await workflow.run(event_data=event_data, thread_id="test-audio-thread")

        flow_nodes = [e.get("node") for e in (state.get("flow_log") or [])]
        assert "multimodal_detection" in flow_nodes
        assert "speech_transcription" in flow_nodes
        assert "input_guard" in flow_nodes

        assert state.get("speech_text") == "我今天血压有点高，感觉头晕"


@pytest.mark.asyncio
async def test_workflow_text_bypasses_multimodal(make_workflow, bp_event):
    """纯文本事件跳过图片/音频分析直接进入常规流程。"""
    workflow = make_workflow()

    state = await workflow.run(event_data=bp_event, thread_id="test-text-thread")

    flow_nodes = [e.get("node") for e in (state.get("flow_log") or [])]
    assert "multimodal_detection" in flow_nodes
    # 不应经过图片/音频节点
    assert "image_analysis" not in flow_nodes
    assert "speech_transcription" not in flow_nodes
    # 应直接进入 input_guard
    assert "input_guard" in flow_nodes
