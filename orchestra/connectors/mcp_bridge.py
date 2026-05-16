"""Model Context Protocol (MCP) bridge — dynamic tool discovery.

Connects to any MCP-compatible server and automatically discovers
and registers its tools into the Orchestra tool surface. This lets
Orchestra use any MCP server as if it were a native connector.

MCP spec: https://modelcontextprotocol.io

Usage::

    bridge = MCPBridge()
    await bridge.connect({"server_url": "http://localhost:3100"})
    # All tools from the MCP server are now available to agents
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from .base import Connector

__all__ = ["MCPBridge"]

log = logging.getLogger("orchestra.connectors.mcp")


class MCPBridge(Connector):
    """Bridge to any MCP (Model Context Protocol) server.

    Discovers tools dynamically via the MCP /tools/list endpoint
    and proxies tool calls through /tools/call. This is how Orchestra
    integrates with the broader MCP ecosystem (filesystem, database,
    git, Puppeteer, Brave Search, etc).
    """

    name = "mcp"
    description = "Connect to any MCP server for dynamic tool discovery."

    def __init__(self) -> None:
        self._server_url: str = ""
        self._tools: list[dict[str, Any]] = []
        self._session_id: str = ""

    @property
    def connected(self) -> bool:
        return bool(self._server_url and self._tools)

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Connect to an MCP server.

        credentials:
          - server_url: Base URL of the MCP server (e.g. http://localhost:3100)
          - server_command: (optional) Command to start the MCP server via stdio
        """
        self._server_url = credentials.get("server_url", "").rstrip("/")
        if not self._server_url:
            log.error("server_url is required for MCP bridge")
            return False

        # Initialize session
        try:
            init_result = await self._mcp_request("initialize", {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "horizon-orchestra", "version": "0.1.0"},
            })
            self._session_id = init_result.get("sessionId", "")

            # Send initialized notification
            await self._mcp_notify("notifications/initialized", {})

            # Discover tools
            tools_result = await self._mcp_request("tools/list", {})
            self._tools = tools_result.get("tools", [])

            log.info(
                "MCP bridge connected to %s — discovered %d tools: %s",
                self._server_url,
                len(self._tools),
                [t.get("name") for t in self._tools],
            )
            return True

        except Exception as exc:
            log.error("MCP connection failed: %s", exc)
            self._server_url = ""
            return False

    async def disconnect(self) -> None:
        self._server_url = ""
        self._tools = []
        self._session_id = ""

    async def _mcp_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request to the MCP server."""
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._server_url}/mcp",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data.get("result", {})

    async def _mcp_notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC 2.0 notification (no response expected)."""
        body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{self._server_url}/mcp", headers=headers, json=body)

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Proxy a tool call to the MCP server."""
        if not self.connected:
            return {"error": "MCP bridge not connected."}

        try:
            result = await self._mcp_request("tools/call", {
                "name": action,
                "arguments": params,
            })

            # Parse MCP content blocks
            content_parts: list[str] = []
            for block in result.get("content", []):
                if block.get("type") == "text":
                    content_parts.append(block.get("text", ""))
                elif block.get("type") == "resource":
                    content_parts.append(json.dumps(block.get("resource", {})))

            return {
                "result": "\n".join(content_parts),
                "is_error": result.get("isError", False),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Convert MCP tool schemas to OpenAI function-calling format."""
        definitions: list[dict[str, Any]] = []
        for tool in self._tools:
            name = tool.get("name", "")
            description = tool.get("description", "")
            input_schema = tool.get("inputSchema", {"type": "object", "properties": {}})

            definitions.append({
                "type": "function",
                "function": {
                    "name": f"mcp_{name}",
                    "description": f"[MCP] {description}",
                    "parameters": input_schema,
                },
            })
        return definitions

    # -- Convenience: discover and list resources ---------------------------

    async def list_resources(self) -> list[dict[str, Any]]:
        """List resources exposed by the MCP server."""
        if not self.connected:
            return []
        try:
            result = await self._mcp_request("resources/list", {})
            return result.get("resources", [])
        except Exception:
            return []

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a specific resource from the MCP server."""
        if not self.connected:
            return {"error": "Not connected"}
        try:
            result = await self._mcp_request("resources/read", {"uri": uri})
            contents = result.get("contents", [])
            if contents:
                return {"uri": uri, "content": contents[0].get("text", "")}
            return {"uri": uri, "content": ""}
        except Exception as exc:
            return {"error": str(exc)}

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List prompt templates from the MCP server."""
        if not self.connected:
            return []
        try:
            result = await self._mcp_request("prompts/list", {})
            return result.get("prompts", [])
        except Exception:
            return []
