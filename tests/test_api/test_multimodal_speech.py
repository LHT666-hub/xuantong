"""语音转写端点测试：POST /api/v1/speech/transcribe。

图片/文档分析已迁移至 :mod:`app.api.routes.documents`，其测试见
``test_documents_api.py``；本文件专注于**语音**能力。

均基于 MockProvider（conftest 的 setup_app_state 注入），无需真实 API Key。
"""

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

TRANSCRIBE_URL = "/api/v1/speech/transcribe"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("utf-8")


@pytest.mark.asyncio
async def test_speech_transcribe():
    transport = ASGITransport(app=app)
    payload = {"audio_base64": _b64(b"fake-audio-bytes"), "language_hints": ["zh"]}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(TRANSCRIBE_URL, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "text" in body
    assert body["language"] == "zh"
    assert "duration_ms" in body


@pytest.mark.asyncio
async def test_speech_transcribe_multipart_upload():
    transport = ASGITransport(app=app)
    files = {"file": ("audio.wav", b"fake-audio-bytes", "audio/wav")}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(TRANSCRIBE_URL, files=files, data={"language_hints": "zh"})
    assert resp.status_code == 200, resp.text
    assert "text" in resp.json()


@pytest.mark.asyncio
async def test_speech_transcribe_with_emotion():
    transport = ASGITransport(app=app)
    payload = {"audio_base64": _b64(b"fake-audio-bytes"), "with_emotion": "true"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(TRANSCRIBE_URL, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "text" in body
    assert "emotion" in body


@pytest.mark.asyncio
async def test_speech_transcribe_missing_data():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(TRANSCRIBE_URL, json={})
    assert resp.status_code == 422, resp.text
