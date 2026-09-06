"""对话消息持久化服务（内存实现）。

面向 changxi 前端的会话/消息存储。开发阶段由本进程内的单例承载，
生产环境可平滑替换为 :class:`app.services.db.chat_service.DbChatService`
（接口保持一致）。

会话（session）是消息的逻辑分组：一个患者可拥有多个会话，每个会话下
按时间顺序保存 user / assistant / system 消息。

存储结构均为「纯 dict 记录」，时间统一以 UTC ISO-8601 字符串保存，
便于 JSON 序列化与字典序排序。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.utils import normalize_patient_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatService:
    """基于内存的对话会话/消息服务（开发/测试阶段）。"""

    def __init__(self) -> None:
        # 消息按插入顺序保存（即时间升序）
        self._messages: list[dict[str, Any]] = []
        # 会话表：session_id(str) -> session dict
        self._sessions: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        """清空全部会话与消息（测试隔离用）。"""
        self._messages.clear()
        self._sessions.clear()

    # ── 会话 ──────────────────────────────────────────────────────

    async def create_session(self, patient_id: str) -> dict[str, Any]:
        """创建新会话，返回会话记录。"""
        session_id = str(uuid4())
        session = {
            "id": session_id,
            "patient_id": normalize_patient_id(patient_id or ""),
            "created_at": _now_iso(),
            "last_message_at": None,
            "message_count": 0,
        }
        self._sessions[session_id] = session
        return dict(session)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """查询会话（供路由做存在性校验）。"""
        session = self._sessions.get(str(session_id))
        return dict(session) if session is not None else None

    async def list_sessions(self, patient_id: str) -> list[dict[str, Any]]:
        """列出某患者的全部会话（按最近活跃时间倒序）。"""
        pid = normalize_patient_id(patient_id or "")
        sessions = [s for s in self._sessions.values() if s["patient_id"] == pid]
        sessions.sort(
            key=lambda s: (s.get("last_message_at") or s.get("created_at") or ""),
            reverse=True,
        )
        return [dict(s) for s in sessions]

    async def delete_session(self, session_id: str) -> bool:
        """删除会话及其全部消息。返回是否删除了存在的会话。"""
        sid = str(session_id)
        if sid not in self._sessions:
            return False
        del self._sessions[sid]
        self._messages = [m for m in self._messages if m["session_id"] != sid]
        return True

    # ── 消息 ──────────────────────────────────────────────────────

    async def add_message(
        self,
        session_id: str,
        patient_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """向会话追加一条消息。

        若会话不存在则隐式创建（便于兼容 POST /chat 一次性写入）。
        """
        sid = str(session_id)
        session = self._sessions.get(sid)
        if session is None:
            session = {
                "id": sid,
                "patient_id": normalize_patient_id(patient_id or ""),
                "created_at": _now_iso(),
                "last_message_at": None,
                "message_count": 0,
            }
            self._sessions[sid] = session

        now = _now_iso()
        message = {
            "id": str(uuid4()),
            "session_id": sid,
            "patient_id": session["patient_id"],
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_at": now,
        }
        self._messages.append(message)
        session["last_message_at"] = now
        session["message_count"] += 1
        return dict(message)

    async def list_messages(
        self, session_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """列出会话消息（时间升序，最多返回最近 ``limit`` 条）。"""
        sid = str(session_id)
        msgs = [m for m in self._messages if m["session_id"] == sid]
        if limit and limit > 0:
            msgs = msgs[-limit:]
        return [dict(m) for m in msgs]


# ── 全局单例（内存模式跨请求共享）──────────────────────────────────────────
_chat_service = ChatService()


def get_chat_service() -> ChatService:
    """返回内存对话服务单例。"""
    return _chat_service


def reset_chat_service() -> None:
    """重置内存对话服务单例（测试用）。"""
    _chat_service.reset()


__all__ = ["ChatService", "get_chat_service", "reset_chat_service"]
