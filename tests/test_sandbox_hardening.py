"""Tests for OS-level sandbox hardening.

Run with: pytest tests/test_sandbox_hardening.py -v
"""
from __future__ import annotations
import asyncio, os, pytest

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===================================================================
# OS Profiles
# ===================================================================

class TestOSProfiles:
    def test_all_imports(self):
        from orchestra.sandbox.os_profiles import (
            OSType, OSProfile, PackageManager, SyscallPolicy,
            FilesystemPolicy, NetworkPolicy, ResourceLimits,
            get_profile, list_profiles, detect_host_os, PROFILES,
        )

    def test_four_profiles_exist(self):
        from orchestra.sandbox.os_profiles import list_profiles
        profiles = list_profiles()
        assert len(profiles) >= 4
        names = [p.os_type.value for p in profiles]
        assert "debian-11" in names
        assert "fedora-37" in names
        assert "openbsd-7.3" in names
        assert "freebsd-13.2" in names

    def test_debian_profile(self):
        from orchestra.sandbox.os_profiles import get_profile
        p = get_profile("debian-11")
        assert p.name == "Debian 11 (Bullseye)"
        assert p.available_package_count == 59913
        assert p.package_manager.name == "apt"
        assert p.native_sandbox == "apparmor"
        assert "python" in p.interpreters or "python3" in p.interpreters

    def test_fedora_profile(self):
        from orchestra.sandbox.os_profiles import get_profile
        p = get_profile("fedora-37")
        assert p.available_package_count == 66166
        assert p.package_manager.name == "dnf"
        assert p.native_sandbox == "selinux"

    def test_openbsd_profile(self):
        from orchestra.sandbox.os_profiles import get_profile
        p = get_profile("openbsd-7.3")
        assert p.available_package_count == 7787
        assert p.native_sandbox == "pledge"

    def test_freebsd_profile(self):
        from orchestra.sandbox.os_profiles import get_profile
        p = get_profile("freebsd-13.2")
        assert p.available_package_count == 30766
        assert p.native_sandbox == "capsicum"

    def test_all_profiles_have_syscall_policy(self):
        from orchestra.sandbox.os_profiles import list_profiles
        for p in list_profiles():
            assert p.syscall_policy is not None
            assert len(p.syscall_policy.allowed_syscalls) > 0

    def test_all_profiles_have_fs_policy(self):
        from orchestra.sandbox.os_profiles import list_profiles
        for p in list_profiles():
            assert p.filesystem_policy is not None
            assert len(p.filesystem_policy.writable_paths) > 0

    def test_all_profiles_have_network_policy(self):
        from orchestra.sandbox.os_profiles import list_profiles
        for p in list_profiles():
            assert p.network_policy is not None

    def test_resource_limits(self):
        from orchestra.sandbox.os_profiles import get_profile
        p = get_profile("debian-11")
        limits = p.resource_limits
        assert limits.max_memory_bytes > 0
        assert limits.max_pids > 0
        assert limits.max_open_files > 0

    def test_detect_host_os(self):
        from orchestra.sandbox.os_profiles import detect_host_os
        # Should return something (may be None on unsupported OS)
        result = detect_host_os()
        # Just verify it doesn't crash


# ===================================================================
# Namespaces
# ===================================================================

class TestNamespaces:
    def test_imports(self):
        from orchestra.sandbox.namespaces import (
            NamespaceManager, CgroupManager, NamespaceConfig,
        )

    def test_namespace_config_defaults(self):
        from orchestra.sandbox.namespaces import NamespaceConfig
        cfg = NamespaceConfig()
        assert cfg.enable_pid_ns is True
        assert cfg.enable_net_ns is True
        assert cfg.enable_mnt_ns is True
        assert cfg.enable_user_ns is True
        assert cfg.hostname == "horizon-sandbox"

    def test_namespace_manager_creation(self):
        from orchestra.sandbox.namespaces import NamespaceManager, NamespaceConfig
        mgr = NamespaceManager(config=NamespaceConfig())
        assert mgr is not None

    def test_build_unshare_cmd(self):
        from orchestra.sandbox.namespaces import NamespaceManager, NamespaceConfig
        mgr = NamespaceManager(config=NamespaceConfig())
        cmd = mgr.build_unshare_cmd("echo hello")
        assert isinstance(cmd, list)
        assert len(cmd) > 0

    def test_cgroup_manager_creation(self):
        from orchestra.sandbox.namespaces import CgroupManager
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("debian-11")
        mgr = CgroupManager(sandbox_id="test-1", limits=profile.resource_limits)
        assert mgr is not None


# ===================================================================
# Seccomp
# ===================================================================

class TestSeccomp:
    def test_imports(self):
        from orchestra.sandbox.seccomp import (
            SeccompProfile, SAFE_SYSCALLS, DANGEROUS_SYSCALLS,
            LINUX_SYSCALL_TABLE, NETWORK_SYSCALLS, FILESYSTEM_SYSCALLS,
        )

    def test_syscall_table_size(self):
        from orchestra.sandbox.seccomp import LINUX_SYSCALL_TABLE
        assert len(LINUX_SYSCALL_TABLE) >= 300

    def test_safe_syscalls(self):
        from orchestra.sandbox.seccomp import SAFE_SYSCALLS
        assert len(SAFE_SYSCALLS) >= 200
        assert "read" in SAFE_SYSCALLS
        assert "write" in SAFE_SYSCALLS
        assert "exit" in SAFE_SYSCALLS or "exit_group" in SAFE_SYSCALLS

    def test_dangerous_syscalls(self):
        from orchestra.sandbox.seccomp import DANGEROUS_SYSCALLS
        assert len(DANGEROUS_SYSCALLS) >= 20
        assert "reboot" in DANGEROUS_SYSCALLS or any("reboot" in s for s in DANGEROUS_SYSCALLS)

    def test_docker_seccomp_json(self):
        from orchestra.sandbox.seccomp import SeccompProfile
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("debian-11")
        sp = SeccompProfile(profile.syscall_policy)
        docker_json = sp.to_docker_seccomp_json()
        assert isinstance(docker_json, dict)
        assert "defaultAction" in docker_json or "syscalls" in docker_json

    def test_oci_seccomp_json(self):
        from orchestra.sandbox.seccomp import SeccompProfile
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("fedora-37")
        sp = SeccompProfile(profile.syscall_policy)
        oci_json = sp.to_oci_seccomp_json()
        assert isinstance(oci_json, dict)

    def test_openbsd_pledge(self):
        from orchestra.sandbox.seccomp import SeccompProfile
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("openbsd-7.3")
        sp = SeccompProfile(profile.syscall_policy)
        pledge = sp.to_pledge_string()
        assert isinstance(pledge, str)
        assert "stdio" in pledge

    def test_freebsd_capsicum(self):
        from orchestra.sandbox.seccomp import SeccompProfile
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("freebsd-13.2")
        sp = SeccompProfile(profile.syscall_policy)
        caps = sp.to_capsicum_rights()
        assert isinstance(caps, (list, dict))

    def test_validate_syscall(self):
        from orchestra.sandbox.seccomp import SeccompProfile
        from orchestra.sandbox.os_profiles import get_profile
        sp = SeccompProfile(get_profile("debian-11").syscall_policy)
        assert sp.validate_syscall_name("read") is True
        assert sp.validate_syscall_name("fake_syscall_xyz") is False

    def test_get_syscall_number(self):
        from orchestra.sandbox.seccomp import SeccompProfile
        from orchestra.sandbox.os_profiles import get_profile
        sp = SeccompProfile(get_profile("debian-11").syscall_policy)
        num = sp.get_syscall_number("read")
        assert num == 0  # read is syscall 0 on x86_64


# ===================================================================
# Filesystem Isolation
# ===================================================================

class TestFilesystem:
    def test_imports(self):
        from orchestra.sandbox.filesystem import (
            FilesystemIsolation, OverlayMount, TmpfsMount, BindMount,
        )

    def test_overlay_mount_dataclass(self):
        from orchestra.sandbox.filesystem import OverlayMount
        mount = OverlayMount(
            mount_id="test", lower_dir="/lower",
            upper_dir="/upper", work_dir="/work", merged_dir="/merged",
        )
        assert mount.mounted is False

    def test_tmpfs_mount_dataclass(self):
        from orchestra.sandbox.filesystem import TmpfsMount
        mount = TmpfsMount(mount_point="/tmp", size_mb=256)
        assert mount.size_mb == 256

    def test_bind_mount_dataclass(self):
        from orchestra.sandbox.filesystem import BindMount
        mount = BindMount(source="/host/path", target="/sandbox/path", read_only=True)
        assert mount.read_only is True

    def test_fs_isolation_creation(self):
        from orchestra.sandbox.filesystem import FilesystemIsolation
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("debian-11")
        fs = FilesystemIsolation(sandbox_id="test", profile=profile)
        assert fs is not None

    def test_unveil_generation(self):
        from orchestra.sandbox.filesystem import FilesystemIsolation
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("openbsd-7.3")
        fs = FilesystemIsolation(sandbox_id="test", profile=profile)
        unveils = fs.generate_unveil_calls()
        assert isinstance(unveils, list)
        assert len(unveils) > 0

    def test_jail_fstab(self):
        from orchestra.sandbox.filesystem import FilesystemIsolation
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("freebsd-13.2")
        fs = FilesystemIsolation(sandbox_id="test", profile=profile)
        fstab = fs.generate_jail_fstab()
        assert isinstance(fstab, str)


# ===================================================================
# Network Isolation
# ===================================================================

class TestNetwork:
    def test_imports(self):
        from orchestra.sandbox.network import (
            NetworkIsolation, FirewallRule, DNSConfig, BandwidthLimit,
        )

    def test_firewall_rule(self):
        from orchestra.sandbox.network import FirewallRule
        rule = FirewallRule(
            chain="OUTPUT", protocol="tcp",
            destination="0.0.0.0/0", port=443, action="ACCEPT",
        )
        assert rule.action == "ACCEPT"

    def test_dns_config(self):
        from orchestra.sandbox.network import DNSConfig
        dns = DNSConfig()
        assert "1.1.1.1" in dns.servers or "8.8.8.8" in dns.servers
        assert "169.254.169.254" in dns.blocked_domains

    def test_bandwidth_limit(self):
        from orchestra.sandbox.network import BandwidthLimit
        bw = BandwidthLimit(ingress_mbps=100, egress_mbps=50)
        assert bw.egress_mbps == 50

    def test_network_isolation_creation(self):
        from orchestra.sandbox.network import NetworkIsolation
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("debian-11")
        net = NetworkIsolation(sandbox_id="test", policy=profile.network_policy)
        assert net is not None

    def test_default_firewall_rules(self):
        from orchestra.sandbox.network import NetworkIsolation
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("debian-11")
        net = NetworkIsolation(sandbox_id="test", policy=profile.network_policy)
        rules = net.build_default_rules()
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_pf_conf_generation(self):
        from orchestra.sandbox.network import NetworkIsolation
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("openbsd-7.3")
        net = NetworkIsolation(sandbox_id="test", policy=profile.network_policy)
        pf = net.generate_pf_conf()
        assert isinstance(pf, str)
        assert "block" in pf.lower() or "pass" in pf.lower()

    def test_ipfw_rules(self):
        from orchestra.sandbox.network import NetworkIsolation
        from orchestra.sandbox.os_profiles import get_profile
        profile = get_profile("freebsd-13.2")
        net = NetworkIsolation(sandbox_id="test", policy=profile.network_policy)
        rules = net.generate_ipfw_rules()
        assert isinstance(rules, list)


# ===================================================================
# Hardened Runtime
# ===================================================================

class TestRuntime:
    def test_imports(self):
        from orchestra.sandbox.runtime import (
            HardenedSandbox, HardenedSandboxPool,
            HardenedSandboxConfig, ISOLATION_LEVELS,
        )

    def test_config_defaults(self):
        from orchestra.sandbox.runtime import HardenedSandboxConfig
        cfg = HardenedSandboxConfig()
        assert cfg.os_profile == "debian-11"
        assert cfg.isolation_level == "standard"
        assert cfg.timeout_seconds == 300.0

    def test_isolation_levels(self):
        from orchestra.sandbox.runtime import ISOLATION_LEVELS
        assert "minimal" in ISOLATION_LEVELS
        assert "standard" in ISOLATION_LEVELS
        assert "maximum" in ISOLATION_LEVELS
        assert "paranoid" in ISOLATION_LEVELS

    def test_paranoid_is_strictest(self):
        from orchestra.sandbox.runtime import ISOLATION_LEVELS
        paranoid = ISOLATION_LEVELS["paranoid"]
        assert paranoid.network_mode in ("none", "loopback")

    def test_sandbox_creation(self):
        from orchestra.sandbox.runtime import HardenedSandbox, HardenedSandboxConfig
        sb = HardenedSandbox(sandbox_id="test-1", config=HardenedSandboxConfig())
        assert sb.state in ("created", "initialized")

    def test_pool_creation(self):
        from orchestra.sandbox.runtime import HardenedSandboxPool
        pool = HardenedSandboxPool(max_sandboxes=10)
        assert pool is not None

    def test_pool_stats(self):
        from orchestra.sandbox.runtime import HardenedSandboxPool
        pool = HardenedSandboxPool()
        stats = pool.get_pool_stats()
        assert isinstance(stats, dict)

    def test_sandbox_has_methods(self):
        from orchestra.sandbox.runtime import HardenedSandbox
        assert hasattr(HardenedSandbox, "create")
        assert hasattr(HardenedSandbox, "start")
        assert hasattr(HardenedSandbox, "execute")
        assert hasattr(HardenedSandbox, "stop")
        assert hasattr(HardenedSandbox, "destroy")
        assert hasattr(HardenedSandbox, "install_packages")
        assert hasattr(HardenedSandbox, "get_security_report")


# ===================================================================
# Full smoke test
# ===================================================================

class TestSandboxSmoke:
    def test_all_modules_import(self):
        import importlib
        failures = []
        count = 0
        for root, dirs, files in os.walk("orchestra"):
            for f in files:
                if f.endswith(".py") and "__pycache__" not in root:
                    mod = os.path.join(root, f).replace("\\", ".").replace("/", ".")[:-3]
                    try:
                        importlib.import_module(mod)
                        count += 1
                    except Exception as e:
                        failures.append(f"{mod}: {e}")
        assert len(failures) == 0, f"Failures:\\n" + "\\n".join(failures)

    def test_package_count_totals(self):
        from orchestra.sandbox.os_profiles import list_profiles
        total = sum(p.available_package_count for p in list_profiles())
        # 59913 + 66166 + 7787 + 30766 = 164,632
        assert total == 164632
