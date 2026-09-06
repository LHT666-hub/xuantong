"""工作流进度中心 —— SSE 实时推送的进程内广播机制。

设计（Task #13 方案 A+C 组合）：
- ``XuantongWorkflow.stream_run()`` 桥接 LangGraph ``astream(stream_mode="updates")``，
  每完成一个节点就向对应 event_id 的 ``ProgressChannel`` 发布一条进度事件；
- SSE 端点（``app/api/routes/stream.py``）订阅频道：先回放历史（迟到的订阅者
  也能拿到已发生的节点事件），再实时等待新事件；
- 频道在工作流结束后保留（供事后连接一次性回放 + complete），由 Hub 做
  容量上限的惰性清理，避免内存无限增长。

纯 asyncio 实现，无第三方依赖，不触碰数据库。
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

# 已结束频道的保留上限（超出后按创建顺序惰性淘汰）
_MAX_CHANNELS = 256


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProgressChannel:
    """单个事件的进度广播频道（一个生产者，多个订阅者）。"""

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        self.created_at = _now_iso()
        self.history: list[dict[str, Any]] = []
        self.finished = False
        self.final_status: str | None = None
        # 每次 publish 后替换为新的 Event，订阅者持有旧引用等待，
        # 避免 wait_for 超时取消共享 Event 导致的竞态。
        self._updated = asyncio.Event()

    def publish(self, item: dict[str, Any]) -> None:
        """发布一条进度事件（自动补 timestamp）。"""
        item = {"timestamp": _now_iso(), **item}
        self.history.append(item)
        updated, self._updated = self._updated, asyncio.Event()
        updated.set()

    def finish(self, final_status: str) -> None:
        """标记工作流结束并广播终态。"""
        self.final_status = final_status
        self.publish({"type": "complete", "final_status": final_status})
        self.finished = True

    async def wait_update(self, timeout: float) -> bool:
        """等待新事件；超时返回 False（用于 SSE 空闲超时 / 心跳）。"""
        event = self._updated
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except (asyncio.TimeoutError, TimeoutError):
            return False


class WorkflowProgressHub:
    """event_id → ProgressChannel 的进程内注册表（全局单例）。"""

    def __init__(self) -> None:
        self._channels: OrderedDict[str, ProgressChannel] = OrderedDict()

    def open(self, event_id: str) -> ProgressChannel:
        """创建（或复用）事件的进度频道，并做容量清理。"""
        channel = self._channels.get(event_id)
        if channel is None:
            channel = ProgressChannel(event_id)
            self._channels[event_id] = channel
            self._evict()
        return channel

    def get(self, event_id: str) -> ProgressChannel | None:
        return self._channels.get(event_id)

    def reset(self) -> None:
        """清空全部频道（测试隔离用）。"""
        self._channels.clear()

    def _evict(self) -> None:
        """超出容量时优先淘汰已结束的旧频道，仍超限则淘汰最旧频道。"""
        if len(self._channels) <= _MAX_CHANNELS:
            return
        for key in list(self._channels):
            if len(self._channels) <= _MAX_CHANNELS:
                break
            if self._channels[key].finished:
                del self._channels[key]
        while len(self._channels) > _MAX_CHANNELS:
            self._channels.popitem(last=False)


# 全局单例：workflow（生产者）与 SSE 路由（消费者）共享
progress_hub = WorkflowProgressHub()

__all__ = ["ProgressChannel", "WorkflowProgressHub", "progress_hub"]
