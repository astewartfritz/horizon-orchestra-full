"""Horizon Orchestra — Seccomp-BPF Syscall Filtering.

Generates architecture-specific syscall filter profiles compatible with
Docker's ``--security-opt seccomp=<file>`` and the OCI runtime spec.
Also produces OpenBSD ``pledge()`` strings and FreeBSD capsicum
capability lists for cross-platform sandbox configuration.

Usage::

    from orchestra.sandbox.seccomp import (
        SeccompProfile, SAFE_SYSCALLS, DANGEROUS_SYSCALLS,
        PROFILE_STANDARD, PROFILE_NETWORK,
    )
    from orchestra.sandbox.os_profiles import SyscallPolicy

    policy = SyscallPolicy(
        allowed_syscalls=list(SAFE_SYSCALLS),
        blocked_syscalls=list(DANGEROUS_SYSCALLS),
        default_action="kill",
    )
    profile = SeccompProfile(policy)
    docker_json = profile.to_docker_seccomp_json()
    profile.write_profile("/tmp/seccomp.json")
"""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "SeccompProfile",
    "LINUX_SYSCALL_TABLE",
    "SAFE_SYSCALLS",
    "DANGEROUS_SYSCALLS",
    "NETWORK_SYSCALLS",
    "FILESYSTEM_SYSCALLS",
    "PROFILE_MINIMAL",
    "PROFILE_STANDARD",
    "PROFILE_NETWORK",
    "PROFILE_FULL",
    "generate_pledge_string",
    "generate_capsicum_rights",
]

log = logging.getLogger("orchestra.sandbox.seccomp")

_IS_LINUX: bool = platform.system() == "Linux"


# ---------------------------------------------------------------------------
# x86_64 syscall number table  (Linux 6.x, amd64 / x86_64)
#
# Authoritative reference:
#   arch/x86/entry/syscalls/syscall_64.tbl  in the Linux source tree.
#
# At least 300 entries — covers every commonly used syscall plus many
# less-common ones needed for full compatibility.
# ---------------------------------------------------------------------------

LINUX_SYSCALL_TABLE: dict[str, int] = {
    # -- File I/O -------------------------------------------------------
    "read":                     0,
    "write":                    1,
    "open":                     2,
    "close":                    3,
    "stat":                     4,
    "fstat":                    5,
    "lstat":                    6,
    "poll":                     7,
    "lseek":                    8,
    "mmap":                     9,
    "mprotect":                10,
    "munmap":                  11,
    "brk":                     12,
    "rt_sigaction":            13,
    "rt_sigprocmask":          14,
    "rt_sigreturn":            15,
    "ioctl":                   16,
    "pread64":                 17,
    "pwrite64":                18,
    "readv":                   19,
    "writev":                  20,
    "access":                  21,
    "pipe":                    22,
    "select":                  23,
    "sched_yield":             24,
    "mremap":                  25,
    "msync":                   26,
    "mincore":                 27,
    "madvise":                 28,
    "shmget":                  29,
    "shmat":                   30,
    "shmctl":                  31,
    "dup":                     32,
    "dup2":                    33,
    "pause":                   34,
    "nanosleep":               35,
    "getitimer":               36,
    "alarm":                   37,
    "setitimer":               38,
    "getpid":                  39,
    "sendfile":                40,
    "socket":                  41,
    "connect":                 42,
    "accept":                  43,
    "sendto":                  44,
    "recvfrom":                45,
    "sendmsg":                 46,
    "recvmsg":                 47,
    "shutdown":                48,
    "bind":                    49,
    "listen":                  50,
    "getsockname":             51,
    "getpeername":             52,
    "socketpair":              53,
    "setsockopt":              54,
    "getsockopt":              55,
    "clone":                   56,
    "fork":                    57,
    "vfork":                   58,
    "execve":                  59,
    "exit":                    60,
    "wait4":                   61,
    "kill":                    62,
    "uname":                   63,
    "semget":                  64,
    "semop":                   65,
    "semctl":                  66,
    "shmdt":                   67,
    "msgget":                  68,
    "msgsnd":                  69,
    "msgrcv":                  70,
    "msgctl":                  71,
    "fcntl":                   72,
    "flock":                   73,
    "fsync":                   74,
    "fdatasync":               75,
    "truncate":                76,
    "ftruncate":               77,
    "getdents":                78,
    "getcwd":                  79,
    "chdir":                   80,
    "fchdir":                  81,
    "rename":                  82,
    "mkdir":                   83,
    "rmdir":                   84,
    "creat":                   85,
    "link":                    86,
    "unlink":                  87,
    "symlink":                 88,
    "readlink":                89,
    "chmod":                   90,
    "fchmod":                  91,
    "chown":                   92,
    "fchown":                  93,
    "lchown":                  94,
    "umask":                   95,
    "gettimeofday":            96,
    "getrlimit":               97,
    "getrusage":               98,
    "sysinfo":                 99,
    "times":                  100,
    "ptrace":                 101,
    "getuid":                 102,
    "syslog":                 103,
    "getgid":                 104,
    "setuid":                 105,
    "setgid":                 106,
    "geteuid":                107,
    "getegid":                108,
    "setpgid":                109,
    "getppid":                110,
    "getpgrp":                111,
    "setsid":                 112,
    "setreuid":               113,
    "setregid":               114,
    "getgroups":              115,
    "setgroups":              116,
    "setresuid":              117,
    "getresuid":              118,
    "setresgid":              119,
    "getresgid":              120,
    "getpgid":                121,
    "setfsuid":               122,
    "setfsgid":               123,
    "getsid":                 124,
    "capget":                 125,
    "capset":                 126,
    "rt_sigpending":          127,
    "rt_sigtimedwait":        128,
    "rt_sigqueueinfo":        129,
    "rt_sigsuspend":          130,
    "sigaltstack":            131,
    "utime":                  132,
    "mknod":                  133,
    "uselib":                 134,
    "personality":            135,
    "ustat":                  136,
    "statfs":                 137,
    "fstatfs":                138,
    "sysfs":                  139,
    "getpriority":            140,
    "setpriority":            141,
    "sched_setparam":         142,
    "sched_getparam":         143,
    "sched_setscheduler":     144,
    "sched_getscheduler":     145,
    "sched_get_priority_max": 146,
    "sched_get_priority_min": 147,
    "sched_rr_get_interval":  148,
    "mlock":                  149,
    "munlock":                150,
    "mlockall":               151,
    "munlockall":             152,
    "vhangup":                153,
    "modify_ldt":             154,
    "pivot_root":             155,
    "_sysctl":                156,
    "prctl":                  157,
    "arch_prctl":             158,
    "adjtimex":               159,
    "setrlimit":              160,
    "chroot":                 161,
    "sync":                   162,
    "acct":                   163,
    "settimeofday":           164,
    "mount":                  165,
    "umount2":                166,
    "swapon":                 167,
    "swapoff":                168,
    "reboot":                 169,
    "sethostname":            170,
    "setdomainname":          171,
    "iopl":                   172,
    "ioperm":                 173,
    "create_module":          174,
    "init_module":            175,
    "delete_module":          176,
    "get_kernel_syms":        177,
    "query_module":           178,
    "quotactl":               179,
    "nfsservctl":             180,
    "getpmsg":                181,
    "putpmsg":                182,
    "afs_syscall":            183,
    "tuxcall":                184,
    "security":               185,
    "gettid":                 186,
    "readahead":              187,
    "setxattr":               188,
    "lsetxattr":              189,
    "fsetxattr":              190,
    "getxattr":               191,
    "lgetxattr":              192,
    "fgetxattr":              193,
    "listxattr":              194,
    "llistxattr":             195,
    "flistxattr":             196,
    "removexattr":            197,
    "lremovexattr":           198,
    "fremovexattr":           199,
    "tkill":                  200,
    "time":                   201,
    "futex":                  202,
    "sched_setaffinity":      203,
    "sched_getaffinity":      204,
    "set_thread_area":        205,
    "io_setup":               206,
    "io_destroy":             207,
    "io_getevents":           208,
    "io_submit":              209,
    "io_cancel":              210,
    "get_thread_area":        211,
    "lookup_dcookie":         212,
    "epoll_create":           213,
    "epoll_ctl_old":          214,
    "epoll_wait_old":         215,
    "remap_file_pages":       216,
    "getdents64":             217,
    "set_tid_address":        218,
    "restart_syscall":        219,
    "semtimedop":             220,
    "fadvise64":              221,
    "timer_create":           222,
    "timer_settime":          223,
    "timer_gettime":          224,
    "timer_getoverrun":       225,
    "timer_delete":           226,
    "clock_settime":          227,
    "clock_gettime":          228,
    "clock_getres":           229,
    "clock_nanosleep":        230,
    "exit_group":             231,
    "epoll_wait":             232,
    "epoll_ctl":              233,
    "tgkill":                 234,
    "utimes":                 235,
    "vserver":                236,
    "mbind":                  237,
    "set_mempolicy":          238,
    "get_mempolicy":          239,
    "mq_open":                240,
    "mq_unlink":              241,
    "mq_timedsend":           242,
    "mq_timedreceive":        243,
    "mq_notify":              244,
    "mq_getsetattr":          245,
    "kexec_load":             246,
    "waitid":                 247,
    "add_key":                248,
    "request_key":            249,
    "keyctl":                 250,
    "ioprio_set":             251,
    "ioprio_get":             252,
    "inotify_init":           253,
    "inotify_add_watch":      254,
    "inotify_rm_watch":       255,
    "migrate_pages":          256,
    "openat":                 257,
    "mkdirat":                258,
    "mknodat":                259,
    "fchownat":               260,
    "futimesat":              261,
    "newfstatat":             262,
    "unlinkat":               263,
    "renameat":               264,
    "linkat":                 265,
    "symlinkat":              266,
    "readlinkat":             267,
    "fchmodat":               268,
    "faccessat":              269,
    "pselect6":               270,
    "ppoll":                  271,
    "unshare":                272,
    "set_robust_list":        273,
    "get_robust_list":        274,
    "splice":                 275,
    "tee":                    276,
    "sync_file_range":        277,
    "vmsplice":               278,
    "move_pages":             279,
    "utimensat":              280,
    "epoll_pwait":            281,
    "signalfd":               282,
    "timerfd_create":         283,
    "eventfd":                284,
    "fallocate":              285,
    "timerfd_settime":        286,
    "timerfd_gettime":        287,
    "accept4":                288,
    "signalfd4":              289,
    "eventfd2":               290,
    "epoll_create1":          291,
    "dup3":                   292,
    "pipe2":                  293,
    "inotify_init1":          294,
    "preadv":                 295,
    "pwritev":                296,
    "rt_tgsigqueueinfo":      297,
    "perf_event_open":        298,
    "recvmmsg":               299,
    "fanotify_init":          300,
    "fanotify_mark":          301,
    "prlimit64":              302,
    "name_to_handle_at":      303,
    "open_by_handle_at":      304,
    "clock_adjtime":          305,
    "syncfs":                 306,
    "sendmmsg":               307,
    "setns":                  308,
    "getcpu":                 309,
    "process_vm_readv":       310,
    "process_vm_writev":      311,
    "kcmp":                   312,
    "finit_module":           313,
    "sched_setattr":          314,
    "sched_getattr":          315,
    "renameat2":              316,
    "seccomp":                317,
    "getrandom":              318,
    "memfd_create":           319,
    "kexec_file_load":        320,
    "bpf":                    321,
    "execveat":               322,
    "userfaultfd":            323,
    "membarrier":             324,
    "mlock2":                 325,
    "copy_file_range":        326,
    "preadv2":                327,
    "pwritev2":               328,
    "pkey_mprotect":          329,
    "pkey_alloc":             330,
    "pkey_free":              331,
    "statx":                  332,
    "io_pgetevents":          333,
    "rseq":                   334,
    "pidfd_send_signal":      335,
    "io_uring_setup":         336,
    "io_uring_enter":         337,
    "io_uring_register":      338,
    "open_tree":              339,
    "move_mount":             340,
    "fsopen":                 341,
    "fsconfig":               342,
    "fsmount":                343,
    "fspick":                 344,
    "pidfd_open":             345,
    "clone3":                 346,
    "close_range":            347,
    "openat2":                348,
    "pidfd_getfd":            349,
    "faccessat2":             350,
    "process_madvise":        351,
    "epoll_pwait2":           352,
    "mount_setattr":          353,
    "quotactl_fd":            354,
    "landlock_create_ruleset": 355,
    "landlock_add_rule":      356,
    "landlock_restrict_self": 357,
    "memfd_secret":           358,
    "process_mrelease":       359,
    "futex_waitv":            360,
    "set_mempolicy_home_node": 361,
    "cachestat":              362,
    "fchmodat2":              363,
    "map_shadow_stack":       364,
    "futex_wake":             365,
    "futex_wait":             366,
    "futex_requeue":          367,
}


# ---------------------------------------------------------------------------
# Syscall category sets
# ---------------------------------------------------------------------------

SAFE_SYSCALLS: frozenset[str] = frozenset([
    # -- File I/O (basic) --
    "read", "write", "open", "close", "stat", "fstat", "lstat",
    "poll", "lseek", "mmap", "mprotect", "munmap", "brk",
    "rt_sigaction", "rt_sigprocmask", "rt_sigreturn",
    "ioctl", "pread64", "pwrite64", "readv", "writev",
    "access", "pipe", "select", "sched_yield",
    "mremap", "msync", "mincore", "madvise",
    "dup", "dup2", "dup3", "pause",
    "nanosleep", "getitimer", "alarm", "setitimer",
    "getpid", "sendfile",
    # -- Socket / network --
    "socket", "connect", "accept", "sendto", "recvfrom",
    "sendmsg", "recvmsg", "shutdown", "bind", "listen",
    "getsockname", "getpeername", "socketpair",
    "setsockopt", "getsockopt", "accept4",
    "recvmmsg", "sendmmsg",
    # -- Process --
    "clone", "fork", "vfork", "execve", "execveat",
    "exit", "exit_group", "wait4", "waitid",
    "kill", "tgkill", "tkill",
    "uname", "getpid", "getppid", "gettid",
    "getuid", "getgid", "geteuid", "getegid",
    "setuid", "setgid", "setreuid", "setregid",
    "setresuid", "getresuid", "setresgid", "getresgid",
    "setpgid", "getpgrp", "setsid", "getpgid", "getsid",
    "setfsuid", "setfsgid",
    "getgroups", "setgroups",
    "capget",
    # -- IPC --
    "shmget", "shmat", "shmctl", "shmdt",
    "semget", "semop", "semctl", "semtimedop",
    "msgget", "msgsnd", "msgrcv", "msgctl",
    # -- File descriptors --
    "fcntl", "flock", "fsync", "fdatasync",
    "truncate", "ftruncate",
    "getdents", "getdents64",
    "getcwd", "chdir", "fchdir",
    "rename", "renameat", "renameat2",
    "mkdir", "mkdirat", "rmdir",
    "creat", "link", "linkat", "unlink", "unlinkat",
    "symlink", "symlinkat", "readlink", "readlinkat",
    "chmod", "fchmod", "fchmodat",
    "chown", "fchown", "fchownat", "lchown",
    "umask",
    # -- Time --
    "gettimeofday", "time",
    "clock_gettime", "clock_getres", "clock_nanosleep",
    "timer_create", "timer_settime", "timer_gettime",
    "timer_getoverrun", "timer_delete",
    # -- Resource / info --
    "getrlimit", "setrlimit", "prlimit64",
    "getrusage", "sysinfo", "times",
    "getpriority", "setpriority",
    # -- Signals --
    "rt_sigpending", "rt_sigtimedwait",
    "rt_sigqueueinfo", "rt_sigsuspend", "rt_tgsigqueueinfo",
    "sigaltstack",
    # -- Scheduling --
    "sched_setparam", "sched_getparam",
    "sched_setscheduler", "sched_getscheduler",
    "sched_get_priority_max", "sched_get_priority_min",
    "sched_rr_get_interval",
    "sched_setaffinity", "sched_getaffinity",
    "sched_setattr", "sched_getattr",
    # -- Memory --
    "mlock", "munlock", "mlockall", "munlockall", "mlock2",
    # -- epoll / event --
    "epoll_create", "epoll_create1", "epoll_ctl",
    "epoll_wait", "epoll_pwait", "epoll_pwait2",
    "eventfd", "eventfd2",
    "signalfd", "signalfd4",
    "timerfd_create", "timerfd_settime", "timerfd_gettime",
    # -- *at family --
    "openat", "openat2", "mknodat",
    "newfstatat", "futimesat",
    "faccessat", "faccessat2",
    "utimensat",
    # -- Thread / futex --
    "set_tid_address", "set_robust_list", "get_robust_list",
    "futex", "futex_waitv", "futex_wake", "futex_wait", "futex_requeue",
    "arch_prctl", "prctl",
    # -- Misc --
    "statfs", "fstatfs", "ustat",
    "pipe2",
    "inotify_init", "inotify_init1",
    "inotify_add_watch", "inotify_rm_watch",
    "ppoll", "pselect6",
    "getrandom", "memfd_create", "statx",
    "copy_file_range", "splice", "tee", "vmsplice",
    "sync", "syncfs", "sync_file_range",
    "fallocate", "fadvise64", "readahead",
    "close_range", "pidfd_open", "pidfd_getfd",
    "clone3", "rseq",
    "io_uring_setup", "io_uring_enter", "io_uring_register",
    "io_setup", "io_destroy", "io_getevents", "io_submit", "io_cancel",
    "io_pgetevents",
    "seccomp", "membarrier",
    "preadv", "pwritev", "preadv2", "pwritev2",
    "pkey_mprotect", "pkey_alloc", "pkey_free",
    "landlock_create_ruleset", "landlock_add_rule",
    "landlock_restrict_self",
    "getcpu", "restart_syscall",
    "mq_open", "mq_unlink", "mq_timedsend",
    "mq_timedreceive", "mq_notify", "mq_getsetattr",
    "ioprio_set", "ioprio_get",
    "utime", "utimes",
    "setns", "unshare",
    "fanotify_init", "fanotify_mark",
    "process_madvise",
    # -- xattr --
    "setxattr", "lsetxattr", "fsetxattr",
    "getxattr", "lgetxattr", "fgetxattr",
    "listxattr", "llistxattr", "flistxattr",
    "removexattr", "lremovexattr", "fremovexattr",
    "remap_file_pages",
    "vhangup",
    "sysfs",
    "set_thread_area", "get_thread_area",
    "pidfd_send_signal",
    "process_mrelease",
    "cachestat",
    "fchmodat2",
    "sched_yield",
    "getpmsg",
    "putpmsg",
    "afs_syscall",
    "tuxcall",
])

DANGEROUS_SYSCALLS: frozenset[str] = frozenset([
    # Mounting / unmounting filesystems
    "mount", "umount2", "pivot_root",
    "move_mount", "open_tree", "fsopen", "fsconfig", "fsmount",
    "fspick", "mount_setattr",
    # System power
    "reboot",
    # Kernel module loading
    "kexec_load", "kexec_file_load",
    "init_module", "finit_module", "delete_module",
    "create_module", "query_module", "get_kernel_syms",
    # Swap
    "swapon", "swapoff",
    # Accounting
    "acct",
    # Time manipulation
    "settimeofday", "adjtimex", "clock_adjtime", "clock_settime",
    # Deprecated / dangerous
    "nfsservctl", "uselib",
    # Quotas
    "quotactl", "quotactl_fd",
    # Direct I/O port access
    "ioperm", "iopl",
    # Segment descriptors
    "modify_ldt",
    # Syslog
    "syslog",
    # Personality (binary emulation)
    "personality",
    # eBPF
    "bpf",
    # Userfaultfd
    "userfaultfd",
    # Perf
    "perf_event_open",
    # Ptrace
    "ptrace",
    # Cross-process memory access
    "process_vm_readv", "process_vm_writev",
    # Process comparison (info leak)
    "kcmp",
    # Handle-based open (bypasses path checks)
    "lookup_dcookie",
    "open_by_handle_at", "name_to_handle_at",
    # Keyring
    "add_key", "request_key", "keyctl",
    # NUMA page migration
    "move_pages", "migrate_pages",
    "mbind", "set_mempolicy", "get_mempolicy",
    "set_mempolicy_home_node",
    # Hostname / domain
    "sethostname", "setdomainname",
    # chroot (container escape vector)
    "chroot",
    # capset (privilege escalation)
    "capset",
    # Mknod (device file creation)
    "mknod",
    # Memory secrets
    "memfd_secret",
    # Shadow stack
    "map_shadow_stack",
])

NETWORK_SYSCALLS: frozenset[str] = frozenset([
    "socket", "connect", "accept", "accept4",
    "sendto", "recvfrom", "sendmsg", "recvmsg",
    "sendmmsg", "recvmmsg",
    "shutdown", "bind", "listen",
    "getsockname", "getpeername", "socketpair",
    "setsockopt", "getsockopt",
    "sendfile",
])

FILESYSTEM_SYSCALLS: frozenset[str] = frozenset([
    "open", "openat", "openat2", "creat",
    "read", "write", "pread64", "pwrite64",
    "readv", "writev", "preadv", "pwritev", "preadv2", "pwritev2",
    "lseek", "truncate", "ftruncate",
    "stat", "fstat", "lstat", "newfstatat", "statx",
    "access", "faccessat", "faccessat2",
    "rename", "renameat", "renameat2",
    "mkdir", "mkdirat", "rmdir",
    "link", "linkat", "unlink", "unlinkat",
    "symlink", "symlinkat", "readlink", "readlinkat",
    "chmod", "fchmod", "fchmodat", "fchmodat2",
    "chown", "fchown", "fchownat", "lchown",
    "getcwd", "chdir", "fchdir",
    "getdents", "getdents64",
    "fcntl", "flock", "fsync", "fdatasync",
    "fallocate", "fadvise64",
    "copy_file_range", "splice", "tee", "vmsplice",
    "sync", "syncfs", "sync_file_range",
    "inotify_init", "inotify_init1",
    "inotify_add_watch", "inotify_rm_watch",
    "fanotify_init", "fanotify_mark",
    "statfs", "fstatfs",
    "umask",
    "close", "close_range", "dup", "dup2", "dup3",
    "pipe", "pipe2",
])

_IPC_SYSCALLS: frozenset[str] = frozenset([
    "shmget", "shmat", "shmctl", "shmdt",
    "semget", "semop", "semctl", "semtimedop",
    "msgget", "msgsnd", "msgrcv", "msgctl",
    "mq_open", "mq_unlink", "mq_timedsend",
    "mq_timedreceive", "mq_notify", "mq_getsetattr",
])


# ---------------------------------------------------------------------------
# Pre-built seccomp profiles (as SyscallPolicy-compatible dicts)
# ---------------------------------------------------------------------------

def _make_minimal_syscalls() -> list[str]:
    """Bare minimum for compute-only tasks (no network, no fork)."""
    return sorted({
        "read", "write", "open", "close", "openat",
        "stat", "fstat", "lstat", "newfstatat", "statx",
        "lseek", "mmap", "mprotect", "munmap", "brk",
        "rt_sigaction", "rt_sigprocmask", "rt_sigreturn",
        "ioctl", "access", "faccessat",
        "pipe", "pipe2", "dup", "dup2", "dup3",
        "nanosleep", "clock_nanosleep", "clock_gettime", "clock_getres",
        "getpid", "gettid", "getuid", "getgid", "geteuid", "getegid",
        "exit", "exit_group",
        "futex", "set_tid_address", "set_robust_list",
        "arch_prctl", "prctl",
        "getrandom", "madvise",
        "fcntl", "flock",
        "getdents64", "getcwd",
        "sched_yield", "sched_getaffinity",
        "getrlimit", "prlimit64",
        "sigaltstack",
        "mremap", "mincore",
        "uname", "sysinfo",
        "readv", "writev", "pread64", "pwrite64",
        "restart_syscall",
        "rseq", "clone3",
        "membarrier",
        "close_range",
    })


def _make_standard_syscalls() -> list[str]:
    """General code execution (Python, Node.js, etc.)."""
    minimal = set(_make_minimal_syscalls())
    extras = {
        # Process management
        "clone", "fork", "vfork", "execve", "execveat",
        "wait4", "waitid", "kill", "tgkill", "tkill",
        "getppid", "setpgid", "getpgrp", "getpgid", "setsid", "getsid",
        "setuid", "setgid", "setreuid", "setregid",
        "setresuid", "getresuid", "setresgid", "getresgid",
        "setfsuid", "setfsgid", "getgroups", "setgroups",
        "capget",
        # Filesystem
        "rename", "renameat", "renameat2",
        "mkdir", "mkdirat", "rmdir",
        "creat", "link", "linkat", "unlink", "unlinkat",
        "symlink", "symlinkat", "readlink", "readlinkat",
        "chmod", "fchmod", "fchmodat",
        "chown", "fchown", "fchownat", "lchown",
        "umask", "chdir", "fchdir", "getdents",
        "truncate", "ftruncate", "fsync", "fdatasync",
        "fallocate", "copy_file_range",
        # Timer / time
        "getitimer", "setitimer", "alarm",
        "timer_create", "timer_settime", "timer_gettime",
        "timer_getoverrun", "timer_delete",
        "gettimeofday", "time",
        # epoll / event
        "select", "poll", "ppoll", "pselect6",
        "epoll_create", "epoll_create1", "epoll_ctl",
        "epoll_wait", "epoll_pwait", "epoll_pwait2",
        "eventfd", "eventfd2",
        "signalfd", "signalfd4",
        "timerfd_create", "timerfd_settime", "timerfd_gettime",
        # inotify
        "inotify_init", "inotify_init1",
        "inotify_add_watch", "inotify_rm_watch",
        # Signals
        "rt_sigpending", "rt_sigtimedwait",
        "rt_sigqueueinfo", "rt_sigsuspend", "rt_tgsigqueueinfo",
        # Memory
        "mlock", "munlock", "mlockall", "munlockall", "mlock2",
        "pkey_mprotect", "pkey_alloc", "pkey_free",
        # Scheduling
        "sched_setparam", "sched_getparam",
        "sched_setscheduler", "sched_getscheduler",
        "sched_get_priority_max", "sched_get_priority_min",
        "sched_rr_get_interval",
        "sched_setaffinity",
        "sched_setattr", "sched_getattr",
        # Misc
        "getrusage", "times", "getpriority", "setpriority",
        "setrlimit",
        "sendfile",
        "statfs", "fstatfs",
        "sync", "syncfs",
        "memfd_create",
        "preadv", "pwritev", "preadv2", "pwritev2",
        "splice", "tee", "vmsplice",
        "fadvise64", "readahead",
        "pidfd_open", "pidfd_getfd",
        "io_setup", "io_destroy", "io_getevents", "io_submit", "io_cancel",
        "io_uring_setup", "io_uring_enter", "io_uring_register",
        "seccomp",
        "setns", "unshare",
        "getcpu",
        "utime", "utimes", "utimensat", "futimesat",
        "landlock_create_ruleset", "landlock_add_rule",
        "landlock_restrict_self",
        "ioprio_set", "ioprio_get",
        # xattr
        "setxattr", "lsetxattr", "fsetxattr",
        "getxattr", "lgetxattr", "fgetxattr",
        "listxattr", "llistxattr", "flistxattr",
        "removexattr", "lremovexattr", "fremovexattr",
        "openat2", "faccessat2", "fchmodat2",
        "futex_waitv", "futex_wake", "futex_wait", "futex_requeue",
        "cachestat",
        "process_madvise",
        "pidfd_send_signal",
        "process_mrelease",
        "io_pgetevents",
    }
    return sorted(minimal | extras)


def _make_network_syscalls() -> list[str]:
    """Standard + networking."""
    standard = set(_make_standard_syscalls())
    return sorted(standard | NETWORK_SYSCALLS)


def _make_full_syscalls() -> list[str]:
    """Standard + network + IPC."""
    network = set(_make_network_syscalls())
    return sorted(network | _IPC_SYSCALLS)


# Public pre-built profile tuples: (allowed, blocked)
PROFILE_MINIMAL: tuple[list[str], list[str]] = (
    _make_minimal_syscalls(),
    sorted(DANGEROUS_SYSCALLS),
)

PROFILE_STANDARD: tuple[list[str], list[str]] = (
    _make_standard_syscalls(),
    sorted(DANGEROUS_SYSCALLS),
)

PROFILE_NETWORK: tuple[list[str], list[str]] = (
    _make_network_syscalls(),
    sorted(DANGEROUS_SYSCALLS),
)

PROFILE_FULL: tuple[list[str], list[str]] = (
    _make_full_syscalls(),
    sorted(DANGEROUS_SYSCALLS),
)


# ---------------------------------------------------------------------------
# OpenBSD pledge / FreeBSD capsicum helpers
# ---------------------------------------------------------------------------

# OpenBSD pledge promise sets
_PLEDGE_SETS: dict[str, str] = {
    "minimal":  "stdio rpath",
    "standard": "stdio rpath wpath cpath proc exec tmppath",
    "network":  "stdio rpath wpath cpath proc exec inet dns tmppath",
    "full":     "stdio rpath wpath cpath proc exec inet dns tmppath unix sendfd recvfd",
}

# FreeBSD capsicum capability right sets
_CAPSICUM_SETS: dict[str, list[str]] = {
    "minimal": [
        "CAP_READ", "CAP_WRITE", "CAP_SEEK", "CAP_FSTAT",
        "CAP_MMAP", "CAP_MMAP_R", "CAP_EVENT",
    ],
    "standard": [
        "CAP_READ", "CAP_WRITE", "CAP_SEEK", "CAP_FSTAT",
        "CAP_MMAP", "CAP_MMAP_R", "CAP_MMAP_W", "CAP_MMAP_X",
        "CAP_MMAP_RW", "CAP_MMAP_RX", "CAP_MMAP_WX", "CAP_MMAP_RWX",
        "CAP_FCNTL", "CAP_EVENT", "CAP_FTRUNCATE",
        "CAP_LOOKUP", "CAP_CREATE", "CAP_UNLINKAT",
        "CAP_MKDIRAT", "CAP_RENAMEAT_SOURCE", "CAP_RENAMEAT_TARGET",
    ],
    "network": [
        "CAP_READ", "CAP_WRITE", "CAP_SEEK", "CAP_FSTAT",
        "CAP_MMAP", "CAP_MMAP_R", "CAP_MMAP_W", "CAP_MMAP_X",
        "CAP_MMAP_RW", "CAP_MMAP_RX", "CAP_MMAP_WX", "CAP_MMAP_RWX",
        "CAP_FCNTL", "CAP_EVENT", "CAP_FTRUNCATE",
        "CAP_LOOKUP", "CAP_CREATE", "CAP_UNLINKAT",
        "CAP_MKDIRAT", "CAP_RENAMEAT_SOURCE", "CAP_RENAMEAT_TARGET",
        "CAP_SOCK_CLIENT", "CAP_SOCK_SERVER",
        "CAP_CONNECT", "CAP_ACCEPT", "CAP_BIND", "CAP_LISTEN",
        "CAP_GETPEERNAME", "CAP_GETSOCKNAME",
        "CAP_SETSOCKOPT", "CAP_GETSOCKOPT",
    ],
    "full": [
        "CAP_READ", "CAP_WRITE", "CAP_SEEK", "CAP_FSTAT",
        "CAP_MMAP", "CAP_MMAP_R", "CAP_MMAP_W", "CAP_MMAP_X",
        "CAP_MMAP_RW", "CAP_MMAP_RX", "CAP_MMAP_WX", "CAP_MMAP_RWX",
        "CAP_FCNTL", "CAP_EVENT", "CAP_FTRUNCATE",
        "CAP_LOOKUP", "CAP_CREATE", "CAP_UNLINKAT",
        "CAP_MKDIRAT", "CAP_RENAMEAT_SOURCE", "CAP_RENAMEAT_TARGET",
        "CAP_SOCK_CLIENT", "CAP_SOCK_SERVER",
        "CAP_CONNECT", "CAP_ACCEPT", "CAP_BIND", "CAP_LISTEN",
        "CAP_GETPEERNAME", "CAP_GETSOCKNAME",
        "CAP_SETSOCKOPT", "CAP_GETSOCKOPT",
        "CAP_SEM_POST", "CAP_SEM_WAIT",
    ],
}


def generate_pledge_string(
    level: str = "standard",
    *,
    extra_promises: list[str] | None = None,
) -> str:
    """Generate an OpenBSD ``pledge()`` promise string.

    Parameters
    ----------
    level:
        One of ``"minimal"``, ``"standard"``, ``"network"``, ``"full"``.
    extra_promises:
        Additional promise strings to append.

    Returns
    -------
    str
        Space-separated pledge promise string.
    """
    base = _PLEDGE_SETS.get(level, _PLEDGE_SETS["standard"])
    if extra_promises:
        promises = set(base.split()) | set(extra_promises)
        return " ".join(sorted(promises))
    return base


def generate_capsicum_rights(
    level: str = "standard",
    *,
    extra_rights: list[str] | None = None,
) -> list[str]:
    """Generate a FreeBSD capsicum capability rights list.

    Parameters
    ----------
    level:
        One of ``"minimal"``, ``"standard"``, ``"network"``, ``"full"``.
    extra_rights:
        Additional ``CAP_*`` right names to include.

    Returns
    -------
    list[str]
        Sorted list of capsicum capability right names.
    """
    base = list(_CAPSICUM_SETS.get(level, _CAPSICUM_SETS["standard"]))
    if extra_rights:
        combined = set(base) | set(extra_rights)
        return sorted(combined)
    return sorted(base)


# ---------------------------------------------------------------------------
# SeccompProfile class
# ---------------------------------------------------------------------------

class SeccompProfile:
    """Generates and applies seccomp-BPF syscall filters.

    Builds a JSON profile compatible with Docker's
    ``--security-opt seccomp=<file>`` format and the OCI runtime-spec
    seccomp format.  Also supports generating OpenBSD pledge strings and
    FreeBSD capsicum capability lists for cross-platform sandboxes.

    Each OS profile has a different syscall whitelist reflecting which
    syscalls that OS's userspace actually needs.

    Parameters
    ----------
    policy:
        A :class:`~orchestra.sandbox.os_profiles.SyscallPolicy` instance
        defining the allow/block/audit lists.
    """

    def __init__(self, policy: Any) -> None:
        self._policy = policy
        self._allowed: list[str] = list(policy.allowed_syscalls)
        self._blocked: list[str] = list(policy.blocked_syscalls)
        self._log_only: list[str] = list(policy.log_only_syscalls)
        self._default_action: str = policy.default_action
        self._architecture: str = getattr(policy, "architecture", "x86_64")

    # -- Properties ---------------------------------------------------------

    @property
    def policy(self) -> Any:
        """The underlying syscall policy."""
        return self._policy

    @property
    def architecture(self) -> str:
        """Target architecture (e.g. ``"x86_64"``)."""
        return self._architecture

    @property
    def default_action(self) -> str:
        """Action for syscalls not in any list."""
        return self._default_action

    # -- Syscall lists ------------------------------------------------------

    def get_allowed_syscalls(self) -> list[str]:
        """Return the allow-listed syscall names."""
        return list(self._allowed)

    def get_blocked_syscalls(self) -> list[str]:
        """Return the explicitly blocked syscall names."""
        return list(self._blocked)

    def get_audit_syscalls(self) -> list[str]:
        """Return the log-only (audit) syscall names."""
        return list(self._log_only)

    # -- Validation ---------------------------------------------------------

    def validate_syscall_name(self, name: str) -> bool:
        """Return *True* if *name* is a known x86_64 syscall."""
        return name in LINUX_SYSCALL_TABLE

    def get_syscall_number(self, name: str) -> int | None:
        """Return the x86_64 syscall number for *name*, or ``None``."""
        return LINUX_SYSCALL_TABLE.get(name)

    def validate_profile(self) -> list[str]:
        """Check the profile for configuration issues.

        Returns a list of warning strings (empty if everything is fine).
        """
        warnings: list[str] = []

        # Check for unknown syscalls in allowed list
        for sc in self._allowed:
            if sc not in LINUX_SYSCALL_TABLE:
                warnings.append(f"Unknown allowed syscall: {sc!r}")

        # Check for overlap between allowed and blocked
        overlap = set(self._allowed) & set(self._blocked)
        if overlap:
            warnings.append(
                f"Syscalls in both allowed and blocked lists: "
                f"{sorted(overlap)}"
            )

        # Check for missing essential syscalls
        essential = {"read", "write", "exit", "exit_group", "brk", "mmap"}
        missing = essential - set(self._allowed)
        if missing:
            warnings.append(
                f"Missing essential syscalls from allow list: "
                f"{sorted(missing)}"
            )

        return warnings

    # -- Docker / OCI profile generation ------------------------------------

    def _action_to_docker(self, action: str) -> str:
        """Map our action names to Docker seccomp action strings."""
        mapping = {
            "kill":   "SCMP_ACT_KILL",
            "errno":  "SCMP_ACT_ERRNO",
            "trap":   "SCMP_ACT_TRAP",
            "log":    "SCMP_ACT_LOG",
            "allow":  "SCMP_ACT_ALLOW",
            "trace":  "SCMP_ACT_TRACE",
        }
        return mapping.get(action, "SCMP_ACT_KILL")

    def _arch_to_docker(self) -> list[str]:
        """Map architecture to Docker seccomp architecture strings."""
        mapping: dict[str, list[str]] = {
            "x86_64":  ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86", "SCMP_ARCH_X32"],
            "amd64":   ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86", "SCMP_ARCH_X32"],
            "aarch64": ["SCMP_ARCH_AARCH64"],
            "arm64":   ["SCMP_ARCH_AARCH64"],
            "arm":     ["SCMP_ARCH_ARM"],
            "s390x":   ["SCMP_ARCH_S390X"],
            "ppc64le": ["SCMP_ARCH_PPC64LE"],
        }
        return mapping.get(self._architecture, ["SCMP_ARCH_X86_64"])

    def to_docker_seccomp_json(self) -> dict[str, Any]:
        """Generate a Docker-compatible seccomp profile JSON.

        Returns a dict that can be written with :func:`json.dumps` and
        passed to ``docker run --security-opt seccomp=<file>``.
        """
        # Build allowed rules
        syscalls: list[dict[str, Any]] = []

        # Whitelist
        if self._allowed:
            syscalls.append({
                "names": list(self._allowed),
                "action": "SCMP_ACT_ALLOW",
            })

        # Log-only
        if self._log_only:
            syscalls.append({
                "names": list(self._log_only),
                "action": "SCMP_ACT_LOG",
            })

        # Explicit block (returns EPERM)
        if self._blocked:
            syscalls.append({
                "names": list(self._blocked),
                "action": "SCMP_ACT_ERRNO",
                "errnoRet": 1,  # EPERM
            })

        profile: dict[str, Any] = {
            "defaultAction": self._action_to_docker(self._default_action),
            "architectures": self._arch_to_docker(),
            "syscalls": syscalls,
        }
        return profile

    def to_oci_seccomp_json(self) -> dict[str, Any]:
        """Generate an OCI runtime-spec compatible seccomp profile.

        The OCI format is similar to Docker's but uses slightly different
        field names and nesting.
        """
        syscalls: list[dict[str, Any]] = []

        if self._allowed:
            syscalls.append({
                "names": list(self._allowed),
                "action": "SCMP_ACT_ALLOW",
            })

        if self._log_only:
            syscalls.append({
                "names": list(self._log_only),
                "action": "SCMP_ACT_LOG",
            })

        if self._blocked:
            syscalls.append({
                "names": list(self._blocked),
                "action": "SCMP_ACT_ERRNO",
                "errnoRet": 1,
            })

        profile: dict[str, Any] = {
            "defaultAction": self._action_to_docker(self._default_action),
            "defaultErrnoRet": 1,
            "architectures": self._arch_to_docker(),
            "listenerPath": "",
            "listenerMetadata": "",
            "flags": ["SECCOMP_FILTER_FLAG_LOG"],
            "syscalls": syscalls,
        }
        return profile

    # -- Pledge / capsicum generation ---------------------------------------

    def to_pledge_string(self, level: str = "standard") -> str:
        """Generate an OpenBSD ``pledge()`` promise string.

        Parameters
        ----------
        level:
            Base level — ``"minimal"``, ``"standard"``, ``"network"``, or
            ``"full"``.
        """
        # Infer extra promises from our allowed syscall list
        extra: list[str] = []
        has_net = bool(set(self._allowed) & NETWORK_SYSCALLS)
        has_fs_write = bool({"mkdir", "unlink", "rename", "link"} & set(self._allowed))

        if has_net and "inet" not in _PLEDGE_SETS.get(level, ""):
            extra.append("inet")
            extra.append("dns")
        if has_fs_write and "wpath" not in _PLEDGE_SETS.get(level, ""):
            extra.append("wpath")
            extra.append("cpath")

        return generate_pledge_string(level, extra_promises=extra)

    def to_capsicum_rights(self, level: str = "standard") -> list[str]:
        """Generate a FreeBSD capsicum capability rights list.

        Parameters
        ----------
        level:
            Base level — ``"minimal"``, ``"standard"``, ``"network"``, or
            ``"full"``.
        """
        extra: list[str] = []
        has_net = bool(set(self._allowed) & NETWORK_SYSCALLS)
        if has_net and level not in ("network", "full"):
            extra.extend([
                "CAP_SOCK_CLIENT", "CAP_SOCK_SERVER",
                "CAP_CONNECT", "CAP_ACCEPT",
            ])
        return generate_capsicum_rights(level, extra_rights=extra)

    # -- File output --------------------------------------------------------

    def write_profile(self, path: str, *, format: str = "docker") -> str:
        """Write the seccomp profile to *path* as JSON.

        Parameters
        ----------
        path:
            Destination file path.
        format:
            ``"docker"`` or ``"oci"``.

        Returns
        -------
        str
            The absolute path written.
        """
        if format == "oci":
            data = self.to_oci_seccomp_json()
        else:
            data = self.to_docker_seccomp_json()

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        log.info("Wrote seccomp profile (%s) to %s", format, out)
        return str(out.resolve())

    # -- Summary / repr -----------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a summary of this profile for logging."""
        return {
            "architecture": self._architecture,
            "default_action": self._default_action,
            "allowed_count": len(self._allowed),
            "blocked_count": len(self._blocked),
            "log_only_count": len(self._log_only),
            "warnings": self.validate_profile(),
        }

    def __repr__(self) -> str:
        return (
            f"SeccompProfile(arch={self._architecture!r}, "
            f"allowed={len(self._allowed)}, "
            f"blocked={len(self._blocked)}, "
            f"default={self._default_action!r})"
        )
