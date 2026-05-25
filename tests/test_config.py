import tempfile
from pathlib import Path

from orchestra.code_agent.config import AgentConfig, LLMConfig


def test_default_config():
    cfg = AgentConfig()
    assert cfg.max_iterations == 50
    assert cfg.memory_type == "json"
    assert cfg.llm.model == "gpt-4o"
    assert cfg.llm.provider == "openai"


def test_config_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        cfg = AgentConfig(
            llm=LLMConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
            max_iterations=100,
            memory_type="none",
        )
        cfg.to_file(str(path))
        assert path.exists()

        loaded = AgentConfig.from_file(str(path))
        assert loaded.llm.provider == "anthropic"
        assert loaded.llm.model == "claude-sonnet-4-20250514"
        assert loaded.max_iterations == 100
        assert loaded.memory_type == "none"
