"""Horizon Orchestra — Git Operations via Subprocess.

Pure asyncio wrapper around the ``git`` CLI. No gitpython dependency.
All operations use ``asyncio.create_subprocess_exec`` for non-blocking I/O.

Usage::

    from orchestra.codebase.git_ops import GitConfig, GitOps

    cfg = GitConfig(repo_path="/path/to/repo", user_name="Bot", user_email="bot@example.com")
    git = GitOps(cfg)
    status = await git.status()
    result = await git.commit("feat: add new feature")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "GitConfig",
    "GitOps",
]

log = logging.getLogger("orchestra.codebase.git_ops")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class GitConfig:
    """Configuration for a git repository.

    Attributes:
        repo_path: Absolute path to the repository root.
        default_branch: Default branch name (typically 'main' or 'master').
        user_name: Git user.name for commits.
        user_email: Git user.email for commits.
        auto_commit: If True, ``GitOps`` methods that modify the working tree
            will automatically stage and commit changes.
    """

    repo_path: str
    default_branch: str = "main"
    user_name: str = ""
    user_email: str = ""
    auto_commit: bool = False


# ---------------------------------------------------------------------------
# GitOps
# ---------------------------------------------------------------------------

class GitOps:
    """Async git operations for a single repository.

    All public methods are coroutines (``async def``) and return plain
    dicts or lists that can be serialised to JSON.

    Args:
        config: Repository configuration.
    """

    def __init__(self, config: GitConfig) -> None:
        self.config = config
        self._repo = Path(config.repo_path).resolve()

    # ------------------------------------------------------------------
    # Status & information
    # ------------------------------------------------------------------

    async def status(self) -> dict[str, Any]:
        """Return parsed git status.

        Returns a dict with keys:
        - ``staged``: list of staged files
        - ``modified``: list of modified but unstaged files
        - ``untracked``: list of untracked files
        - ``branch``: current branch name
        - ``clean``: True if the working tree is clean

        Returns:
            dict with parsed status information.
        """
        stdout, stderr, code = await self._run_git("status", "--porcelain=v1", "-b")
        if code != 0:
            return {"error": stderr, "exit_code": code}

        staged: list[str] = []
        modified: list[str] = []
        untracked: list[str] = []
        branch = "unknown"

        for line in stdout.splitlines():
            if line.startswith("## "):
                # Parse branch from "## main...origin/main [ahead 1]"
                branch_part = line[3:].split("...")[0].split(" ")[0]
                branch = branch_part
                continue

            if len(line) < 3:
                continue

            xy = line[:2]
            path = line[3:]

            # Staged changes: first character non-space
            if xy[0] != " " and xy[0] != "?":
                staged.append(path)
            # Unstaged modifications: second character non-space
            if xy[1] != " " and xy[1] != "?":
                modified.append(path)
            # Untracked files
            if xy == "??":
                untracked.append(path)

        return {
            "branch": branch,
            "staged": staged,
            "modified": modified,
            "untracked": untracked,
            "clean": not staged and not modified and not untracked,
        }

    async def diff(self, staged: bool = False) -> str:
        """Return the current diff.

        Args:
            staged: If True, show staged diff (``git diff --cached``).
                Otherwise show unstaged diff.

        Returns:
            Diff output as a string.
        """
        args = ["diff"]
        if staged:
            args.append("--cached")
        stdout, stderr, code = await self._run_git(*args)
        if code != 0:
            log.warning("git diff error: %s", stderr)
        return stdout

    async def log(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent commit history.

        Args:
            limit: Maximum number of commits to return.

        Returns:
            List of commit dicts with keys: hash, author, email, date,
            subject, body.
        """
        fmt = "%H%x00%an%x00%ae%x00%aI%x00%s%x00%b%x1E"
        stdout, stderr, code = await self._run_git(
            "log", f"-{limit}", f"--format={fmt}", "--no-merges"
        )
        if code != 0:
            log.warning("git log error: %s", stderr)
            return []

        commits: list[dict[str, Any]] = []
        for record in stdout.split("\x1e"):
            record = record.strip()
            if not record:
                continue
            parts = record.split("\x00")
            if len(parts) < 6:
                continue
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "email": parts[2],
                "date": parts[3],
                "subject": parts[4],
                "body": parts[5].strip(),
            })

        return commits

    # ------------------------------------------------------------------
    # Committing
    # ------------------------------------------------------------------

    async def commit(
        self,
        message: str,
        files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Stage files and create a commit.

        Args:
            message: Commit message.
            files: Specific files to stage. If ``None``, all changes
                are staged (``git add -A``).

        Returns:
            Dict with ``success``, ``hash``, ``message``, and optional ``error``.
        """
        # Configure user if provided
        if self.config.user_name:
            await self._run_git("config", "user.name", self.config.user_name)
        if self.config.user_email:
            await self._run_git("config", "user.email", self.config.user_email)

        # Stage files
        if files:
            for f in files:
                _, stderr, code = await self._run_git("add", f)
                if code != 0:
                    return {"success": False, "error": f"git add failed: {stderr}"}
        else:
            _, stderr, code = await self._run_git("add", "-A")
            if code != 0:
                return {"success": False, "error": f"git add -A failed: {stderr}"}

        # Commit
        stdout, stderr, code = await self._run_git("commit", "-m", message)
        if code != 0:
            return {"success": False, "error": stderr, "stdout": stdout}

        # Get the new commit hash
        hash_out, _, _ = await self._run_git("rev-parse", "HEAD")
        commit_hash = hash_out.strip()

        log.info("Committed: %s — %s", commit_hash[:8], message[:60])
        return {
            "success": True,
            "hash": commit_hash,
            "message": message,
            "output": stdout.strip(),
        }

    # ------------------------------------------------------------------
    # Branch management
    # ------------------------------------------------------------------

    async def branch_create(self, name: str) -> dict[str, Any]:
        """Create and switch to a new branch.

        Args:
            name: Branch name.

        Returns:
            Dict with ``success``, ``branch``, and optional ``error``.
        """
        stdout, stderr, code = await self._run_git("checkout", "-b", name)
        if code != 0:
            return {"success": False, "branch": name, "error": stderr}
        log.info("Created branch: %s", name)
        return {"success": True, "branch": name, "output": stdout.strip()}

    async def branch_switch(self, name: str) -> dict[str, Any]:
        """Switch to an existing branch.

        Args:
            name: Branch name to switch to.

        Returns:
            Dict with ``success``, ``branch``, and optional ``error``.
        """
        stdout, stderr, code = await self._run_git("checkout", name)
        if code != 0:
            return {"success": False, "branch": name, "error": stderr}
        log.info("Switched to branch: %s", name)
        return {"success": True, "branch": name, "output": stdout.strip()}

    async def branch_list(self) -> list[dict[str, Any]]:
        """List all local branches.

        Returns:
            List of branch dicts with ``name``, ``current``, and ``hash``.
        """
        stdout, stderr, code = await self._run_git(
            "branch", "-v", "--format=%(refname:short)%09%(objectname:short)%09%(HEAD)"
        )
        if code != 0:
            log.warning("git branch list error: %s", stderr)
            return []

        branches: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                branches.append({
                    "name": parts[0],
                    "hash": parts[1],
                    "current": parts[2] == "*",
                })
            elif len(parts) == 2:
                branches.append({
                    "name": parts[0],
                    "hash": parts[1],
                    "current": False,
                })

        return branches

    async def merge(self, branch: str) -> dict[str, Any]:
        """Merge *branch* into the current branch.

        Args:
            branch: Name of the branch to merge in.

        Returns:
            Dict with ``success``, ``branch``, ``conflicts``, and optional ``error``.
        """
        stdout, stderr, code = await self._run_git("merge", branch, "--no-edit")
        conflicts: list[str] = []

        if code != 0:
            # Extract conflicted files from output
            for line in (stdout + stderr).splitlines():
                if "CONFLICT" in line:
                    m = re.search(r"Merge conflict in (.+)", line)
                    if m:
                        conflicts.append(m.group(1).strip())
            return {
                "success": False,
                "branch": branch,
                "conflicts": conflicts,
                "error": stderr or stdout,
            }

        log.info("Merged %s into current branch", branch)
        return {
            "success": True,
            "branch": branch,
            "conflicts": [],
            "output": stdout.strip(),
        }

    # ------------------------------------------------------------------
    # Stash
    # ------------------------------------------------------------------

    async def stash(self) -> dict[str, Any]:
        """Stash current working tree changes.

        Returns:
            Dict with ``success`` and optional ``error``.
        """
        stdout, stderr, code = await self._run_git("stash")
        if code != 0:
            return {"success": False, "error": stderr}
        return {"success": True, "output": stdout.strip()}

    async def stash_pop(self) -> dict[str, Any]:
        """Pop the most recent stash.

        Returns:
            Dict with ``success``, ``conflicts``, and optional ``error``.
        """
        stdout, stderr, code = await self._run_git("stash", "pop")
        if code != 0:
            return {"success": False, "error": stderr, "output": stdout}
        return {"success": True, "output": stdout.strip()}

    # ------------------------------------------------------------------
    # Remote operations
    # ------------------------------------------------------------------

    async def push(self, remote: str = "origin", branch: str = "") -> dict[str, Any]:
        """Push commits to a remote.

        Args:
            remote: Remote name (default: ``"origin"``).
            branch: Branch to push. If empty, pushes the current branch.

        Returns:
            Dict with ``success``, ``remote``, ``branch``, and optional ``error``.
        """
        args = ["push", remote]
        if branch:
            args.append(branch)
        else:
            # Push current branch with upstream tracking
            args += ["--set-upstream", remote, "HEAD"]

        stdout, stderr, code = await self._run_git(*args)
        if code != 0:
            return {
                "success": False,
                "remote": remote,
                "branch": branch,
                "error": stderr,
            }

        log.info("Pushed to %s/%s", remote, branch or "HEAD")
        return {
            "success": True,
            "remote": remote,
            "branch": branch,
            "output": (stdout + stderr).strip(),
        }

    async def pull(self) -> dict[str, Any]:
        """Pull latest changes from upstream.

        Returns:
            Dict with ``success``, ``updated``, and optional ``error``.
        """
        stdout, stderr, code = await self._run_git("pull", "--ff-only")
        if code != 0:
            return {"success": False, "error": stderr, "output": stdout}

        updated = "Already up to date" not in stdout
        return {
            "success": True,
            "updated": updated,
            "output": stdout.strip(),
        }

    @classmethod
    async def clone(cls, url: str, dest: str) -> dict[str, Any]:
        """Clone a remote repository.

        Args:
            url: Remote URL to clone.
            dest: Destination directory path.

        Returns:
            Dict with ``success``, ``url``, ``dest``, and optional ``error``.
        """
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", url, dest,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        stdout = stdout_b.decode(errors="replace")
        stderr = stderr_b.decode(errors="replace")
        code = proc.returncode or 0

        if code != 0:
            log.error("git clone failed: %s", stderr)
            return {"success": False, "url": url, "dest": dest, "error": stderr}

        log.info("Cloned %s -> %s", url, dest)
        return {
            "success": True,
            "url": url,
            "dest": dest,
            "output": (stdout + stderr).strip(),
        }

    # ------------------------------------------------------------------
    # Core subprocess helper
    # ------------------------------------------------------------------

    async def _run_git(self, *args: str) -> tuple[str, str, int]:
        """Run a git command in the repository directory.

        Args:
            *args: Arguments to pass after ``git`` (e.g. ``"status"``,
                ``"--porcelain"``).

        Returns:
            Tuple of ``(stdout, stderr, returncode)``.
        """
        cmd = ["git"] + list(args)
        log.debug("Running: %s (in %s)", " ".join(cmd), self._repo)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self._repo),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )
            stdout_b, stderr_b = await proc.communicate()
        except FileNotFoundError:
            return "", "git executable not found", 127
        except Exception as exc:
            return "", str(exc), 1

        stdout = stdout_b.decode(errors="replace")
        stderr = stderr_b.decode(errors="replace")
        code = proc.returncode or 0

        if code != 0:
            log.debug("git %s exited %d: %s", args[0] if args else "", code, stderr[:200])

        return stdout, stderr, code
