"""VisionService — 视觉识别服务（血压计读数、OCR、通用图片分析）"""
import json
import logging
from pydantic import BaseModel

from app.xuantong.llm.provider import ModelRequest, ModelTier

logger = logging.getLogger(__name__)


class BPReading(BaseModel):
    """血压计读数结构化结果"""
    systolic: int | None = None       # 收缩压（高压）
    diastolic: int | None = None      # 舒张压（低压）
    pulse: int | None = None          # 脉搏
    unit: str = "mmHg"
    confidence: float = 0.0           # 识别置信度 0-1
    raw_text: str = ""                # 原始识别文本


class VisionService:
    """视觉识别服务。

    使用 qwen3-vl-flash 进行图片理解，qwen3.5-ocr 进行文字提取。
    通过 LLMRuntime 统一调用。
    """

    # 血压计识别 prompt
    BP_MONITOR_PROMPT = """你是一个医疗设备读数识别专家。请仔细观察图片中血压计/血糖仪等医疗设备的屏幕显示，提取以下数值：

1. 收缩压（高压/SYS）
2. 舒张压（低压/DIA）
3. 脉搏（Pulse/心率）

请严格以 JSON 格式输出，不要包含其他文字：
{"systolic": <数值>, "diastolic": <数值>, "pulse": <数值>, "confidence": <0-1的置信度>}

如果某个数值无法识别，设为 null。"""

    # OCR prompt
    OCR_PROMPT = """请识别图片中的所有文字内容，保持原始排版格式。
如果是医疗文档（检验报告、药品标签、处方等），请特别注意：
1. 保留数值和单位
2. 保留表格结构
3. 标注不确定的文字（用[?]标记）

直接输出识别到的文字内容。"""

    def __init__(self, llm_runtime):
        """
        Args:
            llm_runtime: LLMRuntime 实例
        """
        self._runtime = llm_runtime

    async def recognize_bp_monitor(self, image_data: str | bytes) -> BPReading:
        """识别血压计读数。

        Args:
            image_data: 图片 base64 字符串、data URI 或 URL

        Returns:
            BPReading 结构化结果
        """
        image_url = self._normalize_image(image_data)

        messages = [
            {"role": "system", "content": "你是医疗设备读数识别专家，只输出JSON。"},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": self.BP_MONITOR_PROMPT},
                ],
            },
        ]

        request = ModelRequest(
            model_tier=ModelTier.VISION,
            messages=messages,
            temperature=0.1,  # 低温度确保准确
            max_tokens=256,
            agent_role="vision",
        )

        try:
            response = await self._runtime.invoke(
                agent_role="vision",
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                model_tier=ModelTier.VISION,
            )
            return self._parse_bp_response(response.content)
        except Exception as e:
            logger.error(f"BP monitor recognition failed: {e}")
            return BPReading(raw_text=f"识别失败: {str(e)}")

    async def ocr_medical_document(self, image_data: str | bytes) -> str:
        """OCR 医疗文档（检验报告、药品标签、处方等）。

        Args:
            image_data: 图片 base64 字符串、data URI 或 URL

        Returns:
            识别出的文字内容
        """
        image_url = self._normalize_image(image_data)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": self.OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                        "min_pixels": 3072,
                        "max_pixels": 8_388_608,
                    },
                ],
            },
        ]

        request = ModelRequest(
            model_tier=ModelTier.OCR,
            messages=messages,
            temperature=0.0,
            max_tokens=4096,
            agent_role="ocr",
        )

        try:
            response = await self._runtime.invoke(
                agent_role="ocr",
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                model_tier=ModelTier.OCR,
            )
            return response.content
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return f"OCR识别失败: {str(e)}"

    async def analyze_image(self, image_data: str | bytes, prompt: str) -> str:
        """通用图片分析。

        Args:
            image_data: 图片 base64 字符串、data URI 或 URL
            prompt: 分析提示词

        Returns:
            分析结果文本
        """
        image_url = self._normalize_image(image_data)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            },
        ]

        request = ModelRequest(
            model_tier=ModelTier.VISION,
            messages=messages,
            temperature=0.3,
            max_tokens=2048,
            agent_role="vision",
        )

        try:
            response = await self._runtime.invoke(
                agent_role="vision",
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                model_tier=ModelTier.VISION,
            )
            return response.content
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return f"图片分析失败: {str(e)}"

    def _normalize_image(self, image_data: str | bytes) -> str:
        """将图片数据统一为 URL 或 data URI 格式"""
        if isinstance(image_data, bytes):
            import base64
            b64 = base64.b64encode(image_data).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"

        if image_data.startswith("http://") or image_data.startswith("https://"):
            return image_data

        if image_data.startswith("data:"):
            return image_data

        # 假设是纯 base64 字符串
        return f"data:image/jpeg;base64,{image_data}"

    def _parse_bp_response(self, content: str) -> BPReading:
        """解析血压计识别的 JSON 响应"""
        try:
            # 尝试提取 JSON
            text = content.strip()
            # 处理可能的 markdown 代码块
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = json.loads(text)
            return BPReading(
                systolic=data.get("systolic"),
                diastolic=data.get("diastolic"),
                pulse=data.get("pulse"),
                confidence=data.get("confidence", 0.0),
                raw_text=content,
            )
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.warning(f"Failed to parse BP response as JSON: {e}, raw={content[:200]}")
            return BPReading(raw_text=content, confidence=0.0)
