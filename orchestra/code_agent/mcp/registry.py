"""MCPRegistry — manages all MCP server connections configured in .mcp.json.

Connections are lazy: servers are not started until their tools are first
requested or an explicit connect() call is made. This keeps app startup fast
even with many servers configured.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("orchestra.mcp.registry")

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_env(value: str) -> str:
    """Substitute ${VAR} placeholders with environment variable values."""
    def _sub(m: re.Match) -> str:
        return os.environ.get(m.group(1), "")
    return _ENV_RE.sub(_sub, value)


def _resolve_server_env(env: dict[str, str] | None) -> dict[str, str] | None:
    if not env:
        return None
    resolved = {k: _resolve_env(v) for k, v in env.items()}
    # Drop keys whose values resolved to empty string (missing env var)
    return {k: v for k, v in resolved.items() if v} or None


class MCPServerInfo:
    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.command: str = config.get("command", "")
        self.args: list[str] = config.get("args", [])
        self.env_template: dict[str, str] | None = config.get("env")
        self.description: str = config.get("description", "")
        self._client = None
        self._tools: list = []
        self._connected: bool = False
        self._error: str = ""

    @property
    def env(self) -> dict[str, str] | None:
        return _resolve_server_env(self.env_template)

    @property
    def needs_keys(self) -> list[str]:
        """Return any env var names that are required but not set."""
        if not self.env_template:
            return []
        missing = []
        for k, v in self.env_template.items():
            m = _ENV_RE.match(v)
            if m and not os.environ.get(m.group(1)):
                missing.append(m.group(1))
        return missing

    @property
    def ready(self) -> bool:
        """True if all required API keys are present."""
        return len(self.needs_keys) == 0

    async def connect(self) -> bool:
        from orchestra.code_agent.mcp.client import MCPClient
        if self._connected:
            return True
        if not self.command:
            self._error = "No command configured"
            return False
        try:
            client = MCPClient(self.command, self.args, env=self.env)
            tools = await asyncio.wait_for(client.connect(), timeout=60)
            self._client = client
            self._tools = tools
            self._connected = True
            self._error = ""
            log.info("MCP server '%s' connected — %d tools", self.name, len(tools))
            return True
        except Exception as exc:
            self._error = str(exc)
            self._connected = False
            log.warning("MCP server '%s' failed to connect: %s", self.name, exc)
            return False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
        self._client = None
        self._tools = []
        self._connected = False

    def get_tools(self) -> list:
        return self._tools

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "command": self.command,
            "args": self.args,
            "connected": self._connected,
            "tool_count": len(self._tools),
            "tools": [{"name": t.spec.name, "description": t.spec.description}
                      for t in self._tools],
            "needs_keys": self.needs_keys,
            "ready": self.ready,
            "error": self._error,
        }


class MCPRegistry:
    """Singleton registry for all MCP servers configured in .mcp.json."""

    _instance: MCPRegistry | None = None

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerInfo] = {}

    @classmethod
    def get(cls) -> MCPRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self, path: str | Path | None = None) -> None:
        """Load server configs from .mcp.json.  Defaults to project root."""
        if path is None:
            # Search upward from CWD for .mcp.json
            p = Path.cwd()
            while True:
                candidate = p / ".mcp.json"
                if candidate.exists():
                    path = candidate
                    break
                if p.parent == p:
                    break
                p = p.parent

        if path is None or not Path(path).exists():
            log.debug("No .mcp.json found — MCPRegistry empty")
            return

        try:
            data = json.loads(Path(path).read_text("utf-8"))
        except Exception as exc:
            log.warning("Could not parse .mcp.json: %s", exc)
            return

        servers = data.get("mcpServers", {})
        for name, config in servers.items():
            if name not in self._servers:
                self._servers[name] = MCPServerInfo(name, config)
            else:
                # Refresh config but keep connection state
                existing = self._servers[name]
                existing.command = config.get("command", "")
                existing.args = config.get("args", [])
                existing.env_template = config.get("env")
                existing.description = config.get("description", existing.description)

        log.info("MCPRegistry loaded %d servers from %s", len(self._servers), path)

    async def connect(self, name: str) -> bool:
        server = self._servers.get(name)
        if not server:
            return False
        return await server.connect()

    async def connect_all(self, skip_missing_keys: bool = True) -> dict[str, bool]:
        results: dict[str, bool] = {}
        coros = []
        names = []
        for name, server in self._servers.items():
            if server._connected:
                results[name] = True
                continue
            if skip_missing_keys and not server.ready:
                results[name] = False
                continue
            coros.append(server.connect())
            names.append(name)

        if coros:
            outcomes = await asyncio.gather(*coros, return_exceptions=True)
            for name, outcome in zip(names, outcomes):
                results[name] = bool(outcome) if not isinstance(outcome, Exception) else False

        return results

    async def disconnect(self, name: str) -> None:
        server = self._servers.get(name)
        if server:
            await server.disconnect()

    def get_tools(self, server_name: str | None = None):
        if server_name:
            s = self._servers.get(server_name)
            return s.get_tools() if s else []
        tools = []
        for s in self._servers.values():
            tools.extend(s.get_tools())
        return tools

    def status(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._servers.values()]

    def server_names(self) -> list[str]:
        return list(self._servers.keys())

    async def call_tool(self, server_name: str, tool_name: str,
                        arguments: dict[str, Any]) -> Any:
        server = self._servers.get(server_name)
        if not server:
            return {"error": f"Server '{server_name}' not found"}
        if not server._connected:
            ok = await server.connect()
            if not ok:
                return {"error": f"Could not connect to '{server_name}': {server._error}"}
        client = server._client
        if not client:
            return {"error": "No client"}
        # Use the underlying client's call mechanism
        call_fn = client._make_call(tool_name)
        try:
            return await call_fn(arguments)
        except Exception as exc:
            return {"error": str(exc)}
