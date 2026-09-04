"""事件分发器。接收事件并路由到玄同 Runtime 处理。"""
import logging

logger = logging.getLogger(__name__)


class EventDispatcher:
    """事件分发器骨架。V0.1 先建立接口。"""

    def __init__(self):
        self._handlers: dict[str, list] = {}

    def register_handler(self, event_type: str, handler):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def dispatch(self, event_type: str, payload: dict) -> None:
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                await handler(payload)
            except Exception as e:
                logger.error(f"Event handler error for {event_type}: {e}")
