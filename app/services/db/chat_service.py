"""对话消息持久化服务（数据库实现）。

使用 SQLAlchemy AsyncSession 将会话消息写入 ``chat_messages`` 表。
接口与 :class:`app.services.chat_service.ChatService`（内存实现）保持一致，
路由层据 ``app.state.session_factory`` 是否存在自动选择实现。

说明：当前数据模型仅有 ``ChatMessage``（无独立会话表），因此会话为「虚拟」
概念——由消息按 ``session_id`` 聚合派生。``create_session`` / ``get_session``
不写入独立行：新建的空会话在写入首条消息前不会出现在 ``list_sessions`` 中，
``get_session`` 对合法 UUID 返回合成会话以支持后续写入。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_message import ChatMessage
from app.utils import normalize_patient_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_uuid(value: Any) -> UUID | None:
    """将字符串/UUID 安全解析为 UUID，非法返回 None。"""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


class DbChatService:
    """基于数据库的对话会话/消息服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── 会话 ──────────────────────────────────────────────────────

    async def create_session(self, patient_id: str) -> dict[str, Any]:
        """创建新会话（虚拟，不写库），返回会话记录。"""
        return {
            "id": str(uuid4()),
            "patient_id": normalize_patient_id(patient_id or ""),
            "created_at": _now_iso(),
            "last_message_at": None,
            "message_count": 0,
        }

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """查询会话。有消息则派生真实统计；否则对合法 UUID 返回合成会话。"""
        sid = _parse_uuid(session_id)
        if sid is None:
            return None

        row = (
            await self.db.execute(
                select(
                    func.min(ChatMessage.created_at),
                    func.max(ChatMessage.created_at),
                    func.count(ChatMessage.id),
                    ChatMessage.patient_id,
                )
                .where(ChatMessage.session_id == sid)
                .group_by(ChatMessage.patient_id)
            )
        ).first()

        if row is not None and row[2]:
            created_at, last_at, count, patient_id = row
            return {
                "id": str(sid),
                "patient_id": str(patient_id),
                "created_at": created_at.isoformat() if created_at else None,
                "last_message_at": last_at.isoformat() if last_at else None,
                "message_count": count,
            }

        # 尚无消息：合成一个空会话（支持随后写入首条消息）
        return {
            "id": str(sid),
            "patient_id": "",
            "created_at": None,
            "last_message_at": None,
            "message_count": 0,
        }

    async def list_sessions(self, patient_id: str) -> list[dict[str, Any]]:
        """列出某患者的全部会话（按最近活跃时间倒序，由消息聚合派生）。"""
        pid = _parse_uuid(normalize_patient_id(patient_id or ""))
        if pid is None:
            return []

        stmt = (
            select(
                ChatMessage.session_id,
                func.min(ChatMessage.created_at).label("created_at"),
                func.max(ChatMessage.created_at).label("last_message_at"),
                func.count(ChatMessage.id).label("message_count"),
            )
            .where(ChatMessage.patient_id == pid)
            .group_by(ChatMessage.session_id)
            .order_by(func.max(ChatMessage.created_at).desc())
        )
        rows = (await self.db.execute(stmt)).all()
        return [
            {
                "id": str(r.session_id),
                "patient_id": str(pid),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_message_at": (
                    r.last_message_at.isoformat() if r.last_message_at else None
                ),
                "message_count": r.message_count,
            }
            for r in rows
        ]

    async def delete_session(self, session_id: str) -> bool:
        """删除会话下全部消息。返回是否删除了至少一行。"""
        sid = _parse_uuid(session_id)
        if sid is None:
            return False
        result = await self.db.execute(
            delete(ChatMessage).where(ChatMessage.session_id == sid)
        )
        await self.db.flush()
        return (result.rowcount or 0) > 0

    # ── 消息 ──────────────────────────────────────────────────────

    async def add_message(
        self,
        session_id: str,
        patient_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """向会话追加一条消息（写库）。"""
        sid = _parse_uuid(session_id) or uuid4()
        pid = _parse_uuid(normalize_patient_id(patient_id or "")) or uuid4()

        # 显式写入微秒精度的 created_at：TimestampMixin 的 server_default=now()
        # 在 SQLite 下仅精确到秒，同秒内多条消息会导致 list_messages 排序不稳定。
        message = ChatMessage(
            id=uuid4(),
            session_id=sid,
            patient_id=pid,
            role=role,
            content=content,
            metadata_=metadata or {},
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return self._to_dict(message)

    async def list_messages(
        self, session_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """列出会话消息（时间升序，最多返回最近 ``limit`` 条）。"""
        sid = _parse_uuid(session_id)
        if sid is None:
            return []

        stmt = select(ChatMessage).where(ChatMessage.session_id == sid)
        if limit and limit > 0:
            stmt = stmt.order_by(ChatMessage.created_at.desc()).limit(limit)
        else:
            stmt = stmt.order_by(ChatMessage.created_at.asc())

        rows = list((await self.db.execute(stmt)).scalars().all())
        if limit and limit > 0:
            rows.reverse()  # 转回升序
        return [self._to_dict(m) for m in rows]

    def _to_dict(self, message: ChatMessage) -> dict[str, Any]:
        """将 ORM 对象转换为 dict（与内存实现格式一致）。"""
        return {
            "id": str(message.id),
            "session_id": str(message.session_id),
            "patient_id": str(message.patient_id),
            "role": message.role,
            "content": message.content,
            "metadata": message.metadata_ or {},
            "created_at": (
                message.created_at.isoformat() if message.created_at else _now_iso()
            ),
        }


__all__ = ["DbChatService"]
