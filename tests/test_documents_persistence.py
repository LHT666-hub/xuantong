"""文档元数据持久化测试（P0）。

验证 ``/api/v1/documents`` 走数据库持久化：
- 上传后元数据落库；
- **模拟服务重启**（释放旧引擎、用同一 DB 文件重建全新引擎/会话）后数据仍在；
- 分页正确（page/size/total，按患者过滤）；
- 软删除后列表不再出现；
- 404 契约（presign / delete 不存在的文档）。

这些用例使用**基于文件**的临时 SQLite（而非内存库），以便真实模拟进程重启后
从磁盘重新加载数据的场景。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 —— 确保所有模型注册到 Base.metadata
from app.database.base import Base
from app.main import app
from app.api.routes.documents import reset_documents

DOCUMENTS_URL = "/api/v1/documents"


def _make_engine_and_factory(url: str):
    engine = create_async_engine(url, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


class _FileDbHandle:
    """封装基于文件的临时 SQLite，并提供 ``restart`` 模拟进程重启。"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = None

    async def startup(self) -> None:
        self.engine, factory = _make_engine_and_factory(self.url)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        app.state.session_factory = factory

    async def restart(self) -> None:
        """模拟重启：释放旧引擎，用同一 DB 文件重建全新引擎与会话工厂。"""
        if self.engine is not None:
            await self.engine.dispose()
        self.engine, factory = _make_engine_and_factory(self.url)
        app.state.session_factory = factory

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


@pytest.fixture
async def file_db(tmp_path):
    db_path = (tmp_path / "documents.db").as_posix()
    handle = _FileDbHandle(f"sqlite+aiosqlite:///{db_path}")
    original = getattr(app.state, "session_factory", None)
    reset_documents()
    await handle.startup()
    try:
        yield handle
    finally:
        await handle.shutdown()
        app.state.session_factory = original
        reset_documents()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _upload(client, patient_id: str, name: str = "r.pdf", body: bytes = b"%PDF fake"):
    return await client.post(
        DOCUMENTS_URL,
        files={"file": (name, body, "application/pdf")},
        data={"patient_id": patient_id},
    )


# ── 落库 + 重启存活（核心验收）───────────────────────────────────────────────


async def test_upload_persists_and_survives_restart(file_db):
    async with _client() as client:
        resp = await _upload(client, "p-persist", "lab.pdf", b"%PDF-1.4 content")
        assert resp.status_code == 201, resp.text
        doc = resp.json()
        assert doc["document_id"] == doc["id"]
        patient_id = doc["patient_id"]
        assert patient_id == "p-persist"

    # 模拟服务重启：全新引擎 + 会话工厂，指向同一 DB 文件
    await file_db.restart()

    async with _client() as client:
        listing = await client.get(DOCUMENTS_URL, params={"patient_id": "p-persist"})
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 1, f"重启后文档丢失: {body}"
        assert body["documents"][0]["document_id"] == doc["document_id"]
        assert body["documents"][0]["file_name"] == "lab.pdf"
        assert body["documents"][0]["storage_path"] == doc["storage_path"]


async def test_record_contract_fields_exact(file_db):
    """上传响应字段必须逐字保持契约（不多不少）。"""
    async with _client() as client:
        resp = await _upload(client, "p-contract")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "document_id", "id", "patient_id", "doc_type", "file_name",
        "file_size", "content_type", "storage_path", "created_at",
    }


# ── 分页 ─────────────────────────────────────────────────────────────────────


async def test_pagination_across_restart(file_db):
    async with _client() as client:
        for i in range(3):
            await _upload(client, "p-page", f"doc{i}.pdf", b"x" * (i + 1))
        # 另一名患者的文档不应混入
        await _upload(client, "p-page-other", "other.pdf", b"y")

    await file_db.restart()

    async with _client() as client:
        p1 = await client.get(
            DOCUMENTS_URL, params={"patient_id": "p-page", "page": 1, "size": 2}
        )
        b1 = p1.json()
        assert b1["total"] == 3
        assert b1["page"] == 1
        assert b1["size"] == 2
        assert len(b1["documents"]) == 2

        p2 = await client.get(
            DOCUMENTS_URL, params={"patient_id": "p-page", "page": 2, "size": 2}
        )
        assert len(p2.json()["documents"]) == 1


# ── 软删除 ───────────────────────────────────────────────────────────────────


async def test_delete_soft_removes_and_persists(file_db):
    async with _client() as client:
        doc = (await _upload(client, "p-del")).json()
        deleted = await client.delete(f"{DOCUMENTS_URL}/{doc['document_id']}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": True, "document_id": doc["document_id"]}

    await file_db.restart()

    async with _client() as client:
        listing = await client.get(DOCUMENTS_URL, params={"patient_id": "p-del"})
        assert listing.json()["total"] == 0
        # 删除后再取应 404
        again = await client.delete(f"{DOCUMENTS_URL}/{doc['document_id']}")
        assert again.status_code == 404


# ── 404 契约 ─────────────────────────────────────────────────────────────────


async def test_presign_nonexistent_404(file_db):
    async with _client() as client:
        resp = await client.get(f"{DOCUMENTS_URL}/{uuid.uuid4()}/presign")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Document not found"


async def test_presign_existing_after_restart(file_db):
    async with _client() as client:
        doc = (await _upload(client, "p-presign")).json()

    await file_db.restart()

    async with _client() as client:
        resp = await client.get(f"{DOCUMENTS_URL}/{doc['document_id']}/presign")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["document_id"] == doc["document_id"]
    assert body["storage_path"] == doc["storage_path"]
    assert body["expires_in"] > 0
    assert body["url"]
