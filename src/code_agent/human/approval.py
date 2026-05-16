"""Approval/rejection workflow for tool calls with human-in-the-loop.

Users can review, approve, reject, or revert changes at each major step.
The system keeps users informed by automatically committing changes at major steps.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVERTED = "reverted"


@dataclass
class ApprovalRequest:
    id: str
    tool_name: str
    args: dict[str, Any]
    summary: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    feedback: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool_name,
            "args": self.args,
            "summary": self.summary[:200],
            "status": self.status.value,
            "feedback": self.feedback[:200],
        }


class ApprovalManager:
    """Manages approval/rejection of tool calls.

    Keeps users informed, allows revert to earlier states if the agent goes off track.
    Reduces the distance between idea, prototype, and deployable app.
    """

    def __init__(self, auto_approve: bool = False):
        self._requests: dict[str, ApprovalRequest] = {}
        self._pending: asyncio.Event = asyncio.Event()
        self._auto_approve = auto_approve

    def request_approval(self, tool_name: str, args: dict[str, Any],
                         summary: str = "") -> ApprovalRequest:
        import uuid
        req = ApprovalRequest(
            id=str(uuid.uuid4())[:8],
            tool_name=tool_name,
            args=args,
            summary=summary or f"Execute {tool_name}",
        )
        self._requests[req.id] = req

        if self._auto_approve:
            req.status = ApprovalStatus.APPROVED
        else:
            self._pending.set()

        return req

    async def wait_for_decision(self, req_id: str, timeout: float = 300) -> ApprovalRequest:
        req = self._requests.get(req_id)
        if not req:
            raise ValueError(f"Unknown request: {req_id}")

        if self._auto_approve:
            return req

        # Wait for user decision or timeout
        start = asyncio.get_event_loop().time()
        while req.status == ApprovalStatus.PENDING:
            await asyncio.sleep(0.5)
            if asyncio.get_event_loop().time() - start > timeout:
                req.status = ApprovalStatus.REJECTED
                req.feedback = "Timed out waiting for approval"
                break

        return req

    def approve(self, req_id: str, feedback: str = "") -> ApprovalRequest | None:
        req = self._requests.get(req_id)
        if req and req.status == ApprovalStatus.PENDING:
            req.status = ApprovalStatus.APPROVED
            req.feedback = feedback
            self._pending.clear()
        return req

    def reject(self, req_id: str, feedback: str = "") -> ApprovalRequest | None:
        req = self._requests.get(req_id)
        if req and req.status == ApprovalStatus.PENDING:
            req.status = ApprovalStatus.REJECTED
            req.feedback = feedback or "Rejected by user"
            self._pending.clear()
        return req

    def pending_requests(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._requests.values()
                if r.status == ApprovalStatus.PENDING]

    def history(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._requests.values()]
