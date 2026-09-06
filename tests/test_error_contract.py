"""统一错误响应契约测试（P2）。

验证 404 / 422 / 500 三类错误响应**同时**包含顶层 ``detail`` 与 ``error`` 结构，
且 ``error`` 内部同时给出 ``detail``（单数）与 ``details``（恒为数组），
实现新老客户端平滑过渡（老客户端读 detail，新客户端读 error.code/message）。
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.api.routes.documents import reset_documents
from app.api.middleware.error_handler import (
    generic_exception_handler,
    http_exception_handler,
)
from app.exceptions import ValidationError

DOCUMENTS_URL = "/api/v1/documents"


@pytest.fixture(autouse=True)
def _clean_state():
    """强制无 DB（内存路径）以获得确定性的 404，并清空内存文档存储。"""
    original = getattr(app.state, "session_factory", None)
    app.state.session_factory = None
    reset_documents()
    try:
        yield
    finally:
        app.state.session_factory = original
        reset_documents()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _assert_unified_shape(body: dict, expected_code: str):
    """断言统一错误结构：顶层 detail + error{code,message,detail,details[]}。"""
    assert "detail" in body, body
    assert "error" in body, body
    err = body["error"]
    assert err["code"] == expected_code
    assert isinstance(err["message"], str)
    assert "detail" in err          # 单数键恒存在
    assert "details" in err         # 复数键恒存在
    assert isinstance(err["details"], list), "error.details 必须恒为数组"


# ── 404（HTTPException 路径，真实请求）──────────────────────────────────────


async def test_404_has_detail_and_error():
    async with _client() as client:
        resp = await client.get(f"{DOCUMENTS_URL}/{uuid4()}/presign")
    assert resp.status_code == 404
    body = resp.json()
    # 老客户端契约：顶层 detail 逐字保留原始文案
    assert body["detail"] == "Document not found"
    _assert_unified_shape(body, "HTTP_404")
    assert body["error"]["message"] == "Document not found"


# ── 422（RequestValidationError 路径，真实请求）─────────────────────────────


async def test_422_has_detail_and_error():
    async with _client() as client:
        resp = await client.get(DOCUMENTS_URL)  # 缺少必填 patient_id
    assert resp.status_code == 422
    body = resp.json()
    _assert_unified_shape(body, "VALIDATION_ERROR")
    assert isinstance(body["detail"], str)
    assert len(body["error"]["details"]) >= 1  # 字段错误数组非空


# ── 500（未捕获异常处理器，直接调用）────────────────────────────────────────


class _FakeURL:
    path = "/api/boom"


class _FakeRequest:
    method = "GET"
    url = _FakeURL()


async def test_500_handler_has_detail_and_error():
    resp = await generic_exception_handler(_FakeRequest(), RuntimeError("boom"))
    assert resp.status_code == 500
    body = json.loads(resp.body)
    _assert_unified_shape(body, "INTERNAL_ERROR")
    assert body["detail"] == "服务器内部错误"
    assert body["error"]["details"] == []


# ── HTTPException 处理器：detail 非字符串时也保持结构 ────────────────────────


async def test_http_exception_handler_dict_detail():
    from fastapi import HTTPException

    exc = HTTPException(status_code=400, detail={"field": "x", "reason": "bad"})
    resp = await http_exception_handler(_FakeRequest(), exc)
    assert resp.status_code == 400
    body = json.loads(resp.body)
    _assert_unified_shape(body, "HTTP_400")
    # 顶层 detail 逐字保留原始（此处为 dict），保证老客户端兼容
    assert body["detail"] == {"field": "x", "reason": "bad"}
    assert body["error"]["details"] == [{"field": "x", "reason": "bad"}]


# ── XuantongError.to_dict：单数 detail + 复数 details 同时输出 ───────────────


def test_xuantong_error_to_dict_scalar_detail():
    err = ValidationError("参数不合法", detail="field_x")
    body = err.to_dict()
    assert body["detail"] == "参数不合法"           # 顶层人读消息
    e = body["error"]
    assert e["code"] == "VALIDATION_ERROR"
    assert e["message"] == "参数不合法"
    assert e["detail"] == "field_x"                 # 单数：结构化上下文
    assert e["details"] == ["field_x"]              # 复数：恒为数组


def test_xuantong_error_to_dict_no_detail():
    err = ValidationError("出错了")
    body = err.to_dict()
    e = body["error"]
    assert e["detail"] == "出错了"                  # 缺省回退为消息
    assert e["details"] == []                       # 无上下文时为空数组
