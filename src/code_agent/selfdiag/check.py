from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


CHECK_MODULES = [
    "code_agent",
    "code_agent.agent",
    "code_agent.llm.base",
    "code_agent.tools.base",
    "code_agent.config",
    "code_agent.session",
    "code_agent.reviewer",
    "code_agent.cache.base",
    "code_agent.cost.tracker",
    "code_agent.knowledge.base",
    "code_agent.memory.base",
    "code_agent.vector.indexer",
    "code_agent.analysis.analyzer",
    "code_agent.output.testgen",
    "code_agent.watcher.watcher",
    "code_agent.sandbox.docker",
    "code_agent.scaffold.generator",
    "code_agent.improve.self_improve",
    "code_agent.workflow.engine",
    "code_agent.docs.generator",
    "code_agent.visualize.graph",
    "code_agent.prompts.library",
    "code_agent.guardrails.policy",
    "code_agent.monitor.dashboard",
    "code_agent.plugins.loader",
    "code_agent.repl.session",
    "code_agent.mcp.client",
    "code_agent.mcp.server",
    "code_agent.ui.server",
    "code_agent.tui.app",
    "code_agent.orchestrator.base",
    "code_agent.notify.notifier",
    "code_agent.logbook.logger",
    "code_agent.profiles.base",
    "code_agent.swarm.debate",
    "code_agent.transform.rename",
    "code_agent.export.session_export",
    "code_agent.health.checker",
    "code_agent.multilang.analyzer",
    "code_agent.context.manager",
    "code_agent.ratelimit.limiter",
    "code_agent.pipeline.engine",
    "code_agent.fallback.chain",
    "code_agent.optimizer.optimizer",
    "code_agent.learner.learner",
    "code_agent.templates.manager",
    "code_agent.quality.reporter",
    "code_agent.scheduler.scheduler",
    "code_agent.security.scanner",
    "code_agent.dashboard.server",
    "code_agent.telemetry.tracer",
    "code_agent.api.server",
    "code_agent.github.webhook",
    "code_agent.explain.tracer",
    "code_agent.smells.detector",
    "code_agent.validate.config",
    "code_agent.batch.processor",
    "code_agent.licenses.scanner",
    "code_agent.autocomplete.completer",
    "code_agent.promptversion.manager",
    "code_agent.compress.summarizer",
]


@dataclass
class DiagCheck:
    name: str = ""
    status: str = "ok"
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagReport:
    checks: list[DiagCheck] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    warnings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "checks": [asdict(c) for c in self.checks],
        }

    def to_text(self) -> str:
        lines = [f"Self-Diagnosis: {self.passed} passed, {self.failed} failed, {self.warnings} warnings\n"]
        for c in self.checks:
            icon = {"ok": "PASS", "fail": "FAIL", "warn": "WARN"}.get(c.status, "?")
            lines.append(f"  [{icon}] {c.name}: {c.message}")
        return "\n".join(lines)


class SelfDiagnosis:
    """Check that the agent itself is healthy and all modules work."""

    def run(self) -> DiagReport:
        report = DiagReport()

        # Check all modules import
        for mod_name in CHECK_MODULES:
            check = DiagCheck(name=f"import:{mod_name}")
            try:
                importlib.import_module(mod_name)
                check.status = "ok"
                check.message = "OK"
                report.passed += 1
            except ImportError as e:
                check.status = "fail"
                check.message = str(e)
                report.failed += 1
            except Exception as e:
                check.status = "warn"
                check.message = str(e)
                report.warnings += 1
            report.checks.append(check)

        # Check tools register
        try:
            from code_agent.tools import get_all_tools
            tools = get_all_tools()
            report.checks.append(DiagCheck(
                name="tools_registered",
                status="ok",
                message=f"{len(tools)} tools registered",
            ))
            report.passed += 1
        except Exception as e:
            report.checks.append(DiagCheck(
                name="tools_registered",
                status="fail",
                message=str(e),
            ))
            report.failed += 1

        # Check CLI commands
        try:
            from code_agent.cli import main
            cmds = list(main.commands.keys())
            report.checks.append(DiagCheck(
                name="cli_commands",
                status="ok",
                message=f"{len(cmds)} commands available",
                details={"commands": cmds},
            ))
            report.passed += 1
        except Exception as e:
            report.checks.append(DiagCheck(
                name="cli_commands",
                status="warn",
                message=str(e),
            ))
            report.warnings += 1

        # Check version
        try:
            from code_agent import __version__
            report.checks.append(DiagCheck(
                name="version",
                status="ok",
                message=f"v{__version__}",
            ))
            report.passed += 1
        except Exception as e:
            report.checks.append(DiagCheck(
                name="version",
                status="warn",
                message=str(e),
            ))
            report.warnings += 1

        # Check config
        try:
            from code_agent.config import AgentConfig
            cfg = AgentConfig()
            report.checks.append(DiagCheck(
                name="default_config",
                status="ok",
                message=f"Model: {cfg.llm.model}, Workspace: {cfg.workspace}",
            ))
            report.passed += 1
        except Exception as e:
            report.checks.append(DiagCheck(
                name="default_config",
                status="warn",
                message=str(e),
            ))
            report.warnings += 1

        return report
