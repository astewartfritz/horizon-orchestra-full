"""Policy Engine — Declarative, hot-reloadable, default-deny policy system.

Policies are expressed in YAML and evaluated at runtime against every
agent action.  The engine supports:

    * **Default-deny**: if no rule matches, the action is denied.
    * **Hot-reload**: a background task watches YAML mtimes and reloads
      within 1 second of a change.
    * **Hierarchical matching**: policies target agents via glob patterns
      (``"salesforce-*"``, ``"external-*"``, ``"*"``).
    * **Approval workflow**: rules with ``requires_approval`` trigger an
      async approval flow before the action proceeds.
    * **Rich rule types**: network destinations, filesystem paths, tool
      lists, model allow-lists, and connector access.
    * **Full audit trail**: every decision is recorded with rationale.

YAML loading uses a try/except guard around ``import yaml`` so the
module degrades gracefully if PyYAML is not installed.

Beyond NemoClaw: NemoClaw has flat, single-tenant, static policies.
This engine supports multi-tenant hierarchical policies with per-agent,
per-task, per-domain scoping, hot-reload, and an approval workflow.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

__all__ = [
    "PolicyRule",
    "Policy",
    "PolicyDecision",
    "ApprovalRequest",
    "PolicyEngine",
]

log = logging.getLogger("orchestra.guardian.policy_engine")


# ---------------------------------------------------------------------------
# YAML loading guard
# ---------------------------------------------------------------------------

def _load_yaml(text: str) -> Any:
    """Parse YAML text.  Falls back to JSON if PyYAML is unavailable."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        log.warning("pyyaml not installed — falling back to JSON parsing")
        import json
        return json.loads(text)


def _load_yaml_file(path: str) -> Any:
    """Load a YAML file.  Falls back to JSON."""
    with open(path, "r", encoding="utf-8") as fh:
        return _load_yaml(fh.read())


# ---------------------------------------------------------------------------
# PolicyRule
# ---------------------------------------------------------------------------

@dataclass
class PolicyRule:
    """A single rule inside a :class:`Policy`.

    Rules match against a ``(resource, action, target)`` triple.  The
    engine evaluates rules in order and applies the first match.

    Attributes
    ----------
    resource : str
        ``network``, ``filesystem``, ``model``, ``tool``, ``memory``,
        ``connector``, ``agent``, ``*``.
    action : str
        ``outbound``, ``read``, ``write``, ``execute``, ``call``,
        ``delete``, ``spawn``, ``*``.
    destinations : list[str]
        For network rules — allowed destination globs.
    paths : list[str]
        For filesystem rules — allowed path globs.
    tools : list[str]
        For tool rules — allowed tool names.
    allowed_models : list[str]
        For model rules — allowed model identifiers.
    connectors : list[str]
        For connector rules — allowed connector names.
    effect : str
        ``allow``, ``deny``, ``allow_with_approval``, ``log_only``.
    requires_approval : bool
        If ``True``, the action needs explicit human approval.
    approval_timeout : float
        Seconds to wait for approval before auto-deny (default 300).
    log : bool
        Whether to log this rule's evaluations.
    priority : int
        Lower = higher priority.  Used to break ties.
    conditions : dict
        Extra conditions (time-of-day, IP range, etc.)  — extensible.
    description : str
        Human-readable description for audit.
    """

    resource: str = "*"
    action: str = "*"
    destinations: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    allowed_models: list[str] = field(default_factory=list)
    connectors: list[str] = field(default_factory=list)
    effect: str = "deny"
    requires_approval: bool = False
    approval_timeout: float = 300.0
    log: bool = True
    priority: int = 100
    conditions: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyRule":
        """Construct from a parsed YAML dict."""
        return cls(
            resource=data.get("resource", "*"),
            action=data.get("action", "*"),
            destinations=data.get("destinations", []),
            paths=data.get("paths", []),
            tools=data.get("tools", []),
            allowed_models=data.get("allowed_models", []),
            connectors=data.get("connectors", []),
            effect=data.get("effect", "deny"),
            requires_approval=data.get("requires_approval", False),
            approval_timeout=data.get("approval_timeout", 300.0),
            log=data.get("log", True),
            priority=data.get("priority", 100),
            conditions=data.get("conditions", {}),
            description=data.get("description", ""),
        )

    def matches(self, resource: str, action: str, target: str = "") -> bool:
        """Return ``True`` if this rule matches the given action."""
        # Resource match
        if self.resource != "*" and not fnmatch.fnmatch(resource, self.resource):
            return False

        # Action match
        if self.action != "*" and not fnmatch.fnmatch(action, self.action):
            return False

        # Target-specific matching
        if target:
            if resource == "network" and self.destinations:
                if not any(fnmatch.fnmatch(target, d) for d in self.destinations):
                    return False
            elif resource == "filesystem" and self.paths:
                if not any(fnmatch.fnmatch(target, p) for p in self.paths):
                    return False
            elif resource == "tool" and self.tools:
                if target not in self.tools:
                    return False
            elif resource == "model" and self.allowed_models:
                if target not in self.allowed_models:
                    return False
            elif resource == "connector" and self.connectors:
                if target not in self.connectors:
                    return False

        return True


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@dataclass
class Policy:
    """A named collection of rules targeting a set of agents.

    Attributes
    ----------
    policy_id : str
        Unique identifier.
    version : int
        Monotonically increasing version number.
    default_action : str
        ``"deny"`` (recommended) or ``"allow"``.
    agent_pattern : str
        Glob pattern matching agent IDs (e.g. ``"salesforce-*"``).
    rules : list[PolicyRule]
        Ordered list of rules.  First match wins.
    created_at : float
        Creation timestamp.
    tags : list[str]
        Free-form tags for organisation.
    description : str
        Human-readable policy description.
    enabled : bool
        Whether this policy is active.
    """

    policy_id: str = ""
    version: int = 1
    default_action: str = "deny"
    agent_pattern: str = "*"
    rules: list[PolicyRule] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    description: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.policy_id:
            self.policy_id = uuid.uuid4().hex[:12]

    def matches_agent(self, agent_id: str) -> bool:
        """Return ``True`` if this policy applies to *agent_id*."""
        return fnmatch.fnmatch(agent_id, self.agent_pattern)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Policy":
        """Construct from a parsed YAML dict."""
        rules = [PolicyRule.from_dict(r) for r in data.get("rules", [])]
        return cls(
            policy_id=data.get("policy_id", ""),
            version=data.get("version", 1),
            default_action=data.get("default_action", "deny"),
            agent_pattern=data.get("agent_pattern", "*"),
            rules=rules,
            created_at=data.get("created_at", time.time()),
            tags=data.get("tags", []),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to dict (YAML-compatible)."""
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "default_action": self.default_action,
            "agent_pattern": self.agent_pattern,
            "rules": [
                {
                    "resource": r.resource,
                    "action": r.action,
                    "destinations": r.destinations,
                    "paths": r.paths,
                    "tools": r.tools,
                    "allowed_models": r.allowed_models,
                    "connectors": r.connectors,
                    "effect": r.effect,
                    "requires_approval": r.requires_approval,
                    "approval_timeout": r.approval_timeout,
                    "log": r.log,
                    "priority": r.priority,
                    "description": r.description,
                }
                for r in self.rules
            ],
            "created_at": self.created_at,
            "tags": self.tags,
            "description": self.description,
            "enabled": self.enabled,
        }


# ---------------------------------------------------------------------------
# PolicyDecision
# ---------------------------------------------------------------------------

@dataclass
class PolicyDecision:
    """Result of a policy check.

    Attributes
    ----------
    allowed : bool
        Whether the action is permitted.
    effect : str
        The applied effect: ``allow``, ``deny``, ``allow_with_approval``,
        ``log_only``.
    policy_id : str
        Which policy produced this decision.
    rule_index : int
        Index of the matching rule within the policy (-1 if default).
    reason : str
        Human-readable explanation.
    agent_id : str
        The agent that requested the action.
    resource : str
        The resource type.
    action : str
        The action verb.
    target : str
        The specific target.
    timestamp : float
        When the decision was made.
    requires_approval : bool
        Whether the action needs approval before proceeding.
    approval_id : str
        If approval is required, the ID of the approval request.
    """

    allowed: bool = False
    effect: str = "deny"
    policy_id: str = ""
    rule_index: int = -1
    reason: str = ""
    agent_id: str = ""
    resource: str = ""
    action: str = ""
    target: str = ""
    timestamp: float = field(default_factory=time.time)
    requires_approval: bool = False
    approval_id: str = ""


# ---------------------------------------------------------------------------
# ApprovalRequest
# ---------------------------------------------------------------------------

@dataclass
class ApprovalRequest:
    """A pending approval request.

    Created when a rule has ``requires_approval=True``.
    """

    request_id: str = ""
    agent_id: str = ""
    resource: str = ""
    action: str = ""
    target: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    policy_id: str = ""
    rule_index: int = -1
    created_at: float = field(default_factory=time.time)
    timeout: float = 300.0
    status: str = "pending"  # pending | approved | denied | expired
    decided_by: str = ""
    decided_at: Optional[float] = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            self.request_id = uuid.uuid4().hex[:12]

    @property
    def expired(self) -> bool:
        """Return ``True`` if the request has timed out."""
        if self.status != "pending":
            return False
        return time.time() > self.created_at + self.timeout


# ---------------------------------------------------------------------------
# PolicyEngine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """Declarative, hot-reloadable policy engine.  Default-deny.

    Policies are loaded from YAML files and can be updated at runtime
    without restarting any agent.  Policy changes take effect within 1
    second (hot-reload interval).

    Decision flow:
        1. Find all policies matching the agent (by ``agent_pattern``).
        2. Sort by specificity (most specific pattern first).
        3. Evaluate rules in order — first match wins.
        4. If no match: apply ``default_action`` (usually ``deny``).

    Parameters
    ----------
    policies_dir : str, optional
        Directory containing ``*.yaml`` policy files.
    on_decision : callable, optional
        ``async (decision: PolicyDecision)`` called after each decision.
    """

    def __init__(
        self,
        policies_dir: Optional[str] = None,
        on_decision: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._policies: dict[str, Policy] = {}
        self._policies_dir = policies_dir
        self._file_mtimes: dict[str, float] = {}
        self._decisions: list[PolicyDecision] = []
        self._approvals: dict[str, ApprovalRequest] = {}
        self._on_decision = on_decision
        self._hot_reload_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._max_decisions = 10_000

    # -- decision -----------------------------------------------------------

    async def check(
        self,
        agent_id: str,
        resource: str,
        action: str,
        target: str = "",
    ) -> PolicyDecision:
        """Check whether *agent_id* may perform ``(resource, action, target)``.

        Returns a :class:`PolicyDecision` with ``allowed=True/False``.
        """
        matching = self._get_matching_policies(agent_id)

        # Sort by specificity: longer pattern = more specific
        matching.sort(key=lambda p: len(p.agent_pattern), reverse=True)

        for policy in matching:
            if not policy.enabled:
                continue
            for idx, rule in enumerate(policy.rules):
                if rule.matches(resource, action, target):
                    decision = PolicyDecision(
                        allowed=rule.effect in ("allow", "allow_with_approval", "log_only"),
                        effect=rule.effect,
                        policy_id=policy.policy_id,
                        rule_index=idx,
                        reason=rule.description or f"Matched rule {idx} in {policy.policy_id}",
                        agent_id=agent_id,
                        resource=resource,
                        action=action,
                        target=target,
                        requires_approval=rule.requires_approval,
                    )

                    # Handle approval workflow
                    if rule.requires_approval and rule.effect == "allow_with_approval":
                        approval = ApprovalRequest(
                            agent_id=agent_id,
                            resource=resource,
                            action=action,
                            target=target,
                            policy_id=policy.policy_id,
                            rule_index=idx,
                            timeout=rule.approval_timeout,
                        )
                        self._approvals[approval.request_id] = approval
                        decision.approval_id = approval.request_id
                        decision.allowed = False  # Not allowed until approved

                    await self._record_decision(decision)
                    return decision

            # No rule matched — apply default
            decision = PolicyDecision(
                allowed=policy.default_action == "allow",
                effect=policy.default_action,
                policy_id=policy.policy_id,
                rule_index=-1,
                reason=f"Default action ({policy.default_action}) from {policy.policy_id}",
                agent_id=agent_id,
                resource=resource,
                action=action,
                target=target,
            )
            await self._record_decision(decision)
            return decision

        # No policy matched at all — global default deny
        decision = PolicyDecision(
            allowed=False,
            effect="deny",
            policy_id="",
            rule_index=-1,
            reason="No matching policy found (global default deny)",
            agent_id=agent_id,
            resource=resource,
            action=action,
            target=target,
        )
        await self._record_decision(decision)
        return decision

    async def check_bulk(
        self,
        agent_id: str,
        checks: Sequence[tuple[str, str, str]],
    ) -> list[PolicyDecision]:
        """Evaluate multiple ``(resource, action, target)`` tuples at once."""
        return [
            await self.check(agent_id, resource, action, target)
            for resource, action, target in checks
        ]

    # -- policy management --------------------------------------------------

    async def load_policy(self, path: str) -> Policy:
        """Load a single policy from a YAML file."""
        data = _load_yaml_file(path)
        policy = Policy.from_dict(data)
        async with self._lock:
            self._policies[policy.policy_id] = policy
            self._file_mtimes[path] = os.path.getmtime(path)
        log.info(
            "Loaded policy %s (agent=%s, rules=%d)",
            policy.policy_id, policy.agent_pattern, len(policy.rules),
        )
        return policy

    async def apply_policy(self, policy: Policy) -> None:
        """Apply a programmatically created policy."""
        async with self._lock:
            self._policies[policy.policy_id] = policy
        log.info("Applied policy %s", policy.policy_id)

    async def revoke_policy(self, policy_id: str) -> bool:
        """Remove a policy.  Returns ``True`` if found."""
        async with self._lock:
            removed = self._policies.pop(policy_id, None)
        if removed:
            log.info("Revoked policy %s", policy_id)
        return removed is not None

    def get_policy(self, policy_id: str) -> Optional[Policy]:
        """Return a single policy by ID."""
        return self._policies.get(policy_id)

    def get_agent_policies(self, agent_id: str) -> list[Policy]:
        """Return all policies that match *agent_id*."""
        return self._get_matching_policies(agent_id)

    def list_policies(self) -> list[Policy]:
        """Return all registered policies."""
        return list(self._policies.values())

    # -- hot reload ---------------------------------------------------------

    async def start_hot_reload(self, interval_seconds: float = 1.0) -> None:
        """Start background task that watches YAML files for changes.

        Checks mtimes every *interval_seconds* and reloads modified files.
        """
        if self._hot_reload_task and not self._hot_reload_task.done():
            log.warning("Hot-reload already running")
            return

        async def _watcher() -> None:
            while True:
                try:
                    await asyncio.sleep(interval_seconds)
                    await self._check_and_reload()
                except asyncio.CancelledError:
                    break
                except Exception:
                    log.exception("Hot-reload cycle failed")

        self._hot_reload_task = asyncio.create_task(_watcher())
        log.info("Started hot-reload (interval=%.1fs)", interval_seconds)

    async def stop_hot_reload(self) -> None:
        """Stop the hot-reload background task."""
        if self._hot_reload_task and not self._hot_reload_task.done():
            self._hot_reload_task.cancel()
            try:
                await self._hot_reload_task
            except asyncio.CancelledError:
                pass
            self._hot_reload_task = None
            log.info("Stopped hot-reload")

    async def reload_now(self) -> int:
        """Force-reload all policy files.  Returns count reloaded."""
        return await self._check_and_reload(force=True)

    async def load_directory(self, dir_path: Optional[str] = None) -> int:
        """Load all ``*.yaml`` files from a directory.  Returns count."""
        target = dir_path or self._policies_dir
        if not target or not os.path.isdir(target):
            return 0

        count = 0
        for entry in sorted(os.listdir(target)):
            if entry.endswith((".yaml", ".yml")):
                full = os.path.join(target, entry)
                try:
                    await self.load_policy(full)
                    count += 1
                except Exception:
                    log.exception("Failed to load policy %s", full)
        return count

    # -- approval workflow --------------------------------------------------

    async def request_approval(
        self,
        agent_id: str,
        action: str,
        context: Optional[dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """Create a new approval request."""
        req = ApprovalRequest(
            agent_id=agent_id,
            action=action,
            context=context or {},
        )
        self._approvals[req.request_id] = req
        log.info(
            "Approval requested: %s by %s (action=%s)",
            req.request_id, agent_id, action,
        )
        return req

    async def approve(self, request_id: str, approver: str) -> bool:
        """Approve a pending request.  Returns ``True`` if successful."""
        req = self._approvals.get(request_id)
        if not req or req.status != "pending":
            return False
        if req.expired:
            req.status = "expired"
            return False
        req.status = "approved"
        req.decided_by = approver
        req.decided_at = time.time()
        log.info("Approved %s by %s", request_id, approver)
        return True

    async def deny_approval(self, request_id: str, reason: str = "") -> None:
        """Deny a pending approval request."""
        req = self._approvals.get(request_id)
        if not req or req.status != "pending":
            return
        req.status = "denied"
        req.reason = reason
        req.decided_at = time.time()
        log.info("Denied %s: %s", request_id, reason)

    def get_pending_approvals(
        self,
        agent_id: Optional[str] = None,
    ) -> list[ApprovalRequest]:
        """Return all pending (non-expired) approval requests."""
        result: list[ApprovalRequest] = []
        for req in self._approvals.values():
            if req.expired:
                req.status = "expired"
                continue
            if req.status != "pending":
                continue
            if agent_id and req.agent_id != agent_id:
                continue
            result.append(req)
        return result

    # -- audit --------------------------------------------------------------

    def get_decisions(
        self,
        agent_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[PolicyDecision]:
        """Return recent decisions, optionally filtered by agent."""
        decisions = self._decisions
        if agent_id:
            decisions = [d for d in decisions if d.agent_id == agent_id]
        return decisions[-limit:]

    def get_violations(
        self,
        since: Optional[float] = None,
    ) -> list[PolicyDecision]:
        """Return all deny decisions since *since*."""
        result: list[PolicyDecision] = []
        for d in self._decisions:
            if d.effect == "deny":
                if since and d.timestamp < since:
                    continue
                result.append(d)
        return result

    # -- default profiles ---------------------------------------------------

    @staticmethod
    def create_default_deny() -> Policy:
        """Create a policy that blocks everything."""
        return Policy(
            policy_id="default-deny",
            version=1,
            default_action="deny",
            agent_pattern="*",
            rules=[],
            description="Global default-deny policy. Blocks all actions.",
            tags=["system", "default"],
        )

    @staticmethod
    def create_standard(
        agent_name: str,
        allowed_models: Optional[list[str]] = None,
        allowed_tools: Optional[list[str]] = None,
        allowed_domains: Optional[list[str]] = None,
    ) -> Policy:
        """Create a standard agent policy with common permissions."""
        rules: list[PolicyRule] = []

        # Network: inference always allowed
        rules.append(PolicyRule(
            resource="network",
            action="outbound",
            destinations=["*.openai.com", "*.anthropic.com", "*.moonshot.ai",
                          "*.perplexity.ai", "*.together.xyz", "openrouter.ai",
                          "*.googleapis.com"],
            effect="allow",
            description="Allow inference endpoints",
        ))

        if allowed_domains:
            rules.append(PolicyRule(
                resource="network",
                action="outbound",
                destinations=allowed_domains,
                effect="allow",
                description="Allow custom domains",
            ))

        # Filesystem: workspace read/write
        rules.append(PolicyRule(
            resource="filesystem",
            action="read",
            paths=["/workspace/*", "/tmp/*"],
            effect="allow",
            description="Allow workspace + tmp reads",
        ))
        rules.append(PolicyRule(
            resource="filesystem",
            action="write",
            paths=["/workspace/*", "/tmp/*"],
            effect="allow",
            description="Allow workspace + tmp writes",
        ))

        # Models
        if allowed_models:
            rules.append(PolicyRule(
                resource="model",
                action="*",
                allowed_models=allowed_models,
                effect="allow",
                description="Allowed models",
            ))

        # Tools
        if allowed_tools:
            rules.append(PolicyRule(
                resource="tool",
                action="call",
                tools=allowed_tools,
                effect="allow",
                description="Allowed tools",
            ))

        # Memory
        rules.append(PolicyRule(
            resource="memory",
            action="read",
            effect="allow",
            description="Allow memory reads",
        ))
        rules.append(PolicyRule(
            resource="memory",
            action="write",
            effect="allow",
            description="Allow memory writes",
        ))

        return Policy(
            policy_id=f"standard-{agent_name}",
            version=1,
            default_action="deny",
            agent_pattern=f"{agent_name}*",
            rules=rules,
            description=f"Standard policy for {agent_name} agents",
            tags=["standard"],
        )

    @staticmethod
    def create_external_agent() -> Policy:
        """Create a heavily restricted policy for external/cross-org agents."""
        rules = [
            PolicyRule(
                resource="network",
                action="outbound",
                destinations=["*.openai.com", "*.anthropic.com"],
                effect="allow",
                description="Limited inference access",
            ),
            PolicyRule(
                resource="filesystem",
                action="read",
                paths=["/workspace/shared/*"],
                effect="allow",
                description="Read-only shared workspace",
            ),
            PolicyRule(
                resource="model",
                action="*",
                allowed_models=["gemma-4-12b", "gemma-4-e4b"],
                effect="allow",
                description="Small models only",
            ),
            PolicyRule(
                resource="tool",
                action="call",
                tools=["search", "read_file"],
                effect="allow",
                description="Read-only tools",
            ),
            PolicyRule(
                resource="memory",
                action="read",
                effect="allow",
                description="Read-only memory",
            ),
        ]
        return Policy(
            policy_id="external-agent",
            version=1,
            default_action="deny",
            agent_pattern="external-*",
            rules=rules,
            description="Heavily restricted policy for external agents",
            tags=["external", "restricted"],
        )

    # -- internal -----------------------------------------------------------

    def _get_matching_policies(self, agent_id: str) -> list[Policy]:
        """Return all policies whose ``agent_pattern`` matches *agent_id*."""
        return [
            p for p in self._policies.values()
            if p.matches_agent(agent_id) and p.enabled
        ]

    async def _record_decision(self, decision: PolicyDecision) -> None:
        """Record a decision and invoke the callback."""
        self._decisions.append(decision)
        # Trim old decisions to prevent unbounded growth
        if len(self._decisions) > self._max_decisions:
            self._decisions = self._decisions[-self._max_decisions:]

        if self._on_decision:
            try:
                await self._on_decision(decision)
            except Exception:
                log.exception("on_decision callback failed")

    async def _check_and_reload(self, force: bool = False) -> int:
        """Check for modified YAML files and reload them.  Returns count."""
        if not self._policies_dir or not os.path.isdir(self._policies_dir):
            return 0

        count = 0
        for entry in os.listdir(self._policies_dir):
            if not entry.endswith((".yaml", ".yml")):
                continue
            full = os.path.join(self._policies_dir, entry)
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                continue

            if force or mtime > self._file_mtimes.get(full, 0):
                try:
                    await self.load_policy(full)
                    count += 1
                except Exception:
                    log.exception("Failed to reload %s", full)

        if count:
            log.info("Hot-reload: reloaded %d policies", count)
        return count

    def __repr__(self) -> str:
        return (
            f"<PolicyEngine policies={len(self._policies)} "
            f"decisions={len(self._decisions)}>"
        )
