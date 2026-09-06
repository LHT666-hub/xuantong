"""Checkpoint 管理。

LangGraph 的 checkpointer 负责持久化 State 快照，支撑：
- 断点续跑（HITL 暂停后恢复）
- 多轮对话记忆（thread_id 维度）

开发阶段使用进程内 MemorySaver；生产阶段使用 AsyncPostgresSaver
（接 Supabase/Postgres），接口保持一致，仅需切换工厂参数：

    checkpointer, close_fn = await create_checkpointer(
        backend="postgres", database_url=settings.database_url,
    )

依赖说明：postgres 后端需要可选依赖 ``langgraph-checkpoint-postgres``
（``pip install -e ".[postgres]"``），未安装或连接失败时一律优雅降级
为 MemorySaver，绝不阻断服务启动。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

# close_fn 类型别名：无参异步回调，用于关闭连接池（MemorySaver 时为 None）
CloseFn = Callable[[], Awaitable[None]] | None


def get_checkpointer(backend: str = "memory", **kwargs: Any) -> Any:
    """获取 checkpointer 实例（同步版，仅支持 memory 后端）。

    保留此函数是为了兼容 XuantongWorkflow 的同步构造路径；
    postgres 后端请使用异步工厂 :func:`create_checkpointer`。

    Args:
        backend: "memory"（开发默认）。"postgres" 需走异步工厂。
        **kwargs: 传给具体后端的参数（预留）。

    Returns:
        BaseCheckpointSaver 实例。
    """
    if backend == "postgres":
        logger.warning(
            "postgres checkpointer 需要通过异步工厂 create_checkpointer() 创建，"
            "同步路径降级为 MemorySaver"
        )
    return MemorySaver()


def _to_psycopg_dsn(database_url: str) -> str:
    """将 SQLAlchemy async URL 转为 psycopg 可识别的 DSN。

    postgresql+asyncpg://user:pass@host/db → postgresql://user:pass@host/db
    postgresql+psycopg://...               → postgresql://...
    """
    return (
        database_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgresql://")
    )


async def create_checkpointer(
    backend: str = "memory",
    database_url: str = "",
) -> tuple[Any, CloseFn]:
    """异步 checkpointer 工厂。

    Args:
        backend: "memory"（开发默认）或 "postgres"（生产）。
        database_url: SQLAlchemy 风格的数据库 URL（postgres 后端必需，
            会自动转换为 psycopg DSN）。

    Returns:
        (checkpointer, close_fn) 二元组：
        - checkpointer: BaseCheckpointSaver 实例（AsyncPostgresSaver 或 MemorySaver）
        - close_fn: 异步回调，用于应用关闭时释放连接池；memory 后端为 None

    任何异常（依赖缺失、URL 非法、连接失败）都优雅降级为 MemorySaver，
    并记录日志，绝不抛出。
    """
    if backend == "postgres":
        if not database_url:
            logger.warning(
                "workflow_checkpoint_backend=postgres 但未配置 postgres database_url，"
                "降级为 MemorySaver"
            )
            return MemorySaver(), None
        if not database_url.startswith(("postgresql", "postgres")):
            logger.warning(
                "postgres checkpointer 需要 PostgreSQL URL，当前为 %s，降级为 MemorySaver",
                database_url.split("://", 1)[0],
            )
            return MemorySaver(), None
        pool = None
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool

            pg_url = _to_psycopg_dsn(database_url)
            # 连接池由应用持有，关闭时机由 lifespan 控制（checkpointer 需要
            # 存活到应用结束，故不能用临时 async with 立即释放）。
            pool = AsyncConnectionPool(
                conninfo=pg_url,
                max_size=10,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            checkpointer = AsyncPostgresSaver(pool)
            # from_conn_string 内部即此模式；setup() 幂等建表，重启后无操作。
            await checkpointer.setup()

            async def _close() -> None:
                await pool.close()

            logger.info("Postgres checkpointer 已就绪 (AsyncPostgresSaver)")
            return checkpointer, _close
        except ImportError:
            logger.warning(
                "langgraph-checkpoint-postgres 未安装"
                "（pip install -e '.[postgres]'），降级为 MemorySaver"
            )
            return MemorySaver(), None
        except Exception as e:  # noqa: BLE001 — 启动期任何异常都需降级
            logger.error(
                "创建 Postgres checkpointer 失败: %s，降级为 MemorySaver", e
            )
            # 连接池可能已建立但 setup 失败，尽力清理
            if pool is not None:
                try:
                    await pool.close()
                except Exception:  # noqa: BLE001
                    pass
            return MemorySaver(), None
    return MemorySaver(), None


__all__ = ["get_checkpointer", "create_checkpointer"]
