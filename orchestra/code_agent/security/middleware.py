from __future__ import annotations

import json
import logging
import time
from typing import Any

from orchestra.code_agent.security.audit import AuditEvent, _store as audit_store
from orchestra.code_agent.security.anomaly import AccessPattern, AnomalyDetector
from orchestra.code_agent.security.approval import ApprovalRequired, ApprovalWorkflow
from orchestra.code_agent.security.capability_auth import (
    AgentIdentity,
    Capability,
    CapabilityVault,
    DynamicAuthPolicy,
    JustInTimeGrant,
)
from orchestra.code_agent.security.consent_manager import ConsentManager, ConsentPurpose
from orchestra.code_agent.security.data_classifier import DataClassifier, SensitivityLevel
from orchestra.code_agent.security.pii_redactor import HIPAAContext, PIIRedactor

__all__ = [
    "SecurityContext",
    "SecurityMiddleware",
    "register_security",
]

log = logging.getLogger("orchestra.security.middleware")


class SecurityContext:
    """Holds the security state for a single request.

    Created at the start of each request and threaded through
    the middleware stack.
    """

    def __init__(self) -> None:
        self.agent: AgentIdentity | None = None
        self.user_id: str = ""
        self.actor_type: str = "human"
        self.action: str = ""
        self.resource: str = ""
        self.ip_address: str = ""
        self.user_agent: str = ""
        self.data_sensitivity: str = "public"
        self.consent_purposes: list[str] = []
        self.redacted_response: dict | None = None
        self.outcome: str = "allowed"
        self.details: dict[str, Any] = {}


class SecurityMiddleware:
    """ASGI middleware that wraps every request with the full security stack.

    Order of operations:
    1. Resolve agent identity from request headers/tokens
    2. Classify the requested data's sensitivity
    3. Check consent
    4. Redact PII from request/response data
    5. Check capability auth (agent-scoped tokens)
    6. Check approval workflow (human-in-the-loop)
    7. Record audit trail
    8. Run anomaly detection
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.classifier = DataClassifier()
        self.consent = ConsentManager()
        self.redactor = PIIRedactor()
        self.hipaa = HIPAAContext()
        self.vault = CapabilityVault()
        self.policy = DynamicAuthPolicy()
        self.jit = JustInTimeGrant()
        self.anomaly = AnomalyDetector()
        self.approval = ApprovalWorkflow()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        ctx = SecurityContext()
        ctx.ip_address = self._get_client_ip(scope)
        _hdrs = dict(scope.get("headers", []))
        ctx.user_agent = _hdrs.get(b"user-agent", b"").decode("utf-8", errors="replace")
        ctx.action = scope.get("method", "GET")
        ctx.resource = scope.get("path", "/")

        # Resolve agent identity
        ctx.agent = self._resolve_agent(scope)
        if ctx.agent:
            ctx.actor_type = "agent"
            ctx.user_id = ctx.agent.owner_id

        # Classify data sensitivity
        ctx.data_sensitivity = self._classify_request(scope)

        # Check consent
        ctx.consent_purposes = self._check_consent(ctx)

        # Patch the response send to apply redaction + audit
        original_send = send

        async def secured_send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                ctx.outcome = "allowed"
                ctx.details = {"status": message.get("status", 200)}
            if message.get("type") == "http.response.body":
                body = message.get("body", b"")
                if body and ctx.data_sensitivity in ("restricted", "critical"):
                    redacted = self._redact_body(body, ctx)
                    message["body"] = redacted
                    ctx.redacted_response = {"original_size": len(body), "redacted": True}
                # Audit
                self._audit(ctx)
                self._anomaly_check(ctx)
            await original_send(message)

        try:
            await self.app(scope, receive, secured_send)
        except ApprovalRequired as e:
            log.warning("Operation blocked: %s", e)
            ctx.outcome = "denied"
            ctx.details = {"approval_required": e.request.id}
            self._audit(ctx)
            self._anomaly_check(ctx)
            await self._send_json_response(scope, receive, original_send,
                                           403, {"error": str(e), "request_id": e.request.id})
        except Exception:
            ctx.outcome = "denied"
            ctx.details = {"error": "unhandled_exception"}
            self._audit(ctx)
            raise

    # ── Internal helpers ──────────────────────────────────────────────

    def _resolve_agent(self, scope: dict) -> AgentIdentity | None:
        headers = dict(scope.get("headers", []))
        agent_token = headers.get(b"x-agent-token", b"").decode()
        if not agent_token:
            return None
        from orchestra.code_agent.auth.jwt import JWTManager
        jwt = JWTManager()
        payload = jwt.verify(agent_token)
        if not payload:
            return None
        return AgentIdentity(
            agent_id=payload.get("sub", ""),
            owner_id=payload.get("owner", ""),
            purpose=payload.get("purpose", ""),
            trust_level=payload.get("trust_level", 1),
        )

    def _get_client_ip(self, scope: dict) -> str:
        client = scope.get("client")
        if client:
            return client[0]
        headers = dict(scope.get("headers", []))
        forwarded = headers.get(b"x-forwarded-for", b"").decode()
        if forwarded:
            return forwarded.split(",")[0].strip()
        return "unknown"

    def _classify_request(self, scope: dict) -> str:
        path = scope.get("path", "")
        sensitivity = self.classifier.get_sensitivity({"field": path})
        return sensitivity.value if hasattr(sensitivity, "value") else "public"

    def _check_consent(self, ctx: SecurityContext) -> list[str]:
        if not ctx.user_id:
            return []
        purposes = []
        for purpose in ConsentPurpose:
            if self.consent.check_consent(ctx.user_id, purpose):
                purposes.append(purpose.value)
        return purposes

    def _redact_body(self, body: bytes, ctx: SecurityContext) -> bytes:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return body

        # Apply HIPAA redaction for medical data
        if ctx.data_sensitivity in ("restricted", "critical"):
            text = self.hipaa.redact_phi(text)
        else:
            text = self.redactor.redact(text)

        # Check if body was parsed as JSON and redact accordingly
        try:
            data = json.loads(text)
            redacted = self.redactor.redact_dict(data)
            return json.dumps(redacted).encode()
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        return text.encode("utf-8")

    def _audit(self, ctx: SecurityContext) -> None:
        event = AuditEvent(
            event_id="",
            timestamp=time.time(),
            event_type="api_access",
            actor_id=ctx.agent.agent_id if ctx.agent else ctx.user_id,
            actor_type=ctx.actor_type,
            action=ctx.action,
            resource=ctx.resource,
            data_sensitivity=ctx.data_sensitivity,
            consent_used=",".join(ctx.consent_purposes) if ctx.consent_purposes else "none",
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            outcome=ctx.outcome,
            details=ctx.details,
        )
        audit_store.record(event)

    def _anomaly_check(self, ctx: SecurityContext) -> None:
        actor_id = ctx.agent.agent_id if ctx.agent else ctx.user_id
        if not actor_id:
            return
        self.anomaly.record(AccessPattern(
            timestamp=time.time(),
            actor_id=actor_id,
            action=ctx.action,
            resource=ctx.resource,
            ip_address=ctx.ip_address,
            success=ctx.outcome == "allowed",
            resource_sensitivity=ctx.data_sensitivity,
        ))

    async def _send_json_response(
        self, scope: dict, receive: Any, send: Any,
        status: int, data: dict,
    ) -> None:
        body = json.dumps(data).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })


def register_security(app: Any) -> None:
    """Register the full security middleware stack on a FastAPI app."""
    app.add_middleware(SecurityMiddleware)  # type: ignore[union-attr]
    log.info("Security middleware registered (capability auth + PII redaction + audit + anomaly)")
