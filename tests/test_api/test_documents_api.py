"""文档端点测试（changxi 前端文档管理 + 图片分析）。

覆盖路由（prefix=/api/v1）：
- POST   /documents              上传文档（multipart，201）
- GET    /documents              按患者分页列出
- GET    /documents/{id}/presign 预签名下载 URL
- DELETE /documents/{id}         删除文档
- POST   /documents/analyze      图片/文档内容分析（桥接 VisionService）

存储未配置 Supabase 时优雅降级为 local:// 占位；分析基于 MockProvider。
每个用例前后重置内存文档存储以保证隔离。
"""

import base64
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.api.routes.documents import reset_documents

DOCUMENTS_URL = "/api/v1/documents"
ANALYZE_URL = "/api/v1/documents/analyze"


@pytest.fixture(autouse=True)
def _reset_documents_store():
    reset_documents()
    yield
    reset_documents()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("utf-8")


# ── 上传 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_document():
    files = {"file": ("lab_report.pdf", b"%PDF-1.4 fake content", "application/pdf")}
    async with _client() as client:
        resp = await client.post(
            DOCUMENTS_URL,
            files=files,
            data={"patient_id": "p-doc-001", "doc_type": "lab_report"},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["document_id"] == body["id"]
    assert body["patient_id"] == "p-doc-001"
    assert body["doc_type"] == "lab_report"
    assert body["file_name"] == "lab_report.pdf"
    assert body["file_size"] == len(b"%PDF-1.4 fake content")
    assert body["content_type"] == "application/pdf"
    assert "p-doc-001" in body["storage_path"]
    assert body["created_at"]


@pytest.mark.asyncio
async def test_upload_document_default_type():
    files = {"file": ("photo.jpg", b"jpeg-bytes", "image/jpeg")}
    async with _client() as client:
        resp = await client.post(DOCUMENTS_URL, files=files, data={"patient_id": "p-doc-002"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["doc_type"] == "general"


@pytest.mark.asyncio
async def test_upload_empty_file_rejected():
    files = {"file": ("empty.txt", b"", "text/plain")}
    async with _client() as client:
        resp = await client.post(DOCUMENTS_URL, files=files, data={"patient_id": "p-doc-003"})
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_upload_requires_patient_id():
    files = {"file": ("a.pdf", b"data", "application/pdf")}
    async with _client() as client:
        resp = await client.post(DOCUMENTS_URL, files=files)
    assert resp.status_code == 422, resp.text


# ── 列表 / 分页 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_documents_and_pagination():
    async with _client() as client:
        for i in range(3):
            await client.post(
                DOCUMENTS_URL,
                files={"file": (f"doc{i}.pdf", b"x" * (i + 1), "application/pdf")},
                data={"patient_id": "p-doc-list"},
            )
        # 另一名患者的文档不应混入
        await client.post(
            DOCUMENTS_URL,
            files={"file": ("other.pdf", b"y", "application/pdf")},
            data={"patient_id": "p-doc-other"},
        )

        page1 = await client.get(DOCUMENTS_URL, params={"patient_id": "p-doc-list", "page": 1, "size": 2})
        assert page1.status_code == 200, page1.text
        b1 = page1.json()
        assert b1["total"] == 3
        assert b1["page"] == 1
        assert b1["size"] == 2
        assert len(b1["documents"]) == 2

        page2 = await client.get(DOCUMENTS_URL, params={"patient_id": "p-doc-list", "page": 2, "size": 2})
        b2 = page2.json()
        assert len(b2["documents"]) == 1


@pytest.mark.asyncio
async def test_list_documents_requires_patient_id():
    async with _client() as client:
        resp = await client.get(DOCUMENTS_URL)
    assert resp.status_code == 422, resp.text


# ── 预签名 / 删除 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_presign_document():
    async with _client() as client:
        doc = (
            await client.post(
                DOCUMENTS_URL,
                files={"file": ("r.pdf", b"data", "application/pdf")},
                data={"patient_id": "p-doc-presign"},
            )
        ).json()
        resp = await client.get(f"{DOCUMENTS_URL}/{doc['document_id']}/presign")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["document_id"] == doc["document_id"]
    assert body["url"]
    assert body["expires_in"] > 0
    assert body["storage_path"] == doc["storage_path"]


@pytest.mark.asyncio
async def test_presign_nonexistent_document():
    async with _client() as client:
        resp = await client.get(f"{DOCUMENTS_URL}/{uuid.uuid4()}/presign")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_delete_document():
    async with _client() as client:
        doc = (
            await client.post(
                DOCUMENTS_URL,
                files={"file": ("d.pdf", b"data", "application/pdf")},
                data={"patient_id": "p-doc-del"},
            )
        ).json()
        deleted = await client.delete(f"{DOCUMENTS_URL}/{doc['document_id']}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": True, "document_id": doc["document_id"]}

        # 删除后列表为空
        listing = (await client.get(DOCUMENTS_URL, params={"patient_id": "p-doc-del"})).json()
        assert listing["total"] == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_document():
    async with _client() as client:
        resp = await client.delete(f"{DOCUMENTS_URL}/{uuid.uuid4()}")
    assert resp.status_code == 404, resp.text


# ── 图片 / 文档内容分析 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_documents_analyze():
    payload = {"image_base64": _b64(b"fake-image-bytes")}
    async with _client() as client:
        resp = await client.post(ANALYZE_URL, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "analysis" in body
    assert "document_type" in body
    assert isinstance(body["findings"], list)


@pytest.mark.asyncio
async def test_documents_analyze_ocr_mode():
    payload = {"image_base64": _b64(b"fake-image-bytes"), "mode": "ocr"}
    async with _client() as client:
        resp = await client.post(ANALYZE_URL, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "ocr"
    assert body["document_type"] == "ocr"


@pytest.mark.asyncio
async def test_documents_analyze_multipart_upload():
    files = {"file": ("report.jpg", b"fake-image-bytes", "image/jpeg")}
    async with _client() as client:
        resp = await client.post(ANALYZE_URL, files=files)
    assert resp.status_code == 200, resp.text
    assert "analysis" in resp.json()


@pytest.mark.asyncio
async def test_documents_analyze_missing_data():
    async with _client() as client:
        resp = await client.post(ANALYZE_URL, json={})
    assert resp.status_code == 422, resp.text
