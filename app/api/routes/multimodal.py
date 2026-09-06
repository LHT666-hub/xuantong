"""多模态路由 —— 语音转写。

面向 changxi iOS 前端，提供语音转文字端点：
- ``POST /speech/transcribe``  —— 语音转文字（桥接 ``app.state.speech_service``）

图片/文档相关能力（上传、元数据、预签名、内容分析）已迁移至
:mod:`app.api.routes.documents`，本模块专注于**语音**，并对外复用一组通用的
请求/媒体解析工具（``_parse_request`` / ``_resolve_media`` 等）。

端点**同时兼容**两种上传方式：
1. ``multipart/form-data``：文件字段 ``file``（``UploadFile``）+ 可选表单参数；
2. ``application/json``：base64 字符串字段（``audio_base64``）或直传 URL（``audio_url``）。

该 router 在 ``app.main`` 中以 ``prefix="/api/v1"`` 注册，最终路径为
``POST /api/v1/speech/transcribe``。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["multimodal"])


# ── 服务懒加载（conftest/测试环境可能未预置多模态服务）────────────────────────


def _get_speech_service(request: Request):
    """获取 SpeechService，缺失时用 llm_runtime 惰性构建并缓存到 app.state。"""
    svc = getattr(request.app.state, "speech_service", None)
    if svc is None:
        from app.xuantong.llm.speech import SpeechService

        svc = SpeechService(request.app.state.llm_runtime)
        request.app.state.speech_service = svc
    return svc


# ── 请求解析工具（documents.py 复用）─────────────────────────────────────────


async def _parse_request(
    request: Request, file_field: str = "file"
) -> tuple[bytes | None, str | None, dict]:
    """统一解析 multipart/form-data 与 application/json 两种请求。

    Returns:
        (file_bytes, upload_mime, params)：file_bytes 为上传文件的原始字节
        （无上传则 None）；upload_mime 为上传文件声明的 content-type；params 为
        其余参数（JSON body 或表单标量字段）组成的 dict。
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get(file_field)
        file_bytes = await upload.read() if upload is not None else None
        upload_mime = getattr(upload, "content_type", None) if upload is not None else None
        params: dict = {}
        for key, value in form.items():
            if key == file_field:
                continue
            params[key] = value
        return file_bytes, upload_mime, params

    # 其余按 JSON 处理
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
    return None, None, body


def _normalize_json_list(value) -> list[str] | None:
    """将语言提示参数归一化为 list[str]（兼容 JSON 字符串 / 逗号分隔 / 列表）。"""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed if v]
            except (json.JSONDecodeError, ValueError):
                pass
        return [p.strip() for p in text.split(",") if p.strip()]
    return None


def _to_data_uri(file_bytes: bytes, content_type: str | None, fallback_mime: str) -> str:
    """将上传的文件字节编码为 data URI。"""
    mime = content_type or fallback_mime
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _resolve_media(
    file_bytes: bytes | None,
    params: dict,
    b64_keys: tuple[str, ...],
    url_keys: tuple[str, ...],
    upload_mime: str | None,
    fallback_mime: str,
) -> str:
    """从上传文件或参数中解析出可供多模态服务使用的媒体标识（URL 或 data URI）。"""
    if file_bytes:
        return _to_data_uri(file_bytes, upload_mime, fallback_mime)

    for key in url_keys:
        url = params.get(key)
        if isinstance(url, str) and url.strip():
            return url.strip()

    for key in b64_keys:
        raw = params.get(key)
        if isinstance(raw, str) and raw.strip():
            data = raw.strip()
            if data.startswith("data:") or data.startswith("http://") or data.startswith("https://"):
                return data
            # 纯 base64 → 校验并包装为 data URI
            try:
                base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(
                    status_code=422, detail=f"字段 {key} 不是合法的 base64 数据"
                )
            return f"data:{fallback_mime};base64,{data}"

    raise HTTPException(status_code=422, detail="缺少音频/图片数据（file 上传或 base64/url 字段）")


# ── 语音转写 ─────────────────────────────────────────────────────────────────


@router.post("/speech/transcribe")
async def speech_transcribe(request: Request) -> dict:
    """语音转文字。

    请求（二选一）：
    - multipart/form-data：``file``（音频文件）+ 可选 ``language_hints`` / ``with_emotion``
    - application/json：``audio_base64`` 或 ``audio_url`` + 可选 ``language_hints`` / ``with_emotion``

    返回：``{text, language, duration_ms, confidence, emotion}``。
    """
    file_bytes, upload_mime, params = await _parse_request(request)

    audio = _resolve_media(
        file_bytes,
        params,
        b64_keys=("audio_base64", "audio", "data"),
        url_keys=("audio_url", "url"),
        upload_mime=upload_mime,
        fallback_mime="audio/wav",
    )

    language_hints = _normalize_json_list(params.get("language_hints"))
    with_emotion = str(params.get("with_emotion", "")).lower() in {"1", "true", "yes"}

    speech_service = _get_speech_service(request)
    try:
        if with_emotion:
            result = await speech_service.transcribe_with_emotion(audio)
        else:
            result = await speech_service.transcribe(audio, language_hints=language_hints)
    except Exception as e:
        logger.error("speech/transcribe: 转写失败: %s", e)
        raise HTTPException(status_code=502, detail=f"语音转写失败: {e}")

    return {
        "text": result.text,
        "language": result.language,
        "duration_ms": result.duration_ms,
        "confidence": result.confidence,
        "emotion": result.emotion,
    }
