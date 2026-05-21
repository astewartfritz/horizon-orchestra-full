"""FastAPI routes for the Orchestra MCP gateway."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from orchestra.code_agent.mcp.registry import MCPRegistry


def register_mcp_routes(app: Any, prefix: str = "/api/mcp") -> None:
    registry = MCPRegistry.get()
    router = APIRouter(prefix=prefix)

    @router.get("/status")
    async def mcp_status():
        """List all configured MCP servers with connection status and tool counts."""
        return {"servers": registry.status()}

    @router.post("/connect/{name}")
    async def connect_server(name: str):
        """Connect (or reconnect) a specific MCP server."""
        if name not in registry.server_names():
            raise HTTPException(status_code=404, detail=f"Server '{name}' not configured")
        ok = await registry.connect(name)
        servers = registry.status()
        info = next((s for s in servers if s["name"] == name), {})
        return {"connected": ok, "server": info}

    @router.post("/connect")
    async def connect_all():
        """Connect all ready MCP servers (those whose API keys are available)."""
        results = await registry.connect_all(skip_missing_keys=True)
        return {"results": results, "servers": registry.status()}

    @router.post("/disconnect/{name}")
    async def disconnect_server(name: str):
        """Disconnect a specific MCP server."""
        await registry.disconnect(name)
        return {"disconnected": name}

    @router.get("/tools")
    async def list_tools(server: str = ""):
        """List all available MCP tools, optionally filtered by server."""
        tools = registry.get_tools(server or None)
        return {
            "count": len(tools),
            "tools": [
                {"server": _find_server(registry, t), "name": t.spec.name,
                 "description": t.spec.description}
                for t in tools
            ],
        }

    @router.post("/call")
    async def call_tool(body: dict[str, Any]):
        """
        Call an MCP tool.

        Body: { "server": "filesystem", "tool": "read_file", "args": {...} }
        """
        server_name = body.get("server", "")
        tool_name = body.get("tool", "")
        arguments = body.get("args", {})
        if not server_name or not tool_name:
            raise HTTPException(status_code=400, detail="server and tool are required")
        result = await registry.call_tool(server_name, tool_name, arguments)
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(status_code=502, detail=result["error"])
        return {"result": result}

    app.include_router(router)


def _find_server(registry: MCPRegistry, tool) -> str:
    for s in registry._servers.values():
        if tool in s._tools:
            return s.name
    return "unknown"
