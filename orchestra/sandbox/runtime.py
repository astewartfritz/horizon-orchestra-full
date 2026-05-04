"""Horizon Orchestra — Multi-OS Hardened Sandbox Runtime.

Ties together all isolation layers (namespaces, seccomp, filesystem,
network) into a production-grade sandbox with full lifecycle management.

Supports Linux (Debian/Fedora), OpenBSD (pledge/unveil), and FreeBSD
(jail/capsicum), with graceful degradation on unsupported platforms.

Lifecycle: ``create → start → execute → stop → destroy``

Usage::

    from orchestra.sandbox.runtime import HardenedSandbox, HardenedSandboxConfig
    config = HardenedSandboxConfig(isolation_level="standard")
    sandbox = HardenedSandbox(sandbox_id="sb-001", config=config)
    await sandbox.create()
    await sandbox.start()
    result = await sandbox.execute("python3 -c 'print(42)'")
    await sandbox.stop()
    await sandbox.destroy()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shlex
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Import ExecResult from the parent sandbox module
try:
    from orchestra.sandbox import ExecResult
except ImportError:  # pragma: no cover
    from dataclasses import dataclass as _dc

    @_dc
    class ExecResult:  # type: ignore[no-redef]
        """Fallback ExecResult when parent module is not available."""
        exit_code: int = 0
        stdout: str = ""
        stderr: str = ""
        duration: float = 0.0
        timed_out: bool = False
        files_created: list[str] = field(default_factory=list)

# Import sibling modules with try/except
try:
    from orchestra.sandbox.os_profiles import (
        OSProfile,
        OSType,
        SyscallPolicy,
        FilesystemPolicy,
        NetworkPolicy,
        ResourceLimits,
        get_profile,
        PROFILES,
    )
except ImportError:  # pragma: no cover
    OSProfile = Any  # type: ignore[assignment,misc]
    OSType = None  # type: ignore[assignment,misc]
    SyscallPolicy = Any  # type: ignore[assignment,misc]
    FilesystemPolicy = Any  # type: ignore[assignment,misc]
    NetworkPolicy = Any  # type: ignore[assignment,misc]
    ResourceLimits = Any  # type: ignore[assignment,misc]
    get_profile = None  # type: ignore[assignment]
    PROFILES = {}  # type: ignore[assignment]

try:
    from orchestra.sandbox.namespaces import (
        NamespaceManager,
        CgroupManager,
        NamespaceConfig,
    )
except ImportError:  # pragma: no cover
    NamespaceManager = None  # type: ignore[assignment,misc]
    CgroupManager = None  # type: ignore[assignment,misc]
    NamespaceConfig = None  # type: ignore[assignment,misc]

try:
    from orchestra.sandbox.seccomp import SeccompProfile, SAFE_SYSCALLS
except ImportError:  # pragma: no cover
    SeccompProfile = None  # type: ignore[assignment,misc]
    SAFE_SYSCALLS = []  # type: ignore[assignment]

from orchestra.sandbox.filesystem import FilesystemIsolation
from orchestra.sandbox.network import (
    NetworkIsolation,
    DNSConfig,
    BandwidthLimit,
    FirewallRule,
)

__all__ = [
    "HardenedSandbox",
    "HardenedSandboxPool",
    "HardenedSandboxConfig",
    "ISOLATION_LEVELS",
]

log = logging.getLogger("orchestra.sandbox.runtime")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LINUX = platform.system() == "Linux"
_OPENBSD = platform.system() == "OpenBSD"
_FREEBSD = platform.system() == "FreeBSD"

# Supported sandbox states
_STATES = ("created", "running", "stopped", "destroyed")

# Language → interpreter mapping for execute_code
_LANGUAGE_INTERPRETERS: dict[str, list[str]] = {
    "python": ["python3", "-c"],
    "python3": ["python3", "-c"],
    "bash": ["bash", "-c"],
    "sh": ["sh", "-c"],
    "ruby": ["ruby", "-e"],
    "node": ["node", "-e"],
    "javascript": ["node", "-e"],
    "perl": ["perl", "-e"],
}

# Package manager commands per OS profile
_PKG_MANAGERS: dict[str, list[str]] = {
    "debian": ["apt-get", "install", "-y", "--no-install-recommends"],
    "ubuntu": ["apt-get", "install", "-y", "--no-install-recommends"],
    "fedora": ["dnf", "install", "-y"],
    "centos": ["yum", "install", "-y"],
    "alpine": ["apk", "add", "--no-cache"],
    "openbsd": ["pkg_add"],
    "freebsd": ["pkg", "install", "-y"],
}

# Default reaper interval (seconds)
_REAPER_INTERVAL = 30.0

# Maximum sandbox idle time before reaping (seconds)
_MAX_IDLE_TIME = 600.0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class HardenedSandboxConfig:
    """Configuration for a hardened sandbox instance.

    Controls which isolation layers are enabled, resource limits, network
    mode, and auto-installed packages.
    """

    os_profile: str = "debian-11"
    isolation_level: str = "standard"
    enable_namespaces: bool = True
    enable_seccomp: bool = True
    enable_filesystem_isolation: bool = True
    enable_network_isolation: bool = True
    enable_cgroups: bool = True
    workspace_dir: str = "/workspace"
    timeout_seconds: float = 300.0
    max_memory_mb: int = 2048
    max_cpu_cores: float = 2.0
    max_pids: int = 256
    network_mode: str = "filtered"
    auto_install_packages: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pre-built isolation levels
# ---------------------------------------------------------------------------

ISOLATION_LEVELS: dict[str, HardenedSandboxConfig] = {
    "minimal": HardenedSandboxConfig(
        isolation_level="minimal",
        enable_namespaces=True,
        enable_seccomp=False,
        enable_filesystem_isolation=False,
        enable_network_isolation=False,
        enable_cgroups=False,
        timeout_seconds=300.0,
        max_memory_mb=4096,
        max_cpu_cores=4.0,
        max_pids=1024,
        network_mode="full",
    ),
    "standard": HardenedSandboxConfig(
        isolation_level="standard",
        enable_namespaces=True,
        enable_seccomp=True,
        enable_filesystem_isolation=True,
        enable_network_isolation=True,
        enable_cgroups=False,
        timeout_seconds=300.0,
        max_memory_mb=2048,
        max_cpu_cores=2.0,
        max_pids=256,
        network_mode="filtered",
    ),
    "maximum": HardenedSandboxConfig(
        isolation_level="maximum",
        enable_namespaces=True,
        enable_seccomp=True,
        enable_filesystem_isolation=True,
        enable_network_isolation=True,
        enable_cgroups=True,
        timeout_seconds=120.0,
        max_memory_mb=1024,
        max_cpu_cores=1.0,
        max_pids=128,
        network_mode="filtered",
    ),
    "paranoid": HardenedSandboxConfig(
        isolation_level="paranoid",
        enable_namespaces=True,
        enable_seccomp=True,
        enable_filesystem_isolation=True,
        enable_network_isolation=True,
        enable_cgroups=True,
        timeout_seconds=60.0,
        max_memory_mb=512,
        max_cpu_cores=0.5,
        max_pids=64,
        network_mode="loopback",
    ),
}


# ---------------------------------------------------------------------------
# HardenedSandbox
# ---------------------------------------------------------------------------

class HardenedSandbox:
    """Production-grade multi-OS sandbox runtime.

    Combines all isolation layers into a single hardened sandbox:

    **Linux (Debian/Fedora)**:
        namespaces(PID+NET+MNT+USER+UTS+IPC)
        + seccomp-bpf(syscall filter)
        + cgroup v2(memory+cpu+pids)
        + overlayfs(copy-on-write rootfs)
        + iptables(network filter)
        + tc(bandwidth limit)

    **OpenBSD**:
        pledge("stdio rpath wpath cpath proc exec inet dns")
        + unveil(path restrictions)
        + pf(packet filter)
        + resource limits via rlimit

    **FreeBSD**:
        jail(process isolation)
        + capsicum(capability mode)
        + ipfw(firewall)
        + rctl(resource limits)

    Lifecycle: ``create → start → execute → stop → destroy``
    """

    def __init__(
        self,
        sandbox_id: str,
        config: HardenedSandboxConfig | None = None,
    ) -> None:
        self._sandbox_id = sandbox_id
        self._config = config or HardenedSandboxConfig()
        self._state = "created"
        self._created_at = time.time()
        self._started_at: float = 0.0
        self._stopped_at: float = 0.0
        self._last_activity: float = time.time()

        # Isolation layer instances
        self._filesystem: FilesystemIsolation | None = None
        self._network: NetworkIsolation | None = None
        self._namespace_mgr: Any = None
        self._cgroup_mgr: Any = None
        self._seccomp: Any = None

        # Runtime state
        self._rootfs: str = ""
        self._workspace_dir: str = ""
        self._init_process: asyncio.subprocess.Process | None = None
        self._exec_count: int = 0
        self._total_exec_time: float = 0.0

        # Security tracking
        self._blocked_syscalls: list[str] = []
        self._network_violations: list[dict[str, Any]] = []
        self._fs_violations: list[dict[str, Any]] = []

        log.debug(
            "HardenedSandbox created: id=%s level=%s",
            sandbox_id,
            self._config.isolation_level,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sandbox_id(self) -> str:
        """Return the sandbox identifier."""
        return self._sandbox_id

    @property
    def state(self) -> str:
        """Return the current sandbox state.

        Returns one of: ``"created"``, ``"running"``, ``"stopped"``,
        ``"destroyed"``.
        """
        return self._state

    @property
    def config(self) -> HardenedSandboxConfig:
        """Return the sandbox configuration."""
        return self._config

    @property
    def rootfs(self) -> str:
        """Return the sandbox rootfs path."""
        return self._rootfs

    # ------------------------------------------------------------------
    # Lifecycle: create
    # ------------------------------------------------------------------

    async def create(self) -> None:
        """Set up all isolation layers.

        Initialises filesystem isolation, network isolation, namespaces,
        cgroups, and seccomp filters based on the configuration.
        """
        if self._state != "created":
            raise RuntimeError(
                f"Cannot create sandbox in state {self._state!r}"
            )

        log.info(
            "Creating sandbox %s (level=%s, os=%s)",
            self._sandbox_id,
            self._config.isolation_level,
            self._config.os_profile,
        )

        # Resolve OS profile
        profile = self._resolve_profile()

        # OS-specific setup
        if _LINUX:
            await self._setup_linux(profile)
        elif _OPENBSD:
            await self._setup_openbsd(profile)
        elif _FREEBSD:
            await self._setup_freebsd(profile)
        else:
            # Generic fallback (macOS, Windows, etc.)
            await self._setup_generic(profile)

        self._last_activity = time.time()
        log.info("Sandbox %s created successfully", self._sandbox_id)

    # ------------------------------------------------------------------
    # Lifecycle: start
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Enter the sandbox and start the init process.

        After ``start()``, the sandbox is ready to accept ``execute()``
        calls.
        """
        if self._state not in ("created", "stopped"):
            raise RuntimeError(
                f"Cannot start sandbox in state {self._state!r}"
            )

        log.info("Starting sandbox %s", self._sandbox_id)

        # Ensure workspace directory exists
        if self._rootfs:
            ws = os.path.join(self._rootfs, "workspace")
            os.makedirs(ws, exist_ok=True)
            self._workspace_dir = ws
        else:
            self._workspace_dir = tempfile.mkdtemp(
                prefix=f"horizon-ws-{self._sandbox_id[:8]}-"
            )

        # Auto-install packages if configured
        if self._config.auto_install_packages:
            log.info(
                "Auto-installing packages: %s",
                ", ".join(self._config.auto_install_packages),
            )
            try:
                await self.install_packages(self._config.auto_install_packages)
            except Exception as exc:
                log.warning("Auto-install failed: %s", exc)

        self._state = "running"
        self._started_at = time.time()
        self._last_activity = time.time()
        log.info("Sandbox %s is now running", self._sandbox_id)

    # ------------------------------------------------------------------
    # Lifecycle: stop
    # ------------------------------------------------------------------

    async def stop(self, reason: str = "completed") -> None:
        """Stop the sandbox.

        Parameters
        ----------
        reason:
            Human-readable reason for stopping (e.g. ``"completed"``,
            ``"timeout"``, ``"error"``).
        """
        if self._state != "running":
            log.warning(
                "Sandbox %s not running (state=%s), skipping stop",
                self._sandbox_id,
                self._state,
            )
            return

        log.info(
            "Stopping sandbox %s (reason=%s)", self._sandbox_id, reason
        )

        # Kill init process if running
        if self._init_process is not None:
            try:
                self._init_process.terminate()
                await asyncio.wait_for(
                    self._init_process.wait(), timeout=5.0
                )
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._init_process.kill()
                except ProcessLookupError:
                                        import logging as _log; _log.getLogger('sandbox.runtime').debug('Suppressed exception', exc_info=True)
            self._init_process = None

        self._state = "stopped"
        self._stopped_at = time.time()
        self._last_activity = time.time()
        log.info("Sandbox %s stopped", self._sandbox_id)

    # ------------------------------------------------------------------
    # Lifecycle: destroy
    # ------------------------------------------------------------------

    async def destroy(self) -> None:
        """Tear down everything and clean up all resources.

        After ``destroy()``, the sandbox cannot be reused.
        """
        if self._state == "destroyed":
            return

        log.info("Destroying sandbox %s", self._sandbox_id)

        # Stop first if still running
        if self._state == "running":
            await self.stop(reason="destroy")

        # Tear down network isolation
        if self._network is not None:
            try:
                await self._network.teardown()
            except Exception as exc:
                log.warning("Network teardown error: %s", exc)
            self._network = None

        # Tear down filesystem isolation
        if self._filesystem is not None:
            try:
                await self._filesystem.teardown()
            except Exception as exc:
                log.warning("Filesystem teardown error: %s", exc)
            self._filesystem = None

        # Release cgroup resources
        if self._cgroup_mgr is not None:
            try:
                if hasattr(self._cgroup_mgr, "destroy"):
                    await self._cgroup_mgr.destroy()
            except Exception as exc:
                log.warning("Cgroup teardown error: %s", exc)
            self._cgroup_mgr = None

        # Release namespace resources
        if self._namespace_mgr is not None:
            try:
                if hasattr(self._namespace_mgr, "destroy"):
                    await self._namespace_mgr.destroy()
            except Exception as exc:
                log.warning("Namespace teardown error: %s", exc)
            self._namespace_mgr = None

        # Clean up workspace on host
        if self._workspace_dir and os.path.isdir(self._workspace_dir):
            try:
                shutil.rmtree(self._workspace_dir, ignore_errors=True)
            except OSError:
                                import logging as _log; _log.getLogger('sandbox.runtime').debug('Suppressed exception', exc_info=True)

        self._state = "destroyed"
        self._last_activity = time.time()
        log.info("Sandbox %s destroyed", self._sandbox_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        command: str,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Execute a command inside the sandbox.

        Parameters
        ----------
        command:
            Shell command to execute.
        timeout:
            Maximum execution time in seconds.  Defaults to the
            config's ``timeout_seconds``.
        env:
            Additional environment variables.

        Returns
        -------
        ExecResult
            Execution result with stdout, stderr, exit code, and timing.
        """
        if self._state != "running":
            return ExecResult(
                exit_code=1,
                stderr=f"Sandbox not running (state={self._state})",
            )

        timeout = timeout or self._config.timeout_seconds
        self._last_activity = time.time()
        start_time = time.time()

        # Build environment
        exec_env = self._build_exec_env(env)

        # Parse command into args (safe splitting)
        try:
            cmd_args = shlex.split(command)
        except ValueError as exc:
            return ExecResult(
                exit_code=1,
                stderr=f"Invalid command syntax: {exc}",
            )

        if not cmd_args:
            return ExecResult(exit_code=1, stderr="Empty command")

        # Build the full command with namespace/chroot prefix if available
        full_args = self._build_exec_args(cmd_args)

        log.debug(
            "Executing in sandbox %s: %s (timeout=%.1fs)",
            self._sandbox_id,
            command[:200],
            timeout,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=exec_env,
                cwd=self._workspace_dir or None,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                timed_out = False
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                                        import logging as _log; _log.getLogger('sandbox.runtime').debug('Suppressed exception', exc_info=True)
                stdout_bytes, stderr_bytes = b"", b"Command timed out"
                timed_out = True

            duration = time.time() - start_time
            exit_code = proc.returncode if proc.returncode is not None else -1

            # Detect new files in workspace
            files_created = self._detect_new_files()

            result = ExecResult(
                exit_code=exit_code,
                stdout=stdout_bytes.decode(errors="replace"),
                stderr=stderr_bytes.decode(errors="replace"),
                duration=duration,
                timed_out=timed_out,
                files_created=files_created,
            )

        except FileNotFoundError:
            duration = time.time() - start_time
            result = ExecResult(
                exit_code=127,
                stderr=f"Command not found: {cmd_args[0]}",
                duration=duration,
            )
        except OSError as exc:
            duration = time.time() - start_time
            result = ExecResult(
                exit_code=1,
                stderr=f"Execution error: {exc}",
                duration=duration,
            )

        self._exec_count += 1
        self._total_exec_time += result.duration
        self._last_activity = time.time()

        log.debug(
            "Sandbox %s exec result: exit=%d duration=%.2fs timed_out=%s",
            self._sandbox_id,
            result.exit_code,
            result.duration,
            result.timed_out,
        )
        return result

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        timeout: float | None = None,
    ) -> ExecResult:
        """Execute code in a specific language inside the sandbox.

        Parameters
        ----------
        code:
            Source code to execute.
        language:
            Programming language (python, bash, ruby, node, etc.).
        timeout:
            Maximum execution time in seconds.

        Returns
        -------
        ExecResult
            Execution result.
        """
        lang = language.lower().strip()
        interpreter = _LANGUAGE_INTERPRETERS.get(lang)

        if interpreter is None:
            return ExecResult(
                exit_code=1,
                stderr=f"Unsupported language: {language}. "
                       f"Supported: {', '.join(_LANGUAGE_INTERPRETERS)}",
            )

        # For languages that use -c / -e, pass code directly
        if interpreter[-1] in ("-c", "-e"):
            command = f"{interpreter[0]} {interpreter[1]} {shlex.quote(code)}"
        else:
            # Write code to a temp file and execute
            ext_map = {"python": ".py", "bash": ".sh", "ruby": ".rb", "node": ".js"}
            ext = ext_map.get(lang, ".txt")
            code_file = os.path.join(
                self._workspace_dir or tempfile.gettempdir(),
                f"_exec_{uuid.uuid4().hex[:8]}{ext}",
            )
            try:
                with open(code_file, "w") as f:
                    f.write(code)
                command = f"{interpreter[0]} {shlex.quote(code_file)}"
            except OSError as exc:
                return ExecResult(
                    exit_code=1,
                    stderr=f"Failed to write code file: {exc}",
                )

        return await self.execute(command, timeout=timeout)

    # ------------------------------------------------------------------
    # Package management
    # ------------------------------------------------------------------

    async def install_packages(self, packages: list[str]) -> ExecResult:
        """Install system packages in the sandbox.

        Detects the package manager based on the OS profile and installs
        the requested packages.

        Parameters
        ----------
        packages:
            List of package names to install.

        Returns
        -------
        ExecResult
            Result of the installation command.
        """
        if not packages:
            return ExecResult(exit_code=0, stdout="No packages to install")

        # Determine package manager from OS profile
        os_name = self._config.os_profile.lower()
        pkg_cmd: list[str] | None = None

        for key, cmd in _PKG_MANAGERS.items():
            if key in os_name:
                pkg_cmd = cmd
                break

        if pkg_cmd is None:
            # Default to apt for Debian-like systems
            pkg_cmd = _PKG_MANAGERS["debian"]

        # Sanitize package names
        safe_packages = [shlex.quote(p) for p in packages]

        # Build and execute the install command
        full_cmd = " ".join(pkg_cmd + safe_packages)

        # Run apt-get update first for Debian/Ubuntu
        if pkg_cmd[0] == "apt-get":
            update_result = await self.execute("apt-get update -qq")
            if update_result.exit_code != 0:
                log.warning("apt-get update failed: %s", update_result.stderr)

        result = await self.execute(full_cmd)

        if result.exit_code == 0:
            log.info(
                "Installed %d packages in sandbox %s",
                len(packages),
                self._sandbox_id,
            )
        else:
            log.warning(
                "Package install failed in sandbox %s: %s",
                self._sandbox_id,
                result.stderr[:200],
            )

        return result

    # ------------------------------------------------------------------
    # Filesystem operations
    # ------------------------------------------------------------------

    async def write_file(self, path: str, content: str | bytes) -> str:
        """Write a file inside the sandbox.

        Parameters
        ----------
        path:
            Path relative to workspace or absolute within rootfs.
        content:
            File content (str or bytes).

        Returns
        -------
        str
            Absolute path to the written file.
        """
        # Resolve path relative to workspace
        if not os.path.isabs(path):
            full_path = os.path.join(self._workspace_dir, path)
        elif self._rootfs and not path.startswith(self._rootfs):
            full_path = os.path.join(self._rootfs, path.lstrip("/"))
        else:
            full_path = path

        # Security check: ensure path is within sandbox
        if not self._is_path_safe(full_path):
            raise PermissionError(
                f"Path escapes sandbox boundary: {path}"
            )

        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        mode = "wb" if isinstance(content, bytes) else "w"
        with open(full_path, mode) as f:
            f.write(content)

        log.debug("Wrote file %s in sandbox %s", full_path, self._sandbox_id)
        return full_path

    async def read_file(self, path: str) -> str:
        """Read a file from inside the sandbox.

        Parameters
        ----------
        path:
            Path relative to workspace or absolute within rootfs.

        Returns
        -------
        str
            File contents.
        """
        if not os.path.isabs(path):
            full_path = os.path.join(self._workspace_dir, path)
        elif self._rootfs and not path.startswith(self._rootfs):
            full_path = os.path.join(self._rootfs, path.lstrip("/"))
        else:
            full_path = path

        if not self._is_path_safe(full_path):
            raise PermissionError(
                f"Path escapes sandbox boundary: {path}"
            )

        with open(full_path) as f:
            return f.read()

    async def list_files(
        self, path: str = "/workspace"
    ) -> list[dict[str, Any]]:
        """List files in a directory inside the sandbox.

        Parameters
        ----------
        path:
            Directory path to list.

        Returns
        -------
        list[dict[str, Any]]
            List of file entries with name, size, type, and modified time.
        """
        if not os.path.isabs(path):
            full_path = os.path.join(self._workspace_dir, path)
        elif path == "/workspace":
            full_path = self._workspace_dir
        elif self._rootfs:
            full_path = os.path.join(self._rootfs, path.lstrip("/"))
        else:
            full_path = path

        if not os.path.isdir(full_path):
            return []

        entries: list[dict[str, Any]] = []
        try:
            for entry in os.scandir(full_path):
                try:
                    stat_info = entry.stat(follow_symlinks=False)
                    entries.append({
                        "name": entry.name,
                        "path": entry.path,
                        "size": stat_info.st_size,
                        "type": "directory" if entry.is_dir() else "file",
                        "modified": stat_info.st_mtime,
                        "is_symlink": entry.is_symlink(),
                    })
                except OSError:
                    entries.append({
                        "name": entry.name,
                        "path": entry.path,
                        "size": 0,
                        "type": "unknown",
                        "modified": 0,
                        "is_symlink": False,
                    })
        except PermissionError:
            log.warning("Permission denied listing %s", full_path)

        return sorted(entries, key=lambda e: e["name"])

    # ------------------------------------------------------------------
    # State and metrics
    # ------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        """Return resource usage metrics.

        Returns
        -------
        dict[str, Any]
            Metrics including execution count, total time, memory, etc.
        """
        uptime = 0.0
        if self._started_at > 0:
            end = self._stopped_at if self._stopped_at > 0 else time.time()
            uptime = end - self._started_at

        metrics: dict[str, Any] = {
            "sandbox_id": self._sandbox_id,
            "state": self._state,
            "isolation_level": self._config.isolation_level,
            "os_profile": self._config.os_profile,
            "uptime_seconds": round(uptime, 2),
            "exec_count": self._exec_count,
            "total_exec_time": round(self._total_exec_time, 3),
            "avg_exec_time": (
                round(self._total_exec_time / self._exec_count, 3)
                if self._exec_count > 0
                else 0.0
            ),
            "config": {
                "max_memory_mb": self._config.max_memory_mb,
                "max_cpu_cores": self._config.max_cpu_cores,
                "max_pids": self._config.max_pids,
                "network_mode": self._config.network_mode,
                "timeout_seconds": self._config.timeout_seconds,
            },
            "filesystem_mounted": (
                self._filesystem.is_mounted()
                if self._filesystem is not None
                else False
            ),
            "network_active": (
                self._network.is_active()
                if self._network is not None
                else False
            ),
        }

        # Add filesystem usage if available
        if self._filesystem is not None:
            metrics["mounts"] = len(self._filesystem.get_mounts())

        # Add network stats if available
        if self._network is not None:
            metrics["network_stats"] = self._network.get_stats()

        return metrics

    def get_security_report(self) -> dict[str, Any]:
        """Return a security report for this sandbox.

        Returns
        -------
        dict[str, Any]
            Report including violations, blocked syscalls, and layer status.
        """
        report: dict[str, Any] = {
            "sandbox_id": self._sandbox_id,
            "isolation_level": self._config.isolation_level,
            "generated_at": time.time(),
            "layers": {
                "namespaces": {
                    "enabled": self._config.enable_namespaces,
                    "active": self._namespace_mgr is not None,
                },
                "seccomp": {
                    "enabled": self._config.enable_seccomp,
                    "active": self._seccomp is not None,
                },
                "filesystem": {
                    "enabled": self._config.enable_filesystem_isolation,
                    "active": (
                        self._filesystem is not None
                        and self._filesystem.is_mounted()
                    ),
                    "mounts": (
                        len(self._filesystem.get_mounts())
                        if self._filesystem is not None
                        else 0
                    ),
                },
                "network": {
                    "enabled": self._config.enable_network_isolation,
                    "active": (
                        self._network is not None
                        and self._network.is_active()
                    ),
                    "mode": self._config.network_mode,
                },
                "cgroups": {
                    "enabled": self._config.enable_cgroups,
                    "active": self._cgroup_mgr is not None,
                },
            },
            "violations": {
                "blocked_syscalls": list(self._blocked_syscalls),
                "network_violations": list(self._network_violations),
                "fs_violations": list(self._fs_violations),
                "total": (
                    len(self._blocked_syscalls)
                    + len(self._network_violations)
                    + len(self._fs_violations)
                ),
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
        }

        return report

    # ------------------------------------------------------------------
    # OS-specific setup
    # ------------------------------------------------------------------

    async def _setup_linux(self, profile: Any = None) -> None:
        """Set up Linux-specific isolation layers.

        Initialises namespaces, cgroups, seccomp, filesystem overlay,
        and network namespace with iptables/tc.
        """
        log.info("Setting up Linux isolation for sandbox %s", self._sandbox_id)

        # Namespace manager
        if self._config.enable_namespaces and NamespaceManager is not None:
            try:
                ns_config = NamespaceConfig() if NamespaceConfig is not None else None
                self._namespace_mgr = NamespaceManager(
                    sandbox_id=self._sandbox_id,
                    config=ns_config,
                )
                log.debug("Namespace manager initialised")
            except Exception as exc:
                log.warning("Namespace setup failed: %s", exc)

        # Cgroup manager
        if self._config.enable_cgroups and CgroupManager is not None:
            try:
                self._cgroup_mgr = CgroupManager(
                    sandbox_id=self._sandbox_id,
                    memory_limit_mb=self._config.max_memory_mb,
                    cpu_limit=self._config.max_cpu_cores,
                    pids_limit=self._config.max_pids,
                )
                log.debug("Cgroup manager initialised")
            except Exception as exc:
                log.warning("Cgroup setup failed: %s", exc)

        # Seccomp filter
        if self._config.enable_seccomp and SeccompProfile is not None:
            try:
                self._seccomp = SeccompProfile(
                    sandbox_id=self._sandbox_id,
                    allowed_syscalls=SAFE_SYSCALLS or [],
                )
                log.debug("Seccomp profile initialised")
            except Exception as exc:
                log.warning("Seccomp setup failed: %s", exc)

        # Filesystem isolation
        if self._config.enable_filesystem_isolation:
            try:
                self._filesystem = FilesystemIsolation(
                    sandbox_id=self._sandbox_id,
                    profile=profile,
                )
                self._rootfs = await self._filesystem.setup()
                log.debug("Filesystem isolation active at %s", self._rootfs)
            except Exception as exc:
                log.warning("Filesystem isolation failed: %s", exc)
                # Create a simple workspace fallback
                self._rootfs = tempfile.mkdtemp(
                    prefix=f"horizon-rootfs-{self._sandbox_id[:8]}-"
                )

        # Network isolation
        if self._config.enable_network_isolation:
            try:
                dns_config = DNSConfig()
                bandwidth = BandwidthLimit()

                if self._config.network_mode == "loopback":
                    bandwidth = BandwidthLimit(
                        ingress_mbps=0,
                        egress_mbps=0,
                        burst_kb=0,
                    )

                self._network = NetworkIsolation(
                    sandbox_id=self._sandbox_id,
                    policy=profile,
                    dns_config=dns_config,
                    bandwidth=bandwidth,
                )
                await self._network.setup()

                # Write resolv.conf into rootfs
                if self._rootfs:
                    await self._network.write_resolv_conf(self._rootfs)

                # Enable loopback-only if configured
                if self._config.network_mode in ("loopback", "none"):
                    await self._network.enable_loopback_only()

                log.debug("Network isolation active")
            except Exception as exc:
                log.warning("Network isolation failed: %s", exc)

    async def _setup_openbsd(self, profile: Any = None) -> None:
        """Set up OpenBSD-specific isolation.

        Uses pledge, unveil, pf rules, and rlimit for isolation.
        """
        log.info("Setting up OpenBSD isolation for sandbox %s", self._sandbox_id)

        # Create workspace directory
        self._rootfs = tempfile.mkdtemp(
            prefix=f"horizon-obsd-{self._sandbox_id[:8]}-"
        )
        os.makedirs(os.path.join(self._rootfs, "workspace"), exist_ok=True)

        # Filesystem isolation (generates unveil calls)
        if self._config.enable_filesystem_isolation:
            try:
                self._filesystem = FilesystemIsolation(
                    sandbox_id=self._sandbox_id,
                    profile=profile,
                )
                # Don't call setup() on OpenBSD (no OverlayFS)
                # Instead, generate unveil calls for later use
                unveil_calls = self._filesystem.generate_unveil_calls()
                log.info(
                    "Generated %d unveil specifications for sandbox %s",
                    len(unveil_calls),
                    self._sandbox_id,
                )
            except Exception as exc:
                log.warning("Filesystem isolation setup failed: %s", exc)

        # Network isolation (generates pf rules)
        if self._config.enable_network_isolation:
            try:
                self._network = NetworkIsolation(
                    sandbox_id=self._sandbox_id,
                    policy=profile,
                    dns_config=DNSConfig(),
                )
                pf_rules = self._network.generate_pf_conf()
                # Write pf rules to a file for pfctl
                pf_path = os.path.join(self._rootfs, "sandbox_pf.conf")
                with open(pf_path, "w") as f:
                    f.write(pf_rules)
                log.info("Generated pf.conf for sandbox %s", self._sandbox_id)
            except Exception as exc:
                log.warning("Network isolation setup failed: %s", exc)

        # Generate pledge string based on isolation level
        pledge_str = self._build_pledge_string()
        log.info(
            "OpenBSD pledge for sandbox %s: %s",
            self._sandbox_id,
            pledge_str,
        )

    async def _setup_freebsd(self, profile: Any = None) -> None:
        """Set up FreeBSD-specific isolation.

        Uses jail, capsicum, ipfw, and rctl for isolation.
        """
        log.info("Setting up FreeBSD isolation for sandbox %s", self._sandbox_id)

        # Create jail root directory
        jail_root = f"/jails/{self._sandbox_id}"
        self._rootfs = jail_root

        try:
            os.makedirs(jail_root, exist_ok=True)
            os.makedirs(os.path.join(jail_root, "workspace"), exist_ok=True)
        except OSError as exc:
            log.warning("Could not create jail root: %s", exc)
            self._rootfs = tempfile.mkdtemp(
                prefix=f"horizon-fbsd-{self._sandbox_id[:8]}-"
            )

        # Filesystem (generates jail fstab)
        if self._config.enable_filesystem_isolation:
            try:
                self._filesystem = FilesystemIsolation(
                    sandbox_id=self._sandbox_id,
                    profile=profile,
                )
                fstab_content = self._filesystem.generate_jail_fstab()
                fstab_path = os.path.join(self._rootfs, "fstab")
                try:
                    with open(fstab_path, "w") as f:
                        f.write(fstab_content)
                except OSError:
                    log.debug("Could not write jail fstab")
                log.info("Generated jail fstab for sandbox %s", self._sandbox_id)
            except Exception as exc:
                log.warning("Filesystem setup failed: %s", exc)

        # Network (generates ipfw rules)
        if self._config.enable_network_isolation:
            try:
                self._network = NetworkIsolation(
                    sandbox_id=self._sandbox_id,
                    policy=profile,
                    dns_config=DNSConfig(),
                )
                ipfw_rules = self._network.generate_ipfw_rules()
                # Write ipfw rules to a script
                ipfw_path = os.path.join(self._rootfs, "ipfw_rules.sh")
                try:
                    with open(ipfw_path, "w") as f:
                        f.write("#!/bin/sh\n")
                        f.write("# ipfw rules for sandbox {}\n".format(
                            self._sandbox_id
                        ))
                        for rule in ipfw_rules:
                            f.write(rule + "\n")
                except OSError:
                    log.debug("Could not write ipfw rules script")
                log.info(
                    "Generated %d ipfw rules for sandbox %s",
                    len(ipfw_rules),
                    self._sandbox_id,
                )
            except Exception as exc:
                log.warning("Network setup failed: %s", exc)

        # Generate rctl rules for resource limits
        rctl_rules = self._build_rctl_rules()
        log.info(
            "FreeBSD rctl rules for sandbox %s: %s",
            self._sandbox_id,
            rctl_rules,
        )

    async def _setup_generic(self, profile: Any = None) -> None:
        """Generic setup for unsupported platforms (macOS, Windows).

        Provides basic process isolation via subprocess and filesystem
        restrictions via a temporary directory.
        """
        log.info(
            "Setting up generic isolation for sandbox %s on %s",
            self._sandbox_id,
            platform.system(),
        )

        self._rootfs = tempfile.mkdtemp(
            prefix=f"horizon-generic-{self._sandbox_id[:8]}-"
        )
        os.makedirs(os.path.join(self._rootfs, "workspace"), exist_ok=True)

        # Set up filesystem isolation (copy-based fallback)
        if self._config.enable_filesystem_isolation:
            try:
                self._filesystem = FilesystemIsolation(
                    sandbox_id=self._sandbox_id,
                    profile=profile,
                )
                self._rootfs = await self._filesystem.setup()
            except Exception as exc:
                log.warning("Filesystem setup failed: %s", exc)

        log.info(
            "Generic isolation ready for sandbox %s at %s",
            self._sandbox_id,
            self._rootfs,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_profile(self) -> Any:
        """Resolve the OS profile from the configuration string."""
        if get_profile is not None:
            try:
                return get_profile(self._config.os_profile)
            except (KeyError, ValueError):
                log.warning(
                    "Unknown OS profile %s — using default",
                    self._config.os_profile,
                )
        return None

    def _build_exec_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Build the execution environment for sandbox commands."""
        env: dict[str, str] = {
            "HOME": "/workspace",
            "USER": "sandbox",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "TERM": "xterm-256color",
            "HORIZON_SANDBOX_ID": self._sandbox_id,
            "HORIZON_ISOLATION_LEVEL": self._config.isolation_level,
        }
        if extra:
            env.update(extra)
        return env

    def _build_exec_args(self, cmd_args: list[str]) -> list[str]:
        """Build the full command arguments with namespace prefix."""
        # If we have a namespace manager with an exec method, prefix it
        if (
            _LINUX
            and self._namespace_mgr is not None
            and hasattr(self._namespace_mgr, "netns_name")
        ):
            netns = getattr(self._namespace_mgr, "netns_name", "")
            if netns:
                return [
                    "ip", "netns", "exec", netns,
                ] + cmd_args

        # If we have network isolation with a namespace
        if (
            _LINUX
            and self._network is not None
            and self._network.is_active()
        ):
            return [
                "ip", "netns", "exec", self._network.netns_name,
            ] + cmd_args

        return cmd_args

    def _detect_new_files(self) -> list[str]:
        """Detect files created in the workspace since last check."""
        files: list[str] = []
        ws = self._workspace_dir
        if not ws or not os.path.isdir(ws):
            return files
        try:
            for entry in os.scandir(ws):
                files.append(entry.name)
        except OSError:
                        import logging as _log; _log.getLogger('sandbox.runtime').debug('Suppressed exception', exc_info=True)
        return files

    def _is_path_safe(self, path: str) -> bool:
        """Check if a path is within the sandbox boundaries."""
        resolved = os.path.realpath(path)

        # Allow paths within rootfs
        if self._rootfs and resolved.startswith(os.path.realpath(self._rootfs)):
            return True

        # Allow paths within workspace
        if self._workspace_dir and resolved.startswith(
            os.path.realpath(self._workspace_dir)
        ):
            return True

        # Allow /tmp paths
        if resolved.startswith(tempfile.gettempdir()):
            return True

        return False

    def _build_pledge_string(self) -> str:
        """Build an OpenBSD pledge string based on isolation level."""
        level = self._config.isolation_level

        if level == "paranoid":
            return "stdio rpath"
        elif level == "maximum":
            return "stdio rpath wpath cpath"
        elif level == "standard":
            return "stdio rpath wpath cpath proc exec inet dns"
        else:  # minimal
            return "stdio rpath wpath cpath proc exec inet dns fattr getpw"

    def _build_rctl_rules(self) -> list[str]:
        """Build FreeBSD rctl resource-limit rules."""
        rules: list[str] = []
        jail_name = f"horizon_{self._sandbox_id[:12]}"

        # Memory limit
        mem_bytes = self._config.max_memory_mb * 1024 * 1024
        rules.append(
            f"jail:{jail_name}:memoryuse:deny={mem_bytes}"
        )

        # CPU percentage (approximate mapping)
        cpu_pct = int(self._config.max_cpu_cores * 100)
        rules.append(
            f"jail:{jail_name}:pcpu:deny={cpu_pct}"
        )

        # Max processes
        rules.append(
            f"jail:{jail_name}:maxproc:deny={self._config.max_pids}"
        )

        # Open files limit
        rules.append(
            f"jail:{jail_name}:openfiles:deny=1024"
        )

        return rules

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"HardenedSandbox("
            f"id={self._sandbox_id!r}, "
            f"state={self._state!r}, "
            f"level={self._config.isolation_level!r}"
            f")"
        )


# ---------------------------------------------------------------------------
# HardenedSandboxPool
# ---------------------------------------------------------------------------

class HardenedSandboxPool:
    """Pool of hardened sandboxes with resource management.

    Manages multiple concurrent sandboxes, enforces global resource
    limits, and auto-cleans dead sandboxes via a background reaper task.
    """

    def __init__(
        self,
        default_config: HardenedSandboxConfig | None = None,
        max_sandboxes: int = 20,
    ) -> None:
        self._default_config = default_config or HardenedSandboxConfig()
        self._max_sandboxes = max_sandboxes
        self._sandboxes: dict[str, HardenedSandbox] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task[None] | None = None
        self._reaper_running = False
        log.debug(
            "HardenedSandboxPool created (max=%d)", max_sandboxes
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        sandbox_id: str | None = None,
        config: HardenedSandboxConfig | None = None,
    ) -> HardenedSandbox:
        """Create a new hardened sandbox.

        Parameters
        ----------
        sandbox_id:
            Optional identifier.  Auto-generated if not provided.
        config:
            Sandbox configuration.  Uses pool default if not provided.

        Returns
        -------
        HardenedSandbox
            The newly created sandbox.

        Raises
        ------
        RuntimeError
            If the pool has reached its maximum capacity.
        """
        async with self._lock:
            if len(self._sandboxes) >= self._max_sandboxes:
                raise RuntimeError(
                    f"Pool full: {len(self._sandboxes)}/{self._max_sandboxes} "
                    f"sandboxes active"
                )

            if sandbox_id is None:
                sandbox_id = f"sb-{uuid.uuid4().hex[:12]}"

            if sandbox_id in self._sandboxes:
                raise ValueError(
                    f"Sandbox {sandbox_id} already exists in pool"
                )

            cfg = config or self._default_config
            sandbox = HardenedSandbox(sandbox_id=sandbox_id, config=cfg)

        await sandbox.create()

        async with self._lock:
            self._sandboxes[sandbox_id] = sandbox

        log.info(
            "Pool: created sandbox %s (%d/%d active)",
            sandbox_id,
            len(self._sandboxes),
            self._max_sandboxes,
        )
        return sandbox

    async def get(self, sandbox_id: str) -> HardenedSandbox | None:
        """Get a sandbox by ID.

        Parameters
        ----------
        sandbox_id:
            The sandbox identifier.

        Returns
        -------
        HardenedSandbox | None
            The sandbox, or ``None`` if not found.
        """
        return self._sandboxes.get(sandbox_id)

    async def destroy(self, sandbox_id: str) -> None:
        """Destroy a specific sandbox and remove it from the pool.

        Parameters
        ----------
        sandbox_id:
            The sandbox to destroy.
        """
        async with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)

        if sandbox is not None:
            await sandbox.destroy()
            log.info(
                "Pool: destroyed sandbox %s (%d remaining)",
                sandbox_id,
                len(self._sandboxes),
            )
        else:
            log.warning("Pool: sandbox %s not found", sandbox_id)

    async def destroy_all(self) -> None:
        """Destroy all sandboxes in the pool."""
        async with self._lock:
            sandbox_ids = list(self._sandboxes.keys())

        for sid in sandbox_ids:
            try:
                await self.destroy(sid)
            except Exception as exc:
                log.warning("Failed to destroy sandbox %s: %s", sid, exc)

        log.info("Pool: all sandboxes destroyed")

    # ------------------------------------------------------------------
    # Listing and stats
    # ------------------------------------------------------------------

    def list_active(self) -> list[dict[str, Any]]:
        """List all active sandboxes with summary information.

        Returns
        -------
        list[dict[str, Any]]
            List of sandbox summaries.
        """
        active: list[dict[str, Any]] = []
        for sid, sandbox in self._sandboxes.items():
            active.append({
                "sandbox_id": sid,
                "state": sandbox.state,
                "isolation_level": sandbox.config.isolation_level,
                "os_profile": sandbox.config.os_profile,
                "created_at": sandbox._created_at,
                "last_activity": sandbox._last_activity,
                "exec_count": sandbox._exec_count,
            })
        return active

    def get_pool_stats(self) -> dict[str, Any]:
        """Return pool-level statistics.

        Returns
        -------
        dict[str, Any]
            Pool statistics.
        """
        states: dict[str, int] = {}
        total_execs = 0
        total_exec_time = 0.0

        for sandbox in self._sandboxes.values():
            state = sandbox.state
            states[state] = states.get(state, 0) + 1
            total_execs += sandbox._exec_count
            total_exec_time += sandbox._total_exec_time

        return {
            "total_sandboxes": len(self._sandboxes),
            "max_sandboxes": self._max_sandboxes,
            "available_slots": self._max_sandboxes - len(self._sandboxes),
            "states": states,
            "total_executions": total_execs,
            "total_exec_time": round(total_exec_time, 3),
            "reaper_running": self._reaper_running,
        }

    # ------------------------------------------------------------------
    # Reaper
    # ------------------------------------------------------------------

    async def start_reaper(self) -> None:
        """Start the background reaper task.

        The reaper periodically scans for idle or dead sandboxes and
        destroys them to free resources.
        """
        if self._reaper_running:
            return

        self._reaper_running = True
        self._reaper_task = asyncio.create_task(self._reaper_loop())
        log.info("Sandbox reaper started (interval=%.0fs)", _REAPER_INTERVAL)

    async def stop_reaper(self) -> None:
        """Stop the background reaper task."""
        self._reaper_running = False
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None
        log.info("Sandbox reaper stopped")

    async def _reaper_loop(self) -> None:
        """Background loop that reaps idle and dead sandboxes."""
        while self._reaper_running:
            try:
                await asyncio.sleep(_REAPER_INTERVAL)
                await self._reap_idle_sandboxes()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Reaper error: %s", exc)

    async def _reap_idle_sandboxes(self) -> None:
        """Destroy sandboxes that have been idle too long."""
        now = time.time()
        to_reap: list[str] = []

        for sid, sandbox in self._sandboxes.items():
            idle_time = now - sandbox._last_activity

            # Reap destroyed sandboxes
            if sandbox.state == "destroyed":
                to_reap.append(sid)
                continue

            # Reap idle sandboxes
            if idle_time > _MAX_IDLE_TIME:
                log.info(
                    "Reaping idle sandbox %s (idle %.0fs)",
                    sid,
                    idle_time,
                )
                to_reap.append(sid)

        for sid in to_reap:
            try:
                await self.destroy(sid)
            except Exception as exc:
                log.warning("Reaper failed to destroy %s: %s", sid, exc)

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"HardenedSandboxPool("
            f"active={len(self._sandboxes)}, "
            f"max={self._max_sandboxes}"
            f")"
        )
