"""Human-in-the-loop agent loop wrapper.

Keeps users informed by automatically committing changes at major steps.
Users can review, approve, reject, or revert changes.
Reduces the distance between idea, prototype, and deployable app.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from orchestra.code_agent import Agent, AgentConfig
from orchestra.code_agent.human.steps import StepTracker
from orchestra.code_agent.human.approval import ApprovalManager


class HumanInTheLoopAgent:
    """Wraps the Agent with human-in-the-loop controls.

    - Auto-commits changes at every major step (write/edit/scaffold/git)
    - Tracks a visual step history the user can review
    - Supports approve/reject/revert per step
    - Both non-coders and developers share the same editing model:
      visual first for speed, code access when deeper customization is needed
    """

    def __init__(self, config: AgentConfig, workspace: str | Path | None = None):
        self.agent = Agent(config)
        self.workspace = Path(workspace or config.workspace or ".").resolve()
        self.steps = StepTracker(self.workspace)
        self.approval = ApprovalManager(auto_approve=False)
        self.logger = logging.getLogger("orchestra.hitl")

    async def run(self, task: str) -> str:
        """Run a task with human-in-the-loop oversight."""
        self.logger.info("Starting task: %s", task[:100])

        # Record task start as a step
        self.steps.record("task", f"Task: {task[:80]}")

        # The agent's tool execution is wrapped by the step tracker
        # via _build_context and the _run_loop
        result = await self.agent.run(task, stream=True)

        # Record completion
        self.steps.record("complete", f"Task completed: {result[:80]}" if result else "Task completed")

        return result

    def get_step_history(self) -> list[dict[str, Any]]:
        return self.steps.get_steps(limit=50)

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        return self.approval.pending_requests()

    def approve(self, req_id: str, feedback: str = "") -> bool:
        req = self.approval.approve(req_id, feedback)
        if req:
            self.steps.record("approve", f"Approved: {req.summary[:80]}")
            return True
        return False

    def reject(self, req_id: str, feedback: str = "") -> bool:
        req = self.approval.reject(req_id, feedback)
        if req:
            self.steps.record("reject", f"Rejected: {req.summary[:80]}")
            return True
        return False

    def revert_to(self, step_id: int) -> bool:
        """Revert workspace to a previous step's state."""
        success = self.steps.revert_to(step_id)
        if success:
            self.logger.info("Reverted to step %d", step_id)
        return success
