"""Horizon Orchestra — Linux Namespace & Cgroup v2 Manager.

Creates PID, NET, MNT, USER, UTS, and IPC namespaces for sandbox processes
using ``unshare(2)`` via :func:`asyncio.create_subprocess_exec`.  Also
manages cgroup v2 resource limits (memory, CPU, PIDs, I/O).

On non-Linux systems the classes remain importable but operations raise
:class:`PlatformError` with a human-friendly explanation.

Usage::

    from orchestra.sandbox.namespaces import (
        NamespaceManager, CgroupManager, NamespaceConfig,
    )
    from orchestra.sandbox.os_profiles import ResourceLimits

    config  = NamespaceConfig(hostname="my-sandbox")
    manager = NamespaceManager(config=config)
    limits  = ResourceLimits()

    cgroup = CgroupManager(sandbox_id="abc123", limits=limits)
    await cgroup.create()
    await cgroup.apply_limits()

    pid = await manager.create_namespace("abc123", "python3 -c 'print(1)'",
                                          cgroup=cgroup)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shlex
import signal
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "NamespaceConfig",
    "NamespaceManager",
    "CgroupManager",
    "PlatformError",
    "NamespaceError",
    "ExecResult",
]

log = logging.getLogger("orchestra.sandbox.namespaces")

_IS_LINUX: bool = platform.system() == "Linux"
_CGROUP_ROOT: str = "/sys/fs/cgroup"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PlatformError(RuntimeError):
    """Raised when a Linux-only operation is attempted on another OS."""


class NamespaceError(RuntimeError):
    """Raised when namespace or cgroup creation/management fails."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class ExecResult:
    """Result of a command executed inside a namespace."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False
    pid: int = 0


def _require_linux(operation: str) -> None:
    """Raise :class:`PlatformError` if we're not on Linux."""
    if not _IS_LINUX:
        raise PlatformError(
            f"Operation '{operation}' requires Linux namespaces. "
            f"Current platform: {platform.system()}. "
            f"Consider using OS-native isolation (pledge on OpenBSD, "
            f"capsicum/jails on FreeBSD) or Docker."
        )


async def _run_cmd(
    args: list[str],
    *,
    timeout: float | None = 30.0,
    input_data: bytes | None = None,
) -> ExecResult:
    """Run a subprocess via :func:`asyncio.create_subprocess_exec`.

    All arguments are passed directly — no shell interpretation.
    """
    start = time.monotonic()
    log.debug("Running: %s", args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if input_data else asyncio.subprocess.DEVNULL,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=input_data),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(
                exit_code=-1,
                stderr=f"Command timed out after {timeout}s",
                duration=time.monotonic() - start,
                timed_out=True,
                pid=proc.pid or 0,
            )
        return ExecResult(
            exit_code=proc.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration=time.monotonic() - start,
            pid=proc.pid or 0,
        )
    except FileNotFoundError as exc:
        return ExecResult(
            exit_code=-1,
            stderr=f"Command not found: {exc}",
            duration=time.monotonic() - start,
        )
    except OSError as exc:
        return ExecResult(
            exit_code=-1,
            stderr=f"OS error: {exc}",
            duration=time.monotonic() - start,
        )


async def _write_file_async(path: str, content: str) -> None:
    """Write *content* to *path* via a thread-pool (non-blocking)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_file_sync, path, content)


def _write_file_sync(path: str, content: str) -> None:
    """Synchronous helper for file writes."""
    Path(path).write_text(content, encoding="utf-8")


async def _read_file_async(path: str) -> str:
    """Read a file via a thread-pool (non-blocking)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _read_file_sync, path)


def _read_file_sync(path: str) -> str:
    """Synchronous helper for file reads."""
    return Path(path).read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# NamespaceConfig
# ---------------------------------------------------------------------------

@dataclass
class NamespaceConfig:
    """Configuration for Linux namespace creation.

    Each flag controls whether the corresponding namespace is unshared
    for the sandbox process.  UID/GID maps control user namespace
    identity mapping.
    """

    enable_pid_ns: bool = True       # Isolated process tree (PID 1 inside)
    enable_net_ns: bool = True       # Isolated network stack
    enable_mnt_ns: bool = True       # Isolated mount table
    enable_user_ns: bool = True      # Unprivileged user mapping
    enable_uts_ns: bool = True       # Isolated hostname
    enable_ipc_ns: bool = True       # Isolated IPC (shared memory, semaphores)
    uid_map: str = "0 1000 65536"    # Map container root → host user 1000
    gid_map: str = "0 1000 65536"
    hostname: str = "horizon-sandbox"

    # Execution defaults
    default_timeout: float = 300.0   # seconds
    mount_proc: bool = True          # Mount /proc inside PID ns
    mount_tmpfs: bool = True         # Mount /tmp as tmpfs

    def get_unshare_flags(self) -> list[str]:
        """Return ``unshare`` CLI flags for the enabled namespaces."""
        flags: list[str] = []
        if self.enable_pid_ns:
            flags.append("--pid")
        if self.enable_net_ns:
            flags.append("--net")
        if self.enable_mnt_ns:
            flags.append("--mount")
        if self.enable_user_ns:
            flags.append("--user")
        if self.enable_uts_ns:
            flags.append("--uts")
        if self.enable_ipc_ns:
            flags.append("--ipc")
        if self.mount_proc and self.enable_pid_ns:
            flags.append("--mount-proc")
        if self.enable_pid_ns:
            flags.append("--fork")
        return flags

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dictionary."""
        return {
            "enable_pid_ns": self.enable_pid_ns,
            "enable_net_ns": self.enable_net_ns,
            "enable_mnt_ns": self.enable_mnt_ns,
            "enable_user_ns": self.enable_user_ns,
            "enable_uts_ns": self.enable_uts_ns,
            "enable_ipc_ns": self.enable_ipc_ns,
            "uid_map": self.uid_map,
            "gid_map": self.gid_map,
            "hostname": self.hostname,
            "default_timeout": self.default_timeout,
            "mount_proc": self.mount_proc,
            "mount_tmpfs": self.mount_tmpfs,
        }


# ---------------------------------------------------------------------------
# CgroupManager — cgroup v2 resource control
# ---------------------------------------------------------------------------

class CgroupManager:
    """Manages cgroup v2 resource limits for sandbox processes.

    Creates a cgroup under ``/sys/fs/cgroup/horizon-sandbox-{id}/`` and
    writes memory, CPU, PID, and I/O limits to the appropriate control
    files.  All operations are async and use
    :func:`asyncio.create_subprocess_exec` — never ``shell=True``.

    On non-Linux platforms, methods raise :class:`PlatformError`.
    """

    def __init__(self, sandbox_id: str, limits: Any) -> None:
        """
        Parameters
        ----------
        sandbox_id:
            Unique identifier for this sandbox instance.
        limits:
            A :class:`~orchestra.sandbox.os_profiles.ResourceLimits` (or
            duck-typed equivalent with the same attributes).
        """
        self._sandbox_id: str = sandbox_id
        self._limits = limits
        self._cgroup_path: str = os.path.join(
            _CGROUP_ROOT, f"horizon-sandbox-{sandbox_id}"
        )
        self._created: bool = False
        self._pids: list[int] = []

    # -- properties ---------------------------------------------------------

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def cgroup_path(self) -> str:
        return self._cgroup_path

    @property
    def is_created(self) -> bool:
        return self._created

    # -- lifecycle ----------------------------------------------------------

    async def create(self) -> str:
        """Create the cgroup directory.  Returns the cgroup path."""
        _require_linux("cgroup.create")

        path = Path(self._cgroup_path)
        if path.exists():
            log.warning("Cgroup already exists: %s", self._cgroup_path)
        else:
            result = await _run_cmd(["mkdir", "-p", self._cgroup_path])
            if result.exit_code != 0:
                raise NamespaceError(
                    f"Failed to create cgroup {self._cgroup_path}: "
                    f"{result.stderr}"
                )
        self._created = True
        log.info("Created cgroup: %s", self._cgroup_path)
        return self._cgroup_path

    async def apply_limits(self) -> None:
        """Write all resource limits to cgroup v2 control files."""
        _require_linux("cgroup.apply_limits")

        if not self._created:
            raise NamespaceError("Cgroup not yet created — call create() first")

        await self.set_memory_limit(self._limits.max_memory_bytes)
        await self.set_memory_swap_limit(self._limits.max_memory_swap_bytes)
        await self.set_cpu_quota(self._limits.max_cpu_quota_us)
        await self.set_cpu_weight(self._limits.max_cpu_shares)
        await self.set_pids_max(self._limits.max_pids)
        log.info("Applied all resource limits for sandbox %s", self._sandbox_id)

    async def add_process(self, pid: int) -> None:
        """Move *pid* into this cgroup."""
        _require_linux("cgroup.add_process")

        procs_file = os.path.join(self._cgroup_path, "cgroup.procs")
        await _write_file_async(procs_file, str(pid))
        self._pids.append(pid)
        log.debug("Added PID %d to cgroup %s", pid, self._sandbox_id)

    async def get_stats(self) -> dict[str, Any]:
        """Read current cgroup v2 statistics.

        Returns
        -------
        dict
            Keys include ``memory_current``, ``memory_peak``,
            ``cpu_usage_usec``, ``pids_current``, etc.
        """
        _require_linux("cgroup.get_stats")

        stats: dict[str, Any] = {}

        # Memory
        try:
            mem_current = await _read_file_async(
                os.path.join(self._cgroup_path, "memory.current")
            )
            stats["memory_current"] = int(mem_current)
        except (OSError, ValueError):
            stats["memory_current"] = -1

        try:
            mem_peak = await _read_file_async(
                os.path.join(self._cgroup_path, "memory.peak")
            )
            stats["memory_peak"] = int(mem_peak)
        except (OSError, ValueError):
            stats["memory_peak"] = -1

        # CPU
        try:
            cpu_stat_raw = await _read_file_async(
                os.path.join(self._cgroup_path, "cpu.stat")
            )
            for line in cpu_stat_raw.splitlines():
                parts = line.split()
                if len(parts) == 2:
                    stats[f"cpu_{parts[0]}"] = int(parts[1])
        except (OSError, ValueError):
            stats["cpu_usage_usec"] = -1

        # PIDs
        try:
            pids_current = await _read_file_async(
                os.path.join(self._cgroup_path, "pids.current")
            )
            stats["pids_current"] = int(pids_current)
        except (OSError, ValueError):
            stats["pids_current"] = -1

        # I/O
        try:
            io_stat = await _read_file_async(
                os.path.join(self._cgroup_path, "io.stat")
            )
            stats["io_stat"] = io_stat
        except (OSError, ValueError):
            stats["io_stat"] = ""

        return stats

    async def destroy(self) -> None:
        """Kill all processes in the cgroup and remove it."""
        _require_linux("cgroup.destroy")

        # Kill remaining processes
        procs_file = os.path.join(self._cgroup_path, "cgroup.procs")
        try:
            content = await _read_file_async(procs_file)
            for pid_str in content.splitlines():
                pid_str = pid_str.strip()
                if pid_str.isdigit():
                    try:
                        os.kill(int(pid_str), signal.SIGKILL)
                        log.debug("Killed PID %s in cgroup %s", pid_str, self._sandbox_id)
                    except ProcessLookupError:
                        pass
        except OSError:
            pass

        # Wait briefly for processes to exit
        await asyncio.sleep(0.2)

        # Remove cgroup directory
        result = await _run_cmd(["rmdir", self._cgroup_path])
        if result.exit_code != 0:
            log.warning(
                "Could not remove cgroup %s: %s",
                self._cgroup_path, result.stderr,
            )
        else:
            log.info("Destroyed cgroup: %s", self._cgroup_path)

        self._created = False
        self._pids.clear()

    # -- individual limit setters -------------------------------------------

    async def set_memory_limit(self, limit_bytes: int) -> None:
        """Set ``memory.max`` to *limit_bytes*."""
        _require_linux("cgroup.set_memory_limit")
        path = os.path.join(self._cgroup_path, "memory.max")
        await _write_file_async(path, str(limit_bytes))
        log.debug("Set memory.max=%d for %s", limit_bytes, self._sandbox_id)

    async def set_memory_swap_limit(self, limit_bytes: int) -> None:
        """Set ``memory.swap.max`` to *limit_bytes*."""
        _require_linux("cgroup.set_memory_swap_limit")
        path = os.path.join(self._cgroup_path, "memory.swap.max")
        await _write_file_async(path, str(limit_bytes))
        log.debug("Set memory.swap.max=%d for %s", limit_bytes, self._sandbox_id)

    async def set_cpu_quota(
        self, quota_us: int, period_us: int = 100_000
    ) -> None:
        """Set ``cpu.max`` to ``{quota_us} {period_us}``."""
        _require_linux("cgroup.set_cpu_quota")
        path = os.path.join(self._cgroup_path, "cpu.max")
        await _write_file_async(path, f"{quota_us} {period_us}")
        log.debug(
            "Set cpu.max=%d %d for %s", quota_us, period_us, self._sandbox_id,
        )

    async def set_cpu_weight(self, weight: int) -> None:
        """Set ``cpu.weight`` (1–10000, default 100)."""
        _require_linux("cgroup.set_cpu_weight")
        # cgroup v2 cpu.weight range is 1-10000; map from cpu.shares convention
        cgroup_weight = max(1, min(10000, weight))
        path = os.path.join(self._cgroup_path, "cpu.weight")
        await _write_file_async(path, str(cgroup_weight))
        log.debug("Set cpu.weight=%d for %s", cgroup_weight, self._sandbox_id)

    async def set_pids_max(self, max_pids: int) -> None:
        """Set ``pids.max``."""
        _require_linux("cgroup.set_pids_max")
        path = os.path.join(self._cgroup_path, "pids.max")
        await _write_file_async(path, str(max_pids))
        log.debug("Set pids.max=%d for %s", max_pids, self._sandbox_id)

    async def set_io_limit(
        self,
        read_bps: int,
        write_bps: int,
        *,
        device: str = "",
    ) -> None:
        """Set ``io.max`` read/write byte-per-second limits.

        Parameters
        ----------
        read_bps:
            Maximum read bytes per second.
        write_bps:
            Maximum write bytes per second.
        device:
            Block device major:minor (e.g. ``"8:0"``).  If empty, attempts
            to discover the root device automatically.
        """
        _require_linux("cgroup.set_io_limit")

        if not device:
            device = await self._detect_root_device()
            if not device:
                log.warning("Cannot detect root block device for I/O limits")
                return

        path = os.path.join(self._cgroup_path, "io.max")
        value = f"{device} rbps={read_bps} wbps={write_bps}"
        await _write_file_async(path, value)
        log.debug("Set io.max=%s for %s", value, self._sandbox_id)

    async def _detect_root_device(self) -> str:
        """Attempt to discover the root block device major:minor."""
        try:
            stat_result = os.stat("/")
            major = os.major(stat_result.st_dev)
            minor = os.minor(stat_result.st_dev)
            return f"{major}:{minor}"
        except OSError:
            return ""


# ---------------------------------------------------------------------------
# NamespaceManager — Linux namespace lifecycle
# ---------------------------------------------------------------------------

class NamespaceManager:
    """Creates and manages Linux namespaces for sandbox isolation.

    Uses ``unshare(1)`` via :func:`asyncio.create_subprocess_exec` to
    create isolated namespaces for sandbox process trees.  Supports
    PID, NET, MNT, USER, UTS, and IPC namespaces.

    On non-Linux systems (OpenBSD, FreeBSD, macOS), methods raise
    :class:`PlatformError` with a message suggesting the appropriate
    OS-native isolation mechanism.
    """

    def __init__(self, config: NamespaceConfig | None = None) -> None:
        self._config: NamespaceConfig = config or NamespaceConfig()
        self._namespaces: dict[str, _NamespaceState] = {}

    # -- properties ---------------------------------------------------------

    @property
    def config(self) -> NamespaceConfig:
        """The namespace configuration."""
        return self._config

    @property
    def active_count(self) -> int:
        """Number of active namespaces."""
        return sum(
            1 for ns in self._namespaces.values() if ns.alive
        )

    # -- lifecycle ----------------------------------------------------------

    async def create_namespace(
        self,
        sandbox_id: str,
        command: str,
        *,
        cgroup: CgroupManager | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> int:
        """Create a new namespace and launch *command* inside it.

        Parameters
        ----------
        sandbox_id:
            Unique identifier for the sandbox.
        command:
            Command string to execute inside the namespace.
        cgroup:
            Optional :class:`CgroupManager` to associate with the
            namespaced process.
        timeout:
            Execution timeout in seconds (defaults to config value).
        env:
            Additional environment variables.

        Returns
        -------
        int
            PID of the unshare root process on the host.
        """
        _require_linux("namespace.create")

        if sandbox_id in self._namespaces:
            raise NamespaceError(
                f"Namespace already exists for sandbox {sandbox_id!r}"
            )

        effective_timeout = timeout or self._config.default_timeout
        unshare_cmd = self.build_unshare_cmd(command)
        log.info(
            "Creating namespace for sandbox %s: %s",
            sandbox_id, " ".join(unshare_cmd),
        )

        # Launch the process
        proc_env = dict(os.environ)
        proc_env["HOSTNAME"] = self._config.hostname
        if env:
            proc_env.update(env)

        proc = await asyncio.create_subprocess_exec(
            *unshare_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=proc_env,
        )

        pid = proc.pid or 0
        log.info("Namespace process started: PID=%d sandbox=%s", pid, sandbox_id)

        # Write UID/GID maps if user namespace is enabled
        if self._config.enable_user_ns and pid > 0:
            await self.write_uid_map(pid)
            await self.write_gid_map(pid)

        # Add to cgroup if provided
        if cgroup is not None and pid > 0:
            try:
                await cgroup.add_process(pid)
            except (PlatformError, NamespaceError) as exc:
                log.warning("Could not add PID %d to cgroup: %s", pid, exc)

        # Track state
        state = _NamespaceState(
            sandbox_id=sandbox_id,
            host_pid=pid,
            process=proc,
            cgroup=cgroup,
            created_at=time.monotonic(),
            timeout=effective_timeout,
        )
        self._namespaces[sandbox_id] = state

        return pid

    async def enter_namespace(
        self,
        sandbox_id: str,
        command: str,
        *,
        timeout: float = 30.0,
    ) -> ExecResult:
        """Execute a command inside an existing namespace via ``nsenter``.

        Parameters
        ----------
        sandbox_id:
            Must reference a previously created namespace.
        command:
            Command string to execute inside the namespace.
        timeout:
            Execution timeout in seconds.

        Returns
        -------
        ExecResult
            Captured stdout, stderr, exit code, and timing.
        """
        _require_linux("namespace.enter")

        state = self._namespaces.get(sandbox_id)
        if state is None:
            raise NamespaceError(
                f"No namespace found for sandbox {sandbox_id!r}"
            )
        if not state.alive:
            raise NamespaceError(
                f"Namespace for sandbox {sandbox_id!r} is no longer alive"
            )

        cmd_parts = shlex.split(command)
        nsenter_cmd = [
            "nsenter",
            "-t", str(state.host_pid),
            "--pid", "--net", "--mount", "--uts", "--ipc",
        ]
        if self._config.enable_user_ns:
            nsenter_cmd.append("--user")
        nsenter_cmd.extend(["--"] + cmd_parts)

        return await _run_cmd(nsenter_cmd, timeout=timeout)

    async def destroy_namespace(self, sandbox_id: str) -> None:
        """Terminate all processes and clean up the namespace.

        Sends SIGTERM, waits briefly, then SIGKILL if needed.
        """
        _require_linux("namespace.destroy")

        state = self._namespaces.pop(sandbox_id, None)
        if state is None:
            log.warning("No namespace to destroy for sandbox %s", sandbox_id)
            return

        # Terminate the root process
        if state.process.returncode is None:
            log.info("Terminating namespace PID %d", state.host_pid)
            try:
                state.process.terminate()
                try:
                    await asyncio.wait_for(state.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    log.warning(
                        "PID %d did not exit after SIGTERM — sending SIGKILL",
                        state.host_pid,
                    )
                    state.process.kill()
                    await state.process.wait()
            except ProcessLookupError:
                pass

        # Clean up cgroup
        if state.cgroup is not None:
            try:
                await state.cgroup.destroy()
            except (PlatformError, NamespaceError, OSError) as exc:
                log.warning("Cgroup cleanup failed for %s: %s", sandbox_id, exc)

        log.info("Destroyed namespace for sandbox %s", sandbox_id)

    async def wait_namespace(
        self,
        sandbox_id: str,
        *,
        timeout: float | None = None,
    ) -> ExecResult:
        """Wait for the namespace root process to exit.

        Returns
        -------
        ExecResult
            Final stdout, stderr, exit code, and duration.
        """
        state = self._namespaces.get(sandbox_id)
        if state is None:
            raise NamespaceError(f"No namespace for sandbox {sandbox_id!r}")

        effective_timeout = timeout or state.timeout
        start = time.monotonic()

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                state.process.communicate(),
                timeout=effective_timeout,
            )
            return ExecResult(
                exit_code=state.process.returncode or 0,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                duration=time.monotonic() - start,
                pid=state.host_pid,
            )
        except asyncio.TimeoutError:
            state.process.kill()
            await state.process.wait()
            return ExecResult(
                exit_code=-1,
                stderr=f"Namespace process timed out after {effective_timeout}s",
                duration=time.monotonic() - start,
                timed_out=True,
                pid=state.host_pid,
            )

    # -- unshare command builder --------------------------------------------

    def build_unshare_cmd(self, inner_cmd: str) -> list[str]:
        """Build the full ``unshare`` command line for *inner_cmd*.

        Uses :func:`shlex.split` to tokenise *inner_cmd* safely.  All
        arguments are passed positionally to
        :func:`asyncio.create_subprocess_exec` — no shell expansion
        occurs.

        Returns
        -------
        list[str]
            Complete argument vector starting with ``"unshare"``.
        """
        base = ["unshare"]
        base.extend(self._config.get_unshare_flags())

        # Set hostname if UTS namespace is enabled
        if self._config.enable_uts_ns:
            base.extend([
                "--map-root-user" if self._config.enable_user_ns else "",
            ])
            # Filter out empty strings
            base = [arg for arg in base if arg]

        inner_parts = shlex.split(inner_cmd)
        base.extend(["--"] + inner_parts)
        return base

    # -- UID / GID mapping --------------------------------------------------

    async def write_uid_map(self, pid: int) -> None:
        """Write the UID map for the user namespace of *pid*.

        Writes to ``/proc/{pid}/uid_map``.  The map string is taken
        from :attr:`config.uid_map`.
        """
        _require_linux("namespace.write_uid_map")

        uid_map_path = f"/proc/{pid}/uid_map"
        map_content = self._config.uid_map
        log.debug("Writing uid_map for PID %d: %s", pid, map_content)
        try:
            await _write_file_async(uid_map_path, map_content)
        except OSError as exc:
            log.warning("Failed to write uid_map for PID %d: %s", pid, exc)
            # Try via newuidmap helper
            parts = map_content.split()
            if len(parts) == 3:
                result = await _run_cmd([
                    "newuidmap", str(pid),
                    parts[0], parts[1], parts[2],
                ])
                if result.exit_code != 0:
                    raise NamespaceError(
                        f"Failed to set uid_map for PID {pid}: {result.stderr}"
                    ) from exc

    async def write_gid_map(self, pid: int) -> None:
        """Write the GID map for the user namespace of *pid*.

        Writes ``deny`` to ``/proc/{pid}/setgroups`` first (required by
        the kernel), then writes to ``/proc/{pid}/gid_map``.
        """
        _require_linux("namespace.write_gid_map")

        # Deny setgroups first (kernel requirement for unprivileged gid_map)
        setgroups_path = f"/proc/{pid}/setgroups"
        try:
            await _write_file_async(setgroups_path, "deny")
        except OSError as exc:
            log.debug("Could not write setgroups deny for PID %d: %s", pid, exc)

        gid_map_path = f"/proc/{pid}/gid_map"
        map_content = self._config.gid_map
        log.debug("Writing gid_map for PID %d: %s", pid, map_content)
        try:
            await _write_file_async(gid_map_path, map_content)
        except OSError as exc:
            log.warning("Failed to write gid_map for PID %d: %s", pid, exc)
            parts = map_content.split()
            if len(parts) == 3:
                result = await _run_cmd([
                    "newgidmap", str(pid),
                    parts[0], parts[1], parts[2],
                ])
                if result.exit_code != 0:
                    raise NamespaceError(
                        f"Failed to set gid_map for PID {pid}: {result.stderr}"
                    ) from exc

    # -- namespace info -----------------------------------------------------

    def get_namespace_pids(self, sandbox_id: str) -> list[int]:
        """Return the list of host PIDs associated with *sandbox_id*.

        Only returns the root PID on the host side.  For full process
        tree enumeration inside the namespace, use
        :meth:`enter_namespace` to run ``ps``.
        """
        state = self._namespaces.get(sandbox_id)
        if state is None:
            return []
        return [state.host_pid]

    def is_namespace_alive(self, sandbox_id: str) -> bool:
        """Return *True* if the namespace root process is still running."""
        state = self._namespaces.get(sandbox_id)
        if state is None:
            return False
        return state.alive

    def list_namespaces(self) -> list[dict[str, Any]]:
        """Return summary information for all tracked namespaces."""
        result: list[dict[str, Any]] = []
        for sid, state in self._namespaces.items():
            result.append({
                "sandbox_id": sid,
                "host_pid": state.host_pid,
                "alive": state.alive,
                "created_at": state.created_at,
                "has_cgroup": state.cgroup is not None,
            })
        return result

    async def cleanup_dead(self) -> int:
        """Remove tracking entries for namespaces whose processes have exited.

        Returns the number of entries cleaned up.
        """
        dead: list[str] = [
            sid for sid, state in self._namespaces.items()
            if not state.alive
        ]
        for sid in dead:
            state = self._namespaces.pop(sid)
            if state.cgroup is not None:
                try:
                    await state.cgroup.destroy()
                except Exception:  # noqa: BLE001
                    pass
            log.debug("Cleaned up dead namespace: %s", sid)
        return len(dead)


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

@dataclass
class _NamespaceState:
    """Internal bookkeeping for a single namespace."""

    sandbox_id: str
    host_pid: int
    process: asyncio.subprocess.Process
    cgroup: CgroupManager | None
    created_at: float
    timeout: float

    @property
    def alive(self) -> bool:
        """Return *True* if the root process is still running."""
        return self.process.returncode is None

    @property
    def elapsed(self) -> float:
        """Seconds since creation."""
        return time.monotonic() - self.created_at

    @property
    def remaining(self) -> float:
        """Seconds remaining before timeout (may be negative)."""
        return self.timeout - self.elapsed
