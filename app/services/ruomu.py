"""若木 D 模式客户端。

若木在玄同中只承担证据检索：收集其知识库/联网摘要与资料卡，最终面向患者的
回答仍由玄同的家庭医生模型生成，避免多个服务同时作为“常曦”发言。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(slots=True)
class RuomuEvidence:
    brief: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    request_id: str | None = None


class RuomuKnowledgeService:
    def __init__(
        self,
        base_url: str,
        access_key: str,
        timeout: float = 25.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_key = access_key
        self.timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> bool:
        try:
            response = await self._client.get(
                f"{self.base_url}/api/health",
                headers=self._headers(),
                timeout=min(self.timeout, 8.0),
            )
            return response.status_code == 200 and response.json().get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False

    async def retrieve(
        self,
        prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> RuomuEvidence:
        """调用 D 模式并消费其 SSE，返回检索摘要和资料卡。"""
        payload: dict[str, Any] = {
            "mode": "web_knowledge",
            "prompt": prompt[:4000],
        }
        clean_history = [
            {"role": item["role"], "content": str(item["content"])[:4000]}
            for item in (history or [])[-8:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        if clean_history:
            payload["history"] = clean_history

        chunks: list[str] = []
        sources: list[dict[str, Any]] = []
        request_id: str | None = None
        async with self._client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if not raw:
                    continue
                event = json.loads(raw)
                event_type = event.get("type")
                if event_type == "delta":
                    chunks.append(str(event.get("text") or ""))
                elif event_type == "done":
                    sources = event.get("sources") or []
                    request_id = event.get("requestId")
                elif event_type == "error":
                    raise RuntimeError(str(event.get("error") or "若木检索失败"))

        return RuomuEvidence(
            brief="".join(chunks).strip(),
            sources=[item for item in sources if isinstance(item, dict)],
            request_id=request_id,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "accept": "text/event-stream",
            "content-type": "application/json",
            "x-access-key": self.access_key,
        }

__all__ = ["RuomuEvidence", "RuomuKnowledgeService"]
