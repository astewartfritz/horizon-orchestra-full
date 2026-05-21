from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class RemoteHost:
    host: str
    port: int = 22
    user: str = ""
    key_path: str = ""
    name: str = ""


@dataclass
class RemoteResult:
    host: str
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration: float = 0.0
    error: str = ""


_HOSTS_FILE = Path.home() / ".agent-remote-hosts.json"


class RemoteAgent:
    def __init__(self):
        self.hosts: list[RemoteHost] = []
        self.load_hosts()

    def add_host(self, host: RemoteHost) -> None:
        for i, h in enumerate(self.hosts):
            if h.host == host.host:
                self.hosts[i] = host
                break
        else:
            self.hosts.append(host)
        self.save_hosts()

    def remove_host(self, host: str) -> bool:
        before = len(self.hosts)
        self.hosts = [h for h in self.hosts if h.host != host]
        if len(self.hosts) < before:
            self.save_hosts()
            return True
        return False

    def load_hosts(self) -> None:
        if _HOSTS_FILE.exists():
            try:
                data = json.loads(_HOSTS_FILE.read_text(encoding="utf-8"))
                self.hosts = [RemoteHost(**h) for h in data]
            except (json.JSONDecodeError, Exception):
                self.hosts = []

    def save_hosts(self) -> None:
        _HOSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HOSTS_FILE.write_text(
            json.dumps([asdict(h) for h in self.hosts], indent=2),
            encoding="utf-8",
        )

    def run(self, host: str, command: str, timeout: int = 60) -> RemoteResult:
        import time
        start = time.perf_counter()

        host_obj = next((h for h in self.hosts if h.host == host or h.name == host), None)
        if not host_obj:
            return RemoteResult(host=host, command=command, error=f"Host '{host}' not found")

        ssh_cmd = ["ssh"]
        if host_obj.port != 22:
            ssh_cmd.extend(["-p", str(host_obj.port)])
        if host_obj.key_path:
            ssh_cmd.extend(["-i", host_obj.key_path])
        if host_obj.user:
            ssh_cmd.append(f"{host_obj.user}@{host_obj.host}")
        else:
            ssh_cmd.append(host_obj.host)
        ssh_cmd.append(command)

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True, text=True,
                timeout=timeout,
            )
            elapsed = time.perf_counter() - start
            return RemoteResult(
                host=host, command=command,
                stdout=result.stdout, stderr=result.stderr,
                exit_code=result.returncode, duration=elapsed,
            )
        except subprocess.TimeoutExpired:
            return RemoteResult(host=host, command=command, error=f"Timeout after {timeout}s")
        except FileNotFoundError:
            return RemoteResult(host=host, command=command, error="SSH client not found")
        except Exception as e:
            return RemoteResult(host=host, command=command, error=str(e))

    def scp_to(self, host: str, local_path: str, remote_path: str) -> RemoteResult:
        host_obj = next((h for h in self.hosts if h.host == host or h.name == host), None)
        if not host_obj:
            return RemoteResult(host=host, command=f"scp {local_path} {remote_path}", error="Host not found")

        dest = f"{host_obj.user}@{host_obj.host}:{remote_path}" if host_obj.user else f"{host_obj.host}:{remote_path}"
        cmd = ["scp"]
        if host_obj.port != 22:
            cmd.extend(["-P", str(host_obj.port)])
        if host_obj.key_path:
            cmd.extend(["-i", host_obj.key_path])
        cmd.extend([local_path, dest])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return RemoteResult(host=host, command=f"scp {local_path} {remote_path}",
                              stdout=result.stdout, stderr=result.stderr,
                              exit_code=result.returncode)
        except Exception as e:
            return RemoteResult(host=host, command="scp", error=str(e))

    def scp_from(self, host: str, remote_path: str, local_path: str) -> RemoteResult:
        host_obj = next((h for h in self.hosts if h.host == host or h.name == host), None)
        if not host_obj:
            return RemoteResult(host=host, command=f"scp {remote_path} {local_path}", error="Host not found")

        src = f"{host_obj.user}@{host_obj.host}:{remote_path}" if host_obj.user else f"{host_obj.host}:{remote_path}"
        cmd = ["scp"]
        if host_obj.port != 22:
            cmd.extend(["-P", str(host_obj.port)])
        if host_obj.key_path:
            cmd.extend(["-i", host_obj.key_path])
        cmd.extend([src, local_path])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return RemoteResult(host=host, command=f"scp {remote_path} {local_path}",
                              stdout=result.stdout, stderr=result.stderr,
                              exit_code=result.returncode)
        except Exception as e:
            return RemoteResult(host=host, command="scp", error=str(e))

    def list_hosts(self) -> list[RemoteHost]:
        return self.hosts

    def test_connection(self, host: str) -> RemoteResult:
        return self.run(host, "echo connected && uname -a")

    def summary_text(self) -> str:
        if not self.hosts:
            return "No remote hosts configured."
        lines = [f"Remote Hosts ({len(self.hosts)}):", "─" * 60]
        for h in self.hosts:
            lines.append(f"  {h.name or h.host:20} {h.user}@{h.host}:{h.port}")
        return "\n".join(lines)
