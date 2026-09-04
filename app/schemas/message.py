from pydantic import BaseModel
from typing import Literal, Any
from datetime import datetime


class ChatMessage(BaseModel):
    """玄同自有消息模型。核心业务不依赖 LangChain 类型。
    在 LLM 调用边界通过 message_adapter 转换为 BaseMessage。
    """
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    timestamp: datetime | None = None
    source: str | None = None  # 渠道来源
    metadata: dict[str, Any] = {}


def add_chat_messages(left: list[ChatMessage], right: list[ChatMessage]) -> list[ChatMessage]:
    """Reducer for messages in XuantongState."""
    return left + right
