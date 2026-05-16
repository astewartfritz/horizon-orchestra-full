from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from code_agent.tools.base import Tool, ToolResult, ToolSpec


@dataclass
class MCPToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]


class MCPTool(Tool):
    def __init__(self, name: str, description: str, input_schema: dict[str, Any], call_fn):
        params = {}
        required = input_schema.get("required", [])
        properties = input_schema.get("properties", {})

        for pname, pinfo in properties.items():
            params[pname] = {
                "type": pinfo.get("type", "string"),
                "description": pinfo.get("description", ""),
            }
            if pname not in required:
                params[pname]["default"] = None

        self.spec = ToolSpec(
            name=name,
            description=description,
            parameters=params,
        )
        self._call_fn = call_fn

    async def __call__(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self._call_fn(kwargs)
            return ToolResult(output=json.dumps(result, indent=2))
        except Exception as e:
            return ToolResult(error=str(e))


class MCPClient:
    def __init__(self, command: str, args: list[str] | None = None):
        self.command = command
        self.args = args or []
        self._process = None
        self._tools: list[MCPTool] = []

    async def connect(self) -> list[MCPTool]:
        import asyncio

        self._process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        init_req = json.dumps({
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "0.1.0",
                "capabilities": {},
                "clientInfo": {"name": "code-agent", "version": "0.1.0"},
            },
            "id": 1,
        })
        self._send(init_req)
        resp = await self._recv()

        tools_req = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 2,
        })
        self._send(tools_req)
        resp = await self._recv()

        if resp and "result" in resp:
            tools_data = resp["result"].get("tools", [])
            self._tools = []
            for t in tools_data:
                tool = MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    call_fn=self._make_call(t["name"]),
                )
                self._tools.append(tool)
            return self._tools
        return []

    def _make_call(self, tool_name: str):
        async def call_fn(args: dict[str, Any]) -> Any:
            req = json.dumps({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": args},
                "id": 3,
            })
            self._send(req)
            resp = await self._recv()
            if resp and "result" in resp:
                content = resp["result"].get("content", [])
                return [c for c in content]
            return {"error": resp.get("error", "unknown error")}
        return call_fn

    def _send(self, data: str) -> None:
        if self._process and self._process.stdin:
            msg = f"Content-Length: {len(data)}\r\n\r\n{data}"
            self._process.stdin.write(msg.encode())
            import asyncio
            asyncio.ensure_future(self._process.stdin.drain())

    async def _recv(self) -> dict[str, Any] | None:
        if not self._process or not self._process.stdout:
            return None
        import asyncio
        header = await asyncio.wait_for(self._process.stdout.readline(), timeout=30)
        if not header:
            return None
        length = int(header.decode().strip().split(":")[1])
        blank = await self._process.stdout.readline()
        body = await asyncio.wait_for(
            self._process.stdout.readexactly(length), timeout=30
        )
        return json.loads(body.decode())

    async def close(self) -> None:
        if self._process:
            self._process.terminate()
            await self._process.wait()

    @classmethod
    async def from_config(cls, config_path: str) -> MCPClient:
        p = __import__("pathlib").Path(config_path)
        config = json.loads(p.read_text("utf-8"))
        cmd = config.get("command", "")
        args = config.get("args", [])
        client = cls(cmd, args)
        await client.connect()
        return client
