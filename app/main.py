"""玄同 Xuantong — 数字化家庭医生团队多智能体系统"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.database.engine import create_db_engine, create_session_factory
from app.database.base import Base
from app.xuantong.llm.mock import MockProvider
from app.xuantong.llm.qwen import QwenProvider
from app.xuantong.llm.runtime import LLMRuntime
from app.xuantong.llm.vision import VisionService
from app.xuantong.llm.speech import SpeechService
from app.xuantong.agents import register_all_agents
from app.xuantong.runtime.registry import AgentRegistry
from app.xuantong.safety import (
    ActionGuard,
    HITLService,
    InputGuard,
    OutputGuard,
)
from app.xuantong.workflow import XuantongWorkflow
from app.domain.rules.risk_classification import RiskRuleService
from app.api.middleware.error_handler import (
    validation_exception_handler,
    generic_exception_handler,
)
from app.api.routes import (
    system, agents, patients, health_records,
    events, tasks, outcomes, care_teams, timeline, nutrition,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings = Settings()

    # ── 启动：初始化组件 ──────────────────────────────────────
    logger.info("玄同 Xuantong 启动中...")

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

    # LLM Runtime（多模型分层路由 + 超时 + 指数退避重试）
    app.state.llm_runtime = LLMRuntime(
        provider=provider,
        max_retries=settings.llm_max_retries,
        timeout_seconds=settings.llm_timeout,
        retry_base_delay=settings.llm_retry_base_delay,
        settings=settings,
    )

    # 多模态服务
    app.state.vision_service = VisionService(app.state.llm_runtime)
    app.state.speech_service = SpeechService(app.state.llm_runtime)
    logger.info("多模态服务已初始化: VisionService, SpeechService")

    # 注册所有 Agent
    register_all_agents(app.state.llm_runtime)
    app.state.agents = AgentRegistry
    logger.info(f"已注册 {len(AgentRegistry.list_all())} 个 Agent")

    # Safety Guard 四层（纯函数，无状态；HITLService 管理待审队列）
    app.state.input_guard = InputGuard()
    app.state.output_guard = OutputGuard()
    app.state.action_guard = ActionGuard()
    app.state.hitl_service = HITLService()

    # LangGraph 工作流引擎（编排 Agent 协作）
    app.state.workflow = XuantongWorkflow(
        llm_runtime=app.state.llm_runtime,
        agent_registry=app.state.agents,
        risk_service=RiskRuleService(),
        input_guard=app.state.input_guard,
        output_guard=app.state.output_guard,
        action_guard=app.state.action_guard,
        hitl_service=app.state.hitl_service,
    )
    logger.info("玄同工作流引擎已初始化 (LangGraph StateGraph)")

    yield

    # ── 关闭 ─────────────────────────────────────────────────
    logger.info("玄同 Xuantong 关闭中...")
    if hasattr(app.state, 'db_engine'):
        await app.state.db_engine.dispose()


app = FastAPI(
    title="玄同 Xuantong",
    description="数字化家庭医生团队多智能体系统",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全局异常处理 ─────────────────────────────────────────────────────────────
app.add_exception_handler(RequestValidationError, validation_exception_handler)
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
