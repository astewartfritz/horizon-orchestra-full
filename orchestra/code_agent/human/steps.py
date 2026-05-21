"""Step tracking with automatic git commits at major milestones.

Every major step (file write, edit, scaffold, git operation) creates a git commit
so the user can review what changed and revert if the agent goes off track.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Step:
    id: int
    action: str  # write, edit, scaffold, git, bash, read
    summary: str
    files_changed: list[str] = field(default_factory=list)
    commit_hash: str = ""
    commit_message: str = ""
    timestamp: float = 0.0
    status: str = "committed"  # committed, pending_review, rejected, reverted

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "summary": self.summary[:200],
            "files_changed": self.files_changed[:10],
            "commit_hash": self.commit_hash[:12],
            "commit_message": self.commit_message[:100],
            "timestamp": self.timestamp,
            "status": self.status,
        }


class StepTracker:
    """Tracks major steps and creates git commits for each one."""

    MAJOR_ACTIONS = {"write", "edit", "scaffold", "git", "delete"}

    def __init__(self, workspace: str | Path = "."):
        self.workspace = Path(workspace).resolve()
        self._steps: list[Step] = []
        self._counter = 0
        self._last_branch = ""
        self.logger = logging.getLogger("orchestra.steps")
        self._git_available = self._check_git()

    def _check_git(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True, cwd=self.workspace, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def record(self, action: str, summary: str, files: list[str] | None = None,
               auto_commit: bool = True) -> Step:
        self._counter += 1
        step = Step(
            id=self._counter,
            action=action,
            summary=summary,
            files_changed=files or [],
            timestamp=time.time(),
        )

        if action in self.MAJOR_ACTIONS and auto_commit and self._git_available:
            self._commit(step)

        self._steps.append(step)
        self.logger.info("Step %d: %s — %s", step.id, action, summary[:80])
        return step

    def _commit(self, step: Step) -> None:
        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, cwd=self.workspace, timeout=15,
            )

            # Check if there's anything to commit
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, cwd=self.workspace, timeout=10,
            )
            if not status.stdout.strip():
                return

            # Create commit
            branch = self._get_branch()
            msg = f"[Orchestra] {step.action}: {step.summary[:80]}"
            result = subprocess.run(
                ["git", "commit", "-m", msg],
                capture_output=True, text=True, cwd=self.workspace, timeout=15,
            )

            if result.returncode == 0:
                # Get commit hash
                hash_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True, cwd=self.workspace, timeout=5,
                )
                step.commit_hash = hash_result.stdout.strip()
                step.commit_message = msg
                step.status = "committed"
                self.logger.info("  → Committed as %s on %s", step.commit_hash[:8], branch)
        except Exception as e:
            self.logger.warning("  → Commit failed: %s", e)

    def _get_branch(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, cwd=self.workspace, timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    def get_steps(self, limit: int = 20) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._steps[-limit:]]

    def revert_to(self, step_id: int) -> bool:
        """Revert workspace to the state at a given step's commit."""
        for s in self._steps:
            if s.id == step_id and s.commit_hash:
                try:
                    subprocess.run(
                        ["git", "checkout", "--", "."],
                        capture_output=True, cwd=self.workspace, timeout=15,
                    )
                    subprocess.run(
                        ["git", "reset", "--hard", s.commit_hash],
                        capture_output=True, cwd=self.workspace, timeout=15,
                    )
                    s.status = "reverted"
                    self.logger.info("Reverted to step %d (%s)", step_id, s.commit_hash[:8])
                    return True
                except Exception as e:
                    self.logger.error("Revert failed: %s", e)
                    return False
        return False
