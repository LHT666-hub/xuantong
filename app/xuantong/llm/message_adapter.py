"""Message Adapter — 玄同 ChatMessage ↔ LangChain / OpenAI 多模态格式转换"""
from app.schemas.message import ChatMessage


# ─── 多模态消息构建辅助函数 ───────────────────────────────────────────────

def build_text_content(text: str) -> str:
    """纯文本 content"""
    return text


def build_image_content(image_url: str, text: str = "") -> list[dict]:
    """构建图片+文本的多模态 content。

    Args:
        image_url: 图片 URL 或 base64 data URI
        text: 附加文本提示
    """
    parts = [{"type": "image_url", "image_url": {"url": image_url}}]
    if text:
        parts.append({"type": "text", "text": text})
    return parts


def build_audio_content(audio_data: str, text: str = "") -> list[dict]:
    """构建音频的多模态 content。

    Args:
        audio_data: 音频 URL 或 base64 数据
        text: 附加文本提示
    """
    parts = [{"type": "input_audio", "input_audio": {"data": audio_data}}]
    if text:
        parts.append({"type": "text", "text": text})
    return parts


def build_multimodal_message(
    role: str,
    text: str = "",
    image_url: str = "",
    audio_data: str = "",
) -> dict:
    """构建多模态消息 dict（OpenAI 格式）。

    自动判断是纯文本还是多模态。
    """
    if not image_url and not audio_data:
        return {"role": role, "content": text}

    content_parts: list[dict] = []
    if image_url:
        content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
    if audio_data:
        content_parts.append({"type": "input_audio", "input_audio": {"data": audio_data}})
    if text:
        content_parts.append({"type": "text", "text": text})

    return {"role": role, "content": content_parts}


def base64_image_to_data_uri(base64_data: str, mime_type: str = "image/jpeg") -> str:
    """将 base64 图片数据转换为 data URI"""
    if base64_data.startswith("data:"):
        return base64_data
    return f"data:{mime_type};base64,{base64_data}"


# ─── LangChain 转换（保留兼容性）─────────────────────────────────────────

def to_langchain_messages(messages: list[ChatMessage]) -> list:
    """将玄同 ChatMessage 转换为 LangChain BaseMessage 格式。
    在 LLM 调用边界使用。
    """
    from langchain_core.messages import (
        SystemMessage, HumanMessage, AIMessage, ToolMessage,
    )

    result = []
    for msg in messages:
        if msg.role == "system":
            result.append(SystemMessage(content=msg.content))
        elif msg.role == "user":
            result.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            result.append(AIMessage(content=msg.content))
        elif msg.role == "tool":
            result.append(ToolMessage(
                content=msg.content,
                tool_call_id=msg.metadata.get("tool_call_id", ""),
            ))
    return result


def from_langchain_messages(messages: list) -> list[ChatMessage]:
    """将 LangChain BaseMessage 转换为玄同 ChatMessage。"""
    from langchain_core.messages import (
        SystemMessage, HumanMessage, AIMessage, ToolMessage,
    )

    result = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, ToolMessage):
            role = "tool"
        else:
            role = "user"  # fallback

        metadata = {}
        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            metadata["tool_call_id"] = msg.tool_call_id

        result.append(ChatMessage(
            role=role,
            content=msg.content,
            metadata=metadata,
        ))
    return result
