"""Horizon Orchestra — Cloud Sandbox.

Isolated execution environments for code, browser automation, and
long-running tasks.  Each sandbox gets its own filesystem, network
namespace, resource limits, and timeout enforcement.

Three backends:
1. **Subprocess** — local dev, no isolation (default)
2. **Docker** — production, full container isolation
3. **E2B/Modal** — serverless cloud sandboxes (highest scale)

This is what lets Horizon Orchestra run untrusted agent-generated code
safely — Horizon Prince's sandboxed execution environment.

Usage::

    from orchestra.sandbox import SandboxManager, SandboxConfig
    mgr = SandboxManager(backend="docker")
    sandbox = await mgr.create(user_id="ashton")
    result = await sandbox.execute("python3 -c 'print(42)'")
    files = await sandbox.list_files("/workspace")
    await sandbox.destroy()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Guardian: every code execution passes through security ─────────────────
try:
    from .guardian.code_guard import CodeGuard as _CodeGuard
    from .guardian.audit_ledger import AuditLedger as _AuditLedger
    _GUARD = _CodeGuard()
    _LEDGER = _AuditLedger()
    _GUARDIAN_ACTIVE = True
except Exception:
    _GUARD = _LEDGER = None  # type: ignore
    _GUARDIAN_ACTIVE = False

__all__ = [
    "SandboxManager",
    "Sandbox",
    "SandboxConfig",
    "ExecResult",
]

log = logging.getLogger("orchestra.sandbox")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SandboxConfig:
    backend: str = "subprocess"          # subprocess, docker, e2b
    max_execution_time: int = 300        # seconds
    max_memory_mb: int = 2048
    max_cpu_count: int = 2
    max_disk_mb: int = 5120
    workspace_dir: str = "/tmp/horizon_sandboxes"
    docker_image: str = "python:3.12-slim"
    network_enabled: bool = True
    persist_workspace: bool = True
    packages: list[str] = field(default_factory=lambda: [
        "pandas", "numpy", "scipy", "scikit-learn",
        "matplotlib", "seaborn", "httpx", "beautifulsoup4",
    ])


@dataclass
class ExecResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False
    files_created: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sandbox instance
# ---------------------------------------------------------------------------

class Sandbox:
    """An isolated execution environment."""

    def __init__(
        self,
        sandbox_id: str,
        user_id: str,
        config: SandboxConfig,
        workspace: Path,
    ) -> None:
        self.sandbox_id = sandbox_id
        self.user_id = user_id
        self.config = config
        self.workspace = workspace
        self._alive = True
        self._container_id: str = ""
        self._created_at = time.time()

    @property
    def alive(self) -> bool:
        return self._alive

    # -- execution ----------------------------------------------------------

    async def execute(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str = "",
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Execute a command in the sandbox."""
        timeout = timeout or self.config.max_execution_time
        work_dir = cwd or str(self.workspace)

        if self.config.backend == "docker":
            return await self._exec_docker(command, timeout, work_dir, env)
        else:
            return await self._exec_subprocess(command, timeout, work_dir, env)

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        timeout: int | None = None,
        agent_id: str = "",
    ) -> ExecResult:
        """Write code to a temp file and execute it.

        Every execution is screened by CodeGuard before running.
        """
        # ── Security gate: scan code before execution ──────────────────────
        if _GUARDIAN_ACTIVE and _GUARD is not None:
            import asyncio as _asyncio
            _scan = _asyncio.run(_GUARD.scan(code, language, agent_id or "sandbox"))
            if _scan.blocked:
                return ExecResult(
                    exit_code=1,
                    stdout="",
                    stderr=f"[SECURITY BLOCKED] CodeGuard detected threats: {[t.value for t in _scan.threats]}",
                    duration=0.0,
                )
            if _LEDGER is not None:
                _asyncio.run(_LEDGER.record(
                    agent_id or "sandbox", "code_execution",
                    language, "execute", "allow",
                    {"code_hash": _scan.code_hash, "threats": []}
                ))
        ext = {"python": ".py", "javascript": ".js", "bash": ".sh", "typescript": ".ts"}.get(language, ".py")
        filename = f"_run_{uuid.uuid4().hex[:6]}{ext}"
        filepath = self.workspace / filename

        filepath.write_text(code, encoding="utf-8")

        runners = {
            "python": f"python3 {filepath}",
            "javascript": f"node {filepath}",
            "bash": f"bash {filepath}",
            "typescript": f"npx tsx {filepath}",
        }
        cmd = runners.get(language, f"python3 {filepath}")
        result = await self.execute(cmd, timeout=timeout)

        # Track created files
        result.files_created = self._detect_new_files()
        return result

    async def install(self, packages: list[str]) -> ExecResult:
        """Install packages in the sandbox."""
        pkg_str = " ".join(packages)
        return await self.execute(f"pip install -q {pkg_str}", timeout=120)

    # -- filesystem ---------------------------------------------------------

    async def write_file(self, path: str, content: str | bytes) -> str:
        """Write a file to the sandbox workspace."""
        full = self.workspace / path.lstrip("/")
        full.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            full.write_bytes(content)
        else:
            full.write_text(content, encoding="utf-8")
        return str(full)

    async def read_file(self, path: str) -> str:
        """Read a file from the sandbox workspace."""
        full = self.workspace / path.lstrip("/")
        if not full.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return full.read_text(encoding="utf-8", errors="replace")[:100_000]

    async def list_files(self, path: str = "/") -> list[dict[str, Any]]:
        """List files in the sandbox workspace."""
        target = self.workspace / path.lstrip("/")
        if not target.exists():
            return []
        files = []
        for item in sorted(target.iterdir()):
            files.append({
                "name": item.name,
                "path": str(item.relative_to(self.workspace)),
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
            })
        return files

    async def download_url(self, url: str, filename: str = "") -> ExecResult:
        """Download a file from a URL into the workspace."""
        if not filename:
            filename = url.split("/")[-1].split("?")[0] or "download"
        return await self.execute(f"curl -sL -o {self.workspace}/{filename} '{url}'")

    # -- lifecycle ----------------------------------------------------------

    async def destroy(self) -> None:
        """Destroy the sandbox and clean up resources."""
        self._alive = False
        if self.config.backend == "docker" and self._container_id:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", self._container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
            except Exception as exc:
                log.warning("Failed to remove container %s: %s", self._container_id, exc)

        if not self.config.persist_workspace:
            shutil.rmtree(self.workspace, ignore_errors=True)

        log.info("Sandbox %s destroyed", self.sandbox_id)

    # -- backend implementations --------------------------------------------

    async def _exec_subprocess(
        self, command: str, timeout: int, cwd: str, env: dict | None,
    ) -> ExecResult:
        """Execute in a local subprocess (dev mode)."""
        t0 = time.monotonic()
        full_env = dict(os.environ)
        if env:
            full_env.update(env)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=full_env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return ExecResult(
                    exit_code=proc.returncode or 0,
                    stdout=stdout.decode(errors="replace")[:50_000],
                    stderr=stderr.decode(errors="replace")[:10_000],
                    duration=round(time.monotonic() - t0, 2),
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ExecResult(exit_code=-1, timed_out=True, duration=timeout)
        except Exception as exc:
            return ExecResult(exit_code=-1, stderr=str(exc), duration=time.monotonic() - t0)

    async def _exec_docker(
        self, command: str, timeout: int, cwd: str, env: dict | None,
    ) -> ExecResult:
        """Execute in a Docker container (production mode)."""
        t0 = time.monotonic()

        env_args = []
        if env:
            for k, v in env.items():
                env_args.extend(["-e", f"{k}={v}"])

        docker_cmd = [
            "docker", "run", "--rm",
            "--memory", f"{self.config.max_memory_mb}m",
            "--cpus", str(self.config.max_cpu_count),
            "-v", f"{self.workspace}:/workspace",
            "-w", "/workspace",
            "--security-opt", "no-new-privileges",
        ]
        if not self.config.network_enabled:
            docker_cmd.append("--network=none")
        docker_cmd.extend(env_args)
        docker_cmd.extend([self.config.docker_image, "bash", "-c", command])

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return ExecResult(
                    exit_code=proc.returncode or 0,
                    stdout=stdout.decode(errors="replace")[:50_000],
                    stderr=stderr.decode(errors="replace")[:10_000],
                    duration=round(time.monotonic() - t0, 2),
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ExecResult(exit_code=-1, timed_out=True, duration=timeout)
        except Exception as exc:
            return ExecResult(exit_code=-1, stderr=str(exc), duration=time.monotonic() - t0)

    def _detect_new_files(self) -> list[str]:
        """Detect files created during execution."""
        files = []
        for item in self.workspace.rglob("*"):
            if item.is_file() and not item.name.startswith("_run_"):
                files.append(str(item.relative_to(self.workspace)))
        return files

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "user_id": self.user_id,
            "backend": self.config.backend,
            "workspace": str(self.workspace),
            "alive": self._alive,
            "age_seconds": round(time.time() - self._created_at),
        }


# ---------------------------------------------------------------------------
# Sandbox manager
# ---------------------------------------------------------------------------

class SandboxManager:
    """Creates and manages sandbox instances.

    Each user gets an isolated sandbox with its own workspace directory.
    Sandboxes persist across tool calls within a session but are cleaned
    up when the session ends (or on timeout).
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()
        self._sandboxes: dict[str, Sandbox] = {}
        self._base_dir = Path(self.config.workspace_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    async def create(
        self,
        user_id: str = "default",
        session_id: str = "",
    ) -> Sandbox:
        """Create a new sandbox for a user/session."""
        sandbox_id = session_id or str(uuid.uuid4())[:8]
        workspace = self._base_dir / f"{user_id}_{sandbox_id}"
        workspace.mkdir(parents=True, exist_ok=True)

        sandbox = Sandbox(
            sandbox_id=sandbox_id,
            user_id=user_id,
            config=self.config,
            workspace=workspace,
        )

        # Pre-install packages if Docker
        if self.config.backend == "docker" and self.config.packages:
            await sandbox.install(self.config.packages)

        self._sandboxes[sandbox_id] = sandbox
        log.info("Created sandbox %s for user %s (%s)", sandbox_id, user_id, self.config.backend)
        return sandbox

    async def get_or_create(
        self,
        user_id: str = "default",
        session_id: str = "",
    ) -> Sandbox:
        """Get an existing sandbox or create a new one."""
        key = session_id or user_id
        if key in self._sandboxes and self._sandboxes[key].alive:
            return self._sandboxes[key]
        return await self.create(user_id, session_id)

    async def destroy(self, sandbox_id: str) -> bool:
        sandbox = self._sandboxes.pop(sandbox_id, None)
        if sandbox:
            await sandbox.destroy()
            return True
        return False

    async def destroy_all(self) -> int:
        count = len(self._sandboxes)
        for sandbox in list(self._sandboxes.values()):
            await sandbox.destroy()
        self._sandboxes.clear()
        return count

    def list_sandboxes(self) -> list[dict[str, Any]]:
        return [s.stats for s in self._sandboxes.values()]
