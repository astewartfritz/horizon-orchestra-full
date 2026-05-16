from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Callable


class MCPServer:
    def __init__(self, name: str = "code-agent-mcp", version: str = "0.1.0"):
        self.name = name
        self.version = version
        self.tools: dict[str, dict[str, Any]] = {}

    def tool(self, name: str, description: str = "", input_schema: dict[str, Any] | None = None):
        def decorator(fn: Callable) -> Callable:
            self.tools[name] = {
                "fn": fn,
                "description": description,
                "input_schema": input_schema or {"type": "object", "properties": {}},
            }
            return fn
        return decorator

    async def run_stdio(self) -> None:
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(
            lambda: protocol, sys.stdin
        )

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.Protocol, sys.stdout
        )

        buffer = ""
        while True:
            line = await reader.readline()
            if not line:
                break
            buffer += line.decode()

            if "\r\n\r\n" in buffer:
                header, body = buffer.split("\r\n\r\n", 1)
                length = 0
                for h in header.split("\r\n"):
                    if h.lower().startswith("content-length:"):
                        length = int(h.split(":")[1].strip())
                if len(body) >= length:
                    msg = json.loads(body[:length])
                    resp = await self._handle(msg)
                    if resp:
                        resp_data = json.dumps(resp)
                        resp_header = f"Content-Length: {len(resp_data)}\r\n\r\n"
                        writer_transport.write((resp_header + resp_data).encode())
                        await asyncio.sleep(0)
                    buffer = body[length:]

    async def _handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "0.1.0",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.name, "version": self.version},
                },
            }
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": [
                        {
                            "name": name,
                            "description": info["description"],
                            "inputSchema": info["input_schema"],
                        }
                        for name, info in self.tools.items()
                    ]
                },
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            tool = self.tools.get(tool_name)
            if not tool:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
                }
            try:
                result = await tool["fn"](**arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": str(result)}]},
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32000, "message": str(e)},
                }
        return None
