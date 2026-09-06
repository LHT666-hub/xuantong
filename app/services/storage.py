"""Supabase Storage 客户端 —— 文档/图片对象存储。

面向 changxi 前端的文档上传能力：文件字节存入 Supabase Storage 桶，
元数据由 :mod:`app.api.routes.documents` 维护。

设计原则：
- **可选依赖**：未安装 ``supabase`` 库或未配置凭据时，客户端仍可作为「空实现」
  返回占位结果，绝不因缺少云存储而使本地/测试环境崩溃。
- supabase-py 为同步 SDK，统一通过 ``asyncio.to_thread`` 卸载到线程池，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SupabaseStorageClient:
    """Supabase Storage 异步封装（惰性初始化底层 SDK 客户端）。"""

    def __init__(self, url: str, key: str, bucket: str) -> None:
        self.url = url or ""
        self.key = key or ""
        self.bucket = bucket or "documents"
        self._client: Any = None

    @property
    def configured(self) -> bool:
        """是否已配置可用的云存储凭据。"""
        return bool(self.url and self.key)

    def _bucket(self) -> Any:
        """惰性构建并返回 bucket 句柄（需要 supabase-py）。"""
        if self._client is None:
            from supabase import create_client  # 惰性导入，未安装时抛 ImportError

            self._client = create_client(self.url, self.key)
        return self._client.storage.from_(self.bucket)

    async def upload(
        self,
        path: str,
        data: bytes,
        content_type: str | None = None,
        upsert: bool = True,
    ) -> str:
        """上传字节到指定路径，返回存储路径。未配置时返回本地占位路径。"""
        if not self.configured:
            logger.info("Supabase Storage 未配置，跳过实际上传: %s", path)
            return f"local://{path}"

        def _do() -> str:
            options: dict[str, Any] = {"upsert": upsert}
            if content_type:
                options["content-type"] = content_type
            self._bucket().upload(path, data, file_options=options)
            return path

        return await asyncio.to_thread(_do)

    async def delete(self, paths: list[str]) -> None:
        """删除一个或多个对象。未配置时为空操作。"""
        if not self.configured or not paths:
            return

        def _do() -> None:
            self._bucket().remove(list(paths))

        await asyncio.to_thread(_do)

    async def presign(self, path: str, expires_in: int = 3600) -> str:
        """生成对象的预签名下载 URL。未配置时返回本地占位 URL。"""
        if not self.configured:
            return f"local://{self.bucket}/{path}?expires_in={expires_in}"

        def _do() -> str:
            res = self._bucket().create_signed_url(path, expires_in)
            if isinstance(res, dict):
                return res.get("signedURL") or res.get("signedUrl") or ""
            return getattr(res, "signedURL", "") or str(res)

        return await asyncio.to_thread(_do)


def is_storage_configured(settings: Any) -> bool:
    """判断配置中是否具备可用的 Supabase Storage 凭据。"""
    return bool(
        getattr(settings, "supabase_url", "") and getattr(settings, "supabase_key", "")
    )


def get_storage_client(settings: Any) -> SupabaseStorageClient:
    """根据配置构建 Storage 客户端（未配置时返回 configured=False 的空实现）。"""
    return SupabaseStorageClient(
        url=getattr(settings, "supabase_url", ""),
        key=getattr(settings, "supabase_key", ""),
        bucket=getattr(settings, "supabase_storage_bucket", "documents"),
    )


__all__ = [
    "SupabaseStorageClient",
    "is_storage_configured",
    "get_storage_client",
]
