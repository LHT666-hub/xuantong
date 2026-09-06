"""文档路由 —— changxi 前端文档/图片元数据管理与对象存储。

职责（与多模态分析解耦）：
- ``POST /documents``                 上传文档（multipart），保存元数据 + 对象存储
- ``GET  /documents``                 按患者分页列出文档元数据
- ``GET  /documents/{id}/presign``    生成对象的预签名下载 URL
- ``DELETE /documents/{id}``          删除文档（元数据 + 对象存储）

图片/文档的**内容分析**由前端另行调用 ``POST /api/v1/documents/analyze``
（见 :mod:`app.api.routes.multimodal`）。本路由只负责存储与元数据 CRUD。

存储：
- 元数据当前由进程内单例承载（开发/测试阶段），生产可替换为数据库表；
- 文件字节经 :class:`app.services.storage.SupabaseStorageClient` 存入对象存储，
  未配置云存储时优雅降级为本地占位路径，绝不影响接口可用性。

该 router 在 ``app.main`` 中以 ``prefix="/api/v1"`` 注册。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from app.config import Settings
from app.services.storage import get_storage_client
from app.api.routes.multimodal import _parse_request, _resolve_media

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

settings = Settings()


# ── 文档元数据内存存储（开发/测试阶段单例）────────────────────────────────────
_DOCUMENTS: dict[str, dict[str, Any]] = {}


def reset_documents() -> None:
    """清空文档元数据存储（测试隔离用）。"""
    _DOCUMENTS.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _storage_client():
    return get_storage_client(settings)


# ── 上传 ─────────────────────────────────────────────────────────────────────


@router.post("/documents", status_code=201)
async def upload_document(
    file: UploadFile = File(..., description="上传的文档/图片文件"),
    patient_id: str = Form(..., description="所属患者标识"),
    doc_type: str = Form("general", description="文档类型，如 lab_report/prescription/image"),
) -> dict[str, Any]:
    """上传文档：保存文件字节到对象存储，并登记元数据。

    存储路径规则：``{patient_id}/{document_id}/{file_name}``。
    """
    if not patient_id or not patient_id.strip():
        raise HTTPException(status_code=422, detail="patient_id 不能为空")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="上传文件为空")

    document_id = str(uuid4())
    file_name = file.filename or f"{document_id}.bin"
    content_type = file.content_type or "application/octet-stream"
    storage_path = f"{patient_id.strip()}/{document_id}/{file_name}"

    # 对象存储上传（未配置云存储时降级为本地占位路径，不阻断）
    client = _storage_client()
    try:
        stored_path = await client.upload(storage_path, content, content_type=content_type)
    except Exception as e:  # noqa: BLE001 — 云存储异常不应使上传接口 500
        logger.warning("documents: 对象存储上传失败，降级登记元数据: %s", e)
        stored_path = storage_path

    record = {
        "document_id": document_id,
        "id": document_id,
        "patient_id": patient_id.strip(),
        "doc_type": doc_type,
        "file_name": file_name,
        "file_size": len(content),
        "content_type": content_type,
        "storage_path": stored_path,
        "created_at": _now_iso(),
    }
    _DOCUMENTS[document_id] = record
    logger.info("documents: 已登记文档 %s (%s, %d bytes)", document_id, doc_type, len(content))
    return dict(record)


# ── 列表（分页）──────────────────────────────────────────────────────────────


@router.get("/documents")
async def list_documents(
    patient_id: str = Query(..., description="按患者过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """按患者分页列出文档元数据（新→旧）。"""
    matched = [
        d for d in _DOCUMENTS.values() if d["patient_id"] == patient_id.strip()
    ]
    matched.sort(key=lambda d: d.get("created_at") or "", reverse=True)

    total = len(matched)
    start = (page - 1) * size
    end = start + size
    page_items = matched[start:end]

    return {
        "documents": [dict(d) for d in page_items],
        "total": total,
        "page": page,
        "size": size,
    }


# ── 预签名 URL ───────────────────────────────────────────────────────────────


@router.get("/documents/{document_id}/presign")
async def presign_document(
    document_id: str,
    expires_in: int = Query(None, ge=1, le=86400, description="URL 有效期（秒）"),
) -> dict[str, Any]:
    """生成文档对象的预签名下载 URL。"""
    record = _DOCUMENTS.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found")

    ttl = expires_in or settings.supabase_presign_expires_seconds
    client = _storage_client()
    try:
        url = await client.presign(record["storage_path"], expires_in=ttl)
    except Exception as e:  # noqa: BLE001
        logger.warning("documents: 预签名失败，返回占位 URL: %s", e)
        url = f"local://{record['storage_path']}"

    return {
        "document_id": document_id,
        "url": url,
        "expires_in": ttl,
        "storage_path": record["storage_path"],
    }


# ── 删除 ─────────────────────────────────────────────────────────────────────


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str) -> dict[str, Any]:
    """删除文档：移除元数据并尽力删除对象存储中的文件。"""
    record = _DOCUMENTS.pop(document_id, None)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found")

    client = _storage_client()
    try:
        await client.delete([record["storage_path"]])
    except Exception as e:  # noqa: BLE001 — 存储删除失败不影响元数据删除结果
        logger.warning("documents: 对象存储删除失败（元数据已删除）: %s", e)

    return {"deleted": True, "document_id": document_id}


# ── 图片 / 文档内容分析（桥接 VisionService）─────────────────────────────────

_DOCUMENT_ANALYSIS_PROMPT = """你是一位医疗文档与图片解读助手。请分析这张图片/文档，输出：
1. 文档类型（如：血压计读数、检验报告、处方、药品标签、病历、其他）；
2. 关键信息与数值的解读（保留单位）；
3. 需要关注的异常或提示（findings，逐条列出）。
用简洁清晰的中文分点说明，不要臆造不存在的信息，也不要直接下诊断。"""


def _get_vision_service(request: Request):
    """获取 VisionService，缺失时用 llm_runtime 惰性构建并缓存到 app.state。"""
    svc = getattr(request.app.state, "vision_service", None)
    if svc is None:
        from app.xuantong.llm.vision import VisionService

        svc = VisionService(request.app.state.llm_runtime)
        request.app.state.vision_service = svc
    return svc


def _extract_findings(analysis: str) -> list[str]:
    """从分析文本中启发式提取逐条 findings（按行切分，去除编号/项目符号）。"""
    if not analysis:
        return []
    findings: list[str] = []
    for line in analysis.splitlines():
        text = line.strip().lstrip("-*•\u3000 ").strip()
        while text and (text[0].isdigit() or text[0] in ".、)）("):
            text = text[1:].strip()
        if len(text) >= 2:
            findings.append(text)
    return findings[:10]


@router.post("/documents/analyze")
async def analyze_document(request: Request) -> dict:
    """图片/文档内容分析（不落地存储，仅返回解读结果）。

    请求（二选一）：
    - multipart/form-data：``file``（图片文件）+ 可选 ``mode`` / ``prompt``
    - application/json：``image_base64`` 或 ``image_url`` + 可选 ``mode`` / ``prompt``

    ``mode`` 取值：``analyze``（默认）/ ``ocr`` / ``bp``（血压计读数结构化）。
    返回：``{analysis, document_type, findings, mode}``。
    """
    file_bytes, upload_mime, params = await _parse_request(request)

    image = _resolve_media(
        file_bytes,
        params,
        b64_keys=("image_base64", "image", "data"),
        url_keys=("image_url", "url"),
        upload_mime=upload_mime,
        fallback_mime="image/jpeg",
    )

    mode = str(params.get("mode") or "analyze").strip().lower()
    prompt = params.get("prompt")
    prompt = prompt.strip() if isinstance(prompt, str) and prompt.strip() else None

    vision_service = _get_vision_service(request)
    try:
        if mode == "ocr":
            text = await vision_service.ocr_medical_document(image)
            return {"analysis": text, "document_type": "ocr", "findings": [], "mode": mode}
        if mode == "bp":
            reading = await vision_service.recognize_bp_monitor(image)
            findings = []
            if reading.systolic is not None:
                findings.append(f"收缩压 {reading.systolic} {reading.unit}")
            if reading.diastolic is not None:
                findings.append(f"舒张压 {reading.diastolic} {reading.unit}")
            if reading.pulse is not None:
                findings.append(f"脉搏 {reading.pulse} 次/分")
            analysis = (
                f"血压读数：{reading.systolic}/{reading.diastolic} {reading.unit}"
                if reading.systolic is not None and reading.diastolic is not None
                else (reading.raw_text or "未能识别血压读数")
            )
            return {
                "analysis": analysis,
                "document_type": "bp_monitor",
                "findings": findings,
                "mode": mode,
                "reading": reading.model_dump(mode="json"),
            }
        analysis = await vision_service.analyze_image(
            image, prompt or _DOCUMENT_ANALYSIS_PROMPT
        )
        return {
            "analysis": analysis,
            "document_type": "medical_document",
            "findings": _extract_findings(analysis),
            "mode": "analyze",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("documents/analyze: 分析失败: %s", e)
        raise HTTPException(status_code=502, detail=f"文档分析失败: {e}")


__all__ = ["router", "reset_documents"]
