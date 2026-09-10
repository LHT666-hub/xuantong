"""玄同 Xuantong — 数字化家庭医生团队多智能体系统"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.exceptions import XuantongError
from app.database.engine import create_db_engine, create_session_factory
from app.database.base import Base
from app.xuantong.llm.mock import MockProvider
from app.xuantong.llm.qwen import QwenProvider
from app.xuantong.llm.novita import NovitaProvider
from app.xuantong.llm.runtime import LLMRuntime
from app.xuantong.llm.vision import VisionService
from app.xuantong.llm.speech import SpeechService
from app.services.ruomu import RuomuKnowledgeService
from app.xuantong.agents import register_all_agents
from app.xuantong.runtime.registry import AgentRegistry
from app.xuantong.safety import (
    ActionGuard,
    HITLService,
    InputGuard,
    OutputGuard,
)
from app.xuantong.workflow import XuantongWorkflow, create_checkpointer
from app.domain.rules.risk_classification import RiskRuleService
from app.api.middleware.error_handler import (
    validation_exception_handler,
    generic_exception_handler,
    xuantong_exception_handler,
    http_exception_handler,
)
from app.api.middleware.request_logging import RequestLoggingMiddleware
from app.observability.logging import configure_structured_logging
from app.observability.tracing import setup_tracing
from app.api.routes import (
    system, agents, patients, health_records,
    events, tasks, outcomes, care_teams, timeline, nutrition,
)
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.multimodal import router as multimodal_router
from app.api.routes.documents import router as documents_router
from app.api.routes.stream import router as stream_router

# ── Windows 控制台 UTF-8 修复 ────────────────────────────────────────────────
# Windows 控制台默认编码（cp936）会把 UTF-8 中文日志显示为乱码。
# 在任何日志输出前，将 stdout/stderr 重配置为 UTF-8，确保中文正常显示。
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        # 某些环境（如输出被重定向到文件）不支持 reconfigure，忽略即可
        pass

logger = logging.getLogger(__name__)

# ── 结构化 JSON 日志 + PHI 脱敏 ──────────────────────────────────────────────
# 在创建 FastAPI 应用之前安装根 logger 的 JSON 格式化器（幂等，会清除
# uvicorn 默认 handler 以避免重复输出）。日志级别从 settings 读取。
configure_structured_logging(level=Settings().log_level)


async def _build_rag_loop(settings: Settings, llm_runtime):
    """构建 RAG 评估环路（检索 → 评分 → 重写 → 证据分级）。

    任何构建失败（如 data 目录缺失、无文档、依赖缺失）都会优雅降级为
    返回 None，绝不让服务启动崩溃。

    Returns:
        (rag_loop, doc_count)：rag_loop 为 RAGEvaluationLoop 或 None；
        doc_count 为知识库加载的文档数。
    """
    try:
        from app.xuantong.rag import (
            AudienceFilter,
            EntityResolver,
            EvidenceGrader,
            KnowledgeBase,
            QueryRewriter,
            RAGEvaluationLoop,
            RAGRetriever,
            RAGSafetyFilter,
            RetrievalGrader,
            RuleBasedReranker,
        )

        # 解析 data 目录（配置可为相对路径，相对于项目根 app/ 的上级）
        data_dir = Path(settings.rag_data_dir)
        if not data_dir.is_absolute():
            data_dir = Path(__file__).resolve().parent.parent / settings.rag_data_dir

        if not data_dir.exists():
            logger.warning("RAG data 目录不存在，跳过 RAG 构建: %s", data_dir)
            return None, 0

        knowledge_base = KnowledgeBase(data_dir=str(data_dir))
        doc_count = await knowledge_base.load_from_directory(str(data_dir))

        if doc_count == 0:
            logger.warning("RAG 知识库为空（无文档加载），降级为无 RAG 模式")
            return None, 0

        # 检索器：混合检索 + 重排 + 安全过滤 + 受众分层
        retriever = RAGRetriever(
            knowledge_base=knowledge_base,
            reranker=RuleBasedReranker(),
            safety_filter=RAGSafetyFilter(),
            audience_filter=AudienceFilter(),
        )

        # 评估环路：LLM 评分 + 查询重写 + 实体解析 + 证据分级
        rag_loop = RAGEvaluationLoop(
            retriever=retriever,
            grader=RetrievalGrader(llm_runtime=llm_runtime),
            rewriter=QueryRewriter(llm_runtime=llm_runtime),
            max_retries=settings.rag_max_retries,
            relevance_threshold=settings.rag_relevance_threshold,
            entity_resolver=EntityResolver(llm_runtime=llm_runtime),
            evidence_grader=EvidenceGrader(),
        )
        logger.info("RAG 评估环路已构建: %d 篇文档, top_k=%d", doc_count, settings.rag_top_k)
        return rag_loop, doc_count
    except Exception as e:  # noqa: BLE001 — 启动期任何异常都需降级
        logger.warning("RAG 构建失败，降级为无 RAG 模式: %s", e)
        return None, 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings = Settings()

    # ── 启动：初始化组件 ──────────────────────────────────────
    logger.info("玄同 Xuantong 启动中...")

    # LangSmith 链路追踪（默认关闭；开启后 LangGraph 无侵入自动上报执行链路）
    setup_tracing(settings)

    # 数据库
    app.state.db_engine = create_db_engine(settings)
    app.state.session_factory = create_session_factory(app.state.db_engine)

    # 初始化数据库表（开发模式：SQLite 自动创建表）
    if settings.database_url.startswith("sqlite"):
        async with app.state.db_engine.begin() as conn:
            # 导入所有模型以确保它们被注册
            from app.models import (  # noqa: F401
                User, Organization, Team, Patient,
                CareTeam, CareTeamMember, PatientTeamAssignment,
                HealthRecord, Measurement, Medication,
                Event, Task, ServiceOutcome, Followup,
                TimelineEntry, AgentRun, WorkflowRun, AuditLog,
                ChatMessage,
            )
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"数据库已初始化: {settings.database_url}")
    else:
        logger.info(f"数据库已连接: {settings.database_url}")

    # LLM Provider 选择
    if settings.llm_provider == "qwen":
        provider = QwenProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            default_model=settings.llm_model_specialist,
        )
        logger.info(f"LLM Provider: Qwen (百炼 DashScope), 主模型={settings.llm_model_lead}")
    else:
        provider = MockProvider()
        logger.info("LLM Provider: Mock (测试模式)")

    # Novita AI 医疗模型（Ling 3.0 Flash Santé）
    medical_provider = None
    if settings.use_medical_model and settings.novita_api_key:
        medical_provider = NovitaProvider(
            api_key=settings.novita_api_key,
            base_url=settings.novita_base_url,
            default_model=settings.medical_model_id,
        )
        logger.info(
            f"Novita 医疗模型已启用: {settings.medical_model_id}, "
            f"医疗 Agent: {settings.medical_agents}"
        )
    elif settings.use_medical_model and not settings.novita_api_key:
        logger.warning("Novita 医疗模型已配置启用但 NOVITA_API_KEY 为空，降级为 Qwen")
    else:
        logger.info("Novita 医疗模型已通过配置禁用 (use_medical_model=False)")

    # LLM Runtime（多模型分层路由 + 超时 + 指数退避重试 + 医疗模型路由）
    app.state.llm_runtime = LLMRuntime(
        provider=provider,
        max_retries=settings.llm_max_retries,
        timeout_seconds=settings.llm_timeout,
        retry_base_delay=settings.llm_retry_base_delay,
        settings=settings,
        medical_provider=medical_provider,
    )

    # 多模态服务
    app.state.vision_service = VisionService(app.state.llm_runtime)
    app.state.speech_service = SpeechService(app.state.llm_runtime)
    logger.info("多模态服务已初始化: VisionService, SpeechService")

    # 若木只提供知识库/联网证据，最终回答仍由玄同模型生成。
    app.state.ruomu_service = None
    if settings.ruomu_enabled and settings.ruomu_access_key:
        app.state.ruomu_service = RuomuKnowledgeService(
            base_url=settings.ruomu_base_url,
            access_key=settings.ruomu_access_key,
            timeout=settings.ruomu_timeout,
        )
        logger.info("若木 D 模式证据服务已启用")
    elif settings.ruomu_enabled:
        logger.warning("若木已配置启用但 RUOMU_ACCESS_KEY 为空，跳过外部证据检索")

    # 注册所有 Agent
    register_all_agents(app.state.llm_runtime)
    app.state.agents = AgentRegistry
    logger.info(f"已注册 {len(AgentRegistry.list_all())} 个 Agent")

    # Safety Guard 四层（纯函数，无状态；HITLService 管理待审队列）
    app.state.input_guard = InputGuard()
    app.state.output_guard = OutputGuard()
    app.state.action_guard = ActionGuard()
    app.state.hitl_service = HITLService()

    # RAG 评估环路（检索 → 评分 → 重写 → 证据分级）——构建失败则优雅降级
    if settings.rag_enabled:
        rag_loop, rag_doc_count = await _build_rag_loop(settings, app.state.llm_runtime)
    else:
        rag_loop, rag_doc_count = None, 0
        logger.info("RAG 已通过配置禁用 (rag_enabled=False)")
    app.state.rag_loop = rag_loop
    app.state.rag_enabled = rag_loop is not None

    # LangGraph checkpointer（memory 默认 / postgres 持久化，失败优雅降级）
    checkpointer, checkpoint_close = await create_checkpointer(
        backend=settings.workflow_checkpoint_backend,
        database_url=settings.database_url,
    )
    app.state.checkpoint_close = checkpoint_close
    logger.info(
        "Checkpointer 后端: %s (%s)",
        settings.workflow_checkpoint_backend,
        type(checkpointer).__name__,
    )

    # LangGraph 工作流引擎（编排 Agent 协作）
    app.state.workflow = XuantongWorkflow(
        llm_runtime=app.state.llm_runtime,
        agent_registry=app.state.agents,
        risk_service=RiskRuleService(),
        input_guard=app.state.input_guard,
        output_guard=app.state.output_guard,
        action_guard=app.state.action_guard,
        hitl_service=app.state.hitl_service,
        checkpointer=checkpointer,
        rag_loop=rag_loop,
        rag_enabled=app.state.rag_enabled,
    )
    logger.info(
        "玄同工作流引擎已初始化 (LangGraph StateGraph), RAG=%s",
        "启用" if app.state.rag_enabled else "禁用",
    )

    yield

    # ── 关闭 ─────────────────────────────────────────────────
    logger.info("玄同 Xuantong 关闭中...")
    if getattr(app.state, "checkpoint_close", None) is not None:
        await app.state.checkpoint_close()
    if getattr(app.state, "ruomu_service", None) is not None:
        await app.state.ruomu_service.close()
    if hasattr(app.state, 'db_engine'):
        await app.state.db_engine.dispose()


app = FastAPI(
    title="玄同 Xuantong",
    description="数字化家庭医生团队多智能体系统",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS（fail-closed，从配置读取白名单）──────────────────────────────────────
settings = Settings()

# 解析 CORS 白名单（逗号分隔），过滤空白项。
cors_origins = [
    o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()
]
if settings.debug and cors_origins == ["*"]:
    logger.warning(
        "CORS allow_origins=['*'] in DEBUG mode — DO NOT use in production"
    )

# CORS 规范冲突规避：allow_credentials=True 不能与通配符 '*' 同时使用。
# 含 '*' 时关闭 credentials，否则开启。
cors_allow_credentials = "*" not in cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 请求追踪中间件（在 CORS 之后注册）────────────────────────────────────────
# 生成 request_id、记录结构化 request_start/request_end 日志，
# 并将 request_id 写入响应头 X-Request-ID。
app.add_middleware(RequestLoggingMiddleware)

# ── 全局异常处理 ─────────────────────────────────────────────────────────────
# HTTPException 统一包装为 {"detail":..., "error":{...}} 兼容结构（老客户端读 detail，
# 新客户端读 error.code/message）。StarletteHTTPException 是 FastAPI HTTPException 的父类。
from starlette.exceptions import HTTPException as StarletteHTTPException

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(XuantongError, xuantong_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ── 注册路由（统一 /api 前缀）────────────────────────────────────────────────
for router in (
    system.router,
    agents.router,
    patients.router,
    health_records.router,
    events.router,
    tasks.router,
    outcomes.router,
    care_teams.router,
    timeline.router,
    nutrition.router,
):
    app.include_router(router, prefix="/api")

# ── 认证路由（JWT）────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

# ── changxi 前端多模态 / 对话路由（/api/v1）──────────────────────────────────
app.include_router(chat_router, prefix="/api/v1", tags=["chat"])
app.include_router(multimodal_router, prefix="/api/v1", tags=["multimodal"])
app.include_router(documents_router, prefix="/api/v1", tags=["documents"])
app.include_router(stream_router, prefix="/api/v1", tags=["stream"])
