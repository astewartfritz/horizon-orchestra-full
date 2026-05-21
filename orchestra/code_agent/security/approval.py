from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ApprovalWorkflow",
    "ApprovalRequest",
    "ApprovalStatus",
    "ApprovalPolicy",
    "ApprovalRequired",
]

log = logging.getLogger("orchestra.security.approval")


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = ""
    agent_purpose: str = ""
    action: str = ""
    resource: str = ""
    justification: str = ""
    risk_level: str = "medium"
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600)
    decided_by: str = ""
    decided_at: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalPolicy:
    name: str
    description: str
    resource_pattern: str  # glob pattern like "patient/*/phi"
    risk_level: str  # low, medium, high, critical
    auto_approve: bool = False  # skip human if trust_level >= threshold
    min_approvers: int = 1
    notify_roles: list[str] = field(default_factory=lambda: ["admin", "security"])


class ApprovalRequired(Exception):
    """Raised when an operation requires human approval."""
    def __init__(self, request: ApprovalRequest) -> None:
        self.request = request
        super().__init__(f"Approval required: {request.action} on {request.resource}")


class ApprovalWorkflow:
    """Human-in-the-loop approval system for high-risk agent operations.

    Agents request access to sensitive operations.  Human approvers
    review and approve/deny.  Requests expire after a TTL.
    """

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._policies: list[ApprovalPolicy] = [
            ApprovalPolicy(
                "phi_access", "Access to PHI data",
                "patient/*/phi", "high",
            ),
            ApprovalPolicy(
                "data_export", "Export data outside system",
                "*/export", "critical",
            ),
            ApprovalPolicy(
                "admin_action", "Administrative action",
                "admin/*", "high",
            ),
            ApprovalPolicy(
                "delete_data", "Delete user data",
                "*/delete", "critical",
            ),
            ApprovalPolicy(
                "financial_write", "Write to financial records",
                "billing/*/write", "high",
            ),
            ApprovalPolicy(
                "agent_config_change", "Change agent configuration",
                "agent/config/*", "medium",
            ),
        ]
        self._auto_approve_agents: set[str] = set()  # trusted agent IDs

    def register_policy(self, policy: ApprovalPolicy) -> None:
        """Add a custom approval policy."""
        self._policies.append(policy)

    def trust_agent(self, agent_id: str) -> None:
        """Mark an agent as trusted (auto-approve certain actions)."""
        self._auto_approve_agents.add(agent_id)

    def check_action(self, agent_id: str, agent_purpose: str,
                     action: str, resource: str, justification: str = "",
                     context: dict[str, Any] | None = None) -> ApprovalRequest | None:
        """Check if an action requires approval. Returns None if allowed.

        If a policy matches and the agent isn't trusted, creates an
        ApprovalRequest and raises ApprovalRequired.
        """
        matching = self._find_policy(resource)

        if not matching:
            return None  # no policy matched — allowed

        # Auto-approve trusted agents for non-critical
        if agent_id in self._auto_approve_agents and matching.risk_level != "critical":
            return None

        # Create approval request
        req = ApprovalRequest(
            agent_id=agent_id,
            agent_purpose=agent_purpose,
            action=action,
            resource=resource,
            justification=justification or f"{action} on {resource} by {agent_id}",
            risk_level=matching.risk_level,
            expires_at=time.time() + 3600,
            context=context or {},
        )
        self._requests[req.id] = req
        log.warning(
            "Approval required: agent=%s action=%s resource=%s request=%s",
            agent_id, action, resource, req.id,
        )
        return req

    def approve(self, request_id: str, approver: str) -> bool:
        """Approve a pending request. Returns True on success."""
        req = self._requests.get(request_id)
        if not req or req.status != ApprovalStatus.PENDING:
            return False
        if req.expires_at < time.time():
            req.status = ApprovalStatus.EXPIRED
            return False
        req.status = ApprovalStatus.APPROVED
        req.decided_by = approver
        req.decided_at = time.time()
        log.info("Request %s approved by %s", request_id, approver)
        return True

    def deny(self, request_id: str, approver: str) -> bool:
        """Deny a pending request. Returns True on success."""
        req = self._requests.get(request_id)
        if not req or req.status != ApprovalStatus.PENDING:
            return False
        req.status = ApprovalStatus.DENIED
        req.decided_by = approver
        req.decided_at = time.time()
        log.info("Request %s denied by %s", request_id, approver)
        return True

    def get_pending(self, limit: int = 50) -> list[ApprovalRequest]:
        """Return pending requests that haven't expired."""
        self._sweep_expired()
        return [r for r in self._requests.values()
                if r.status == ApprovalStatus.PENDING][:limit]

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        return self._requests.get(request_id)

    def get_stats(self) -> dict[str, int]:
        return {
            "pending": sum(1 for r in self._requests.values() if r.status == ApprovalStatus.PENDING),
            "approved": sum(1 for r in self._requests.values() if r.status == ApprovalStatus.APPROVED),
            "denied": sum(1 for r in self._requests.values() if r.status == ApprovalStatus.DENIED),
            "expired": sum(1 for r in self._requests.values() if r.status == ApprovalStatus.EXPIRED),
        }

    def _find_policy(self, resource: str) -> ApprovalPolicy | None:
        """Find the first matching policy for a resource."""
        import fnmatch
        for policy in self._policies:
            if fnmatch.fnmatch(resource, policy.resource_pattern):
                return policy
        return None

    def _sweep_expired(self) -> None:
        now = time.time()
        for req in self._requests.values():
            if req.status == ApprovalStatus.PENDING and req.expires_at < now:
                req.status = ApprovalStatus.EXPIRED
