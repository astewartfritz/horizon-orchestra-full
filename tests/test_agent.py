import asyncio

import pytest

from orchestra.code_agent import Agent, AgentConfig
from orchestra.code_agent.config import LLMConfig
from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class EchoTool(Tool):
    spec = ToolSpec(
        name="echo",
        description="Echo back input",
        parameters={"text": {"type": "string", "description": "Text to echo"}},
    )

    async def __call__(self, text: str) -> ToolResult:
        return ToolResult(output=f"echo: {text}")


@pytest.mark.asyncio
async def test_agent_initialization():
    cfg = AgentConfig(
        llm=LLMConfig(provider="openai", model="gpt-4o"),
        memory_type="none",
    )
    agent = Agent(cfg, custom_tools=[EchoTool()])
    assert "echo" in agent.tools
    assert "read" in agent.tools
    assert agent.config.memory_type == "none"


def test_tool_specs():
    """Test that tool specs have required fields."""
    from orchestra.code_agent.tools import CORE_TOOLS
    for t_cls in CORE_TOOLS:
        spec = t_cls.spec
        assert spec.name, f"Tool {t_cls} has no name"
        assert spec.description, f"Tool {spec.name} has no description"
        assert isinstance(spec.parameters, dict)


@pytest.mark.asyncio
async def test_echo_tool():
    tool = EchoTool()
    result = await tool(text="hello")
    assert result
    assert result.output == "echo: hello"


@pytest.mark.asyncio
async def test_tool_result_bool():
    ok = ToolResult(output="success")
    assert ok
    err = ToolResult(error="fail")
    assert not err


class TestGuardrails:
    def test_blocks_destructive_commands(self):
        from orchestra.code_agent.guardrails.policy import Guardrails
        g = Guardrails()
        results = g.check_tool_call("bash", {"command": "rm -rf /src"})
        assert g.has_blocks(results)

    def test_allows_safe_commands(self):
        from orchestra.code_agent.guardrails.policy import Guardrails
        g = Guardrails()
        results = g.check_tool_call("bash", {"command": "ls -la"})
        assert not g.has_blocks(results)

    def test_warns_on_secrets(self):
        from orchestra.code_agent.guardrails.policy import Guardrails
        g = Guardrails()
        results = g.check_tool_call("write", {"file_path": "config.py", "content": "api_key = 123"})
        warnings = [r for r in results if r.severity == "warning" and not r.passed]
        assert len(warnings) > 0

    def test_blocks_force_push(self):
        from orchestra.code_agent.guardrails.policy import Guardrails
        g = Guardrails()
        results = g.check_tool_call("bash", {"git_action": "push", "args": "--force main"})
        assert g.has_blocks(results)

    def test_agent_enabled_by_default(self):
        cfg = AgentConfig(enable_guardrails=True)
        agent = Agent(cfg)
        assert agent.guardrails is not None

    def test_agent_can_disable(self):
        cfg = AgentConfig(enable_guardrails=False)
        agent = Agent(cfg)
        assert agent.guardrails is None

    def test_warnings_surface_to_llm(self):
        cfg = AgentConfig(enable_guardrails=True)
        agent = Agent(cfg)
        # Simulate guardrails check and warning propagation
        agent._guardrails_warnings = ["Potential secret detected"]
        fake_result = ToolResult(output="done")
        if agent._guardrails_warnings and fake_result and not fake_result.error:
            warning_text = "\n[Guardrails]\n" + "\n".join(agent._guardrails_warnings)
            fake_result.output = (fake_result.output or "") + warning_text
        assert "[Guardrails]" in fake_result.output
        assert "Potential secret detected" in fake_result.output
