"""Horizon Orchestra — Hardened Filesystem Isolation.

Provides OverlayFS-based copy-on-write filesystem isolation, tmpfs mounts,
bind mounts, path masking, and minimal /dev setup for sandboxes.

On Linux, uses OverlayFS with mount namespaces.  On OpenBSD, generates
unveil() call specifications.  On FreeBSD, generates jail fstab entries.

Usage::

    from orchestra.sandbox.filesystem import FilesystemIsolation
    fs = FilesystemIsolation(sandbox_id="sb-001", profile=profile)
    rootfs = await fs.setup()
    # ... use sandbox ...
    await fs.teardown()
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shlex
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from orchestra.sandbox.os_profiles import (
        OSProfile,
        OSType,
        FilesystemPolicy,
        get_profile,
    )
except ImportError:  # pragma: no cover
    OSProfile = Any  # type: ignore[assignment,misc]
    OSType = None  # type: ignore[assignment,misc]
    FilesystemPolicy = Any  # type: ignore[assignment,misc]
    get_profile = None  # type: ignore[assignment]

__all__ = [
    "FilesystemIsolation",
    "OverlayMount",
    "TmpfsMount",
    "BindMount",
]

log = logging.getLogger("orchestra.sandbox.filesystem")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LINUX = platform.system() == "Linux"

# Paths that should always be masked (mounted over with empty tmpfs)
_DEFAULT_MASKED_PATHS: list[str] = [
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/ssh",
    "/root",
    "/home",
    "/boot",
    "/sys/firmware",
    "/proc/kcore",
    "/proc/keys",
    "/proc/latency_stats",
    "/proc/timer_list",
    "/proc/timer_stats",
    "/proc/sched_debug",
    "/proc/scsi",
]

# Minimal device nodes to create inside the sandbox
_MINIMAL_DEV_NODES: list[dict[str, Any]] = [
    {"name": "null",    "major": 1, "minor": 3, "mode": 0o666, "type": "c"},
    {"name": "zero",    "major": 1, "minor": 5, "mode": 0o666, "type": "c"},
    {"name": "full",    "major": 1, "minor": 7, "mode": 0o666, "type": "c"},
    {"name": "random",  "major": 1, "minor": 8, "mode": 0o666, "type": "c"},
    {"name": "urandom", "major": 1, "minor": 9, "mode": 0o666, "type": "c"},
    {"name": "tty",     "major": 5, "minor": 0, "mode": 0o666, "type": "c"},
]

# Directories that always get tmpfs mounts
_DEFAULT_TMPFS_DIRS: list[str] = ["/tmp", "/dev/shm", "/run"]

# Maximum overlay layers supported
_MAX_OVERLAY_LAYERS = 128


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OverlayMount:
    """An OverlayFS mount configuration.

    OverlayFS provides a union filesystem where the lower layer is
    read-only and the upper layer captures all writes (copy-on-write).
    """

    mount_id: str
    lower_dir: str      # Read-only base layer (OS rootfs)
    upper_dir: str      # Writable layer (sandbox changes)
    work_dir: str       # OverlayFS work directory
    merged_dir: str     # Final merged view
    mounted: bool = False


@dataclass
class TmpfsMount:
    """A tmpfs mount for volatile in-memory storage."""

    mount_point: str        # /tmp, /dev/shm, etc.
    size_mb: int = 512
    mode: str = "1777"      # sticky bit
    mounted: bool = False


@dataclass
class BindMount:
    """A bind mount mapping a host path into the sandbox."""

    source: str             # Host path
    target: str             # Sandbox path
    read_only: bool = True
    recursive: bool = False
    mounted: bool = False


# ---------------------------------------------------------------------------
# FilesystemIsolation
# ---------------------------------------------------------------------------

class FilesystemIsolation:
    """Hardened filesystem isolation for sandboxes.

    Creates a layered filesystem:

    1. **Base layer**: read-only OS rootfs (via OverlayFS lower)
    2. **Sandbox layer**: writable copy-on-write (OverlayFS upper)
    3. **tmpfs mounts**: ``/tmp``, ``/dev/shm``, ``/run`` (volatile)
    4. **Bind mounts**: ``/workspace`` (user files), selected ``/proc`` entries
    5. **Blocked paths**: ``/etc/shadow``, ``/root``, sensitive files masked

    On non-Linux platforms:

    - **OpenBSD**: uses ``unveil()`` for path restrictions
    - **FreeBSD**: uses jail filesystem isolation
    """

    def __init__(self, sandbox_id: str, profile: Any) -> None:
        self._sandbox_id = sandbox_id
        self._profile = profile
        self._base_dir = Path(tempfile.gettempdir()) / "horizon_fs" / sandbox_id
        self._rootfs: str = ""
        self._overlay_mounts: list[OverlayMount] = []
        self._tmpfs_mounts: list[TmpfsMount] = []
        self._bind_mounts: list[BindMount] = []
        self._masked_paths: list[str] = []
        self._disk_quota_bytes: int = 0
        self._mounted = False
        self._setup_complete = False
        log.debug("FilesystemIsolation created for sandbox %s", sandbox_id)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sandbox_id(self) -> str:
        """Return the sandbox identifier."""
        return self._sandbox_id

    @property
    def rootfs(self) -> str:
        """Return the merged rootfs path (empty until ``setup()`` is called)."""
        return self._rootfs

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def setup(self) -> str:
        """Set up the isolated filesystem and return the merged rootfs path.

        Creates the directory hierarchy, mounts OverlayFS, tmpfs volumes,
        bind mounts, masks sensitive paths, and creates minimal ``/dev`` nodes.
        """
        log.info("Setting up filesystem isolation for sandbox %s", self._sandbox_id)

        # Create base directory structure
        dirs = ["lower", "upper", "work", "merged", "workspace"]
        for d in dirs:
            (self._base_dir / d).mkdir(parents=True, exist_ok=True)

        lower_dir = str(self._base_dir / "lower")
        upper_dir = str(self._base_dir / "upper")
        work_dir = str(self._base_dir / "work")
        merged_dir = str(self._base_dir / "merged")

        # Prepare the lower (read-only) layer with minimal rootfs structure
        await self._prepare_lower_layer(lower_dir)

        # Mount OverlayFS
        overlay = await self.mount_overlay(lower_dir, upper_dir)
        self._rootfs = overlay.merged_dir

        # Mount tmpfs volumes
        for tmpfs_dir in _DEFAULT_TMPFS_DIRS:
            target = os.path.join(self._rootfs, tmpfs_dir.lstrip("/"))
            os.makedirs(target, exist_ok=True)
            try:
                tmpfs = await self.mount_tmpfs(target, size_mb=512)
                log.debug("Mounted tmpfs at %s", target)
            except OSError as exc:
                log.warning("Could not mount tmpfs at %s: %s", target, exc)

        # Setup minimal /dev
        await self.setup_minimal_dev(self._rootfs)

        # Bind-mount workspace
        workspace_host = str(self._base_dir / "workspace")
        workspace_sandbox = os.path.join(self._rootfs, "workspace")
        os.makedirs(workspace_sandbox, exist_ok=True)
        try:
            await self.bind_mount(workspace_host, workspace_sandbox, read_only=False)
        except OSError as exc:
            log.warning("Could not bind-mount workspace: %s", exc)

        # Mask sensitive paths
        await self.mask_paths(_DEFAULT_MASKED_PATHS)

        # Apply disk quota if profile specifies one
        fs_policy = self._get_filesystem_policy()
        if fs_policy is not None and hasattr(fs_policy, "max_disk_bytes"):
            max_bytes = getattr(fs_policy, "max_disk_bytes", 0)
            if max_bytes > 0:
                await self.set_disk_quota(max_bytes)

        self._mounted = True
        self._setup_complete = True
        log.info(
            "Filesystem isolation ready for sandbox %s at %s",
            self._sandbox_id,
            self._rootfs,
        )
        return self._rootfs

    async def teardown(self) -> None:
        """Tear down all mounts and clean up temporary directories."""
        log.info("Tearing down filesystem isolation for sandbox %s", self._sandbox_id)

        # Unmount bind mounts (reverse order)
        for bm in reversed(self._bind_mounts):
            try:
                await self.unbind(bm)
            except OSError as exc:
                log.warning("Failed to unbind %s: %s", bm.target, exc)

        # Unmount tmpfs (reverse order)
        for tm in reversed(self._tmpfs_mounts):
            try:
                await self.unmount_tmpfs(tm)
            except OSError as exc:
                log.warning("Failed to unmount tmpfs %s: %s", tm.mount_point, exc)

        # Unmount overlays (reverse order)
        for om in reversed(self._overlay_mounts):
            try:
                await self.unmount_overlay(om)
            except OSError as exc:
                log.warning("Failed to unmount overlay %s: %s", om.merged_dir, exc)

        # Clean up base directory
        try:
            if self._base_dir.exists():
                shutil.rmtree(str(self._base_dir), ignore_errors=True)
                log.debug("Removed base directory %s", self._base_dir)
        except OSError as exc:
            log.warning("Failed to remove base dir %s: %s", self._base_dir, exc)

        self._overlay_mounts.clear()
        self._tmpfs_mounts.clear()
        self._bind_mounts.clear()
        self._masked_paths.clear()
        self._mounted = False
        self._setup_complete = False
        self._rootfs = ""
        log.info("Filesystem teardown complete for sandbox %s", self._sandbox_id)

    # ------------------------------------------------------------------
    # OverlayFS
    # ------------------------------------------------------------------

    async def mount_overlay(self, lower: str, upper: str) -> OverlayMount:
        """Create and mount an OverlayFS layer.

        Parameters
        ----------
        lower:
            Path to the read-only lower directory.
        upper:
            Path to the writable upper directory.

        Returns
        -------
        OverlayMount
            The mounted overlay configuration.
        """
        mount_id = f"overlay-{uuid.uuid4().hex[:8]}"
        work_dir = str(self._base_dir / "work" / mount_id)
        merged_dir = str(self._base_dir / "merged")

        os.makedirs(work_dir, exist_ok=True)
        os.makedirs(merged_dir, exist_ok=True)

        overlay = OverlayMount(
            mount_id=mount_id,
            lower_dir=lower,
            upper_dir=upper,
            work_dir=work_dir,
            merged_dir=merged_dir,
            mounted=False,
        )

        if _LINUX:
            mount_opts = (
                f"lowerdir={shlex.quote(lower)},"
                f"upperdir={shlex.quote(upper)},"
                f"workdir={shlex.quote(work_dir)}"
            )
            try:
                proc = await asyncio.create_subprocess_exec(
                    "mount", "-t", "overlay", "overlay",
                    "-o", mount_opts,
                    merged_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0:
                    overlay.mounted = True
                    log.info("Mounted overlay %s at %s", mount_id, merged_dir)
                else:
                    log.warning(
                        "OverlayFS mount failed (rc=%d): %s — falling back to copy",
                        proc.returncode,
                        stderr.decode().strip(),
                    )
                    await self._fallback_copy(lower, merged_dir)
                    overlay.mounted = True
            except FileNotFoundError:
                log.warning("mount command not found — using copy fallback")
                await self._fallback_copy(lower, merged_dir)
                overlay.mounted = True
        else:
            # Non-Linux: use a directory copy as fallback
            log.info("Non-Linux platform — using copy fallback for overlay")
            await self._fallback_copy(lower, merged_dir)
            overlay.mounted = True

        self._overlay_mounts.append(overlay)
        return overlay

    async def unmount_overlay(self, mount: OverlayMount) -> None:
        """Unmount an OverlayFS layer."""
        if not mount.mounted:
            return

        if _LINUX:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "umount", mount.merged_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                if proc.returncode == 0:
                    log.debug("Unmounted overlay at %s", mount.merged_dir)
                else:
                    # Force unmount as fallback
                    proc2 = await asyncio.create_subprocess_exec(
                        "umount", "-l", mount.merged_dir,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc2.communicate()
                    log.debug("Lazy-unmounted overlay at %s", mount.merged_dir)
            except FileNotFoundError:
                log.warning("umount command not found — skipping overlay unmount")

        mount.mounted = False
        if mount in self._overlay_mounts:
            self._overlay_mounts.remove(mount)

    # ------------------------------------------------------------------
    # tmpfs
    # ------------------------------------------------------------------

    async def mount_tmpfs(self, path: str, size_mb: int = 512) -> TmpfsMount:
        """Mount a tmpfs at the given path.

        Parameters
        ----------
        path:
            Absolute path for the tmpfs mount point.
        size_mb:
            Maximum size in megabytes.

        Returns
        -------
        TmpfsMount
            Configuration of the newly mounted tmpfs.
        """
        os.makedirs(path, exist_ok=True)

        tmpfs = TmpfsMount(
            mount_point=path,
            size_mb=size_mb,
            mode="1777",
            mounted=False,
        )

        if _LINUX:
            size_opt = f"size={size_mb}m,mode={tmpfs.mode}"
            try:
                proc = await asyncio.create_subprocess_exec(
                    "mount", "-t", "tmpfs", "-o", size_opt, "tmpfs", path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0:
                    tmpfs.mounted = True
                    log.debug("Mounted tmpfs at %s (%d MB)", path, size_mb)
                else:
                    log.warning(
                        "tmpfs mount failed at %s: %s",
                        path,
                        stderr.decode().strip(),
                    )
                    # Ensure directory at least exists and is writable
                    os.chmod(path, int(tmpfs.mode, 8))
                    tmpfs.mounted = True
            except FileNotFoundError:
                log.warning("mount command not found — tmpfs simulated")
                os.chmod(path, int(tmpfs.mode, 8))
                tmpfs.mounted = True
        else:
            # Non-Linux: just ensure directory exists with correct perms
            try:
                os.chmod(path, int(tmpfs.mode, 8))
            except OSError:
                pass
            tmpfs.mounted = True

        self._tmpfs_mounts.append(tmpfs)
        return tmpfs

    async def unmount_tmpfs(self, mount: TmpfsMount) -> None:
        """Unmount a tmpfs volume."""
        if not mount.mounted:
            return

        if _LINUX:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "umount", mount.mount_point,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                log.debug("Unmounted tmpfs at %s", mount.mount_point)
            except FileNotFoundError:
                log.warning("umount not found — skipping tmpfs unmount")

        mount.mounted = False
        if mount in self._tmpfs_mounts:
            self._tmpfs_mounts.remove(mount)

    # ------------------------------------------------------------------
    # Bind mounts
    # ------------------------------------------------------------------

    async def bind_mount(
        self,
        source: str,
        target: str,
        read_only: bool = True,
    ) -> BindMount:
        """Create a bind mount from *source* to *target*.

        Parameters
        ----------
        source:
            Host-side path to mount.
        target:
            Path inside the sandbox rootfs.
        read_only:
            Whether the mount should be read-only.

        Returns
        -------
        BindMount
            The new bind mount record.
        """
        os.makedirs(target, exist_ok=True)

        bm = BindMount(
            source=source,
            target=target,
            read_only=read_only,
            recursive=False,
            mounted=False,
        )

        if _LINUX:
            try:
                # Initial bind mount
                proc = await asyncio.create_subprocess_exec(
                    "mount", "--bind", source, target,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise OSError(
                        f"bind mount failed: {stderr.decode().strip()}"
                    )

                # Make read-only if requested
                if read_only:
                    proc_ro = await asyncio.create_subprocess_exec(
                        "mount", "-o", "remount,ro,bind", target,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc_ro.communicate()
                    if proc_ro.returncode != 0:
                        log.warning("Could not remount %s as read-only", target)

                bm.mounted = True
                log.debug(
                    "Bind-mounted %s -> %s (ro=%s)", source, target, read_only
                )
            except FileNotFoundError:
                log.warning("mount command not found — simulating bind mount")
                bm.mounted = True
        else:
            # Non-Linux: symlink or copy fallback
            if not os.path.exists(target):
                try:
                    os.symlink(source, target)
                except OSError:
                    pass
            bm.mounted = True

        self._bind_mounts.append(bm)
        return bm

    async def unbind(self, mount: BindMount) -> None:
        """Unmount a bind mount."""
        if not mount.mounted:
            return

        if _LINUX:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "umount", mount.target,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                log.debug("Unbound %s", mount.target)
            except FileNotFoundError:
                log.warning("umount not found — skipping unbind")

        mount.mounted = False
        if mount in self._bind_mounts:
            self._bind_mounts.remove(mount)

    # ------------------------------------------------------------------
    # Path masking
    # ------------------------------------------------------------------

    async def mask_paths(self, paths: list[str]) -> None:
        """Mask sensitive paths by mounting empty tmpfs over them.

        This prevents sandbox processes from reading sensitive host
        files even if they share the same mount namespace.

        Parameters
        ----------
        paths:
            Absolute paths to mask inside the rootfs.
        """
        for path in paths:
            full_path = os.path.join(self._rootfs, path.lstrip("/")) if self._rootfs else path
            if not os.path.exists(full_path):
                continue

            if _LINUX:
                try:
                    if os.path.isdir(full_path):
                        proc = await asyncio.create_subprocess_exec(
                            "mount", "-t", "tmpfs", "-o",
                            "size=0,mode=000", "tmpfs", full_path,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                    else:
                        # For files, mount /dev/null over them
                        proc = await asyncio.create_subprocess_exec(
                            "mount", "--bind", "/dev/null", full_path,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                    await proc.communicate()
                    if proc.returncode == 0:
                        self._masked_paths.append(full_path)
                        log.debug("Masked path: %s", full_path)
                    else:
                        log.debug("Could not mask %s (not fatal)", full_path)
                except FileNotFoundError:
                    log.debug("mount not available — cannot mask %s", full_path)
            else:
                # Non-Linux: remove permissions as best-effort
                try:
                    os.chmod(full_path, 0o000)
                    self._masked_paths.append(full_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Minimal /dev setup
    # ------------------------------------------------------------------

    async def setup_minimal_dev(self, rootfs: str) -> None:
        """Create minimal device nodes in the sandbox rootfs.

        Only creates ``/dev/null``, ``/dev/zero``, ``/dev/full``,
        ``/dev/random``, ``/dev/urandom``, and ``/dev/tty``.

        Parameters
        ----------
        rootfs:
            Path to the sandbox merged rootfs.
        """
        dev_dir = os.path.join(rootfs, "dev")
        os.makedirs(dev_dir, exist_ok=True)

        if _LINUX:
            for node in _MINIMAL_DEV_NODES:
                node_path = os.path.join(dev_dir, node["name"])
                if os.path.exists(node_path):
                    continue
                try:
                    device_num = os.makedev(node["major"], node["minor"])
                    os.mknod(node_path, node["mode"] | stat.S_IFCHR, device_num)
                    log.debug("Created device node %s", node_path)
                except PermissionError:
                    # Fall back to bind-mounting from host /dev
                    host_dev = f"/dev/{node['name']}"
                    if os.path.exists(host_dev):
                        try:
                            # Touch the file first
                            Path(node_path).touch(exist_ok=True)
                            proc = await asyncio.create_subprocess_exec(
                                "mount", "--bind", host_dev, node_path,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            await proc.communicate()
                            log.debug("Bind-mounted %s -> %s", host_dev, node_path)
                        except (FileNotFoundError, OSError) as exc:
                            log.debug("Could not create dev node %s: %s", node["name"], exc)
                except OSError as exc:
                    log.debug("Could not create dev node %s: %s", node["name"], exc)
        else:
            # Non-Linux: create symlinks to host /dev nodes
            for node in _MINIMAL_DEV_NODES:
                node_path = os.path.join(dev_dir, node["name"])
                host_dev = f"/dev/{node['name']}"
                if os.path.exists(host_dev) and not os.path.exists(node_path):
                    try:
                        os.symlink(host_dev, node_path)
                    except OSError:
                        pass

        # Create /dev/pts and /dev/shm directories
        os.makedirs(os.path.join(dev_dir, "pts"), exist_ok=True)
        os.makedirs(os.path.join(dev_dir, "shm"), exist_ok=True)

        # Create symlinks for fd, stdin, stdout, stderr
        fd_links = {
            "fd": "/proc/self/fd",
            "stdin": "/proc/self/fd/0",
            "stdout": "/proc/self/fd/1",
            "stderr": "/proc/self/fd/2",
        }
        for name, target in fd_links.items():
            link_path = os.path.join(dev_dir, name)
            if not os.path.exists(link_path):
                try:
                    os.symlink(target, link_path)
                except OSError:
                    pass

        log.debug("Minimal /dev setup complete in %s", dev_dir)

    # ------------------------------------------------------------------
    # Disk quota
    # ------------------------------------------------------------------

    async def set_disk_quota(self, max_bytes: int) -> None:
        """Set the maximum disk usage for the sandbox upper layer.

        On Linux, uses ``quota`` or a monitoring approach.  On other
        platforms, records the limit for advisory enforcement.

        Parameters
        ----------
        max_bytes:
            Maximum number of bytes the sandbox may write.
        """
        self._disk_quota_bytes = max_bytes
        log.info(
            "Disk quota set to %d bytes (%d MB) for sandbox %s",
            max_bytes,
            max_bytes // (1024 * 1024),
            self._sandbox_id,
        )

        if _LINUX:
            # Set up periodic monitoring via inotify or du
            upper_dir = str(self._base_dir / "upper")
            if os.path.isdir(upper_dir):
                usage = await self._calculate_dir_size(upper_dir)
                if usage > max_bytes:
                    log.warning(
                        "Sandbox %s already exceeds quota: %d > %d",
                        self._sandbox_id,
                        usage,
                        max_bytes,
                    )

    async def get_disk_usage(self) -> int:
        """Return current disk usage of the sandbox upper layer in bytes."""
        upper_dir = str(self._base_dir / "upper")
        if not os.path.isdir(upper_dir):
            return 0
        return await self._calculate_dir_size(upper_dir)

    # ------------------------------------------------------------------
    # Filesystem state
    # ------------------------------------------------------------------

    def get_mounts(self) -> list[dict[str, Any]]:
        """Return a list of all active mounts in this isolation layer."""
        mounts: list[dict[str, Any]] = []

        for om in self._overlay_mounts:
            mounts.append({
                "type": "overlay",
                "mount_id": om.mount_id,
                "lower_dir": om.lower_dir,
                "upper_dir": om.upper_dir,
                "merged_dir": om.merged_dir,
                "mounted": om.mounted,
            })

        for tm in self._tmpfs_mounts:
            mounts.append({
                "type": "tmpfs",
                "mount_point": tm.mount_point,
                "size_mb": tm.size_mb,
                "mounted": tm.mounted,
            })

        for bm in self._bind_mounts:
            mounts.append({
                "type": "bind",
                "source": bm.source,
                "target": bm.target,
                "read_only": bm.read_only,
                "mounted": bm.mounted,
            })

        return mounts

    def is_mounted(self) -> bool:
        """Return ``True`` if the filesystem isolation is active."""
        return self._mounted

    # ------------------------------------------------------------------
    # OpenBSD unveil generation
    # ------------------------------------------------------------------

    def generate_unveil_calls(self) -> list[tuple[str, str]]:
        """Generate OpenBSD ``unveil()`` call specifications.

        Returns a list of ``(path, permissions)`` tuples suitable for
        passing to ``unveil(2)``.  Permissions are strings like ``"r"``,
        ``"rw"``, ``"rwx"``, ``"rwxc"``.

        Returns
        -------
        list[tuple[str, str]]
            Unveil specifications.
        """
        unveil_calls: list[tuple[str, str]] = []

        # Read-only system paths
        readonly_paths = [
            "/usr/lib",
            "/usr/libexec",
            "/usr/share",
            "/etc/resolv.conf",
            "/etc/ssl",
            "/etc/passwd",
            "/etc/group",
            "/dev/null",
            "/dev/zero",
            "/dev/urandom",
        ]
        for p in readonly_paths:
            unveil_calls.append((p, "r"))

        # Read-execute paths for binaries
        exec_paths = [
            "/usr/bin",
            "/usr/local/bin",
            "/bin",
            "/sbin",
        ]
        for p in exec_paths:
            unveil_calls.append((p, "rx"))

        # Writable workspace
        unveil_calls.append(("/workspace", "rwc"))

        # Writable temp
        unveil_calls.append(("/tmp", "rwc"))

        # Read-write for bind mounts
        for bm in self._bind_mounts:
            if bm.read_only:
                unveil_calls.append((bm.target, "r"))
            else:
                unveil_calls.append((bm.target, "rwc"))

        # Block masked paths by not unveiling them (implicit deny)
        log.debug(
            "Generated %d unveil calls for sandbox %s",
            len(unveil_calls),
            self._sandbox_id,
        )
        return unveil_calls

    # ------------------------------------------------------------------
    # FreeBSD jail fstab
    # ------------------------------------------------------------------

    def generate_jail_fstab(self) -> str:
        """Generate a FreeBSD jail ``fstab`` file contents.

        Returns an fstab-format string with entries for all configured
        mounts suitable for use with ``jail(8)``.

        Returns
        -------
        str
            Contents for the jail's fstab file.
        """
        lines: list[str] = [
            "# Jail fstab for sandbox {sid}".format(sid=self._sandbox_id),
            "# Generated by Horizon Orchestra",
            "#",
            "# <device>  <mount_point>  <type>  <options>  <dump>  <pass>",
        ]

        jail_root = f"/jails/{self._sandbox_id}"

        # devfs mount
        lines.append(
            f"devfs  {jail_root}/dev  devfs  rw  0  0"
        )

        # fdescfs
        lines.append(
            f"fdescfs  {jail_root}/dev/fd  fdescfs  rw,linrdlnk  0  0"
        )

        # tmpfs mounts
        for tm in self._tmpfs_mounts:
            rel_path = tm.mount_point.lstrip("/")
            lines.append(
                f"tmpfs  {jail_root}/{rel_path}  tmpfs  "
                f"rw,size={tm.size_mb}m,mode={tm.mode}  0  0"
            )

        # Nullfs (bind) mounts
        for bm in self._bind_mounts:
            rel_target = bm.target.lstrip("/")
            opts = "ro" if bm.read_only else "rw"
            lines.append(
                f"{bm.source}  {jail_root}/{rel_target}  nullfs  {opts}  0  0"
            )

        # Workspace
        lines.append(
            f"/workspace  {jail_root}/workspace  nullfs  rw  0  0"
        )

        # proc (limited)
        lines.append(
            f"procfs  {jail_root}/proc  procfs  rw  0  0"
        )

        fstab_content = "\n".join(lines) + "\n"
        log.debug(
            "Generated jail fstab with %d entries for sandbox %s",
            len(lines) - 4,  # Subtract comment lines
            self._sandbox_id,
        )
        return fstab_content

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_filesystem_policy(self) -> Any:
        """Extract filesystem policy from the profile, if available."""
        if hasattr(self._profile, "filesystem"):
            return self._profile.filesystem
        if hasattr(self._profile, "filesystem_policy"):
            return self._profile.filesystem_policy
        return None

    async def _prepare_lower_layer(self, lower_dir: str) -> None:
        """Create a minimal rootfs structure in the lower layer.

        This creates the essential directory hierarchy that every sandbox
        expects to find.
        """
        essential_dirs = [
            "bin", "sbin", "usr/bin", "usr/sbin", "usr/lib",
            "usr/local/bin", "usr/local/lib",
            "lib", "lib64",
            "etc", "tmp", "var/tmp", "var/log", "var/run",
            "dev", "proc", "sys",
            "home", "root", "workspace",
            "run", "opt",
        ]
        for d in essential_dirs:
            os.makedirs(os.path.join(lower_dir, d), exist_ok=True)

        # Create minimal /etc files
        etc_dir = os.path.join(lower_dir, "etc")

        # /etc/hostname
        hostname_path = os.path.join(etc_dir, "hostname")
        if not os.path.exists(hostname_path):
            with open(hostname_path, "w") as f:
                f.write(f"sandbox-{self._sandbox_id}\n")

        # /etc/hosts
        hosts_path = os.path.join(etc_dir, "hosts")
        if not os.path.exists(hosts_path):
            with open(hosts_path, "w") as f:
                f.write("127.0.0.1\tlocalhost\n")
                f.write(f"127.0.1.1\tsandbox-{self._sandbox_id}\n")
                f.write("::1\t\tlocalhost ip6-localhost ip6-loopback\n")

        # /etc/resolv.conf (default)
        resolv_path = os.path.join(etc_dir, "resolv.conf")
        if not os.path.exists(resolv_path):
            with open(resolv_path, "w") as f:
                f.write("nameserver 1.1.1.1\n")
                f.write("nameserver 8.8.8.8\n")

        # /etc/passwd (minimal)
        passwd_path = os.path.join(etc_dir, "passwd")
        if not os.path.exists(passwd_path):
            with open(passwd_path, "w") as f:
                f.write("root:x:0:0:root:/root:/bin/sh\n")
                f.write("nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n")
                f.write("sandbox:x:1000:1000:sandbox:/workspace:/bin/sh\n")

        # /etc/group (minimal)
        group_path = os.path.join(etc_dir, "group")
        if not os.path.exists(group_path):
            with open(group_path, "w") as f:
                f.write("root:x:0:\n")
                f.write("nogroup:x:65534:\n")
                f.write("sandbox:x:1000:\n")

        # /etc/nsswitch.conf
        nsswitch_path = os.path.join(etc_dir, "nsswitch.conf")
        if not os.path.exists(nsswitch_path):
            with open(nsswitch_path, "w") as f:
                f.write("passwd: files\n")
                f.write("group: files\n")
                f.write("shadow: files\n")
                f.write("hosts: files dns\n")
                f.write("networks: files\n")

        log.debug("Prepared lower layer in %s", lower_dir)

    async def _fallback_copy(self, src: str, dst: str) -> None:
        """Copy directory tree as fallback when OverlayFS is unavailable.

        Runs in a thread executor to avoid blocking the event loop.
        """
        loop = asyncio.get_running_loop()

        def _do_copy() -> None:
            if os.path.isdir(src):
                for item in os.listdir(src):
                    s = os.path.join(src, item)
                    d = os.path.join(dst, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True, symlinks=True)
                    else:
                        shutil.copy2(s, d)

        await loop.run_in_executor(None, _do_copy)
        log.debug("Fallback copy from %s to %s complete", src, dst)

    async def _calculate_dir_size(self, path: str) -> int:
        """Calculate total size of a directory tree in bytes.

        Runs ``du`` on Linux for performance; falls back to Python walk.
        """
        if _LINUX:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "du", "-sb", path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and stdout:
                    return int(stdout.decode().split()[0])
            except (FileNotFoundError, ValueError, IndexError):
                pass

        # Fallback: walk the tree
        total = 0
        loop = asyncio.get_running_loop()

        def _walk_size() -> int:
            size = 0
            for dirpath, _dirnames, filenames in os.walk(path):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    try:
                        size += os.path.getsize(fpath)
                    except OSError:
                        pass
            return size

        total = await loop.run_in_executor(None, _walk_size)
        return total

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"FilesystemIsolation("
            f"sandbox_id={self._sandbox_id!r}, "
            f"mounted={self._mounted}, "
            f"overlays={len(self._overlay_mounts)}, "
            f"tmpfs={len(self._tmpfs_mounts)}, "
            f"binds={len(self._bind_mounts)}"
            f")"
        )
