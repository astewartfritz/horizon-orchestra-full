"""Horizon Orchestra — Dev Team Mode.

Implements a multi-agent software development pipeline where specialized
sub-agents collaborate to plan, implement, test, review, document, and
security-audit code.  Inspired by real software engineering team structures.

Role pipeline::

    ARCHITECT  →  Creates a structured implementation plan, splitting the task
                  into discrete, independently-implementable subtasks.

    CODER(s)   →  Parallel implementation of each subtask.  Each coder runs in
                  isolation (simulated worktrees) to avoid conflicts.

    TESTER     →  Writes and "runs" (via LLM synthesis) tests for each
                  implementation, reporting pass/fail and coverage gaps.

    REVIEWER   →  Audits code quality, SOLID principles, naming, type safety,
                  and correctness.

    DOCS       →  Generates module-level docstrings, README fragments, and
                  API reference for the combined implementation.

    SECURITY   →  Scans for OWASP-top-10 issues, hardcoded secrets, unsafe
                  deserialization, path traversal, and injection vectors.

    DEVOPS     →  Produces Dockerfile, CI/CD pipeline YAML, and deployment
                  notes for the implementation.

Usage::

    from orchestra.dev_team import DevTeam, DevTeamConfig
    from orchestra.router import ModelRouter
    from orchestra.agent_loop import ToolRegistry

    router = ModelRouter()
    team = DevTeam(DevTeamConfig(), router=router, tool_registry=ToolRegistry())
    result = await team.execute("Build a FastAPI CRUD service for a Todo list")
    print(result.plan)
    print(result.review)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "DevRole",
    "DevAgent",
    "DevTeamConfig",
    "DevTeam",
    "DevTeamResult",
]

log = logging.getLogger("orchestra.dev_team")

# ---------------------------------------------------------------------------
# Enums & Dataclasses
# ---------------------------------------------------------------------------


class DevRole(str, Enum):
    """Enumeration of development team roles.

    Each role maps to a distinct system prompt and tool subset that specialises
    the underlying LLM for that aspect of software engineering.
    """

    ARCHITECT = "architect"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    DOCS = "docs"
    SECURITY = "security"
    DEVOPS = "devops"


@dataclass
class DevAgent:
    """Descriptor for a single dev-team agent.

    Attributes:
        role: The :class:`DevRole` this agent fulfils.
        name: Human-readable agent name (e.g. ``"Alice the Architect"``).
        model: Model identifier to use (falls back to lead_model if empty).
        system_prompt: Full role-specific system prompt injected before every
            call.
        tools: List of tool names available to this agent.
        specialization: One-line description of this agent's primary focus.
    """

    role: DevRole
    name: str
    model: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    specialization: str = ""


@dataclass
class DevTeamConfig:
    """Configuration for the dev team pipeline.

    Attributes:
        roles: Override map from :class:`DevRole` to custom :class:`DevAgent`.
            Roles not present in this map use the default definitions.
        lead_model: Model to use when a role has no specific model set.
        max_parallel_agents: Maximum number of CODER agents running in parallel.
        auto_review: If ``True``, automatically run REVIEWER after all coders
            finish (even if not explicitly requested).
    """

    roles: dict[DevRole, DevAgent] = field(default_factory=dict)
    lead_model: str = "kimi-k2.5"
    max_parallel_agents: int = 4
    auto_review: bool = True


@dataclass
class DevTeamResult:
    """Aggregated output from a full dev-team pipeline run.

    Attributes:
        plan: ARCHITECT's structured implementation plan (markdown).
        implementations: Mapping of subtask name → implementation code/prose.
        test_results: TESTER's output per implementation.
        review: REVIEWER's consolidated code review.
        documentation: DOCS agent's generated documentation.
        security_findings: SECURITY agent's vulnerability report.
        devops_artifacts: DEVOPS agent's Dockerfile, CI YAML, etc.
        total_duration: Wall-clock seconds for the full pipeline.
        agents_used: Ordered list of agent names that participated.
    """

    plan: str
    implementations: dict[str, str] = field(default_factory=dict)
    test_results: str = ""
    review: str = ""
    documentation: str = ""
    security_findings: str = ""
    devops_artifacts: str = ""
    total_duration: float = 0.0
    agents_used: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Default role system prompts
# ---------------------------------------------------------------------------

_DEFAULT_PROMPTS: dict[DevRole, str] = {
    DevRole.ARCHITECT: """\
You are a Principal Software Architect with 20+ years of experience designing
large-scale distributed systems.  Your responsibility is to thoroughly analyze
the given task, identify all technical requirements and constraints, and produce
a detailed implementation plan.

Structure your response as follows:
1. **Requirements Analysis** — functional and non-functional requirements.
2. **Component Breakdown** — list every file/module that must be created or
   modified, with a one-line purpose for each.
3. **Subtask List** — numbered list of independent implementation subtasks that
   parallel coders can execute.  Each subtask should be scoped to 1–3 files.
4. **Technology Decisions** — libraries, frameworks, patterns, and rationale.
5. **Interfaces & Contracts** — key function signatures, dataclasses, and API
   shapes that coders must respect.
6. **Risk Register** — potential failure points and mitigation strategies.

Be precise, exhaustive, and implementation-ready.  Do not write code; write
decisions and instructions that another engineer can follow exactly.""",

    DevRole.CODER: """\
You are a Senior Software Engineer specialising in Python 3.12+ and modern
async/await patterns.  You write production-quality code that is:
- Correct: handles edge cases, validates inputs, returns meaningful errors.
- Idiomatic: uses dataclasses, type hints, f-strings, pathlib, and asyncio
  naturally.
- Efficient: avoids blocking I/O in async contexts; uses connection pooling.
- Well-tested: includes at minimum happy-path and error-path logic.
- Documented: every public function/class has a Google-style docstring.

You will be given one subtask from the ARCHITECT's plan.  Implement it fully —
no placeholders, no TODO comments, no stub methods.  Output the complete file
content for each file needed to satisfy the subtask.  Use markdown code fences
labelled with the file path, e.g.:

```python:/path/to/module.py
# ... full implementation ...
```

If the subtask requires installing a dependency, note it in a
`requirements.txt` section at the end.""",

    DevRole.TESTER: """\
You are a Quality Assurance Engineer with deep expertise in pytest, hypothesis-
based property testing, and test-driven development.  Your mission is to ensure
the implementation is correct, robust, and production-ready.

For each piece of code provided:
1. Write a comprehensive pytest test suite (including fixtures, parametrize,
   and mocks where appropriate).
2. Identify at least 5 test cases per public function: happy path, boundary
   conditions, invalid inputs, concurrent usage, and resource-exhaustion
   scenarios.
3. Assess test coverage gaps — which code paths are not exercised and why.
4. Simulate test execution: reason through what each test would produce and
   report PASS / FAIL with a brief justification.
5. Produce a coverage summary table (function name, estimated coverage %).

Always use ``pytest`` idioms.  Prefer ``pytest.raises`` over bare try/except.
Mock external services with ``unittest.mock.AsyncMock``.  Never rely on live
network calls in tests.""",

    DevRole.REVIEWER: """\
You are a Staff Engineer conducting a thorough code review.  You evaluate code
against the following dimensions and produce actionable feedback:

**Correctness**: Logic errors, off-by-one mistakes, race conditions, incorrect
assumptions, unhandled exceptions.

**Design**: SOLID principles adherence, separation of concerns, appropriate
abstraction levels, cohesion and coupling.

**Performance**: Unnecessary allocations, blocking calls in async code, missing
caching opportunities, N+1 query patterns.

**Maintainability**: Naming clarity, magic numbers/strings, code duplication,
cyclomatic complexity, module organisation.

**Type Safety**: Missing or incorrect type annotations, unsafe casts, runtime
type violations.

**Compatibility**: Python version constraints, platform-specific code, breaking
API changes.

Format your review as:
- A severity-tagged issue list (🔴 Critical / 🟡 Major / 🟢 Minor / 💡 Suggestion).
- A **Summary Score** (0–10) with a one-paragraph justification.
- A **Merge Decision**: APPROVE / REQUEST_CHANGES / BLOCK with reasoning.""",

    DevRole.DOCS: """\
You are a Technical Writer and Developer Advocate specialising in open-source
Python library documentation.  You produce documentation that is accurate,
comprehensive, and pleasant to read.

For each module provided, generate:
1. **Module docstring** — one-paragraph overview, key concepts, and usage
   prerequisites.
2. **Usage Examples** — at least two realistic, runnable code snippets per
   public class/function.
3. **API Reference** — parameter descriptions, return types, raised exceptions,
   and side effects for every public symbol.
4. **Architecture Notes** — a brief explanation of the module's internal
   structure for contributors.
5. **README Section** — a self-contained markdown section that can be dropped
   into a project README.

Write in clear, active voice.  Prefer short sentences.  Include type
annotations in all examples.  Highlight any breaking changes or deprecations.""",

    DevRole.SECURITY: """\
You are a Senior Application Security Engineer with specialisation in Python
backend systems.  You conduct threat modelling and static analysis on code
submissions.

Review code for the following vulnerability categories (OWASP Top 10 + extras):
1. **Injection** (SQL, command, LDAP, template).
2. **Broken Authentication** (token handling, session fixation, credential leaks).
3. **Sensitive Data Exposure** (hardcoded secrets, plaintext storage, logging PII).
4. **Broken Access Control** (privilege escalation, IDOR, path traversal).
5. **Security Misconfiguration** (debug flags, open CORS, default credentials).
6. **Insecure Deserialization** (pickle, yaml.load, eval on untrusted input).
7. **Dependency Vulnerabilities** (known CVEs in imported packages).
8. **Cryptographic Failures** (weak algorithms, reused IVs, missing HTTPS).
9. **Server-Side Request Forgery** (SSRF via unvalidated URLs).
10. **Supply Chain Risks** (typosquatting, pinned vs. floating deps).

For each finding, provide: severity (Critical/High/Medium/Low/Info), CWE ID,
affected line range, proof-of-concept exploit scenario, and recommended fix.
Conclude with an overall Security Rating (A–F) and a remediation roadmap.""",

    DevRole.DEVOPS: """\
You are a Senior DevOps/Platform Engineer specialising in containerisation,
CI/CD pipelines, and cloud-native deployments.  Given an application
implementation, you produce all the operational artifacts needed to run it
reliably in production.

Produce the following artifacts:
1. **Dockerfile** — multi-stage build with a minimal final image (python:3.12-slim
   or distroless), non-root user, pinned base image digest, and health check.
2. **docker-compose.yml** — local development stack with all dependencies
   (databases, caches, queues) and proper restart policies.
3. **GitHub Actions CI** — lint (ruff/mypy), test (pytest with coverage), build
   Docker image, push to GHCR, and notify on failure.
4. **Kubernetes manifests** — Deployment, Service, ConfigMap, and HorizontalPodAutoscaler
   YAMLs appropriate for the service's scale profile.
5. **Environment variable documentation** — table of all required env vars,
   with example values, whether they are secrets, and where to obtain them.
6. **Runbook** — step-by-step operational instructions for deploy, rollback,
   log access, and incident response.""",
}

_DEFAULT_TOOLS: dict[DevRole, list[str]] = {
    DevRole.ARCHITECT: ["web_search", "read_file", "list_directory"],
    DevRole.CODER: ["read_file", "write_file", "run_python", "web_search", "bash"],
    DevRole.TESTER: ["read_file", "run_python", "bash"],
    DevRole.REVIEWER: ["read_file", "web_search"],
    DevRole.DOCS: ["read_file", "write_file"],
    DevRole.SECURITY: ["read_file", "web_search", "bash"],
    DevRole.DEVOPS: ["read_file", "write_file", "bash", "web_search"],
}

_DEFAULT_SPECS: dict[DevRole, str] = {
    DevRole.ARCHITECT: "System design, component decomposition, and technical planning",
    DevRole.CODER: "Production-quality Python implementation with full type hints",
    DevRole.TESTER: "pytest test suites, coverage analysis, and defect detection",
    DevRole.REVIEWER: "Code quality auditing, design review, and merge decisions",
    DevRole.DOCS: "API documentation, usage examples, and README sections",
    DevRole.SECURITY: "Vulnerability scanning, threat modelling, and remediation advice",
    DevRole.DEVOPS: "Dockerfile, CI/CD pipelines, and Kubernetes manifests",
}


# ---------------------------------------------------------------------------
# DevTeam
# ---------------------------------------------------------------------------


class DevTeam:
    """Orchestrates a pipeline of specialised development sub-agents.

    The pipeline executes sequentially by default, except for the CODER phase
    which can run multiple agents in parallel (one per subtask).

    Args:
        config: Team configuration, including role overrides and model choices.
        router: A ``ModelRouter`` instance for LLM API calls.
        tool_registry: A ``ToolRegistry`` for tool dispatch (may be ``None``
            if the implementation does not require tool calls).

    Example::

        team = DevTeam(DevTeamConfig(lead_model="kimi-k2.5"), router=router)
        result = await team.execute("Build a REST API for task management")
        print(result.plan)
    """

    def __init__(
        self,
        config: DevTeamConfig | None = None,
        router: Any = None,
        tool_registry: Any = None,
    ) -> None:
        self.config = config or DevTeamConfig()
        self.router = router
        self.tool_registry = tool_registry
        self._default_roles = self._build_default_roles()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, task: str) -> DevTeamResult:
        """Run the full development pipeline on a task description.

        Pipeline stages (in order):
        1. ARCHITECT → implementation plan + subtask list
        2. CODER(s)  → parallel implementation of each subtask
        3. TESTER    → test synthesis and coverage report
        4. REVIEWER  → code review and merge decision
        5. DOCS      → documentation generation
        6. SECURITY  → vulnerability scan
        7. DEVOPS    → operational artifacts

        Args:
            task: Plain-English task description, e.g.
                ``"Build a FastAPI CRUD service for a Todo list with SQLite"``.

        Returns:
            A :class:`DevTeamResult` with all pipeline outputs.
        """
        log.info("DevTeam.execute: task=%r", task[:80])
        t0 = time.monotonic()
        agents_used: list[str] = []

        # ── Stage 1: ARCHITECT ──────────────────────────────────────────────
        log.info("[1/7] ARCHITECT: planning...")
        architect = self._get_agent_for_role(DevRole.ARCHITECT)
        agents_used.append(architect.name)
        plan = await self._run_role(DevRole.ARCHITECT, task, context="")
        log.debug("Plan length: %d chars", len(plan))

        # Extract subtask list from the plan
        subtasks = self._extract_subtasks(plan)
        log.info("ARCHITECT produced %d subtasks", len(subtasks))

        # ── Stage 2: CODER(s) — parallel ───────────────────────────────────
        log.info("[2/7] CODER(s): implementing %d subtask(s)...", len(subtasks))
        implementations = await self._parallel_coders(subtasks, plan_context=plan)
        coder = self._get_agent_for_role(DevRole.CODER)
        agents_used.append(coder.name)

        # Build a combined code blob for downstream roles
        combined_code = "\n\n".join(
            f"## Subtask: {name}\n\n{impl}" for name, impl in implementations.items()
        )

        # ── Stage 3: TESTER ────────────────────────────────────────────────
        log.info("[3/7] TESTER: writing and evaluating tests...")
        tester = self._get_agent_for_role(DevRole.TESTER)
        agents_used.append(tester.name)
        test_context = f"PLAN:\n{plan}\n\nIMPLEMENTATIONS:\n{combined_code}"
        test_results = await self._run_role(DevRole.TESTER, task, context=test_context)

        # ── Stage 4: REVIEWER ──────────────────────────────────────────────
        log.info("[4/7] REVIEWER: auditing code quality...")
        reviewer = self._get_agent_for_role(DevRole.REVIEWER)
        agents_used.append(reviewer.name)
        review_context = f"ORIGINAL TASK:\n{task}\n\nPLAN:\n{plan}\n\nCODE:\n{combined_code}\n\nTEST RESULTS:\n{test_results}"
        review = await self._run_role(DevRole.REVIEWER, task, context=review_context)

        # ── Stage 5: DOCS ──────────────────────────────────────────────────
        log.info("[5/7] DOCS: generating documentation...")
        docs_agent = self._get_agent_for_role(DevRole.DOCS)
        agents_used.append(docs_agent.name)
        docs_context = f"TASK:\n{task}\n\nCODE:\n{combined_code}"
        documentation = await self._run_role(DevRole.DOCS, task, context=docs_context)

        # ── Stage 6: SECURITY ──────────────────────────────────────────────
        log.info("[6/7] SECURITY: scanning for vulnerabilities...")
        sec_agent = self._get_agent_for_role(DevRole.SECURITY)
        agents_used.append(sec_agent.name)
        sec_context = f"CODE TO AUDIT:\n{combined_code}"
        security_findings = await self._run_role(
            DevRole.SECURITY, task, context=sec_context
        )

        # ── Stage 7: DEVOPS ────────────────────────────────────────────────
        log.info("[7/7] DEVOPS: creating operational artifacts...")
        devops_agent = self._get_agent_for_role(DevRole.DEVOPS)
        agents_used.append(devops_agent.name)
        devops_context = (
            f"APPLICATION DESCRIPTION:\n{task}\n\n"
            f"PLAN:\n{plan}\n\n"
            f"CODE SUMMARY:\n{combined_code[:3000]}..."
        )
        devops_artifacts = await self._run_role(
            DevRole.DEVOPS, task, context=devops_context
        )

        duration = time.monotonic() - t0
        log.info("DevTeam pipeline complete in %.1fs", duration)

        return DevTeamResult(
            plan=plan,
            implementations=implementations,
            test_results=test_results,
            review=review,
            documentation=documentation,
            security_findings=security_findings,
            devops_artifacts=devops_artifacts,
            total_duration=duration,
            agents_used=agents_used,
        )

    # ------------------------------------------------------------------
    # Role runner
    # ------------------------------------------------------------------

    async def _run_role(
        self, role: DevRole, task: str, context: str
    ) -> str:
        """Invoke the LLM for a specific role with its system prompt.

        Args:
            role: The :class:`DevRole` to execute.
            task: Original user task (always included).
            context: Additional context from previous pipeline stages.

        Returns:
            Raw LLM text response.
        """
        agent = self._get_agent_for_role(role)
        model_id = agent.model or self.config.lead_model
        system_prompt = self._build_system_prompt(agent, task)

        user_content = f"TASK:\n{task}"
        if context:
            user_content = f"{user_content}\n\n{context}"

        log.debug("_run_role(%s) with model=%s", role.value, model_id)

        if self.router is None:
            # No router configured — return a stub for testing
            return f"[{role.value.upper()} output for: {task[:60]}]"

        try:
            client = await self.router.get_client(model_id)
            model_cfg = self.router.get_model(model_id)
            resp = await client.chat.completions.create(
                model=model_cfg.model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=4096,
                temperature=0.3 if role in (DevRole.CODER, DevRole.TESTER) else 0.5,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            log.error("_run_role(%s) failed: %s", role.value, exc)
            return f"[ERROR in {role.value}: {exc}]"

    # ------------------------------------------------------------------
    # Parallel coders
    # ------------------------------------------------------------------

    async def _parallel_coders(
        self,
        subtasks: list[str],
        plan_context: str = "",
    ) -> dict[str, str]:
        """Execute multiple CODER agents in parallel, one per subtask.

        Each coder is isolated: it receives only its own subtask description +
        the architect's plan as context, simulating a git worktree isolation.

        Args:
            subtasks: List of subtask descriptions from the ARCHITECT.
            plan_context: Full architect plan (shared read-only context).

        Returns:
            Dict mapping subtask description → implementation output.
        """
        semaphore = asyncio.Semaphore(self.config.max_parallel_agents)

        async def _run_one(subtask: str) -> tuple[str, str]:
            async with semaphore:
                context = (
                    f"ARCHITECT'S PLAN (read-only reference):\n{plan_context}\n\n"
                    f"YOUR SUBTASK (implement this and only this):\n{subtask}"
                )
                result = await self._run_role(DevRole.CODER, subtask, context=context)
                return subtask, result

        if not subtasks:
            # Fallback: run a single coder on the full task
            single_result = await self._run_role(
                DevRole.CODER, "Implement the full task", context=plan_context
            )
            return {"full_implementation": single_result}

        tasks = [_run_one(st) for st in subtasks]
        results: dict[str, str] = {}

        for coro in asyncio.as_completed(tasks):
            subtask, impl = await coro
            results[subtask] = impl
            log.debug("CODER finished subtask: %s (%d chars)", subtask[:40], len(impl))

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_agent_for_role(self, role: DevRole) -> DevAgent:
        """Return the :class:`DevAgent` for a given role.

        Checks config overrides first, then falls back to defaults.

        Args:
            role: The :class:`DevRole` to look up.

        Returns:
            The configured or default :class:`DevAgent`.
        """
        return self.config.roles.get(role) or self._default_roles[role]

    def _build_system_prompt(self, agent: DevAgent, task: str) -> str:
        """Construct the full system prompt for a dev agent.

        Combines the role's base prompt with a preamble identifying the agent
        and task context.

        Args:
            agent: The :class:`DevAgent` whose prompt to use.
            task: The original user task (injected into preamble).

        Returns:
            Full system prompt string.
        """
        preamble = (
            f"You are {agent.name}, a member of an AI-powered software development team.\n"
            f"Your specialisation: {agent.specialization}\n"
            f"Overall project goal: {task[:200]}\n\n"
        )
        return preamble + agent.system_prompt

    @staticmethod
    def _extract_subtasks(plan: str) -> list[str]:
        """Parse the ARCHITECT's output to extract an ordered subtask list.

        Looks for numbered lists (``1. ...``, ``2. ...``) or bullet lists
        (``- ...``, ``* ...``) that appear under a "Subtask" heading.  Falls
        back to a single-item list containing the whole plan if no list is found.

        Args:
            plan: Raw markdown text from the ARCHITECT role.

        Returns:
            List of subtask strings (may be empty, which triggers single-coder
            fallback in ``_parallel_coders``).
        """
        import re

        subtasks: list[str] = []

        # Prefer lines under a "Subtask" section
        in_subtask_section = False
        for line in plan.splitlines():
            stripped = line.strip()
            # Detect section header
            if re.search(r"subtask", stripped, re.IGNORECASE) and stripped.startswith("#"):
                in_subtask_section = True
                continue
            if in_subtask_section and stripped.startswith("#"):
                # New section — stop collecting
                break
            if in_subtask_section:
                # Numbered item: "1. Do thing"
                m = re.match(r"^\d+\.\s+(.+)$", stripped)
                if m:
                    subtasks.append(m.group(1).strip())
                    continue
                # Bullet item: "- Do thing" or "* Do thing"
                m = re.match(r"^[-*]\s+(.+)$", stripped)
                if m:
                    subtasks.append(m.group(1).strip())

        if not subtasks:
            # Global search for numbered list
            for line in plan.splitlines():
                m = re.match(r"^\d+\.\s+(.+)$", line.strip())
                if m:
                    subtasks.append(m.group(1).strip())

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for st in subtasks:
            if st not in seen:
                seen.add(st)
                unique.append(st)

        log.debug("Extracted %d subtasks from plan", len(unique))
        return unique[:20]  # cap at 20 to avoid runaway parallelism

    def _build_default_roles(self) -> dict[DevRole, DevAgent]:
        """Construct the default :class:`DevAgent` set for all roles.

        Returns:
            Dict mapping every :class:`DevRole` to a fully-configured
            :class:`DevAgent` with production-quality system prompts.
        """
        agents: dict[DevRole, DevAgent] = {}
        role_names = {
            DevRole.ARCHITECT: "Alex the Architect",
            DevRole.CODER: "Casey the Coder",
            DevRole.TESTER: "Taylor the Tester",
            DevRole.REVIEWER: "Riley the Reviewer",
            DevRole.DOCS: "Dakota the Documentation Engineer",
            DevRole.SECURITY: "Sam the Security Engineer",
            DevRole.DEVOPS: "Devon the DevOps Engineer",
        }
        for role in DevRole:
            agents[role] = DevAgent(
                role=role,
                name=role_names[role],
                model=self.config.lead_model,
                system_prompt=_DEFAULT_PROMPTS[role],
                tools=_DEFAULT_TOOLS[role],
                specialization=_DEFAULT_SPECS[role],
            )
        return agents
