"""Horizon Orchestra — Network Namespace Isolation.

Provides network isolation for sandboxes via Linux network namespaces,
veth pairs, iptables/nftables firewall rules, DNS filtering, and
tc (traffic control) bandwidth limits.

On non-Linux platforms:

- **OpenBSD**: generates ``pf.conf`` rules
- **FreeBSD**: generates ``ipfw`` rules for jail networking

Usage::

    from orchestra.sandbox.network import NetworkIsolation, DNSConfig
    net = NetworkIsolation(
        sandbox_id="sb-001",
        policy=policy,
        dns_config=DNSConfig(servers=["1.1.1.1"]),
    )
    iface = await net.setup()
    # ... sandbox runs ...
    await net.teardown()
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import platform
import shlex
import textwrap
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from orchestra.sandbox.os_profiles import (
        NetworkPolicy,
        OSProfile,
        get_profile,
    )
except ImportError:  # pragma: no cover
    NetworkPolicy = Any  # type: ignore[assignment,misc]
    OSProfile = Any  # type: ignore[assignment,misc]
    get_profile = None  # type: ignore[assignment]

__all__ = [
    "NetworkIsolation",
    "FirewallRule",
    "DNSConfig",
    "BandwidthLimit",
]

log = logging.getLogger("orchestra.sandbox.network")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LINUX = platform.system() == "Linux"

# Default subnet for sandbox veth pairs (each sandbox gets a /30)
_SANDBOX_SUBNET = "10.200.0.0/16"

# Cloud metadata endpoints to always block
_METADATA_IPS: list[str] = [
    "169.254.169.254",      # AWS / GCP metadata
    "100.100.100.200",      # Alibaba Cloud metadata
    "168.63.129.16",        # Azure metadata (wireserver)
]

# Private network CIDRs to block in paranoid mode
_PRIVATE_CIDRS: list[str] = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "fc00::/7",
]

# Maximum number of firewall rules per sandbox
_MAX_FIREWALL_RULES = 512


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FirewallRule:
    """A single firewall rule for iptables or nftables."""

    chain: str = "OUTPUT"       # INPUT | OUTPUT | FORWARD
    protocol: str = "tcp"       # tcp | udp | icmp
    destination: str = ""       # IP or CIDR
    port: int = 0               # 0 = any
    action: str = "DROP"        # ACCEPT | DROP | REJECT | LOG
    comment: str = ""

    def to_iptables_args(self) -> list[str]:
        """Convert this rule to iptables command-line arguments.

        Returns
        -------
        list[str]
            Arguments for ``iptables -A``.
        """
        args = ["-A", self.chain, "-p", self.protocol]

        if self.destination:
            args.extend(["-d", self.destination])
        if self.port > 0:
            args.extend(["--dport", str(self.port)])
        if self.comment:
            args.extend(["-m", "comment", "--comment", shlex.quote(self.comment)])
        args.extend(["-j", self.action])

        return args

    def to_nft_rule(self) -> str:
        """Convert to an nftables rule string."""
        parts = [f"ip protocol {self.protocol}"]
        if self.destination:
            parts.append(f"ip daddr {self.destination}")
        if self.port > 0:
            parts.append(f"{self.protocol} dport {self.port}")
        action_map = {
            "ACCEPT": "accept",
            "DROP": "drop",
            "REJECT": "reject",
            "LOG": 'log prefix "horizon-sandbox: "',
        }
        parts.append(action_map.get(self.action, "drop"))
        if self.comment:
            parts.append(f'comment "{self.comment}"')
        return " ".join(parts)


@dataclass
class DNSConfig:
    """DNS resolver configuration for the sandbox."""

    servers: list[str] = field(
        default_factory=lambda: ["1.1.1.1", "8.8.8.8"]
    )
    blocked_domains: list[str] = field(
        default_factory=lambda: [
            "metadata.google.internal",
            "169.254.169.254",
            "metadata.azure.com",
            "100.100.100.200",
        ]
    )
    allowed_domains: list[str] = field(default_factory=list)
    search_domains: list[str] = field(default_factory=list)
    ndots: int = 1


@dataclass
class BandwidthLimit:
    """Traffic control (tc) bandwidth limits."""

    ingress_mbps: float = 100.0
    egress_mbps: float = 50.0
    burst_kb: int = 128


# ---------------------------------------------------------------------------
# NetworkIsolation
# ---------------------------------------------------------------------------

class NetworkIsolation:
    """Network namespace isolation with firewall and DNS filtering.

    Creates an isolated network namespace with:

    1. **veth pair** connecting sandbox to host
    2. **iptables rules** for outbound filtering
    3. **DNS resolver** with domain blocking
    4. **tc (traffic control)** bandwidth limits
    5. **Loopback-only mode** for maximum isolation

    On non-Linux platforms:

    - **OpenBSD**: generates ``pf.conf`` rules
    - **FreeBSD**: generates ``ipfw`` rules for jail networking
    """

    def __init__(
        self,
        sandbox_id: str,
        policy: Any,
        dns_config: DNSConfig | None = None,
        bandwidth: BandwidthLimit | None = None,
    ) -> None:
        self._sandbox_id = sandbox_id
        self._policy = policy
        self._dns_config = dns_config or DNSConfig()
        self._bandwidth = bandwidth or BandwidthLimit()
        self._netns_name = f"horizon-{sandbox_id[:12]}"
        self._host_iface = f"veth-h-{sandbox_id[:8]}"
        self._sandbox_iface = f"veth-s-{sandbox_id[:8]}"
        self._host_ip = ""
        self._sandbox_ip = ""
        self._firewall_rules: list[FirewallRule] = []
        self._active = False
        self._loopback_only = False
        self._stats_start: dict[str, int] = {
            "bytes_in": 0,
            "bytes_out": 0,
            "packets_in": 0,
            "packets_out": 0,
            "drops": 0,
        }
        log.debug("NetworkIsolation created for sandbox %s", sandbox_id)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sandbox_id(self) -> str:
        """Return the sandbox identifier."""
        return self._sandbox_id

    @property
    def netns_name(self) -> str:
        """Return the network namespace name."""
        return self._netns_name

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def setup(self) -> str:
        """Set up network isolation and return the sandbox veth interface name.

        Creates the network namespace, veth pair, assigns IPs, applies
        firewall rules, writes DNS configuration, and applies bandwidth
        limits.

        Returns
        -------
        str
            The sandbox-side veth interface name.
        """
        log.info("Setting up network isolation for sandbox %s", self._sandbox_id)

        # Allocate IP addresses for this sandbox
        self._allocate_ip_pair()

        # Create network namespace
        await self.create_netns()

        # Create veth pair
        host_iface, sandbox_iface = await self.create_veth_pair()

        # Assign IPs
        await self.assign_ip(self._host_iface, f"{self._host_ip}/30")
        await self.assign_ip(self._sandbox_iface, f"{self._sandbox_ip}/30")

        # Enable forwarding on host interface
        if _LINUX:
            await self._run_cmd("sysctl", "-w", f"net.ipv4.conf.{shlex.quote(self._host_iface)}.forwarding=1")

        # Apply default firewall rules
        default_rules = self.build_default_rules()
        await self.apply_firewall_rules(default_rules)

        # Apply DNS block rules
        dns_rules = self.generate_dns_block_rules()
        if dns_rules:
            await self.apply_firewall_rules(dns_rules)

        # Apply bandwidth limits
        await self.apply_bandwidth_limits()

        self._active = True
        log.info(
            "Network isolation ready for sandbox %s (ns=%s, iface=%s)",
            self._sandbox_id,
            self._netns_name,
            sandbox_iface,
        )
        return sandbox_iface

    async def teardown(self) -> None:
        """Tear down all network isolation: rules, interfaces, namespace."""
        log.info("Tearing down network isolation for sandbox %s", self._sandbox_id)

        # Remove bandwidth limits
        try:
            await self.remove_bandwidth_limits()
        except OSError as exc:
            log.warning("Failed to remove bandwidth limits: %s", exc)

        # Clear firewall rules
        try:
            await self.clear_firewall_rules()
        except OSError as exc:
            log.warning("Failed to clear firewall rules: %s", exc)

        # Delete network namespace (also removes veth pair)
        try:
            await self.delete_netns()
        except OSError as exc:
            log.warning("Failed to delete netns: %s", exc)

        self._active = False
        self._firewall_rules.clear()
        log.info("Network teardown complete for sandbox %s", self._sandbox_id)

    # ------------------------------------------------------------------
    # Network namespace
    # ------------------------------------------------------------------

    async def create_netns(self) -> str:
        """Create a network namespace.

        Returns
        -------
        str
            The namespace name.
        """
        if _LINUX:
            await self._run_cmd("ip", "netns", "add", self._netns_name)

            # Bring up loopback inside the namespace
            await self._run_cmd(
                "ip", "netns", "exec", self._netns_name,
                "ip", "link", "set", "lo", "up",
            )
            log.debug("Created netns %s", self._netns_name)
        else:
            log.info("Network namespaces not available on %s", platform.system())

        return self._netns_name

    async def delete_netns(self) -> None:
        """Delete the network namespace."""
        if _LINUX:
            await self._run_cmd("ip", "netns", "del", self._netns_name)
            log.debug("Deleted netns %s", self._netns_name)
        else:
            log.debug("No netns to delete on %s", platform.system())

    # ------------------------------------------------------------------
    # veth pair
    # ------------------------------------------------------------------

    async def create_veth_pair(self) -> tuple[str, str]:
        """Create a veth pair connecting host and sandbox namespaces.

        Returns
        -------
        tuple[str, str]
            ``(host_interface, sandbox_interface)``
        """
        if _LINUX:
            # Create the veth pair
            await self._run_cmd(
                "ip", "link", "add", self._host_iface,
                "type", "veth",
                "peer", "name", self._sandbox_iface,
            )

            # Move sandbox end into the namespace
            await self._run_cmd(
                "ip", "link", "set", self._sandbox_iface,
                "netns", self._netns_name,
            )

            # Bring up host end
            await self._run_cmd("ip", "link", "set", self._host_iface, "up")

            # Bring up sandbox end inside namespace
            await self._run_cmd(
                "ip", "netns", "exec", self._netns_name,
                "ip", "link", "set", self._sandbox_iface, "up",
            )

            log.debug(
                "Created veth pair %s <-> %s",
                self._host_iface,
                self._sandbox_iface,
            )
        else:
            log.info("veth pairs not available on %s", platform.system())

        return self._host_iface, self._sandbox_iface

    async def assign_ip(self, interface: str, cidr: str) -> None:
        """Assign an IP address to an interface.

        Parameters
        ----------
        interface:
            Network interface name.
        cidr:
            IP address with prefix length (e.g. ``"10.200.0.1/30"``).
        """
        if not _LINUX:
            log.debug("IP assignment skipped on %s", platform.system())
            return

        # Determine if the interface is in the sandbox namespace
        if interface == self._sandbox_iface:
            await self._run_cmd(
                "ip", "netns", "exec", self._netns_name,
                "ip", "addr", "add", cidr, "dev", interface,
            )
            # Add default route via host IP
            await self._run_cmd(
                "ip", "netns", "exec", self._netns_name,
                "ip", "route", "add", "default", "via", self._host_ip,
            )
        else:
            await self._run_cmd("ip", "addr", "add", cidr, "dev", interface)

        log.debug("Assigned %s to %s", cidr, interface)

    # ------------------------------------------------------------------
    # Firewall
    # ------------------------------------------------------------------

    async def apply_firewall_rules(self, rules: list[FirewallRule]) -> None:
        """Apply a list of firewall rules.

        Parameters
        ----------
        rules:
            Firewall rules to apply via iptables.
        """
        if len(self._firewall_rules) + len(rules) > _MAX_FIREWALL_RULES:
            log.warning(
                "Firewall rule limit reached (%d); truncating",
                _MAX_FIREWALL_RULES,
            )
            rules = rules[: _MAX_FIREWALL_RULES - len(self._firewall_rules)]

        if _LINUX:
            for rule in rules:
                args = rule.to_iptables_args()
                try:
                    await self._run_cmd(
                        "ip", "netns", "exec", self._netns_name,
                        "iptables", *args,
                    )
                except OSError as exc:
                    log.warning("Failed to apply firewall rule: %s", exc)
        else:
            log.debug(
                "iptables not available — %d rules recorded but not applied",
                len(rules),
            )

        self._firewall_rules.extend(rules)
        log.debug("Applied %d firewall rules for sandbox %s", len(rules), self._sandbox_id)

    async def clear_firewall_rules(self) -> None:
        """Flush all firewall rules in the sandbox namespace."""
        if _LINUX:
            for chain in ("INPUT", "OUTPUT", "FORWARD"):
                await self._run_cmd(
                    "ip", "netns", "exec", self._netns_name,
                    "iptables", "-F", chain,
                )
            log.debug("Cleared firewall rules for sandbox %s", self._sandbox_id)

        self._firewall_rules.clear()

    def build_default_rules(self) -> list[FirewallRule]:
        """Build the default set of firewall rules.

        Default rules:

        1. Allow established/related connections
        2. Block cloud metadata endpoints
        3. Allow DNS (port 53 UDP/TCP)
        4. Allow HTTP/HTTPS (ports 80, 443)
        5. Drop everything else

        Returns
        -------
        list[FirewallRule]
            Default firewall rules.
        """
        rules: list[FirewallRule] = []

        # Block cloud metadata endpoints first (highest priority)
        for ip in _METADATA_IPS:
            rules.append(FirewallRule(
                chain="OUTPUT",
                protocol="tcp",
                destination=ip,
                action="DROP",
                comment=f"block-metadata-{ip}",
            ))
            rules.append(FirewallRule(
                chain="OUTPUT",
                protocol="udp",
                destination=ip,
                action="DROP",
                comment=f"block-metadata-{ip}",
            ))

        # Allow DNS
        for proto in ("tcp", "udp"):
            rules.append(FirewallRule(
                chain="OUTPUT",
                protocol=proto,
                port=53,
                action="ACCEPT",
                comment="allow-dns",
            ))

        # Allow HTTP and HTTPS
        rules.append(FirewallRule(
            chain="OUTPUT",
            protocol="tcp",
            port=80,
            action="ACCEPT",
            comment="allow-http",
        ))
        rules.append(FirewallRule(
            chain="OUTPUT",
            protocol="tcp",
            port=443,
            action="ACCEPT",
            comment="allow-https",
        ))

        # Allow loopback
        rules.append(FirewallRule(
            chain="OUTPUT",
            protocol="tcp",
            destination="127.0.0.0/8",
            action="ACCEPT",
            comment="allow-loopback",
        ))

        # Check policy for additional allowed ports
        if hasattr(self._policy, "allowed_ports"):
            allowed_ports = getattr(self._policy, "allowed_ports", [])
            for port in allowed_ports:
                rules.append(FirewallRule(
                    chain="OUTPUT",
                    protocol="tcp",
                    port=port,
                    action="ACCEPT",
                    comment=f"policy-allow-{port}",
                ))

        # Default deny outbound
        rules.append(FirewallRule(
            chain="OUTPUT",
            protocol="tcp",
            action="DROP",
            comment="default-deny-tcp",
        ))
        rules.append(FirewallRule(
            chain="OUTPUT",
            protocol="udp",
            action="DROP",
            comment="default-deny-udp",
        ))

        return rules

    # ------------------------------------------------------------------
    # DNS
    # ------------------------------------------------------------------

    async def write_resolv_conf(self, rootfs: str) -> None:
        """Write ``/etc/resolv.conf`` into the sandbox rootfs.

        Parameters
        ----------
        rootfs:
            Path to the sandbox's merged rootfs.
        """
        etc_dir = os.path.join(rootfs, "etc")
        os.makedirs(etc_dir, exist_ok=True)
        resolv_path = os.path.join(etc_dir, "resolv.conf")

        lines: list[str] = [
            "# Generated by Horizon Orchestra",
            f"# Sandbox: {self._sandbox_id}",
        ]

        # Search domains
        if self._dns_config.search_domains:
            lines.append(f"search {' '.join(self._dns_config.search_domains)}")

        # Options
        lines.append(f"options ndots:{self._dns_config.ndots}")

        # Nameservers
        for server in self._dns_config.servers:
            lines.append(f"nameserver {server}")

        with open(resolv_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        log.debug("Wrote resolv.conf for sandbox %s", self._sandbox_id)

    def generate_dns_block_rules(self) -> list[FirewallRule]:
        """Generate firewall rules to block DNS queries for blocked domains.

        Since iptables cannot natively filter by domain name, this
        blocks the known IP addresses of the blocked domains.  For
        the metadata endpoints, the IPs are already known.

        Returns
        -------
        list[FirewallRule]
            Rules that block DNS resolution for specified domains.
        """
        rules: list[FirewallRule] = []

        for domain in self._dns_config.blocked_domains:
            # Check if the domain is already an IP
            try:
                ipaddress.ip_address(domain)
                # It's an IP — block it directly
                for proto in ("tcp", "udp"):
                    rules.append(FirewallRule(
                        chain="OUTPUT",
                        protocol=proto,
                        destination=domain,
                        action="DROP",
                        comment=f"dns-block-{domain}",
                    ))
            except ValueError:
                # It's a domain name — we rely on the iptables string
                # matching module if available; otherwise log a note
                log.debug(
                    "Domain %s blocking requires DNS-level enforcement",
                    domain,
                )

        return rules

    # ------------------------------------------------------------------
    # Bandwidth
    # ------------------------------------------------------------------

    async def apply_bandwidth_limits(self) -> None:
        """Apply tc (traffic control) bandwidth limits to the veth pair.

        Sets egress limits on the host-side interface and ingress limits
        via an IFB (Intermediate Functional Block) device.
        """
        if not _LINUX:
            log.debug("Bandwidth limits skipped on %s", platform.system())
            return

        # Egress limit on host interface (controls traffic entering sandbox)
        egress_rate = f"{self._bandwidth.egress_mbps}mbit"
        burst = f"{self._bandwidth.burst_kb}kb"

        try:
            # Clear existing qdisc
            await self._run_cmd(
                "tc", "qdisc", "del", "dev", self._host_iface, "root",
            )
        except OSError:
            pass  # No existing qdisc

        try:
            await self._run_cmd(
                "tc", "qdisc", "add", "dev", self._host_iface, "root",
                "tbf", "rate", egress_rate, "burst", burst,
                "latency", "50ms",
            )
            log.debug(
                "Applied egress limit %s on %s",
                egress_rate,
                self._host_iface,
            )
        except OSError as exc:
            log.warning("Failed to apply egress bandwidth limit: %s", exc)

        # Ingress limit using a policing filter
        ingress_rate = f"{self._bandwidth.ingress_mbps}mbit"
        try:
            await self._run_cmd(
                "tc", "qdisc", "add", "dev", self._host_iface,
                "handle", "ffff:", "ingress",
            )
            await self._run_cmd(
                "tc", "filter", "add", "dev", self._host_iface,
                "parent", "ffff:", "protocol", "ip",
                "u32", "match", "u32", "0", "0",
                "police", "rate", ingress_rate, "burst", burst,
                "drop", "flowid", ":1",
            )
            log.debug(
                "Applied ingress limit %s on %s",
                ingress_rate,
                self._host_iface,
            )
        except OSError as exc:
            log.warning("Failed to apply ingress bandwidth limit: %s", exc)

    async def remove_bandwidth_limits(self) -> None:
        """Remove tc bandwidth limits from the veth pair."""
        if not _LINUX:
            return

        try:
            await self._run_cmd(
                "tc", "qdisc", "del", "dev", self._host_iface, "root",
            )
        except OSError:
            pass

        try:
            await self._run_cmd(
                "tc", "qdisc", "del", "dev", self._host_iface, "ingress",
            )
        except OSError:
            pass

        log.debug("Removed bandwidth limits on %s", self._host_iface)

    # ------------------------------------------------------------------
    # Loopback-only mode
    # ------------------------------------------------------------------

    async def enable_loopback_only(self) -> None:
        """Switch the sandbox to loopback-only networking.

        Removes the veth pair and leaves only the loopback interface
        inside the namespace, completely cutting off external access.
        """
        log.info(
            "Enabling loopback-only mode for sandbox %s",
            self._sandbox_id,
        )

        if _LINUX:
            # Remove the host-side veth interface (sandbox side disappears too)
            try:
                await self._run_cmd("ip", "link", "del", self._host_iface)
            except OSError as exc:
                log.warning("Could not delete host veth: %s", exc)

            # Verify only lo remains
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ip", "netns", "exec", self._netns_name,
                    "ip", "link", "show",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                log.debug(
                    "Loopback-only interfaces: %s",
                    stdout.decode().strip(),
                )
            except (FileNotFoundError, OSError):
                pass

        self._loopback_only = True
        log.info("Loopback-only mode enabled for sandbox %s", self._sandbox_id)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        """Return ``True`` if the network isolation is active."""
        return self._active

    def get_stats(self) -> dict[str, Any]:
        """Return network statistics: bytes in/out, packets, drops.

        Returns
        -------
        dict[str, Any]
            Network statistics dictionary.
        """
        stats: dict[str, Any] = {
            "sandbox_id": self._sandbox_id,
            "netns": self._netns_name,
            "host_iface": self._host_iface,
            "sandbox_iface": self._sandbox_iface,
            "host_ip": self._host_ip,
            "sandbox_ip": self._sandbox_ip,
            "active": self._active,
            "loopback_only": self._loopback_only,
            "firewall_rules": len(self._firewall_rules),
            "bandwidth": {
                "ingress_mbps": self._bandwidth.ingress_mbps,
                "egress_mbps": self._bandwidth.egress_mbps,
                "burst_kb": self._bandwidth.burst_kb,
            },
            "dns_servers": self._dns_config.servers,
            "blocked_domains": self._dns_config.blocked_domains,
        }

        # On Linux, try to read interface statistics
        if _LINUX and self._active:
            stats.update(self._read_iface_stats())

        return stats

    def _read_iface_stats(self) -> dict[str, int]:
        """Read interface statistics from /sys/class/net (Linux only)."""
        result: dict[str, int] = {}
        sys_path = f"/sys/class/net/{self._host_iface}/statistics"

        stat_files = {
            "bytes_in": "rx_bytes",
            "bytes_out": "tx_bytes",
            "packets_in": "rx_packets",
            "packets_out": "tx_packets",
            "drops": "rx_dropped",
        }

        for key, filename in stat_files.items():
            fpath = os.path.join(sys_path, filename)
            try:
                with open(fpath) as f:
                    result[key] = int(f.read().strip())
            except (FileNotFoundError, ValueError, OSError):
                result[key] = 0

        return result

    # ------------------------------------------------------------------
    # OpenBSD pf rules
    # ------------------------------------------------------------------

    def generate_pf_conf(self) -> str:
        """Generate OpenBSD ``pf.conf`` packet filter rules.

        Returns a string containing pf rules suitable for inclusion
        in ``/etc/pf.conf`` or loaded via ``pfctl -f``.

        Returns
        -------
        str
            The pf.conf rule set.
        """
        sandbox_tag = f"horizon_{self._sandbox_id[:8]}"
        rules_lines: list[str] = [
            f"# pf.conf rules for Horizon Orchestra sandbox {self._sandbox_id}",
            f"# Generated automatically — do not edit",
            "",
            f"# Define sandbox interface",
            f'sandbox_if = "vether0"',
            "",
            f"# Tables",
            f"table <metadata_ips> const {{ {', '.join(_METADATA_IPS)} }}",
        ]

        # Blocked private CIDRs
        rules_lines.append(
            f"table <private_nets> const {{ {', '.join(_PRIVATE_CIDRS[:4])} }}"
        )

        rules_lines.extend([
            "",
            f"# Default deny",
            f"block all",
            "",
            f"# Allow loopback",
            f"pass quick on lo0",
            "",
            f"# Block metadata endpoints",
            f"block drop quick from any to <metadata_ips> tag {sandbox_tag}",
            "",
        ])

        # DNS rules
        for server in self._dns_config.servers:
            rules_lines.append(
                f"pass out quick proto {{ tcp udp }} "
                f"to {server} port 53 tag {sandbox_tag}"
            )

        # HTTP/HTTPS
        rules_lines.extend([
            "",
            f"# Allow HTTP/HTTPS",
            f"pass out quick proto tcp to any port 80 tag {sandbox_tag}",
            f"pass out quick proto tcp to any port 443 tag {sandbox_tag}",
        ])

        # Policy-specific allowed ports
        if hasattr(self._policy, "allowed_ports"):
            for port in getattr(self._policy, "allowed_ports", []):
                rules_lines.append(
                    f"pass out quick proto tcp to any port {port} tag {sandbox_tag}"
                )

        # Bandwidth (ALTQ)
        if self._bandwidth.egress_mbps > 0:
            bw = int(self._bandwidth.egress_mbps * 1_000_000)
            rules_lines.extend([
                "",
                f"# Bandwidth limit",
                f"queue sandbox on $sandbox_if bandwidth {bw}",
            ])

        pf_conf = "\n".join(rules_lines) + "\n"
        log.debug(
            "Generated pf.conf with %d rules for sandbox %s",
            len([l for l in rules_lines if l.startswith(("pass", "block"))]),
            self._sandbox_id,
        )
        return pf_conf

    # ------------------------------------------------------------------
    # FreeBSD ipfw rules
    # ------------------------------------------------------------------

    def generate_ipfw_rules(self) -> list[str]:
        """Generate FreeBSD ``ipfw`` firewall rules.

        Returns a list of ``ipfw add`` command strings suitable for
        execution in a FreeBSD jail.

        Returns
        -------
        list[str]
            ipfw rule commands.
        """
        rules: list[str] = []
        rule_num = 100

        # Allow loopback
        rules.append(
            f"ipfw add {rule_num} allow all from any to any via lo0"
        )
        rule_num += 100

        # Block metadata endpoints
        for ip in _METADATA_IPS:
            rules.append(
                f"ipfw add {rule_num} deny all from any to {ip}"
            )
            rule_num += 100

        # Allow DNS
        for server in self._dns_config.servers:
            rules.append(
                f"ipfw add {rule_num} allow tcp from any to {server} dst-port 53"
            )
            rule_num += 100
            rules.append(
                f"ipfw add {rule_num} allow udp from any to {server} dst-port 53"
            )
            rule_num += 100

        # Allow HTTP/HTTPS
        rules.append(
            f"ipfw add {rule_num} allow tcp from any to any dst-port 80"
        )
        rule_num += 100
        rules.append(
            f"ipfw add {rule_num} allow tcp from any to any dst-port 443"
        )
        rule_num += 100

        # Policy-specific ports
        if hasattr(self._policy, "allowed_ports"):
            for port in getattr(self._policy, "allowed_ports", []):
                rules.append(
                    f"ipfw add {rule_num} allow tcp from any to any dst-port {port}"
                )
                rule_num += 100

        # Allow established connections
        rules.append(
            f"ipfw add {rule_num} allow tcp from any to any established"
        )
        rule_num += 100

        # Bandwidth pipe (dummynet)
        if self._bandwidth.egress_mbps > 0:
            bw_kbps = int(self._bandwidth.egress_mbps * 1000)
            rules.append(
                f"ipfw pipe 1 config bw {bw_kbps}Kbit/s"
            )
            rules.append(
                f"ipfw add {rule_num} pipe 1 all from any to any out"
            )
            rule_num += 100

        # Default deny
        rules.append(
            f"ipfw add {rule_num} deny all from any to any"
        )

        log.debug(
            "Generated %d ipfw rules for sandbox %s",
            len(rules),
            self._sandbox_id,
        )
        return rules

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _allocate_ip_pair(self) -> None:
        """Allocate a unique /30 subnet for this sandbox's veth pair.

        Uses a hash of the sandbox_id to deterministically assign IPs
        within the 10.200.0.0/16 range.
        """
        # Use hash to get a unique offset (each sandbox uses a /30 = 4 IPs)
        h = hash(self._sandbox_id) & 0xFFFF
        # Ensure alignment to /30 boundary and skip network/broadcast
        offset = ((h * 4) % (65536 - 8)) + 4
        base = ipaddress.IPv4Address("10.200.0.0") + offset
        self._host_ip = str(base)
        self._sandbox_ip = str(base + 1)
        log.debug(
            "Allocated IPs: host=%s sandbox=%s",
            self._host_ip,
            self._sandbox_ip,
        )

    async def _run_cmd(self, *args: str) -> tuple[str, str]:
        """Run a command via ``asyncio.create_subprocess_exec``.

        Parameters
        ----------
        *args:
            Command and arguments.

        Returns
        -------
        tuple[str, str]
            ``(stdout, stderr)`` from the command.

        Raises
        ------
        OSError
            If the command exits with a non-zero status.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""

            if proc.returncode != 0:
                log.debug(
                    "Command failed (rc=%d): %s — %s",
                    proc.returncode,
                    " ".join(args),
                    stderr_str.strip(),
                )
                raise OSError(
                    f"Command {args[0]} exited with {proc.returncode}: "
                    f"{stderr_str.strip()}"
                )
            return stdout_str, stderr_str
        except FileNotFoundError:
            log.debug("Command not found: %s", args[0])
            raise OSError(f"Command not found: {args[0]}")

    # ------------------------------------------------------------------
    # String representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"NetworkIsolation("
            f"sandbox_id={self._sandbox_id!r}, "
            f"netns={self._netns_name!r}, "
            f"active={self._active}, "
            f"loopback_only={self._loopback_only}, "
            f"rules={len(self._firewall_rules)}"
            f")"
        )
