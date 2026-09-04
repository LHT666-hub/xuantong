import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def mock_llm_runtime():
    from app.xuantong.llm import LLMRuntime, MockProvider
    return LLMRuntime(MockProvider())


@pytest.fixture
def sample_patient_context():
    from app.schemas.patient import PatientContext
    return PatientContext(
        patient_id="test-001",
        name="张阿姨",
        age=68,
        gender="女",
        chronic_diseases=["高血压", "2型糖尿病"],
        allergies=["青霉素"],
        risk_level="green",
    )


@pytest.fixture(autouse=True)
def setup_app_state():
    """Ensure app.state has llm_runtime, guards, workflow and agents registered."""
    from app.xuantong.llm import LLMRuntime, MockProvider
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
    from app.main import app

    # Setup
    llm = LLMRuntime(MockProvider())
    app.state.llm_runtime = llm
    AgentRegistry.clear()
    register_all_agents(llm)
    app.state.agents = AgentRegistry
    app.state.input_guard = InputGuard()
    app.state.output_guard = OutputGuard()
    app.state.action_guard = ActionGuard()
    app.state.hitl_service = HITLService()

    # RAG setup (optional — disabled by default in tests)
    rag_loop = getattr(app.state, "rag_loop", None)
    rag_enabled = getattr(app.state, "rag_enabled", False)

    app.state.workflow = XuantongWorkflow(
        llm_runtime=llm,
        agent_registry=AgentRegistry,
        risk_service=RiskRuleService(),
        input_guard=app.state.input_guard,
        output_guard=app.state.output_guard,
        action_guard=app.state.action_guard,
        hitl_service=app.state.hitl_service,
        rag_loop=rag_loop,
        rag_enabled=rag_enabled,
    )

    yield

    # Teardown
    AgentRegistry.clear()
