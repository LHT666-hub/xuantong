import pytest
from app.xuantong.runtime.registry import AgentRegistry
from app.xuantong.agents import register_all_agents
from app.xuantong.llm import LLMRuntime, MockProvider


@pytest.fixture(autouse=True)
def clean_registry():
    AgentRegistry.clear()
    yield
    AgentRegistry.clear()


def test_register_8_agents():
    llm = LLMRuntime(MockProvider())
    register_all_agents(llm)
    assert len(AgentRegistry.list_all()) == 8


def test_assistant_is_execution_phase():
    llm = LLMRuntime(MockProvider())
    register_all_agents(llm)
    assistant = AgentRegistry.get("assistant")
    assert assistant is not None
    assert assistant.phase == "execution"


def test_family_doctor_is_consultation():
    llm = LLMRuntime(MockProvider())
    register_all_agents(llm)
    fd = AgentRegistry.get("family_doctor")
    assert fd is not None
    assert fd.phase == "consultation"
    assert fd.implemented == True


def test_tcm_implemented():
    llm = LLMRuntime(MockProvider())
    register_all_agents(llm)
    tcm = AgentRegistry.get("tcm")
    assert tcm is not None
    assert tcm.implemented == True


def test_nutrition_and_rehabilitation_implemented():
    llm = LLMRuntime(MockProvider())
    register_all_agents(llm)
    nutrition = AgentRegistry.get("nutrition")
    rehab = AgentRegistry.get("rehabilitation")
    assert nutrition is not None and nutrition.implemented == True
    assert rehab is not None and rehab.implemented == True


def test_all_8_agents_implemented():
    llm = LLMRuntime(MockProvider())
    register_all_agents(llm)
    assert len(AgentRegistry.list_implemented()) == 8
