"""Horizon Orchestra — Sandbox Isolation Layer.

OS-level sandbox isolation with namespace creation, syscall filtering,
and per-OS security profiles.  Supports Linux (namespaces + seccomp),
OpenBSD (pledge/unveil), and FreeBSD (capsicum/jails).

Sub-modules:
    os_profiles  — Pre-built profiles for Debian, Fedora, OpenBSD, FreeBSD
    namespaces   — Linux namespace & cgroup v2 management
    seccomp      — Seccomp-BPF filter generation & OS-native equivalents
    filesystem   — Hardened filesystem isolation (OverlayFS, tmpfs, bind)
    network      — Network namespace isolation (veth, iptables, DNS, tc)
    runtime      — Multi-OS hardened sandbox runtime
"""

from __future__ import annotations

from typing import Any

# Conditional imports — these modules may not all be available yet
try:
    from orchestra.sandbox.os_profiles import (
        OSProfile,
        OSType,
        PackageManager,
        SyscallPolicy,
        FilesystemPolicy,
        NetworkPolicy,
        ResourceLimits,
        get_profile,
        list_profiles,
        detect_host_os,
        PROFILES,
    )
except ImportError:  # pragma: no cover
    OSProfile = Any  # type: ignore[assignment,misc]
    OSType = None  # type: ignore[assignment,misc]
    PackageManager = Any  # type: ignore[assignment,misc]
    SyscallPolicy = Any  # type: ignore[assignment,misc]
    FilesystemPolicy = Any  # type: ignore[assignment,misc]
    NetworkPolicy = Any  # type: ignore[assignment,misc]
    ResourceLimits = Any  # type: ignore[assignment,misc]
    get_profile = None  # type: ignore[assignment]
    list_profiles = None  # type: ignore[assignment]
    detect_host_os = None  # type: ignore[assignment]
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
    from orchestra.sandbox.seccomp import (
        SeccompProfile,
        SAFE_SYSCALLS,
        DANGEROUS_SYSCALLS,
    )
except ImportError:  # pragma: no cover
    SeccompProfile = None  # type: ignore[assignment,misc]
    SAFE_SYSCALLS = []  # type: ignore[assignment]
    DANGEROUS_SYSCALLS = []  # type: ignore[assignment]

__all__ = [
    "OSProfile",
    "OSType",
    "PackageManager",
    "SyscallPolicy",
    "FilesystemPolicy",
    "NetworkPolicy",
    "ResourceLimits",
    "get_profile",
    "list_profiles",
    "detect_host_os",
    "PROFILES",
    "NamespaceManager",
    "CgroupManager",
    "NamespaceConfig",
    "SeccompProfile",
    "SAFE_SYSCALLS",
    "DANGEROUS_SYSCALLS",
]
