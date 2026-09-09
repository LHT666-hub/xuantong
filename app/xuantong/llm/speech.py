"""SpeechService — 语音识别服务（qwen3-asr-flash，支持方言）"""
import logging
from pydantic import BaseModel

from app.xuantong.llm.provider import ModelRequest, ModelTier

logger = logging.getLogger(__name__)


class TranscriptionResult(BaseModel):
    """语音转文字结果"""
    text: str = ""                    # 识别出的文字
    language: str = "zh"              # 检测到的语言/方言
    confidence: float = 0.0           # 识别置信度
    emotion: str = ""                 # 情绪标签（neutral/happy/sad/angry/anxious）
    duration_ms: int = 0              # 音频时长（毫秒）
    raw_response: str = ""            # 原始响应


class SpeechService:
    """语音识别服务。

    使用 qwen3-asr-flash（OpenAI 兼容模式）。
    支持：
    - 普通话、粤语、四川话、闽南语等方言自动检测
    - 情绪识别
    - 通过 language_hints 提升特定方言准确率
    """

    # 支持的方言列表
    SUPPORTED_LANGUAGES = [
        "zh",       # 普通话
        "yue",      # 粤语
        "sc",       # 四川话
        "mn",       # 闽南语
        "en",       # 英语
    ]

    def __init__(self, llm_runtime):
        """
        Args:
            llm_runtime: LLMRuntime 实例
        """
        self._runtime = llm_runtime

    async def transcribe(
        self,
        audio_url: str,
        language_hints: list[str] | None = None,
    ) -> TranscriptionResult:
        """语音转文字（支持方言）。

        Args:
            audio_url: 音频文件 URL 或 base64 数据
            language_hints: 语言提示列表，如 ["zh", "yue"]
                           默认 ["zh"]，支持粤语/四川话/闽南语自动检测

        Returns:
            TranscriptionResult 结构化结果
        """
        hints = language_hints or ["zh"]

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_url},
                    }
                ],
            }
        ]

        extra_body = {
            "asr_options": {
                "language_hints": hints,
            }
        }

        request = ModelRequest(
            model_tier=ModelTier.ASR,
            messages=messages,
            temperature=0.0,
            extra_body=extra_body,
            agent_role="asr",
        )

        try:
            response = await self._runtime.invoke(
                agent_role="asr",
                messages=request.messages,
                temperature=request.temperature,
                model_tier=ModelTier.ASR,
                extra_body=extra_body,
            )
            return TranscriptionResult(
                text=response.content,
                language=hints[0] if hints else "zh",
                confidence=0.9,  # 占位值：qwen3-asr-flash 不返回置信度；保持 float 以兼容前端契约
                raw_response=response.content,
            )
        except Exception as e:
            logger.error(f"Speech transcription failed: {e}")
            return TranscriptionResult(
                text="",
                raw_response=f"语音识别失败: {str(e)}",
            )

    async def transcribe_with_emotion(self, audio_url: str) -> TranscriptionResult:
        """语音转文字 + 情绪识别。

        使用 qwen3-asr-flash 的情绪识别能力。

        Args:
            audio_url: 音频文件 URL 或 base64 数据

        Returns:
            TranscriptionResult（含 emotion 字段）
        """
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_url},
                    }
                ],
            }
        ]

        extra_body = {
            "asr_options": {
                "language_hints": ["zh"],
                "enable_emotion_detection": True,
            }
        }

        request = ModelRequest(
            model_tier=ModelTier.ASR,
            messages=messages,
            temperature=0.0,
            extra_body=extra_body,
            agent_role="asr",
        )

        try:
            response = await self._runtime.invoke(
                agent_role="asr",
                messages=request.messages,
                temperature=request.temperature,
                model_tier=ModelTier.ASR,
                extra_body=extra_body,
            )
            # 尝试解析情绪信息（如果模型返回结构化数据）
            text = response.content
            emotion = self._extract_emotion(text)

            return TranscriptionResult(
                text=text,
                language="zh",
                confidence=0.85,  # 占位值：上游未返回置信度；保持 float 以兼容前端契约
                emotion=emotion,
                raw_response=text,
            )
        except Exception as e:
            logger.error(f"Speech transcription with emotion failed: {e}")
            return TranscriptionResult(
                text="",
                raw_response=f"语音识别失败: {str(e)}",
            )

    def _extract_emotion(self, text: str) -> str:
        """从响应文本中提取情绪标签。

        qwen3-asr-flash 可能在响应中包含情绪信息，
        具体格式取决于 API 版本。这里做基础解析。
        """
        # 如果响应是 JSON 格式，尝试提取
        import json
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data.get("emotion", "neutral")
        except (json.JSONDecodeError, TypeError):
            pass

        # 关键词匹配（简单启发式）
        emotion_keywords = {
            "angry": ["生气", "愤怒", "怒"],
            "sad": ["难过", "悲伤", "哭"],
            "happy": ["开心", "高兴", "笑"],
            "anxious": ["焦虑", "紧张", "担心"],
        }
        for emotion, keywords in emotion_keywords.items():
            if any(kw in text for kw in keywords):
                return emotion

        return "neutral"
