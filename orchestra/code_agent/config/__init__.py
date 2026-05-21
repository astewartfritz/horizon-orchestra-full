from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class LLMConfig:
    provider: Literal["openai", "anthropic", "ollama", "custom"] = "openai"
    model: str = "gpt-4o"
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    timeout: float = 600.0


@dataclass
class ReasoningConfig:
    strategy: Literal["cot", "plan", "reflect", "auto"] = "auto"
    plan_first: bool = True
    verify_steps: bool = False
    max_plans: int = 3
    save_traces: bool = True
    trace_dir: str = ".agent-reasoning"
    show_thinking: bool = True


@dataclass
class SkillsConfig:
    enabled: bool = True
    library_path: str = ".agent-skills.db"
    retrieval_top_k: int = 3
    distill_on_completion: bool = True


@dataclass
class AgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    max_iterations: int = 50
    max_tool_rounds: int = 30
    workspace: str | None = None
    system_prompt: str | None = None
    memory_type: Literal["none", "json", "sqlite"] = "json"
    memory_path: str | None = None
    verbose: bool = False
    allow_bash: bool = True
    allow_web: bool = True
    confirm_commands: bool = False
    enable_guardrails: bool = True
    enable_nemoclaw: bool = True
    enable_skills: bool = True
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)

    @classmethod
    def from_file(cls, path: str | Path) -> AgentConfig:
        path = Path(path)
        raw = json.loads(path.read_text("utf-8"))
        llm_raw = raw.pop("llm", {})
        llm = LLMConfig(**llm_raw)
        return cls(llm=llm, **raw)

    def to_file(self, path: str | Path) -> None:
        data = {
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "api_key": self.llm.api_key or os.environ.get(self._env_key()),
                "base_url": self.llm.base_url,
                "max_tokens": self.llm.max_tokens,
                "temperature": self.llm.temperature,
                "timeout": self.llm.timeout,
            },
            "max_iterations": self.max_iterations,
            "max_tool_rounds": self.max_tool_rounds,
            "workspace": self.workspace,
            "memory_type": self.memory_type,
            "verbose": self.verbose,
            "allow_bash": self.allow_bash,
            "allow_web": self.allow_web,
            "confirm_commands": self.confirm_commands,
        }
        Path(path).write_text(json.dumps(data, indent=2), "utf-8")

    def _env_key(self) -> str:
        return {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(
            self.llm.provider, ""
        )


__all__ = [
    "AgentConfig",
    "LLMConfig",
    "ReasoningConfig",
    "SkillsConfig",
]
