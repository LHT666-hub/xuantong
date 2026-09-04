"""Checkpoint 管理。

LangGraph 的 checkpointer 负责持久化 State 快照，支撑：
- 断点续跑（HITL 暂停后恢复）
- 多轮对话记忆（thread_id 维度）

开发阶段使用进程内 MemorySaver；生产阶段可替换为 PostgresSaver
（接 Supabase），接口保持一致，仅需切换本工厂函数。
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer(backend: str = "memory", **kwargs: Any) -> Any:
    """获取 checkpointer 实例。

    Args:
        backend: "memory"（开发默认）或 "postgres"（生产，预留）。
        **kwargs: 传给具体后端的参数（如 postgres 的连接串）。

    Returns:
        BaseCheckpointSaver 实例。当前仅实现 memory 后端。
    """
    if backend == "postgres":
        # 生产阶段接 Supabase/Postgres：
        #   from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        #   return AsyncPostgresSaver.from_conn_string(kwargs["conn_string"])
        # Phase 2 尚未接入，降级为内存实现，避免误用导致数据丢失假象。
        return MemorySaver()
    return MemorySaver()


__all__ = ["get_checkpointer"]
