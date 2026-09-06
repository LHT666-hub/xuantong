"""对话路由 —— changxi 前端会话与消息管理 + 轻量 AI 对话。

设计定位：
- ``POST /chat`` 是**轻量级对话**端点：直接以家庭医生角色的 LLM 完成一轮问答，
  并将 user/assistant 消息持久化到会话存储。它**不触发** 13 节点 LangGraph
  工作流（完整会诊/任务链路仍由 ``POST /api/events`` 承担）。
- 会话管理端点（``/chat/sessions`` 系列）负责多轮会话的增删查，供前端历史列表、
  会话详情、消息回放使用。
- 安全：入站经 ``InputGuard``（危机/注入/超长），出站经 ``OutputGuard``（4 态）。

持久化：``app.state.session_factory`` 存在时用 ``DbChatService``（生产），
否则回退到内存单例 ``ChatService``（开发/测试）。

该 router 在 ``app.main`` 中以 ``prefix="/api/v1"`` 注册。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.services.chat_service import get_chat_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# ── 请求 / 响应模型 ──────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """前端对话请求（兼容旧接口）。"""

    message: str = Field(..., min_length=1, description="用户消息（不可为空）")
    patient_id: str | None = Field(default=None, description="可选患者标识")
    session_id: str | None = Field(default=None, description="可选会话 ID；缺省则新建会话")
    context: list[dict] | None = Field(
        default=None,
        description="可选历史上下文，形如 [{'role': 'user', 'content': '...'}]",
    )


class ChatResponse(BaseModel):
    """对话响应（前端强依赖 ``reply`` 字段）。"""

    reply: str
    agent_role: str = "family_doctor"
    session_id: str | None = None
    metadata: dict | None = None


class CreateSessionRequest(BaseModel):
    """创建会话请求。"""

    patient_id: str = Field(..., min_length=1, description="所属患者标识")


class MessageCreate(BaseModel):
    """追加消息请求。"""

    role: Literal["user", "assistant", "system"] = Field(..., description="消息角色")
    content: str = Field(..., min_length=1, description="消息内容（不可为空）")
    metadata: dict | None = Field(default=None, description="可选元数据")


# ── 对话系统提示词（轻量自然语言，非 JSON 结构化调度）───────────────────────────

CHAT_SYSTEM_PROMPT = """你是"玄同"数字化家庭医生团队的家庭医生，正在与患者进行日常健康对话。

请用温暖、专业、通俗易懂的中文回答患者的健康咨询。遵守以下边界：
- 你不直接下诊断，也不擅自调整患者的用药方案；涉及诊断或处方调整时，
  引导患者与线下医生确认，或说明会安排团队随访。
- 遇到胸痛、呼吸困难、意识障碍、自伤/自杀等紧急情况，立即建议拨打 120
  或就近急诊，并把患者安全放在第一位。
- 回答简洁清晰，聚焦患者当前的问题，避免冗长说教。
- 如需团队其他成员（护士、公卫医师、药师、家医助理）介入的正式健康事件，
  请提示会通过健康事件上报流程处理。
"""

# 危机 / 越权 / 降级场景下的安全兜底回复
_EMERGENCY_REPLY = (
    "您描述的情况可能属于紧急状况，请立即拨打 120 或前往就近医院急诊，"
    "并注意保持安静、有人陪同。家庭医生团队会同步关注您的安全。"
)
_BLOCK_REPLY = (
    "抱歉，我无法处理该请求。如果您有健康方面的疑问，欢迎换个方式描述，"
    "我会尽力为您提供帮助。"
)
_DEGRADED_REPLY = (
    "感谢您的留言，家庭医生团队已收到。当前智能助手暂时繁忙，"
    "我们会尽快人工跟进并与您联系，请留意后续通知。"
)

_AGENT_ROLE = "family_doctor"


# ── 服务选择（DB / 内存）─────────────────────────────────────────────────────


@asynccontextmanager
async def _chat_service(request: Request):
    """按运行模式返回对话服务：有 session_factory 用 DB，否则用内存单例。"""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbChatService

        async with get_db_context(session_factory) as db:
            yield DbChatService(db)
    else:
        yield get_chat_service()


# ── 会话管理端点 ─────────────────────────────────────────────────────────────


@router.post("/chat/sessions", status_code=201)
async def create_chat_session(request: Request, payload: CreateSessionRequest) -> dict[str, Any]:
    """创建新的对话会话。"""
    async with _chat_service(request) as svc:
        session = await svc.create_session(payload.patient_id)
    return session


@router.get("/chat/sessions")
async def list_chat_sessions(
    request: Request,
    patient_id: str = Query(..., min_length=1, description="按患者过滤"),
) -> dict[str, Any]:
    """列出某患者的全部会话（按最近活跃倒序）。"""
    async with _chat_service(request) as svc:
        sessions = await svc.list_sessions(patient_id)
    return {"sessions": sessions, "patient_id": patient_id, "count": len(sessions)}


@router.post("/chat/sessions/{session_id}/messages", status_code=201)
async def add_chat_message(
    request: Request, session_id: str, payload: MessageCreate
) -> dict[str, Any]:
    """向指定会话追加一条消息。会话不存在返回 404。"""
    async with _chat_service(request) as svc:
        session = await svc.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        message = await svc.add_message(
            session_id=session_id,
            patient_id=session.get("patient_id", ""),
            role=payload.role,
            content=payload.content,
            metadata=payload.metadata,
        )
    return message


@router.get("/chat/sessions/{session_id}/messages")
async def list_chat_messages(
    request: Request,
    session_id: str,
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """列出会话消息（时间升序，最多最近 ``limit`` 条）。会话不存在返回 404。"""
    async with _chat_service(request) as svc:
        session = await svc.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        messages = await svc.list_messages(session_id, limit=limit)
    return {"messages": messages, "session_id": session_id, "count": len(messages)}


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(request: Request, session_id: str) -> dict[str, Any]:
    """删除会话及其全部消息。会话不存在返回 404。"""
    async with _chat_service(request) as svc:
        deleted = await svc.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return {"deleted": True, "session_id": session_id}


# ── 轻量对话端点（兼容旧接口）────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    """轻量级 AI 对话（直接 LLM 调用，不走完整工作流），并持久化到会话。

    流程：
    1. 解析/创建会话（``session_id`` 缺省时新建）。
    2. 持久化 user 消息。
    3. InputGuard → LLM(family_doctor) → OutputGuard 生成回复。
    4. 持久化 assistant 消息。
    5. 返回 ``{reply, agent_role, session_id, metadata}``。
    """
    async with _chat_service(request) as svc:
        # 1) 解析 / 创建会话
        session_id = payload.session_id
        if session_id:
            session = await svc.get_session(session_id)
            if session is None:
                # 传入的会话不存在则以其为 ID 隐式建档（兼容前端本地生成的会话 ID）
                session = await svc.create_session(payload.patient_id or "")
                session_id = session["id"]
            patient_id = session.get("patient_id") or (payload.patient_id or "")
        else:
            session = await svc.create_session(payload.patient_id or "")
            session_id = session["id"]
            patient_id = session.get("patient_id") or ""

        # 2) 持久化用户消息（失败不阻断对话）
        await _safe_add_message(svc, session_id, patient_id, "user", payload.message)

    # 3) 生成回复
    reply, metadata = await _compose_reply(request, payload)

    # 4) 持久化助手回复
    async with _chat_service(request) as svc:
        await _safe_add_message(svc, session_id, patient_id, "assistant", reply, metadata)

    # 5) 返回
    return ChatResponse(
        reply=reply, agent_role=_AGENT_ROLE, session_id=session_id, metadata=metadata
    )


async def _safe_add_message(
    svc, session_id: str, patient_id: str, role: str, content: str, metadata: dict | None = None
) -> None:
    """持久化消息，异常仅记录日志，不影响对话主流程。"""
    try:
        await svc.add_message(
            session_id=session_id,
            patient_id=patient_id,
            role=role,
            content=content,
            metadata=metadata,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("chat: 消息持久化失败（已跳过）: %s", e)


async def _compose_reply(request: Request, payload: ChatRequest) -> tuple[str, dict | None]:
    """InputGuard → LLM → OutputGuard，返回 (reply, metadata)。"""
    llm_runtime = request.app.state.llm_runtime
    input_guard = getattr(request.app.state, "input_guard", None)
    output_guard = getattr(request.app.state, "output_guard", None)

    message = payload.message.strip()

    # 入站安全检查
    if input_guard is not None:
        try:
            guard_result = input_guard.check(message)
            action = getattr(guard_result.action, "value", str(guard_result.action))
            if action == "emergency":
                logger.warning("chat: 检测到危机信号，返回紧急引导（patient=%s）", payload.patient_id)
                return _EMERGENCY_REPLY, {"guard": "emergency", "reason": guard_result.reason}
            if action == "block":
                logger.info("chat: 入站被阻断（%s）", guard_result.reason)
                return _BLOCK_REPLY, {"guard": "block", "reason": guard_result.reason}
            if guard_result.sanitized_input:
                message = guard_result.sanitized_input
        except Exception as e:  # 安全层异常不应阻断对话
            logger.warning("chat: InputGuard 检查异常，跳过: %s", e)

    # 组装对话消息
    messages: list[dict] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    for turn in payload.context or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    # 调用 LLM（失败降级，绝不 500）
    try:
        response = await llm_runtime.invoke(
            agent_role=_AGENT_ROLE, messages=messages, temperature=0.7
        )
        reply = (response.content or "").strip() or _DEGRADED_REPLY
    except Exception as e:
        logger.error("chat: LLM 调用失败，返回降级回复: %s", e)
        return _DEGRADED_REPLY, {"degraded": True, "reason": str(e)}

    # 出站安全处置（OutputGuard 4 态）
    reply = _guard_reply(reply, output_guard, _AGENT_ROLE)
    return reply, None


def _guard_reply(reply: str, output_guard, agent_role: str) -> str:
    """对模型回复执行 OutputGuard 4 态处置，异常时降级为原样返回。"""
    if output_guard is None or not reply:
        return reply
    try:
        result = output_guard.check(reply, agent_role)
    except Exception as e:
        logger.warning("chat: OutputGuard 检查异常，跳过: %s", e)
        return reply

    action = getattr(result.action, "value", str(result.action))
    if action == "rewrite" and result.rewritten_content:
        logger.info("chat: 回复已改写（%s）", result.reason)
        return result.rewritten_content
    if action == "block":
        logger.warning("chat: 回复被阻断（%s）", result.reason)
        return _DEGRADED_REPLY
    if action == "escalate":
        logger.warning("chat: 回复需人工审核（%s）", result.reason)
    return reply
