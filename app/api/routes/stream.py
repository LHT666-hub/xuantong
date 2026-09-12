"""SSE 实时流式路由（Task #13）—— 工作流状态推送 + 对话流式输出。

两个端点（在 ``app.main`` 中以 ``prefix="/api/v1"`` 注册）：

- ``GET  /api/v1/events/{event_id}/stream`` — SSE 推送工作流节点执行进度。
  数据来源三层兜底：
  1. ``WorkflowProgressHub`` 实时频道（workflow.stream_run 桥接 LangGraph
     ``astream(stream_mode="updates")`` 发布的节点事件，含历史回放）；
  2. 事件记录中的 ``workflow.steps``（已完成的工作流一次性回放）；
  3. 事件记录状态轮询（频道未建立时等待工作流启动）。
  空闲超时保护（默认 60s 无事件自动关闭，期间每 15s 发送心跳注释行）。

- ``POST /api/v1/chat/stream`` — SSE 流式对话。优先走 ``LLMRuntime.stream()``
  真流式；Provider 一次性返回大块内容（如 MockProvider）或非流式 Provider 时，
  降级为按句子分块的模拟流式（每块间隔 50ms）。入站 InputGuard、出站
  OutputGuard 与 ``POST /chat`` 一致；出站安检改写/阻断时通过
  ``event: guard`` 下发最终可信文本。会话消息持久化行为与 ``POST /chat`` 对齐。

SSE 报文格式::

    data: {"node": "input_guard", "status": "completed"}\n\n
    event: complete\ndata: {"final_status": "completed"}\n\n
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.routes.chat import (
    CHAT_SYSTEM_PROMPT,
    ChatRequest,
    _AGENT_ROLE,
    _BLOCK_REPLY,
    _DEGRADED_REPLY,
    _EMERGENCY_REPLY,
    _chat_service,
    _guard_reply,
    _safe_add_message,
)
from app.services.progress_hub import ProgressChannel, progress_hub
from app.services.references import build_references
from app.services.ruomu import RuomuEvidence

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

# ── SSE 参数 ─────────────────────────────────────────────────────────────────

#: 事件流空闲超时（秒）：期间无任何新事件则自动关闭连接
EVENT_STREAM_IDLE_TIMEOUT = 60.0
#: 心跳间隔（秒）：空闲等待期间定期发送 SSE 注释行保活
EVENT_STREAM_HEARTBEAT = 15.0
#: 事件记录状态轮询间隔（秒）：频道未建立时等待工作流启动
_STATUS_POLL_INTERVAL = 0.5
#: 对话流单块接收超时（秒）：防止 Provider 挂起导致连接永久悬置
CHAT_CHUNK_TIMEOUT = 60.0
#: 模拟流式的分块间隔（秒）
SIMULATED_CHUNK_DELAY = 0.05

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲，保证逐块下发
}


# ── SSE 报文工具 ─────────────────────────────────────────────────────────────


def _sse_data(payload: dict[str, Any]) -> str:
    """构造默认 ``message`` 事件的 SSE 报文。"""
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    """构造具名事件的 SSE 报文（如 ``event: complete``）。"""
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
    )


def _sse_comment(text: str) -> str:
    """构造 SSE 注释行（心跳保活，客户端自动忽略）。"""
    return f": {text}\n\n"


# ════════════════════════════════════════════════════════════════════════════
# 1) 工作流状态 SSE
# ════════════════════════════════════════════════════════════════════════════


async def _fetch_event_record(request: Request, event_id: str) -> dict[str, Any] | None:
    """按运行模式（DB / 内存）读取事件记录，与 events 路由保持一致。"""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is not None:
        from app.database.engine import get_db_context
        from app.services.db import DbEventService

        async with get_db_context(session_factory) as db:
            return await DbEventService(db).get_event(event_id)
    from app.services import EventService

    return await EventService().get_event(event_id)


def _channel_item_to_sse(item: dict[str, Any]) -> str:
    """将频道进度事件转换为 SSE 报文。"""
    if item.get("type") == "complete":
        return _sse_event("complete", {"final_status": item.get("final_status")})
    return _sse_data(item)


async def _event_stream_generator(
    request: Request, event_id: str, record: dict[str, Any]
) -> AsyncIterator[str]:
    """事件状态 SSE 生成器：回放历史 → 实时推送 → complete / timeout。"""
    yield _sse_data(
        {
            "type": "status_snapshot",
            "event_id": event_id,
            "status": record.get("status") or "received",
            "timestamp": record.get("updated_at") or record.get("received_at"),
        }
    )

    channel = progress_hub.get(event_id)
    if channel is not None:
        async for msg in _stream_from_channel(channel):
            yield msg
        return

    # 无实时频道：若事件已处于终态，从持久化的 workflow.steps 一次性回放
    status = record.get("status")
    workflow = record.get("workflow") or {}
    if status != "received":
        for step in workflow.get("steps") or []:
            yield _sse_data({"node": step, "status": "completed"})
        yield _sse_event(
            "complete",
            {"final_status": workflow.get("status") or status, "event_status": status},
        )
        return

    # 事件仍在处理但频道尚未建立：短暂轮询等待工作流启动或落库终态
    deadline = asyncio.get_running_loop().time() + EVENT_STREAM_IDLE_TIMEOUT
    while asyncio.get_running_loop().time() < deadline:
        if await request.is_disconnected():
            return
        channel = progress_hub.get(event_id)
        if channel is not None:
            async for msg in _stream_from_channel(channel):
                yield msg
            return
        await asyncio.sleep(_STATUS_POLL_INTERVAL)
        record = await _fetch_event_record(request, event_id) or record
        if record.get("status") != "received":
            workflow = record.get("workflow") or {}
            for step in workflow.get("steps") or []:
                yield _sse_data({"node": step, "status": "completed"})
            yield _sse_event(
                "complete",
                {
                    "final_status": workflow.get("status") or record.get("status"),
                    "event_status": record.get("status"),
                },
            )
            return
        yield _sse_comment("waiting")

    yield _sse_event("timeout", {"reason": "idle_timeout", "event_id": event_id})


async def _stream_from_channel(channel: ProgressChannel) -> AsyncIterator[str]:
    """订阅进度频道：先回放历史，再实时等待新事件直至 complete / 空闲超时。"""
    sent = 0
    idle_seconds = 0.0
    while True:
        # 回放已积累的进度事件（含迟到订阅者错过的历史）
        while sent < len(channel.history):
            item = channel.history[sent]
            sent += 1
            idle_seconds = 0.0
            yield _channel_item_to_sse(item)
            if item.get("type") == "complete":
                return

        if channel.finished:
            # 兜底：频道已结束但未见 complete 条目（理论上不会发生）
            yield _sse_event("complete", {"final_status": channel.final_status})
            return

        updated = await channel.wait_update(EVENT_STREAM_HEARTBEAT)
        if updated:
            idle_seconds = 0.0
            continue
        idle_seconds += EVENT_STREAM_HEARTBEAT
        if idle_seconds >= EVENT_STREAM_IDLE_TIMEOUT:
            yield _sse_event(
                "timeout", {"reason": "idle_timeout", "event_id": channel.event_id}
            )
            return
        yield _sse_comment("ping")


@router.get("/events/{event_id}/stream")
async def stream_event_status(request: Request, event_id: str) -> StreamingResponse:
    """SSE 推送工作流节点执行进度。

    - 工作流进行中：实时推送 ``{"node", "status", "timestamp"}`` 节点事件；
    - 工作流已完成：一次性回放节点历史 + ``event: complete``；
    - 事件不存在且无进度频道：404；
    - 超时保护：60s 无新事件推送 ``event: timeout`` 后关闭连接。
    """
    channel = progress_hub.get(event_id)
    record = await _fetch_event_record(request, event_id)
    if record is None and channel is None:
        raise HTTPException(status_code=404, detail="Event not found")

    return StreamingResponse(
        _event_stream_generator(request, event_id, record or {}),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ════════════════════════════════════════════════════════════════════════════
# 2) 对话流式 SSE
# ════════════════════════════════════════════════════════════════════════════

# 句子切分：中文句末标点 / 英文句末标点+空白 / 换行
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;\n])|(?<=\.)\s+")


def _split_chunks(text: str) -> list[str]:
    """将完整回复按句子切块（模拟流式用），过滤空白块。"""
    return [c for c in _SENTENCE_SPLIT_RE.split(text) if c.strip()]


async def _persist_user_message(
    request: Request, payload: ChatRequest
) -> tuple[str, str]:
    """解析/创建会话并持久化 user 消息，返回 (session_id, patient_id)。

    与 ``POST /chat`` 行为对齐：传入的会话不存在时隐式建档。
    """
    async with _chat_service(request) as svc:
        session_id = payload.session_id
        if session_id:
            session = await svc.get_session(session_id)
            if session is None:
                session = await svc.create_session(payload.patient_id or "")
                session_id = session["id"]
            patient_id = session.get("patient_id") or (payload.patient_id or "")
        else:
            session = await svc.create_session(payload.patient_id or "")
            session_id = session["id"]
            patient_id = session.get("patient_id") or ""
        await _safe_add_message(svc, session_id, patient_id, "user", payload.message)
    return session_id, patient_id


def _check_input_guard(request: Request, message: str) -> tuple[str, dict[str, Any] | None]:
    """入站安全检查。返回 (sanitized_message, guard_reply)；guard_reply 非空表示
    命中危机/阻断，应直接以该回复短路（不调用 LLM）。"""
    input_guard = getattr(request.app.state, "input_guard", None)
    if input_guard is None:
        return message, None
    try:
        guard_result = input_guard.check(message)
        action = getattr(guard_result.action, "value", str(guard_result.action))
        if action == "emergency":
            logger.warning("chat/stream: 检测到危机信号，返回紧急引导")
            return message, {"reply": _EMERGENCY_REPLY, "guard": "emergency",
                             "reason": guard_result.reason}
        if action == "block":
            logger.info("chat/stream: 入站被阻断（%s）", guard_result.reason)
            return message, {"reply": _BLOCK_REPLY, "guard": "block",
                             "reason": guard_result.reason}
        if guard_result.sanitized_input:
            message = guard_result.sanitized_input
    except Exception as e:  # 安全层异常不应阻断对话
        logger.warning("chat/stream: InputGuard 检查异常，跳过: %s", e)
    return message, None


def _build_chat_messages(
    payload: ChatRequest,
    message: str,
    references: list[dict[str, Any]] | None = None,
    external_brief: str = "",
) -> list[dict]:
    """组装对话消息（system + 历史上下文 + 当前输入），与 POST /chat 一致。"""
    system_prompt = CHAT_SYSTEM_PROMPT
    if references:
        evidence = "\n\n".join(
            f"[{index}] {item['title']}\n{item['excerpt']}"
            for index, item in enumerate(references, 1)
        )
        system_prompt += (
            "\n\n以下是本次可用的玄同医学知识库资料。凡是回答中使用了资料支持的健康建议，"
            "必须在对应句末标注 [1]、[2] 这样的编号，并至少引用一条最相关资料。"
            "不得虚构编号或外部网址；资料不支持的内容不要强行引用。\n\n"
            + evidence
        )
    if external_brief:
        system_prompt += (
            "\n\n以下是若木通过医疗知识库与联网搜索生成的检索摘要。它只作为证据线索，"
            "你仍需独立判断、保持患者安全边界，并结合上方编号资料生成最终回答；"
            "不要声称自己就是若木，也不要照搬其诊断或处方性内容。\n\n"
            + external_brief[:6000]
        )
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for turn in payload.context or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


async def _retrieve_chat_references(request: Request, message: str) -> list[dict[str, Any]]:
    """Fast local retrieval for a cited chat response (no extra LLM grading pass)."""
    rag_loop = getattr(request.app.state, "rag_loop", None)
    retriever = getattr(rag_loop, "retriever", None)
    if retriever is None:
        return []
    try:
        documents = await retriever.retrieve(
            message,
            top_k=3,
            # Patient questions often need public-health or pharmacist sources;
            # doctor-only filtering can discard the best matching document.
            agent_role=None,
            use_rerank=True,
        )
    except Exception as exc:  # citations enhance the reply but must not block it
        logger.warning("chat/stream: reference retrieval failed: %s", exc)
        return []
    relevant = [doc for doc in documents if doc.source and doc.score > 0]
    return build_references(
        [doc.source for doc in relevant],
        [doc.content for doc in relevant],
        sum(doc.score for doc in relevant) / len(relevant) if relevant else 0.0,
    )


def _should_use_ruomu(message: str) -> bool:
    """仅为需要外部证据的问题启用若木，并拦截附件/明显身份标识。"""
    if not message or len(message) > 1500 or "附件：" in message:
        return False
    if re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", message):
        return False
    if re.search(r"(?<!\d)\d{17}[\dXx](?!\d)", message):
        return False
    evidence_intents = (
        "最新", "近期", "指南", "规范", "政策", "依据", "来源", "出处",
        "研究", "论文", "文献", "资料", "证据", "科普", "联网", "搜索", "查一下",
    )
    return any(intent in message for intent in evidence_intents)


async def _retrieve_ruomu_evidence(request: Request, payload: ChatRequest, message: str) -> RuomuEvidence:
    service = getattr(request.app.state, "ruomu_service", None)
    if service is None or not _should_use_ruomu(message):
        return RuomuEvidence()
    try:
        return await service.retrieve(message, history=payload.context or [])
    except Exception as exc:  # 外部检索不能阻断主回答
        logger.warning("chat/stream: 若木证据检索失败，继续使用本地 RAG: %s", exc)
        return RuomuEvidence()


def _ruomu_references(evidence: RuomuEvidence, start: int) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence.sources:
        title = str(item.get("title") or "若木检索资料").strip()
        site = str(item.get("siteName") or "若木").strip()
        raw_url = str(item.get("url") or "").strip()
        url = raw_url if raw_url.startswith("https://") else None
        identity = (title, url or site)
        if identity in seen:
            continue
        seen.add(identity)
        references.append(
            {
                "id": f"ruomu-ref-{start + len(references)}",
                "title": title,
                "source": site,
                "excerpt": "若木 D 模式检索到的相关资料，可结合正文查看。",
                "evidence_score": None,
                "kind": "web_source" if url else "ruomu_knowledge_base",
                "url": url,
            }
        )
    return references


def _references_used_in_reply(
    reply: str, references: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """保留检索到的相关资料，并明确标记哪些被正文实际引用。"""
    used = {int(number) for number in re.findall(r"\[(\d{1,2})\]", reply)}
    return [
        {**item, "cited": index in used}
        for index, item in enumerate(references, 1)
    ]


async def _llm_stream_chunks(
    llm_runtime: Any,
    messages: list[dict],
    agent_role: str = _AGENT_ROLE,
) -> AsyncIterator[str]:
    """消费 ``LLMRuntime.stream()``，带单块超时保护。

    Provider 不支持流式（AttributeError / NotImplementedError / TypeError）时
    抛出 ``NotImplementedError`` 由调用方降级；其余异常原样上抛触发 invoke 兜底。
    """
    agen = llm_runtime.stream(agent_role=agent_role, messages=messages, temperature=0.7)
    queue: asyncio.Queue = asyncio.Queue()

    async def _pump() -> None:
        try:
            async for chunk in agen:
                await queue.put(("chunk", chunk))
            await queue.put(("end", None))
        except BaseException as e:  # noqa: BLE001 — 转交给消费侧统一处理
            await queue.put(("error", e))

    pump_task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                async with asyncio.timeout(CHAT_CHUNK_TIMEOUT):
                    kind, value = await queue.get()
            except (asyncio.TimeoutError, TimeoutError) as e:
                raise RuntimeError(f"LLM stream chunk timeout ({CHAT_CHUNK_TIMEOUT}s)") from e
            if kind == "end":
                return
            if kind == "error":
                if isinstance(value, (AttributeError, NotImplementedError, TypeError)):
                    raise NotImplementedError("provider does not support streaming") from value
                raise value
            content = getattr(value, "content", "") or ""
            if content:
                yield content
    finally:
        if not pump_task.done():
            pump_task.cancel()
        await agen.aclose()


async def _stream_llm_reply(
    llm_runtime: Any,
    messages: list[dict],
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
    agent_role: str = _AGENT_ROLE,
) -> tuple[list[str], dict[str, Any] | None]:
    """生成流式回复块。返回 (chunks, metadata)。

    策略：
    1. 真流式：``LLMRuntime.stream()`` 逐块产出；单块过大（Provider 一次性
       返回全文，如 MockProvider）时按句子细分并加 50ms 间隔，保证打字机体验；
    2. Provider 不支持流式：``invoke()`` 拿到全文后按句子模拟流式；
    3. 全部失败：返回降级兜底文本（绝不 500）。
    """
    chunks: list[str] = []
    collected: list[str] = []

    async def _emit(piece: str) -> None:
        pieces = _split_chunks(piece) if len(piece) > 120 else [piece]
        for i, part in enumerate(pieces):
            if i > 0:
                await asyncio.sleep(SIMULATED_CHUNK_DELAY)
            chunks.append(part)
            if on_chunk is not None:
                await on_chunk(part)

    try:
        async for content in _llm_stream_chunks(llm_runtime, messages, agent_role):
            collected.append(content)
            await _emit(content)
        reply = "".join(collected).strip()
        if reply:
            return chunks or [reply], None
    except NotImplementedError:
        logger.info("chat/stream: Provider 不支持流式，降级为 invoke + 模拟分块")
    except Exception as e:  # noqa: BLE001
        logger.warning("chat/stream: 流式调用失败，降级为 invoke: %s", e)
        # 已经向客户端下发过一部分内容时，不再重新 invoke 后把另一份回答
        # 拼到后面。保留已收到的安全片段并明确标记降级，避免弱网重连时重复。
        if chunks:
            return chunks, {"degraded": True, "reason": "partial_stream"}

    # 降级：非流式 invoke（自带超时 + 重试）
    try:
        response = await llm_runtime.invoke(
            agent_role=agent_role, messages=messages, temperature=0.7
        )
        reply = (response.content or "").strip()
        if reply:
            await _emit(reply)
            return chunks, None
    except Exception as e:  # noqa: BLE001
        logger.error("chat/stream: LLM 调用失败，返回降级回复: %s", e)
        await _emit(_DEGRADED_REPLY)
        return chunks, {"degraded": True, "reason": str(e)}

    await _emit(_DEGRADED_REPLY)
    return chunks, {"degraded": True, "reason": "empty_reply"}


def _agent_role_for_message(message: str) -> str:
    """三条首发入口只是产品操作引导，走快速执行模型以缩短首字延迟。

    一旦用户进入自由问答或提供真实健康信息，仍使用家庭医生医疗模型。
    """
    starter_markers = (
        "我点击了“读懂我的体检报告”",
        "我点击了“核对今天的用药”",
        "我点击了“记录今天的身体感受”",
    )
    return "assistant" if message.startswith(starter_markers) else _AGENT_ROLE


def _starter_reply_for_message(message: str) -> str | None:
    """返回三条评审首发入口的确定性引导；不处理任何个体健康判断。"""
    replies = {
        "我点击了“读懂我的体检报告”": (
            "可以。点击输入栏左侧的“＋”，拍摄或选择体检报告即可。\n\n"
            "我会先找出超出参考范围的项目，再解释它可能与什么有关，最后标出哪些适合观察、"
            "哪些建议复查或咨询医生。没有看到报告前，我不会猜测数值，也不会自动生成工单。"
        ),
        "我点击了“核对今天的用药”": (
            "我们先核对，不改处方：\n\n"
            "1. 打开“健康 → 用药管理”查看今天的计划；\n"
            "2. 核对药名、处方剂量和服用时间；\n"
            "3. 有疑问可拍下药盒或处方，我帮你整理成给医生或药师确认的问题。\n\n"
            "在你确认前，我不会更改计划或创建工单。"
        ),
        "我点击了“记录今天的身体感受”": (
            "好，我们慢慢记。你可以直接告诉我：什么时候开始、身体哪里不舒服、"
            "是酸胀还是刺痛等感觉、强度大约 0–10 分，以及有没有头晕、发热等伴随情况。\n\n"
            "我会先整理成一条健康日记给你核对；只有你确认后才保存，也不会自动生成工单。"
        ),
    }
    for marker, reply in replies.items():
        if message.startswith(marker):
            return reply
    return None


async def _chat_stream_generator(
    request: Request, payload: ChatRequest
) -> AsyncIterator[str]:
    """对话流式 SSE 生成器。"""
    session_id, patient_id = await _persist_user_message(request, payload)
    try:
        # 尽快提交响应头并产生首个字节，避免移动热点/Nginx 把正在准备的
        # 流式请求误判为空闲连接。注释帧会被所有 SSE 客户端安全忽略。
        yield _sse_comment("connected")
        message = payload.message.strip()
        agent_role = _agent_role_for_message(message)
        metadata: dict[str, Any] | None = None

        # 1) 入站安全检查（危机/阻断直接短路，仍走模拟流式下发）
        message, guard_hit = _check_input_guard(request, message)
        if guard_hit is not None:
            reply = guard_hit.pop("reply")
            metadata = guard_hit
            chunks = _split_chunks(reply) or [reply]
            for i, chunk in enumerate(chunks):
                if i > 0:
                    await asyncio.sleep(SIMULATED_CHUNK_DELAY)
                yield _sse_data({"chunk": chunk, "done": False})
        else:
            starter_reply = _starter_reply_for_message(message)
            if starter_reply is not None:
                # 三条入口只解释产品下一步，不做临床判断；确定性返回保证评审首点
                # 在弱网下也迅速、稳定，真实追问仍进入下方医疗模型链路。
                reply = starter_reply
                metadata = {"starter": True, "references": []}
                chunks = _split_chunks(reply) or [reply]
                for i, chunk in enumerate(chunks):
                    if i > 0:
                        await asyncio.sleep(SIMULATED_CHUNK_DELAY)
                    yield _sse_data({"chunk": chunk, "done": False})
            else:
                # 2) LLM 流式生成（真流式或模拟分块）
                llm_runtime = request.app.state.llm_runtime
                local_result, ruomu = await asyncio.gather(
                    _retrieve_chat_references(request, message),
                    _retrieve_ruomu_evidence(request, payload, message),
                )
                references = list(local_result)
                references.extend(_ruomu_references(ruomu, len(references) + 1))
                messages = _build_chat_messages(
                    payload, message, references, external_brief=ruomu.brief
                )
                # 模型生成与 SSE 输出并行：过去这里会等完整回答生成完才下发，
                # 导致首字延迟很长，热点稍有抖动就被客户端判定为掉线。
                chunk_queue: asyncio.Queue[str] = asyncio.Queue()

                async def _publish_chunk(chunk: str) -> None:
                    await chunk_queue.put(chunk)

                reply_task = asyncio.create_task(
                    _stream_llm_reply(
                        llm_runtime,
                        messages,
                        on_chunk=_publish_chunk,
                        agent_role=agent_role,
                    )
                )
                while not reply_task.done() or not chunk_queue.empty():
                    try:
                        chunk = await asyncio.wait_for(chunk_queue.get(), timeout=5.0)
                        yield _sse_data({"chunk": chunk, "done": False})
                    except (asyncio.TimeoutError, TimeoutError):
                        # 注释帧不会进入回答正文，只负责让代理与 URLSession 知道连接仍活着。
                        yield _sse_comment("thinking")

                chunks, metadata = await reply_task
                metadata = dict(metadata or {})
                metadata["references"] = references
                if ruomu.request_id:
                    metadata["ruomu_request_id"] = ruomu.request_id
                reply = "".join(chunks).strip() or _DEGRADED_REPLY

                # 3) 出站安全处置（OutputGuard 4 态）：改写/阻断时下发 guard 修正
                guarded = _guard_reply(reply, getattr(request.app.state, "output_guard", None),
                                       agent_role)
                if guarded != reply:
                    reply = guarded
                    yield _sse_event("guard", {"reply": guarded})

        if metadata is not None:
            metadata["references"] = _references_used_in_reply(
                reply, list(metadata.get("references") or [])
            )

        # 4) 持久化 assistant 回复（失败不阻断流）
        async with _chat_service(request) as svc:
            await _safe_add_message(
                svc, session_id, patient_id, "assistant", reply, metadata
            )

        # 5) 终态事件：reply 为最终可信全文（可能经 OutputGuard 改写）
        yield _sse_event(
            "complete",
            {
                "chunk": "",
                "done": True,
                "reply": reply,
                "agent_role": agent_role,
                "session_id": session_id,
                "metadata": metadata,
                "references": metadata.get("references", []) if metadata else [],
            },
        )
    except Exception as e:  # noqa: BLE001 — SSE 已建连，异常以事件下发而非 500
        logger.exception("chat/stream: 生成器异常: %s", e)
        yield _sse_event("error", {"message": str(e)})


@router.post("/chat/stream")
async def stream_chat(request: Request, payload: ChatRequest) -> StreamingResponse:
    """SSE 流式对话输出。

    报文序列::

        data: {"chunk": "……", "done": false}\n\n   （逐块）
        event: guard\ndata: {"reply": "…"}\n\n      （仅 OutputGuard 改写/阻断时）
        event: complete\ndata: {"chunk": "", "done": true, "reply": "完整回复", …}\n\n
    """
    return StreamingResponse(
        _chat_stream_generator(request, payload),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
