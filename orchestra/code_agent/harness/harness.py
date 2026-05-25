"""Agent execution harness — secure confinement + three observability layers.

Restrictions:
  1. Writes allowed only inside a per-run harness workspace.
  2. Runs directory, tracer, and LLM configuration are read-only.
  3. Seed system prompt is non-deletable from the conversation.

Observability (see ``observability.py``):
  §3.1 Component — every failure maps to one component class.
  §3.2 Experience — layered evidence corpus distilled from rollouts.
  §3.3 Decision — change manifest pairing edits with predictions.
"""

from __future__ import annotations

import copy
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestra.code_agent.config import AgentConfig
from orchestra.code_agent.harness.observability import Observability
from orchestra.code_agent.security.layers import FilesystemLayer, LayerDecision

_log = logging.getLogger(__name__)

# Tools that read or write the filesystem and need restriction.
_FS_TOOLS = frozenset({
    "read", "write", "edit", "glob", "bash", "diff", "patch", "apply_edit",
})

# Tools that modify agent configuration or behaviour.
_CONFIG_TOOLS = frozenset({
    "configure", "set_config", "update_config",
})


@dataclass
class HarnessConfig:
    """Configuration for the agent harness."""

    workspace_root: str = ""
    """Root directory where per-run workspaces are created."""

    runs_dir: str = ".agent-runs"
    """Read-only directory for past runs."""

    lock_llm_config: bool = True
    """Freeze LLM provider, model, max_tokens, temperature at launch."""

    protect_seed_prompt: bool = True
    """Prevent removal of the first system message."""

    enable_observability: bool = True
    """Enable all three observability layers (§3.1–3.3)."""

    allowed_write_extensions: set[str] = field(default_factory=lambda: {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html", ".md", ".json",
        ".yaml", ".yml", ".toml", ".cfg", ".ini", ".txt", ".csv", ".xml",
        ".sh", ".ps1", ".bat", ".env", ".sql", ".rs", ".go", ".java", ".c",
        ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt", ".scala",
    })
    """Allowed file extensions for write operations."""


class HarnessFilesystem:
    """Read-only + workspace-confined filesystem facade.

    Used by the harness to wrap file tools so the agent can only write
    inside its per-run workspace directory.
    """

    def __init__(self, workspace: Path, allowed_extensions: set[str]):
        self._workspace = workspace.resolve()
        self._layer = FilesystemLayer(str(self._workspace))
        self._allowed_extensions = allowed_extensions
        self._allowed_extensions.add("")

    def check_read(self, path: str) -> LayerDecision:
        return self._layer.check_read(path)

    def check_write(self, path: str, content: str = "") -> LayerDecision:
        target = Path(path).resolve()
        ext = target.suffix.lower()
        if ext not in self._allowed_extensions:
            return LayerDecision(
                False, "harness",
                f"Extension {ext!r} not in allowed set for writes",
            )
        return self._layer.check_write(path, content)

    def check_command(self, command: str) -> LayerDecision:
        """Prevent commands that write outside workspace or modify config."""
        cmd_lower = command.strip().lower()

        # Block destructive/escape commands
        dangerous = [
            "rm -rf /", "rm -rf ~", "rm -rf .", "rm -rf *", "rm -rf ..",
            "chmod 777", "chmod -r", "chown",
            "mount", "mkfs", "dd if=", "format ",
            "git push --force", "git push -f",
            "pip install", "npm install -g", "cargo install",
        ]
        for pattern in dangerous:
            if pattern in cmd_lower:
                return LayerDecision(
                    False, "harness", f"Command blocked: matches dangerous pattern {pattern!r}"
                )

        # Prevent writing to tracer/runs/config paths
        protected_dirs = [".agent-traces", ".agent-runs", ".agent-sessions"]
        for d in protected_dirs:
            if d in cmd_lower and any(op in cmd_lower for op in [">", ">>", "mv ", "cp ", "rm "]):
                return LayerDecision(
                    False, "harness",
                    f"Write to protected directory {d!r} blocked",
                )

        return LayerDecision(True, "harness")


class RestrictedTool:
    """Wraps a Tool with harness filesystem, config checks, and observability."""

    def __init__(self, inner: Any, name: str, fs: HarnessFilesystem,
                 obs: Observability | None = None):
        self._inner = inner
        self._name = name
        self._fs = fs
        self._obs = obs
        self.spec = inner.spec

    async def __call__(self, **kwargs: Any) -> Any:
        from orchestra.code_agent.tools.base import ToolResult

        if self._obs:
            self._obs.on_tool_call(self._name, kwargs)

        if self._name in _FS_TOOLS:
            # Check read paths
            for path_key in ("file_path", "file1", "file2", "path", "pattern", "workdir"):
                raw = kwargs.get(path_key)
                if raw:
                    decision = self._fs.check_read(str(raw))
                    if not decision.allowed:
                        return ToolResult(error=decision.reason)

            # Check write paths (write, edit, patch, apply_edit)
            if self._name in ("write", "edit", "patch", "apply_edit"):
                file_path = kwargs.get("file_path", "")
                content = kwargs.get("content") or kwargs.get("new_string") or ""
                decision = self._fs.check_write(str(file_path), content)
                if not decision.allowed:
                    return ToolResult(error=decision.reason)

            # Check bash commands
            if self._name == "bash":
                command = kwargs.get("command", "")
                decision = self._fs.check_command(command)
                if not decision.allowed:
                    return ToolResult(error=decision.reason)

        if self._name in _CONFIG_TOOLS:
            err = "Configuration tools are disabled in harness mode"
            if self._obs:
                self._obs.on_tool_result(self._name, "blocked", err)
            return ToolResult(error=err)

        try:
            result = await self._inner(**kwargs)
        except Exception as exc:
            if self._obs:
                self._obs.on_failure(self._name, str(exc))
            raise

        if self._obs:
            out = result.content if hasattr(result, "content") else str(result)
            self._obs.on_tool_result(self._name, "success", out)

        return result


class _FrozenConfig:
    """Prevents runtime modification of LLM configuration."""

    def __init__(self, config: AgentConfig):
        self._config = copy.deepcopy(config)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._config, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_config":
            object.__setattr__(self, name, value)
            return
        if name == "llm":
            raise RuntimeError("LLM configuration is read-only in harness mode")
        object.__setattr__(self._config, name, value)


class AgentHarness:
    """Secure execution wrapper for agents.

    Usage::

        harness = AgentHarness(config)
        result = await harness.run("implement feature X")
    """

    def __init__(
        self,
        config: AgentConfig,
        harness_config: HarnessConfig | None = None,
    ):
        self._harness_config = harness_config or HarnessConfig()
        self._original_config = config

        # Per-run workspace
        root = Path(self._harness_config.workspace_root or Path.cwd())
        run_id = uuid.uuid4().hex[:12]
        self.workspace_dir = root / ".agent-runs" / run_id
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # Filesystem enforcer
        self._fs = HarnessFilesystem(
            self.workspace_dir,
            self._harness_config.allowed_write_extensions,
        )

        # Ensure runs dir exists but is treated as read-only
        runs_path = Path(self._harness_config.runs_dir)
        runs_path.mkdir(parents=True, exist_ok=True)
        self._runs_dir = runs_path.resolve()

        # Seed prompt to protect
        self._seed_prompt = config.system_prompt or ""
        self._prompt_protected = False

        # Observability (all three layers)
        self._observability: Observability | None = None
        if self._harness_config.enable_observability:
            self._observability = Observability()

        _log.info(
            "Harness workspace: %s  (runs: %s)",
            self.workspace_dir, self._runs_dir,
        )

    async def run(
        self,
        task: str,
        tools: list[Any] | None = None,
        **agent_kwargs: Any,
    ) -> str:
        """Run the agent inside the harness workspace.

        Returns the agent's final output.
        """
        obs = self._observability
        if obs:
            obs.start_run(task)

        config = self._build_config()
        agent = self._build_agent(config, tools)

        # Protect seed system prompt
        if self._harness_config.protect_seed_prompt and self._seed_prompt:
            self._prompt_protected = True

        if obs:
            obs.on_tool_call("run", {"task": task[:200]})

        try:
            result = await agent.run(task, **agent_kwargs)
        except Exception as exc:
            exc_name = type(exc).__name__
            if obs:
                obs.on_failure(exc_name, str(exc))
            raise
        finally:
            # Re-insert seed prompt if it was removed
            self._restore_seed_prompt(agent)

        if obs:
            obs.on_tool_result("run", "success")
            obs.end_run(result)

        return result

    @property
    def observability(self) -> Observability | None:
        """Access observability data after a run."""
        return self._observability

    def _build_config(self) -> AgentConfig:
        config = copy.deepcopy(self._original_config)

        # Lock workspace to harness workspace
        config.workspace = str(self.workspace_dir)

        # Freeze LLM config if requested
        if self._harness_config.lock_llm_config:
            config = _FrozenConfig(config)  # type: ignore[assignment]

        return config

    def _build_agent(self, config: AgentConfig, tools: list[Any] | None) -> Any:
        from orchestra.code_agent import Agent

        wrap_tools = self._harness_config.lock_llm_config
        tools = tools or []

        if self._harness_config.enable_observability:
            obs = self._observability or Observability()
        else:
            obs = None

        if wrap_tools:
            wrapped = []
            for t in tools:
                name = getattr(t, "spec", None)
                name = name.name if name else getattr(t, "__class__", type(t)).__name__.lower()
                wrapped.append(RestrictedTool(t, name, self._fs, obs=obs))
            tools = wrapped

        return Agent(config, tools=tools)

    def _restore_seed_prompt(self, agent: Any) -> None:
        if not self._prompt_protected:
            return
        if not hasattr(agent, "messages"):
            return
        from orchestra.code_agent.llm.base import Message

        msgs = agent.messages
        # Check if first system message matches seed
        if msgs and msgs[0].role == "system":
            # Mark as non-deletable by re-inserting if missing or changed
            if msgs[0].content != self._seed_prompt:
                msgs.insert(0, Message(role="system", content=self._seed_prompt))
        elif self._seed_prompt:
            msgs.insert(0, Message(role="system", content=self._seed_prompt))
