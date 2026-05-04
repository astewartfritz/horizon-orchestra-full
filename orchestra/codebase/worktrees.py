"""Horizon Orchestra — Multi-Agent Git Worktrees.

Implements the parallel worktree pattern made famous by Codex: multiple
agents work in isolated git worktrees simultaneously, then merge their
changes back into the main branch. Conflict resolution is LLM-assisted.

Usage::

    from orchestra.codebase.worktrees import WorktreeManager
    from orchestra.router import ModelRouter

    router = ModelRouter()
    mgr = WorktreeManager(repo_path="/path/to/repo", router=router)

    wt = await mgr.create("feature-auth", base_branch="main")
    print(wt.path)  # /path/to/repo/../_worktrees/feature-auth

    # Agents work in wt.path independently, then:
    result = await mgr.merge(wt.id)
    if result.conflicts:
        result = await mgr.auto_resolve_conflicts(result)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

__all__ = [
    "WorktreeStatus",
    "Worktree",
    "MergeResult",
    "WorktreeManager",
]

log = logging.getLogger("orchestra.codebase.worktrees")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class WorktreeStatus(str, Enum):
    """Lifecycle status of a git worktree."""

    ACTIVE = "active"
    MERGED = "merged"
    ABANDONED = "abandoned"


@dataclass
class Worktree:
    """A git worktree representing an isolated working directory.

    Attributes:
        id: Unique identifier (short UUID).
        name: Human-readable name (also used as the branch name).
        branch: Git branch checked out in this worktree.
        path: Absolute filesystem path to the worktree directory.
        agent_id: ID of the agent working in this worktree.
        status: Current lifecycle status.
        created_at: Unix timestamp of creation.
        base_branch: Branch from which this worktree was forked.
    """

    id: str
    name: str
    branch: str
    path: str
    agent_id: str = ""
    status: WorktreeStatus = WorktreeStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    base_branch: str = "main"


@dataclass
class MergeResult:
    """Outcome of merging a worktree branch into the target.

    Attributes:
        success: True if the merge completed without conflicts.
        conflicts: List of file paths with merge conflicts.
        merged_files: List of file paths that merged cleanly.
        conflict_files: Alias for conflicts (for clarity).
        resolution: Description of how conflicts were resolved.
        worktree_id: ID of the source worktree.
        target_branch: Branch that was merged into.
        diff: Full diff text of merged changes.
    """

    success: bool
    conflicts: list[str] = field(default_factory=list)
    merged_files: list[str] = field(default_factory=list)
    conflict_files: list[str] = field(default_factory=list)
    resolution: str = ""
    worktree_id: str = ""
    target_branch: str = "main"
    diff: str = ""


# ---------------------------------------------------------------------------
# WorktreeManager
# ---------------------------------------------------------------------------

class WorktreeManager:
    """Manage a pool of git worktrees for parallel agent work.

    Each worktree is created as a sibling directory next to the main repo
    under a ``_worktrees/`` subdirectory.

    Args:
        repo_path: Absolute path to the main git repository.
        router: ModelRouter for LLM-based conflict resolution. Optional;
            if not provided, auto-resolve will fall back to a heuristic.
        worktrees_dir: Where to store worktrees. Defaults to a
            ``_worktrees`` directory adjacent to *repo_path*.
    """

    def __init__(
        self,
        repo_path: str | Path,
        router: Any | None = None,
        worktrees_dir: str | Path | None = None,
    ) -> None:
        self._repo = Path(repo_path).resolve()
        self.router = router
        if worktrees_dir:
            self._wt_base = Path(worktrees_dir).resolve()
        else:
            self._wt_base = self._repo.parent / "_worktrees"
        self._wt_base.mkdir(parents=True, exist_ok=True)
        self._registry: dict[str, Worktree] = {}  # id → Worktree

    # ------------------------------------------------------------------
    # Create / remove worktrees
    # ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        base_branch: str = "main",
        agent_id: str = "",
    ) -> Worktree:
        """Create a new git worktree on a fresh branch.

        1. Creates branch ``name`` from ``base_branch``.
        2. Runs ``git worktree add <path> <branch>``.
        3. Registers and returns the :class:`Worktree`.

        Args:
            name: Worktree/branch name (must be a valid git branch name).
            base_branch: Branch to fork from.
            agent_id: Optional agent identifier for bookkeeping.

        Returns:
            Fully initialised :class:`Worktree` dataclass.

        Raises:
            RuntimeError: If the git worktree command fails.
        """
        wt_id = str(uuid.uuid4())[:8]
        wt_path = self._wt_base / name

        # Create branch from base_branch
        _, stderr, code = await self._run_git(
            "branch", name, base_branch,
        )
        if code != 0 and "already exists" not in stderr:
            raise RuntimeError(f"git branch failed: {stderr}")

        # Add the worktree
        _, stderr, code = await self._run_git(
            "worktree", "add", str(wt_path), name,
        )
        if code != 0:
            raise RuntimeError(f"git worktree add failed: {stderr}")

        worktree = Worktree(
            id=wt_id,
            name=name,
            branch=name,
            path=str(wt_path),
            agent_id=agent_id,
            status=WorktreeStatus.ACTIVE,
            base_branch=base_branch,
        )
        self._registry[wt_id] = worktree
        log.info("Created worktree %s at %s (branch: %s)", wt_id, wt_path, name)
        return worktree

    async def list(self) -> list[Worktree]:
        """Return all tracked worktrees.

        Also syncs with ``git worktree list`` to pick up externally added
        worktrees.

        Returns:
            List of :class:`Worktree` objects.
        """
        # Refresh from git
        await self._sync_from_git()
        return list(self._registry.values())

    async def remove(self, worktree_id: str) -> bool:
        """Remove a worktree and delete its directory.

        Args:
            worktree_id: Worktree ID from :attr:`Worktree.id`.

        Returns:
            True if the worktree was removed, False if not found.
        """
        wt = self._registry.get(worktree_id)
        if not wt:
            log.warning("Worktree %s not found", worktree_id)
            return False

        _, stderr, code = await self._run_git(
            "worktree", "remove", "--force", wt.path,
        )
        if code != 0:
            log.warning("git worktree remove failed: %s", stderr)

        wt.status = WorktreeStatus.ABANDONED
        del self._registry[worktree_id]
        log.info("Removed worktree %s", worktree_id)
        return True

    # ------------------------------------------------------------------
    # Merging
    # ------------------------------------------------------------------

    async def merge(
        self,
        worktree_id: str,
        target_branch: str = "main",
    ) -> MergeResult:
        """Merge a worktree branch into *target_branch*.

        Switches the main repo to *target_branch*, runs ``git merge``,
        collects conflict/merged file lists, and updates worktree status.

        Args:
            worktree_id: ID of the worktree to merge.
            target_branch: Branch to merge into.

        Returns:
            :class:`MergeResult` with conflict details.
        """
        wt = self._registry.get(worktree_id)
        if not wt:
            return MergeResult(
                success=False,
                worktree_id=worktree_id,
                target_branch=target_branch,
                resolution=f"Worktree {worktree_id} not found",
            )

        # Ensure main repo is on target_branch
        _, stderr, code = await self._run_git("checkout", target_branch)
        if code != 0:
            return MergeResult(
                success=False,
                worktree_id=worktree_id,
                target_branch=target_branch,
                resolution=f"Could not switch to {target_branch}: {stderr}",
            )

        # Get diff before merge
        diff_out, _, _ = await self._run_git("diff", target_branch, wt.branch)

        # Run the merge
        stdout, stderr, code = await self._run_git(
            "merge", wt.branch, "--no-edit", "--no-ff",
        )
        output = stdout + "\n" + stderr

        conflicts: list[str] = []
        merged_files: list[str] = []

        if code != 0:
            # Extract conflicted files
            for line in output.splitlines():
                m = re.search(r"CONFLICT.*?in (.+)", line)
                if m:
                    conflicts.append(m.group(1).strip())
            # Also check git status
            status_out, _, _ = await self._run_git("status", "--porcelain")
            for line in status_out.splitlines():
                if line.startswith("UU") or line.startswith("AA") or line.startswith("DD"):
                    fname = line[3:].strip()
                    if fname not in conflicts:
                        conflicts.append(fname)

            result = MergeResult(
                success=False,
                conflicts=conflicts,
                conflict_files=conflicts,
                worktree_id=worktree_id,
                target_branch=target_branch,
                diff=diff_out,
            )
            log.warning("Merge of %s has %d conflicts", wt.branch, len(conflicts))
            return result

        # Successful merge: extract merged files
        for line in output.splitlines():
            m = re.match(r"\s+(.+?)\s*\|", line)
            if m:
                merged_files.append(m.group(1).strip())

        wt.status = WorktreeStatus.MERGED
        log.info("Successfully merged %s into %s", wt.branch, target_branch)
        return MergeResult(
            success=True,
            merged_files=merged_files,
            worktree_id=worktree_id,
            target_branch=target_branch,
            diff=diff_out,
        )

    async def auto_resolve_conflicts(
        self,
        merge_result: MergeResult,
        model: str = "kimi-k2.5",
    ) -> MergeResult:
        """Use an LLM to resolve merge conflicts in conflicted files.

        For each conflicted file, reads the conflict markers and asks the
        LLM to produce a merged version. Writes the resolved content back
        and stages the file.

        Args:
            merge_result: Result from a failed :meth:`merge` call.
            model: LLM model name to use for conflict resolution.

        Returns:
            Updated :class:`MergeResult` with resolved conflicts.
        """
        if not merge_result.conflicts:
            return merge_result

        resolved: list[str] = []
        still_conflicted: list[str] = []

        for file_path in merge_result.conflicts:
            abs_path = self._repo / file_path
            if not abs_path.exists():
                still_conflicted.append(file_path)
                continue

            content = abs_path.read_text(encoding="utf-8", errors="replace")
            if "<<<<<<" not in content:
                # Already resolved externally
                resolved.append(file_path)
                continue

            # Ask LLM to resolve
            resolved_content = await self._llm_resolve_conflict(
                file_path, content, model
            )

            if resolved_content:
                abs_path.write_text(resolved_content, encoding="utf-8")
                # Stage the resolved file
                await self._run_git("add", file_path)
                resolved.append(file_path)
                log.info("LLM resolved conflict in %s", file_path)
            else:
                still_conflicted.append(file_path)
                log.warning("Could not resolve conflict in %s", file_path)

        # Complete the merge commit if all conflicts resolved
        if not still_conflicted:
            _, stderr, code = await self._run_git(
                "commit", "--no-edit", "-m",
                f"Merge {merge_result.worktree_id}: auto-resolved {len(resolved)} conflict(s)",
            )
            if code == 0:
                merge_result.success = True
                merge_result.resolution = (
                    f"LLM auto-resolved {len(resolved)} conflict(s)"
                )
            else:
                merge_result.resolution = f"Commit after resolution failed: {stderr}"
        else:
            merge_result.resolution = (
                f"Resolved {len(resolved)}/{len(merge_result.conflicts)} conflicts. "
                f"Still conflicted: {still_conflicted}"
            )

        merge_result.conflicts = still_conflicted
        merge_result.merged_files.extend(resolved)
        return merge_result

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    async def diff_worktree(self, worktree_id: str) -> str:
        """Return the diff between a worktree's branch and its base branch.

        Args:
            worktree_id: ID of the worktree to diff.

        Returns:
            Unified diff string.
        """
        wt = self._registry.get(worktree_id)
        if not wt:
            return f"Worktree {worktree_id} not found"

        stdout, stderr, code = await self._run_git(
            "diff", wt.base_branch, wt.branch,
        )
        if code != 0:
            return f"git diff error: {stderr}"
        return stdout

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _sync_from_git(self) -> None:
        """Sync the internal registry with ``git worktree list`` output."""
        stdout, _, code = await self._run_git("worktree", "list", "--porcelain")
        if code != 0:
            return

        # Parse porcelain output blocks
        blocks = stdout.strip().split("\n\n")
        git_paths: set[str] = set()

        for block in blocks:
            wt_path = ""
            branch = ""
            for line in block.splitlines():
                if line.startswith("worktree "):
                    wt_path = line[len("worktree "):].strip()
                elif line.startswith("branch "):
                    branch = line[len("branch "):].strip().replace("refs/heads/", "")

            if wt_path and wt_path != str(self._repo):
                git_paths.add(wt_path)

                # Check if we already track this worktree
                existing = next(
                    (w for w in self._registry.values() if w.path == wt_path), None
                )
                if not existing and branch:
                    # Externally created worktree — register it
                    wt_id = str(uuid.uuid4())[:8]
                    wt_name = Path(wt_path).name
                    self._registry[wt_id] = Worktree(
                        id=wt_id,
                        name=wt_name,
                        branch=branch,
                        path=wt_path,
                    )

    async def _llm_resolve_conflict(
        self,
        file_path: str,
        content: str,
        model: str,
    ) -> str:
        """Ask the LLM to resolve a single conflict-marked file.

        Args:
            file_path: Relative path to the file (for context).
            content: File content with ``<<<<<<<``, ``=======``, ``>>>>>>>``
                conflict markers.
            model: LLM model name.

        Returns:
            Resolved file content, or empty string on failure.
        """
        if self.router is None:
            # Heuristic fallback: keep "ours" (lines after <<<<<<< up to =======)
            return self._heuristic_resolve(content)

        prompt = f"""\
Resolve the merge conflict in the file below. Return ONLY the resolved file
content — no explanations, no conflict markers, no markdown.

File: {file_path}

Content with conflict markers:
```
{content[:8000]}
```

Return the complete, merged file content:"""

        try:
            client, model_id = self.router.get_client(model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert software engineer who resolves git merge "
                            "conflicts. Produce the best merged version of the file that "
                            "incorporates both sets of changes where possible."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=8192,
            )
            resolved = response.choices[0].message.content or ""
            # Strip any accidental markdown fences
            resolved = resolved.strip()
            if resolved.startswith("```"):
                resolved = re.sub(r"^```[a-z]*\s*\n", "", resolved)
                resolved = re.sub(r"\n```\s*$", "", resolved)
            return resolved.strip()
        except Exception as exc:
            log.warning("LLM conflict resolution failed for %s: %s", file_path, exc)
            return self._heuristic_resolve(content)

    @staticmethod
    def _heuristic_resolve(content: str) -> str:
        """Heuristic conflict resolution: interleave both sides.

        Picks the "ours" side for simple conflicts. Used as a fallback
        when no LLM is available.

        Args:
            content: File content with conflict markers.

        Returns:
            Content with conflict markers removed, keeping both sides.
        """
        lines = content.splitlines(keepends=True)
        result: list[str] = []
        in_ours = False
        in_theirs = False

        for line in lines:
            if line.startswith("<<<<<<<"):
                in_ours = True
            elif line.startswith("======="):
                in_ours = False
                in_theirs = True
            elif line.startswith(">>>>>>>"):
                in_theirs = False
            elif in_ours or in_theirs:
                result.append(line)
            else:
                result.append(line)

        return "".join(result)

    async def _run_git(self, *args: str) -> tuple[str, str, int]:
        """Run a git command in the main repo directory.

        Args:
            *args: Arguments after ``git``.

        Returns:
            Tuple of ``(stdout, stderr, returncode)``.
        """
        cmd = ["git"] + list(args)
        log.debug("git %s (in %s)", " ".join(args[:3]), self._repo)

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
            return "", "git not found", 127
        except Exception as exc:
            return "", str(exc), 1

        return (
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
            proc.returncode or 0,
        )
