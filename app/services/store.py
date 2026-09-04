"""开发阶段内存存储（后续迁移到 Supabase / PostgreSQL）。

当前 SQLAlchemy 模型使用 PostgreSQL 专用类型（JSONB / UUID），且 workflow
引擎遵循「不直接操作数据库」的设计原则。为保证 Event → Task → Outcome →
Timeline 的端到端闭环可演示、可测试，服务层统一读写本进程内的单例存储。

存储结构均为「纯 dict 记录」，字段与 API 响应契约保持一致，时间统一以
UTC ISO-8601 字符串保存，便于 JSON 序列化与字典序排序。
"""

from __future__ import annotations

from typing import Any


class InMemoryStore:
    """进程内单例存储（开发/演示阶段）。"""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.outcomes: dict[str, dict[str, Any]] = {}
        self.timeline: list[dict[str, Any]] = []

    def reset(self) -> None:
        """清空全部数据（测试隔离用）。"""
        self.events.clear()
        self.tasks.clear()
        self.outcomes.clear()
        self.timeline.clear()


# 全局单例：所有服务默认共享同一份存储，保证跨路由的数据一致性。
_store = InMemoryStore()


def get_store() -> InMemoryStore:
    """返回全局内存存储单例。"""
    return _store


def reset_store() -> None:
    """重置全局内存存储（测试用）。"""
    _store.reset()


__all__ = ["InMemoryStore", "get_store", "reset_store"]
