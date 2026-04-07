"""Horizon Orchestra — OS Sandbox Profiles.

Pre-built, production-grade sandbox profiles for each supported operating
system.  Each profile defines the syscall whitelist, package manager,
filesystem layout, security primitives, and resource defaults for that OS.

Supported targets:
    * Debian 11 (Bullseye)  — 59,913 packages, apparmor + seccomp
    * Fedora 37             — 66,166 packages, SELinux + seccomp
    * OpenBSD 7.3           — 7,787  packages, pledge/unveil
    * FreeBSD 13.2          — 30,766 packages, capsicum/jails

Usage::

    from orchestra.sandbox.os_profiles import get_profile, list_profiles

    profile = get_profile("debian-11")
    for p in list_profiles():
        print(p.name, p.available_package_count)
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

__all__ = [
    "OSType",
    "PackageManager",
    "SyscallPolicy",
    "FilesystemPolicy",
    "NetworkPolicy",
    "ResourceLimits",
    "OSProfile",
    "PROFILES",
    "get_profile",
    "list_profiles",
    "detect_host_os",
]

log = logging.getLogger("orchestra.sandbox.os_profiles")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class OSType(str, Enum):
    """Supported operating-system targets for sandboxed execution."""

    DEBIAN_11 = "debian-11"
    FEDORA_37 = "fedora-37"
    OPENBSD_73 = "openbsd-7.3"
    FREEBSD_132 = "freebsd-13.2"
    UBUNTU_2404 = "ubuntu-24.04"

    # ------------------------------------------------------------------
    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_string(cls, raw: str) -> OSType:
        """Resolve a human-readable string to an ``OSType`` member.

        Accepts the canonical value (``"debian-11"``) as well as common
        aliases like ``"debian"``, ``"fedora"``, etc.
        """
        normalised = raw.strip().lower()
        # Try direct match first
        for member in cls:
            if normalised == member.value:
                return member
        # Fuzzy / alias matching
        _aliases: dict[str, OSType] = {
            "debian": cls.DEBIAN_11,
            "bullseye": cls.DEBIAN_11,
            "debian11": cls.DEBIAN_11,
            "fedora": cls.FEDORA_37,
            "fedora37": cls.FEDORA_37,
            "openbsd": cls.OPENBSD_73,
            "openbsd73": cls.OPENBSD_73,
            "freebsd": cls.FREEBSD_132,
            "freebsd13": cls.FREEBSD_132,
            "freebsd132": cls.FREEBSD_132,
            "ubuntu": cls.UBUNTU_2404,
            "ubuntu2404": cls.UBUNTU_2404,
        }
        if normalised in _aliases:
            return _aliases[normalised]
        raise ValueError(
            f"Unknown OS type {raw!r}. "
            f"Supported: {[m.value for m in cls]}"
        )


# ---------------------------------------------------------------------------
# Data-classes — policy & configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PackageManager:
    """Package manager metadata for a sandboxed OS environment."""

    name: str                    # "apt" | "dnf" | "pkg_add" | "pkg"
    install_cmd: str             # "apt-get install -y"
    update_cmd: str              # "apt-get update"
    search_cmd: str              # "apt-cache search"
    list_installed_cmd: str      # "dpkg -l"
    package_count: int           # Total available packages
    cache_dir: str               # "/var/cache/apt"
    config_dir: str              # "/etc/apt"

    def install_packages(self, packages: list[str]) -> str:
        """Return a shell command that installs *packages*."""
        pkg_list = " ".join(packages)
        return f"{self.install_cmd} {pkg_list}"

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dictionary."""
        return {
            "name": self.name,
            "install_cmd": self.install_cmd,
            "update_cmd": self.update_cmd,
            "search_cmd": self.search_cmd,
            "list_installed_cmd": self.list_installed_cmd,
            "package_count": self.package_count,
            "cache_dir": self.cache_dir,
            "config_dir": self.config_dir,
        }


@dataclass
class SyscallPolicy:
    """Syscall allow/deny policy for seccomp-bpf (or OS-native equivalent)."""

    allowed_syscalls: list[str] = field(default_factory=list)
    blocked_syscalls: list[str] = field(default_factory=list)
    log_only_syscalls: list[str] = field(default_factory=list)
    default_action: str = "kill"        # "kill" | "errno" | "log" | "allow"
    architecture: str = "x86_64"

    # -- convenience helpers ------------------------------------------------

    def is_allowed(self, syscall: str) -> bool:
        """Return *True* if *syscall* is explicitly white-listed."""
        return syscall in self.allowed_syscalls

    def is_blocked(self, syscall: str) -> bool:
        """Return *True* if *syscall* is explicitly blocked."""
        return syscall in self.blocked_syscalls

    def merge(self, other: SyscallPolicy) -> SyscallPolicy:
        """Return a new policy that is the union of *self* and *other*."""
        return SyscallPolicy(
            allowed_syscalls=sorted(
                set(self.allowed_syscalls) | set(other.allowed_syscalls)
            ),
            blocked_syscalls=sorted(
                set(self.blocked_syscalls) | set(other.blocked_syscalls)
            ),
            log_only_syscalls=sorted(
                set(self.log_only_syscalls) | set(other.log_only_syscalls)
            ),
            default_action=self.default_action,
            architecture=self.architecture,
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dictionary."""
        return {
            "allowed": self.allowed_syscalls,
            "blocked": self.blocked_syscalls,
            "log_only": self.log_only_syscalls,
            "default_action": self.default_action,
            "architecture": self.architecture,
        }


@dataclass
class FilesystemPolicy:
    """Filesystem restrictions for the sandbox environment."""

    writable_paths: list[str] = field(
        default_factory=lambda: ["/workspace", "/tmp"]
    )
    readable_paths: list[str] = field(
        default_factory=lambda: ["/usr", "/lib", "/lib64", "/etc", "/bin", "/sbin"]
    )
    hidden_paths: list[str] = field(
        default_factory=lambda: [
            "/proc/kcore",
            "/proc/sysrq-trigger",
            "/proc/acpi",
            "/sys/firmware",
        ]
    )
    blocked_paths: list[str] = field(
        default_factory=lambda: [
            "/etc/shadow",
            "/etc/gshadow",
            "/root",
            "/home",
            "/boot",
        ]
    )
    max_file_size_mb: int = 100
    max_total_disk_mb: int = 5120
    tmpfs_size_mb: int = 512
    overlay_enabled: bool = True
    read_only_rootfs: bool = True

    def is_path_allowed(self, path: str, mode: str = "r") -> bool:
        """Check whether *path* is accessible under the given *mode*.

        Parameters
        ----------
        path:
            Absolute filesystem path to check.
        mode:
            ``"r"`` for read, ``"w"`` for write.
        """
        # Blocked paths take precedence
        for blocked in self.blocked_paths:
            if path == blocked or path.startswith(blocked + "/"):
                return False
        # Hidden paths
        for hidden in self.hidden_paths:
            if path == hidden or path.startswith(hidden + "/"):
                return False
        if mode == "w":
            for writable in self.writable_paths:
                if path == writable or path.startswith(writable + "/"):
                    return True
            return False
        # mode == "r"
        for readable in self.readable_paths + self.writable_paths:
            if path == readable or path.startswith(readable + "/"):
                return True
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "writable_paths": self.writable_paths,
            "readable_paths": self.readable_paths,
            "hidden_paths": self.hidden_paths,
            "blocked_paths": self.blocked_paths,
            "max_file_size_mb": self.max_file_size_mb,
            "max_total_disk_mb": self.max_total_disk_mb,
            "tmpfs_size_mb": self.tmpfs_size_mb,
            "overlay_enabled": self.overlay_enabled,
            "read_only_rootfs": self.read_only_rootfs,
        }


@dataclass
class NetworkPolicy:
    """Network restrictions for the sandbox environment."""

    enabled: bool = True
    allowed_outbound_ports: list[int] = field(
        default_factory=lambda: [80, 443, 53]
    )
    blocked_outbound_ports: list[int] = field(
        default_factory=lambda: [22, 25, 445]
    )
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(
        default_factory=lambda: [
            "metadata.google.internal",
            "169.254.169.254",
        ]
    )
    max_bandwidth_mbps: float = 50.0
    dns_servers: list[str] = field(
        default_factory=lambda: ["1.1.1.1", "8.8.8.8"]
    )
    enable_ipv6: bool = False

    def is_port_allowed(self, port: int) -> bool:
        """Return *True* if outbound traffic on *port* is permitted."""
        if port in self.blocked_outbound_ports:
            return False
        if self.allowed_outbound_ports:
            return port in self.allowed_outbound_ports
        return True

    def is_domain_allowed(self, domain: str) -> bool:
        """Return *True* if *domain* is not blocked."""
        if domain in self.blocked_domains:
            return False
        if self.allowed_domains:
            return domain in self.allowed_domains
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "allowed_outbound_ports": self.allowed_outbound_ports,
            "blocked_outbound_ports": self.blocked_outbound_ports,
            "allowed_domains": self.allowed_domains,
            "blocked_domains": self.blocked_domains,
            "max_bandwidth_mbps": self.max_bandwidth_mbps,
            "dns_servers": self.dns_servers,
            "enable_ipv6": self.enable_ipv6,
        }


@dataclass
class ResourceLimits:
    """cgroup v2 / OS-native resource limits for a sandbox."""

    max_memory_bytes: int = 2 * 1024**3          # 2 GiB
    max_memory_swap_bytes: int = 0                # No swap
    max_cpu_shares: int = 1024                    # cgroup cpu.weight
    max_cpu_quota_us: int = 200_000               # 200 ms per 100 ms period → 2 cores
    max_pids: int = 256
    max_open_files: int = 1024
    max_processes: int = 64
    max_threads: int = 128
    max_file_locks: int = 64
    oom_score_adj: int = 1000                     # first to die on OOM

    # -- helpers ------------------------------------------------------------

    @property
    def max_memory_mb(self) -> int:
        """Memory limit expressed in MiB (rounded)."""
        return self.max_memory_bytes // (1024 * 1024)

    def scale(self, factor: float) -> ResourceLimits:
        """Return a new ``ResourceLimits`` scaled by *factor*."""
        return ResourceLimits(
            max_memory_bytes=int(self.max_memory_bytes * factor),
            max_memory_swap_bytes=int(self.max_memory_swap_bytes * factor),
            max_cpu_shares=self.max_cpu_shares,
            max_cpu_quota_us=int(self.max_cpu_quota_us * factor),
            max_pids=max(16, int(self.max_pids * factor)),
            max_open_files=max(64, int(self.max_open_files * factor)),
            max_processes=max(8, int(self.max_processes * factor)),
            max_threads=max(16, int(self.max_threads * factor)),
            max_file_locks=max(8, int(self.max_file_locks * factor)),
            oom_score_adj=self.oom_score_adj,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_memory_bytes": self.max_memory_bytes,
            "max_memory_swap_bytes": self.max_memory_swap_bytes,
            "max_cpu_shares": self.max_cpu_shares,
            "max_cpu_quota_us": self.max_cpu_quota_us,
            "max_pids": self.max_pids,
            "max_open_files": self.max_open_files,
            "max_processes": self.max_processes,
            "max_threads": self.max_threads,
            "max_file_locks": self.max_file_locks,
            "oom_score_adj": self.oom_score_adj,
        }


# ---------------------------------------------------------------------------
# Core profile class
# ---------------------------------------------------------------------------

@dataclass
class OSProfile:
    """Complete sandbox profile for a specific OS target.

    Bundles every isolation dimension — syscall filtering, filesystem
    restrictions, network policy, resource limits, and OS-specific security
    primitives — into a single reusable configuration object.
    """

    os_type: OSType
    name: str                          # "Debian 11 (Bullseye)"
    base_image: str                    # "debian:bullseye-slim"
    package_manager: PackageManager
    syscall_policy: SyscallPolicy
    filesystem_policy: FilesystemPolicy
    network_policy: NetworkPolicy
    resource_limits: ResourceLimits

    # OS-specific security primitives
    native_sandbox: str                # "none" | "pledge" | "capsicum" | "apparmor" | "selinux"
    init_commands: list[str] = field(default_factory=list)
    cleanup_commands: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)

    # Package ecosystem
    default_packages: list[str] = field(default_factory=list)
    available_package_count: int = 0

    # Supported language interpreters
    interpreters: dict[str, str] = field(default_factory=dict)

    # -- helpers ------------------------------------------------------------

    def summary(self) -> str:
        """One-line summary of the profile."""
        return (
            f"{self.name}: {self.available_package_count:,} pkgs, "
            f"sandbox={self.native_sandbox}, "
            f"image={self.base_image}"
        )

    def validate(self) -> list[str]:
        """Return a list of configuration warnings (empty if OK)."""
        warnings: list[str] = []
        if not self.syscall_policy.allowed_syscalls:
            warnings.append(f"[{self.name}] No allowed syscalls defined")
        if not self.default_packages:
            warnings.append(f"[{self.name}] No default packages defined")
        if not self.interpreters:
            warnings.append(f"[{self.name}] No interpreters defined")
        if self.resource_limits.max_memory_bytes < 128 * 1024 * 1024:
            warnings.append(f"[{self.name}] Memory limit < 128 MiB — very low")
        return warnings

    def as_dict(self) -> dict[str, Any]:
        """Full JSON-serialisable representation of the profile."""
        return {
            "os_type": self.os_type.value,
            "name": self.name,
            "base_image": self.base_image,
            "package_manager": self.package_manager.as_dict(),
            "syscall_policy": self.syscall_policy.as_dict(),
            "filesystem_policy": self.filesystem_policy.as_dict(),
            "network_policy": self.network_policy.as_dict(),
            "resource_limits": self.resource_limits.as_dict(),
            "native_sandbox": self.native_sandbox,
            "init_commands": self.init_commands,
            "cleanup_commands": self.cleanup_commands,
            "env_vars": self.env_vars,
            "default_packages": self.default_packages,
            "available_package_count": self.available_package_count,
            "interpreters": self.interpreters,
        }


# ---------------------------------------------------------------------------
# Shared syscall lists (used by multiple profiles)
# ---------------------------------------------------------------------------

_LINUX_SAFE_SYSCALLS: list[str] = [
    # -- File I/O --
    "read", "write", "open", "close", "stat", "fstat", "lstat",
    "poll", "lseek", "mmap", "mprotect", "munmap", "brk",
    "ioctl", "access", "pipe", "select", "sched_yield",
    "mremap", "msync", "mincore", "madvise", "dup", "dup2", "dup3",
    "nanosleep", "getitimer", "alarm", "setitimer",
    "getpid", "sendfile", "socket", "connect", "accept",
    "sendto", "recvfrom", "sendmsg", "recvmsg", "shutdown",
    "bind", "listen", "getsockname", "getpeername",
    "socketpair", "setsockopt", "getsockopt",
    "clone", "fork", "vfork", "execve",
    "exit", "wait4", "kill", "uname",
    "fcntl", "flock", "fsync", "fdatasync", "truncate", "ftruncate",
    "getdents", "getcwd", "chdir", "fchdir",
    "rename", "mkdir", "rmdir", "creat", "link", "unlink",
    "symlink", "readlink", "chmod", "fchmod", "chown", "fchown",
    "lchown", "umask", "gettimeofday", "getrlimit", "getrusage",
    "sysinfo", "times", "getuid", "getgid", "setuid", "setgid",
    "geteuid", "getegid", "setpgid", "getppid", "getpgrp",
    "setsid", "setreuid", "setregid", "getgroups", "setgroups",
    "setresuid", "getresuid", "setresgid", "getresgid",
    "getpgid", "setfsuid", "setfsgid", "getsid", "capget",
    "rt_sigaction", "rt_sigprocmask", "rt_sigreturn",
    "rt_sigpending", "rt_sigtimedwait", "rt_sigqueueinfo",
    "rt_sigsuspend", "sigaltstack",
    "pread64", "pwrite64", "readv", "writev",
    "preadv", "pwritev", "preadv2", "pwritev2",
    # -- Memory --
    "mlock", "munlock", "mlockall", "munlockall",
    # -- Scheduling --
    "sched_setparam", "sched_getparam", "sched_setscheduler",
    "sched_getscheduler", "sched_get_priority_max",
    "sched_get_priority_min", "sched_rr_get_interval",
    "sched_setaffinity", "sched_getaffinity",
    # -- Timer --
    "timer_create", "timer_settime", "timer_gettime",
    "timer_getoverrun", "timer_delete",
    "clock_gettime", "clock_getres", "clock_nanosleep",
    # -- epoll / eventfd / signalfd --
    "epoll_create", "epoll_create1", "epoll_ctl", "epoll_wait",
    "epoll_pwait", "epoll_pwait2",
    "eventfd", "eventfd2",
    "signalfd", "signalfd4",
    "timerfd_create", "timerfd_settime", "timerfd_gettime",
    # -- File-descriptor --
    "openat", "mkdirat", "mknodat", "fchownat",
    "newfstatat", "unlinkat", "renameat", "renameat2",
    "linkat", "symlinkat", "readlinkat", "fchmodat",
    "faccessat", "faccessat2",
    # -- Misc --
    "set_tid_address", "set_robust_list", "get_robust_list",
    "futex", "arch_prctl", "prctl",
    "getdents64", "statfs", "fstatfs",
    "exit_group", "tgkill", "tkill",
    "pipe2", "inotify_init", "inotify_init1",
    "inotify_add_watch", "inotify_rm_watch",
    "ppoll", "pselect6",
    "accept4", "recvmmsg", "sendmmsg",
    "getrandom", "memfd_create", "statx",
    "copy_file_range", "splice", "tee", "vmsplice",
    "close_range", "openat2", "pidfd_open",
    "clone3", "rseq",
    "io_uring_setup", "io_uring_enter", "io_uring_register",
    "fadvise64", "readahead",
    "setns", "unshare",
    "seccomp", "membarrier",
    "mlock2",
    "pkey_mprotect", "pkey_alloc", "pkey_free",
    "landlock_create_ruleset", "landlock_add_rule",
    "landlock_restrict_self",
]

_LINUX_DANGEROUS_SYSCALLS: list[str] = [
    "mount", "umount2", "pivot_root",
    "reboot", "kexec_load", "kexec_file_load",
    "init_module", "finit_module", "delete_module",
    "swapon", "swapoff",
    "acct",
    "settimeofday", "adjtimex", "clock_adjtime",
    "nfsservctl",
    "quotactl",
    "ioperm", "iopl",
    "modify_ldt",
    "create_module", "query_module", "get_kernel_syms",
    "syslog",
    "personality",
    "uselib",
    "bpf",
    "userfaultfd",
    "perf_event_open",
    "ptrace",
    "process_vm_readv", "process_vm_writev",
    "kcmp",
    "lookup_dcookie",
    "open_by_handle_at", "name_to_handle_at",
    "add_key", "request_key", "keyctl",
    "move_pages", "migrate_pages",
    "mbind", "set_mempolicy", "get_mempolicy",
]

_OPENBSD_PLEDGE_PROMISES: str = "stdio rpath wpath cpath proc exec inet dns tmppath"

_OPENBSD_UNVEIL_RULES: list[tuple[str, str]] = [
    ("/workspace", "rwc"),
    ("/tmp", "rwc"),
    ("/usr", "r"),
    ("/usr/lib", "r"),
    ("/usr/local", "r"),
    ("/etc/resolv.conf", "r"),
    ("/dev/null", "rw"),
    ("/dev/urandom", "r"),
]

_FREEBSD_CAPSICUM_RIGHTS: list[str] = [
    "CAP_READ",
    "CAP_WRITE",
    "CAP_SEEK",
    "CAP_FSTAT",
    "CAP_MMAP",
    "CAP_MMAP_R",
    "CAP_MMAP_W",
    "CAP_MMAP_X",
    "CAP_MMAP_RW",
    "CAP_MMAP_RX",
    "CAP_MMAP_WX",
    "CAP_MMAP_RWX",
    "CAP_FCNTL",
    "CAP_EVENT",
    "CAP_FTRUNCATE",
    "CAP_LOOKUP",
    "CAP_CREATE",
    "CAP_UNLINKAT",
    "CAP_MKDIRAT",
    "CAP_RENAMEAT_SOURCE",
    "CAP_RENAMEAT_TARGET",
    "CAP_SOCK_CLIENT",
    "CAP_SOCK_SERVER",
    "CAP_CONNECT",
    "CAP_ACCEPT",
    "CAP_BIND",
    "CAP_LISTEN",
    "CAP_GETPEERNAME",
    "CAP_GETSOCKNAME",
    "CAP_SETSOCKOPT",
    "CAP_GETSOCKOPT",
]


# ---------------------------------------------------------------------------
# Pre-built profiles
# ---------------------------------------------------------------------------

DEBIAN_11_PROFILE = OSProfile(
    os_type=OSType.DEBIAN_11,
    name="Debian 11 (Bullseye)",
    base_image="debian:bullseye-slim",
    package_manager=PackageManager(
        name="apt",
        install_cmd="apt-get install -y",
        update_cmd="apt-get update",
        search_cmd="apt-cache search",
        list_installed_cmd="dpkg -l",
        package_count=59_913,
        cache_dir="/var/cache/apt",
        config_dir="/etc/apt",
    ),
    syscall_policy=SyscallPolicy(
        allowed_syscalls=list(_LINUX_SAFE_SYSCALLS),
        blocked_syscalls=list(_LINUX_DANGEROUS_SYSCALLS),
        log_only_syscalls=[
            "personality", "ptrace", "process_vm_readv",
        ],
        default_action="kill",
        architecture="x86_64",
    ),
    filesystem_policy=FilesystemPolicy(
        writable_paths=["/workspace", "/tmp", "/var/tmp"],
        readable_paths=[
            "/usr", "/lib", "/lib64", "/etc", "/bin", "/sbin",
            "/opt", "/var/lib/dpkg",
        ],
        hidden_paths=[
            "/proc/kcore", "/proc/sysrq-trigger",
            "/proc/acpi", "/sys/firmware",
            "/proc/keys", "/proc/timer_list",
        ],
        blocked_paths=[
            "/etc/shadow", "/etc/gshadow", "/root", "/home", "/boot",
            "/var/log/auth.log", "/var/run/secrets",
        ],
        max_file_size_mb=100,
        max_total_disk_mb=5120,
        tmpfs_size_mb=512,
        overlay_enabled=True,
        read_only_rootfs=True,
    ),
    network_policy=NetworkPolicy(
        enabled=True,
        allowed_outbound_ports=[80, 443, 53],
        blocked_outbound_ports=[22, 25, 445, 3306, 5432, 6379],
        allowed_domains=[],
        blocked_domains=[
            "metadata.google.internal", "169.254.169.254",
            "metadata.internal",
        ],
        max_bandwidth_mbps=50.0,
        dns_servers=["1.1.1.1", "8.8.8.8"],
        enable_ipv6=False,
    ),
    resource_limits=ResourceLimits(
        max_memory_bytes=2 * 1024**3,
        max_memory_swap_bytes=0,
        max_cpu_shares=1024,
        max_cpu_quota_us=200_000,
        max_pids=256,
        max_open_files=1024,
        max_processes=64,
        max_threads=128,
        max_file_locks=64,
        oom_score_adj=1000,
    ),
    native_sandbox="apparmor",
    init_commands=[
        "apt-get update -qq",
        "apt-get install -y --no-install-recommends python3 python3-pip nodejs curl git build-essential ca-certificates",
        "rm -rf /var/lib/apt/lists/*",
        "useradd -m -s /bin/bash sandbox",
        "mkdir -p /workspace && chown sandbox:sandbox /workspace",
    ],
    cleanup_commands=[
        "rm -rf /tmp/* /var/tmp/*",
        "apt-get clean",
    ],
    env_vars={
        "DEBIAN_FRONTEND": "noninteractive",
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/workspace",
        "SANDBOX": "1",
        "TERM": "xterm-256color",
    },
    default_packages=[
        "python3", "python3-pip", "python3-venv",
        "nodejs", "curl", "wget", "git",
        "build-essential", "ca-certificates",
        "jq", "file", "unzip",
    ],
    available_package_count=59_913,
    interpreters={
        "python": "/usr/bin/python3",
        "node": "/usr/bin/node",
        "bash": "/bin/bash",
        "sh": "/bin/sh",
    },
)


FEDORA_37_PROFILE = OSProfile(
    os_type=OSType.FEDORA_37,
    name="Fedora 37",
    base_image="fedora:37",
    package_manager=PackageManager(
        name="dnf",
        install_cmd="dnf install -y",
        update_cmd="dnf check-update",
        search_cmd="dnf search",
        list_installed_cmd="rpm -qa",
        package_count=66_166,
        cache_dir="/var/cache/dnf",
        config_dir="/etc/dnf",
    ),
    syscall_policy=SyscallPolicy(
        allowed_syscalls=list(_LINUX_SAFE_SYSCALLS) + [
            # SELinux-compat extras
            "getxattr", "lgetxattr", "fgetxattr",
            "setxattr", "lsetxattr", "fsetxattr",
            "listxattr", "llistxattr", "flistxattr",
            "removexattr", "lremovexattr", "fremovexattr",
        ],
        blocked_syscalls=list(_LINUX_DANGEROUS_SYSCALLS),
        log_only_syscalls=[
            "personality", "ptrace",
        ],
        default_action="kill",
        architecture="x86_64",
    ),
    filesystem_policy=FilesystemPolicy(
        writable_paths=["/workspace", "/tmp", "/var/tmp"],
        readable_paths=[
            "/usr", "/lib", "/lib64", "/etc", "/bin", "/sbin",
            "/opt", "/var/lib/rpm", "/var/lib/dnf",
        ],
        hidden_paths=[
            "/proc/kcore", "/proc/sysrq-trigger",
            "/proc/acpi", "/sys/firmware",
            "/proc/keys", "/proc/timer_list",
        ],
        blocked_paths=[
            "/etc/shadow", "/etc/gshadow", "/root", "/home", "/boot",
            "/var/log/audit", "/var/run/secrets",
        ],
        max_file_size_mb=100,
        max_total_disk_mb=5120,
        tmpfs_size_mb=512,
        overlay_enabled=True,
        read_only_rootfs=True,
    ),
    network_policy=NetworkPolicy(
        enabled=True,
        allowed_outbound_ports=[80, 443, 53],
        blocked_outbound_ports=[22, 25, 445, 3306, 5432, 6379],
        allowed_domains=[],
        blocked_domains=[
            "metadata.google.internal", "169.254.169.254",
            "metadata.internal",
        ],
        max_bandwidth_mbps=50.0,
        dns_servers=["1.1.1.1", "8.8.8.8"],
        enable_ipv6=False,
    ),
    resource_limits=ResourceLimits(
        max_memory_bytes=2 * 1024**3,
        max_memory_swap_bytes=0,
        max_cpu_shares=1024,
        max_cpu_quota_us=200_000,
        max_pids=256,
        max_open_files=1024,
        max_processes=64,
        max_threads=128,
        max_file_locks=64,
        oom_score_adj=1000,
    ),
    native_sandbox="selinux",
    init_commands=[
        "dnf install -y python3 python3-pip nodejs curl git gcc make ca-certificates",
        "dnf clean all",
        "useradd -m -s /bin/bash sandbox",
        "mkdir -p /workspace && chown sandbox:sandbox /workspace",
    ],
    cleanup_commands=[
        "rm -rf /tmp/* /var/tmp/*",
        "dnf clean all",
    ],
    env_vars={
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/workspace",
        "SANDBOX": "1",
        "TERM": "xterm-256color",
    },
    default_packages=[
        "python3", "python3-pip",
        "nodejs", "curl", "wget", "git",
        "gcc", "make", "ca-certificates",
        "jq", "file", "unzip",
    ],
    available_package_count=66_166,
    interpreters={
        "python": "/usr/bin/python3",
        "node": "/usr/bin/node",
        "bash": "/bin/bash",
        "sh": "/bin/sh",
    },
)


OPENBSD_73_PROFILE = OSProfile(
    os_type=OSType.OPENBSD_73,
    name="OpenBSD 7.3",
    base_image="openbsd-7.3",
    package_manager=PackageManager(
        name="pkg_add",
        install_cmd="pkg_add -I",
        update_cmd="pkg_add -u",
        search_cmd="pkg_info -Q",
        list_installed_cmd="pkg_info -a",
        package_count=7_787,
        cache_dir="/var/db/pkg",
        config_dir="/etc",
    ),
    syscall_policy=SyscallPolicy(
        allowed_syscalls=[
            # OpenBSD uses pledge — so this is a conceptual mapping.
            # Actual enforcement is via pledge() + unveil().
            "read", "write", "open", "close", "stat", "fstat",
            "lseek", "mmap", "mprotect", "munmap", "brk",
            "ioctl", "access", "pipe", "select", "dup", "dup2",
            "nanosleep", "getpid", "socket", "connect", "accept",
            "sendto", "recvfrom", "sendmsg", "recvmsg", "shutdown",
            "bind", "listen", "getsockname", "getpeername",
            "fork", "execve", "exit", "wait4", "kill",
            "fcntl", "flock", "fsync", "truncate", "ftruncate",
            "getdents", "getcwd", "chdir", "rename", "mkdir",
            "rmdir", "creat", "link", "unlink", "symlink",
            "readlink", "chmod", "chown", "umask",
            "gettimeofday", "getrlimit", "getrusage",
            "getuid", "getgid", "geteuid", "getegid",
            "sigaction", "sigprocmask", "sigreturn",
            "poll", "clock_gettime", "clock_getres",
            "kqueue", "kevent",
            "pledge", "unveil",
        ],
        blocked_syscalls=[
            "mount", "reboot", "ptrace",
            "settimeofday", "adjtime",
            "mknod", "chroot", "sysctl",
        ],
        log_only_syscalls=[],
        default_action="kill",
        architecture="amd64",
    ),
    filesystem_policy=FilesystemPolicy(
        writable_paths=["/workspace", "/tmp"],
        readable_paths=[
            "/usr", "/usr/lib", "/usr/local", "/etc/resolv.conf",
            "/dev/null", "/dev/urandom",
        ],
        hidden_paths=["/dev/mem", "/dev/kmem"],
        blocked_paths=[
            "/etc/master.passwd", "/root", "/home",
            "/var/log/authlog",
        ],
        max_file_size_mb=100,
        max_total_disk_mb=2048,
        tmpfs_size_mb=256,
        overlay_enabled=False,
        read_only_rootfs=True,
    ),
    network_policy=NetworkPolicy(
        enabled=True,
        allowed_outbound_ports=[80, 443, 53],
        blocked_outbound_ports=[22, 25, 445],
        allowed_domains=[],
        blocked_domains=[
            "metadata.google.internal", "169.254.169.254",
        ],
        max_bandwidth_mbps=25.0,
        dns_servers=["1.1.1.1", "8.8.8.8"],
        enable_ipv6=False,
    ),
    resource_limits=ResourceLimits(
        max_memory_bytes=1 * 1024**3,
        max_memory_swap_bytes=0,
        max_cpu_shares=512,
        max_cpu_quota_us=100_000,
        max_pids=128,
        max_open_files=512,
        max_processes=32,
        max_threads=64,
        max_file_locks=32,
        oom_score_adj=1000,
    ),
    native_sandbox="pledge",
    init_commands=[
        "pkg_add -I python-3.11 node curl git",
        "mkdir -p /workspace",
        "useradd -m -s /bin/ksh sandbox",
        "chown sandbox:sandbox /workspace",
    ],
    cleanup_commands=[
        "rm -rf /tmp/*",
    ],
    env_vars={
        "LANG": "en_US.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/workspace",
        "SANDBOX": "1",
        "TERM": "xterm-256color",
    },
    default_packages=[
        "python-3.11", "node", "curl", "git",
    ],
    available_package_count=7_787,
    interpreters={
        "python": "/usr/local/bin/python3",
        "node": "/usr/local/bin/node",
        "sh": "/bin/sh",
        "ksh": "/bin/ksh",
    },
)


FREEBSD_132_PROFILE = OSProfile(
    os_type=OSType.FREEBSD_132,
    name="FreeBSD 13.2",
    base_image="freebsd:13.2",
    package_manager=PackageManager(
        name="pkg",
        install_cmd="pkg install -y",
        update_cmd="pkg update",
        search_cmd="pkg search",
        list_installed_cmd="pkg info",
        package_count=30_766,
        cache_dir="/var/cache/pkg",
        config_dir="/usr/local/etc/pkg",
    ),
    syscall_policy=SyscallPolicy(
        allowed_syscalls=[
            # FreeBSD uses capsicum — this is a conceptual mapping.
            "read", "write", "open", "close", "stat", "fstat",
            "lseek", "mmap", "mprotect", "munmap", "brk",
            "ioctl", "access", "pipe", "select", "dup", "dup2",
            "nanosleep", "getpid", "socket", "connect", "accept",
            "sendto", "recvfrom", "sendmsg", "recvmsg", "shutdown",
            "bind", "listen", "getsockname", "getpeername",
            "fork", "execve", "exit", "wait4", "kill",
            "fcntl", "flock", "fsync", "truncate", "ftruncate",
            "getdents", "getcwd", "chdir", "rename", "mkdir",
            "rmdir", "creat", "link", "unlink", "symlink",
            "readlink", "chmod", "chown", "umask",
            "gettimeofday", "getrlimit", "getrusage",
            "getuid", "getgid", "geteuid", "getegid",
            "sigaction", "sigprocmask", "sigreturn",
            "poll", "clock_gettime", "clock_getres",
            "kqueue", "kevent",
            "cap_enter", "cap_rights_limit", "cap_rights_get",
            "cap_ioctls_limit", "cap_ioctls_get",
            "cap_fcntls_limit", "cap_fcntls_get",
        ],
        blocked_syscalls=[
            "mount", "reboot", "ptrace",
            "settimeofday", "adjtime",
            "mknod", "chroot", "sysctl",
            "jail", "jail_attach",
        ],
        log_only_syscalls=[],
        default_action="kill",
        architecture="amd64",
    ),
    filesystem_policy=FilesystemPolicy(
        writable_paths=["/workspace", "/tmp"],
        readable_paths=[
            "/usr", "/usr/lib", "/usr/local", "/etc",
            "/lib", "/libexec",
        ],
        hidden_paths=["/dev/mem", "/dev/kmem"],
        blocked_paths=[
            "/etc/master.passwd", "/root", "/home",
            "/var/log/auth.log",
        ],
        max_file_size_mb=100,
        max_total_disk_mb=4096,
        tmpfs_size_mb=512,
        overlay_enabled=False,
        read_only_rootfs=True,
    ),
    network_policy=NetworkPolicy(
        enabled=True,
        allowed_outbound_ports=[80, 443, 53],
        blocked_outbound_ports=[22, 25, 445],
        allowed_domains=[],
        blocked_domains=[
            "metadata.google.internal", "169.254.169.254",
        ],
        max_bandwidth_mbps=50.0,
        dns_servers=["1.1.1.1", "8.8.8.8"],
        enable_ipv6=False,
    ),
    resource_limits=ResourceLimits(
        max_memory_bytes=2 * 1024**3,
        max_memory_swap_bytes=0,
        max_cpu_shares=1024,
        max_cpu_quota_us=200_000,
        max_pids=256,
        max_open_files=1024,
        max_processes=64,
        max_threads=128,
        max_file_locks=64,
        oom_score_adj=1000,
    ),
    native_sandbox="capsicum",
    init_commands=[
        "pkg install -y python311 node20 curl git",
        "mkdir -p /workspace",
        "pw useradd sandbox -m -s /bin/sh",
        "chown sandbox:sandbox /workspace",
    ],
    cleanup_commands=[
        "rm -rf /tmp/*",
        "pkg clean -a -y",
    ],
    env_vars={
        "LANG": "en_US.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/workspace",
        "SANDBOX": "1",
        "TERM": "xterm-256color",
    },
    default_packages=[
        "python311", "node20", "curl", "wget", "git",
    ],
    available_package_count=30_766,
    interpreters={
        "python": "/usr/local/bin/python3.11",
        "node": "/usr/local/bin/node",
        "sh": "/bin/sh",
        "csh": "/bin/csh",
    },
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROFILES: dict[OSType, OSProfile] = {
    OSType.DEBIAN_11: DEBIAN_11_PROFILE,
    OSType.FEDORA_37: FEDORA_37_PROFILE,
    OSType.OPENBSD_73: OPENBSD_73_PROFILE,
    OSType.FREEBSD_132: FREEBSD_132_PROFILE,
}

_PROFILE_ALIASES: dict[str, OSType] = {
    "debian": OSType.DEBIAN_11,
    "debian-11": OSType.DEBIAN_11,
    "bullseye": OSType.DEBIAN_11,
    "fedora": OSType.FEDORA_37,
    "fedora-37": OSType.FEDORA_37,
    "openbsd": OSType.OPENBSD_73,
    "openbsd-7.3": OSType.OPENBSD_73,
    "freebsd": OSType.FREEBSD_132,
    "freebsd-13.2": OSType.FREEBSD_132,
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_profile(os_type: str | OSType) -> OSProfile:
    """Look up a sandbox profile by OS type or alias.

    Parameters
    ----------
    os_type:
        An :class:`OSType` member or a string alias such as ``"debian-11"``
        or ``"fedora"``.

    Returns
    -------
    OSProfile
        The matching profile.

    Raises
    ------
    ValueError
        If no matching profile is found.
    """
    if isinstance(os_type, str):
        normalised = os_type.strip().lower()
        if normalised in _PROFILE_ALIASES:
            key = _PROFILE_ALIASES[normalised]
        else:
            try:
                key = OSType(normalised)
            except ValueError:
                try:
                    key = OSType.from_string(normalised)
                except ValueError:
                    raise ValueError(
                        f"Unknown OS profile {os_type!r}. "
                        f"Available: {[p.name for p in PROFILES.values()]}"
                    ) from None
    else:
        key = os_type

    if key not in PROFILES:
        raise ValueError(
            f"No profile registered for {key!r}. "
            f"Available: {[p.name for p in PROFILES.values()]}"
        )
    return PROFILES[key]


def list_profiles() -> list[OSProfile]:
    """Return all registered :class:`OSProfile` instances."""
    return list(PROFILES.values())


def detect_host_os() -> OSType | None:
    """Auto-detect the current host OS and return the matching ``OSType``.

    Returns ``None`` if the host does not match any supported profile.
    """
    system = platform.system().lower()
    release = platform.release().lower()
    log.debug("Detecting host OS: system=%s release=%s", system, release)

    if system == "linux":
        # Attempt to read /etc/os-release
        os_release = _read_os_release()
        if os_release:
            os_id = os_release.get("ID", "").lower()
            version_id = os_release.get("VERSION_ID", "")
            log.debug("os-release: id=%s version=%s", os_id, version_id)
            if os_id == "debian" and version_id.startswith("11"):
                return OSType.DEBIAN_11
            if os_id == "fedora" and version_id.startswith("37"):
                return OSType.FEDORA_37
            if os_id == "ubuntu" and version_id.startswith("24.04"):
                return OSType.UBUNTU_2404
        # Fallback: try Debian-family detection
        if Path("/etc/debian_version").exists():
            return OSType.DEBIAN_11
        return None

    if system == "openbsd":
        if "7.3" in release:
            return OSType.OPENBSD_73
        return OSType.OPENBSD_73  # best-effort

    if system == "freebsd":
        if "13.2" in release:
            return OSType.FREEBSD_132
        return OSType.FREEBSD_132  # best-effort

    return None


def _read_os_release() -> dict[str, str]:
    """Parse ``/etc/os-release`` into a dict.  Returns empty on failure."""
    result: dict[str, str] = {}
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip('"').strip("'")
            result[key.strip()] = value
    except OSError:
        log.debug("Could not read /etc/os-release")
    return result
