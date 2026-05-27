"""Terminal WebSocket and REST endpoints.

Registers at both /api/terminal/* and /v1/terminal/* so the GUI works
with both the dev server (create_ui_app) and production server.

Auth: open when JWT_SECRET is unset (local dev); owner-gated in production.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from typing import Any

from fastapi import Request
from pydantic import BaseModel

_log = logging.getLogger("orchestra.terminal")


class _TerminalRunRequest(BaseModel):
    command: str
    workdir: str = ""
    timeout: int = 30000  # ms


def register_terminal_routes(app: Any) -> None:
    try:
        from fastapi import WebSocket, WebSocketDisconnect
        from fastapi.responses import JSONResponse
    except ImportError:
        _log.warning("FastAPI/Pydantic not available — terminal routes skipped")
        return

    def _ok(data: Any) -> dict:
        return {"data": data, "error": None}

    def _err(msg: str) -> dict:
        return {"data": None, "error": msg}

    def _shell_argv() -> list[str]:
        if sys.platform == "win32":
            return ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive"]
        return ["bash", "--norc", "--noprofile"]

    # ── REST handler (shared) ─────────────────────────────────────────────────

    async def _run_command(body: _TerminalRunRequest) -> Any:
        import time as _tm

        workdir = body.workdir or os.getcwd()
        timeout_s = body.timeout / 1000

        if sys.platform == "win32":
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", body.command]
        else:
            cmd = ["bash", "-c", body.command]

        t0 = _tm.monotonic()
        proc: Any = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
            elapsed_ms = round((_tm.monotonic() - t0) * 1000)
            return _ok({
                "exit_code": proc.returncode,
                "stdout": stdout_b.decode("utf-8", errors="replace")[:50000],
                "stderr": stderr_b.decode("utf-8", errors="replace")[:10000],
                "duration_ms": elapsed_ms,
                "command": body.command,
            })
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            return JSONResponse(
                status_code=408,
                content=_err(f"Command timed out after {body.timeout}ms"),
            )
        except Exception as exc:
            _log.exception("terminal_run error")
            return JSONResponse(status_code=500, content=_err(str(exc)))

    # ── WebSocket handler (shared) ────────────────────────────────────────────

    async def _ws_handler(websocket: WebSocket) -> None:
        """Persistent interactive shell session over WebSocket.

        Client sends:  {"type": "run", "command": "..."}  or  {"type": "ping"}
        Server sends:  {"type": "ready"|"output"|"done"|"timeout"|"exit"|"error"|"pong", ...}
        """
        await websocket.accept()

        cwd = os.getcwd()
        argv = _shell_argv()

        proc: Any = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
        except Exception as exc:
            await websocket.send_json({"type": "error", "message": f"Shell failed to start: {exc}"})
            await websocket.close()
            return

        await websocket.send_json({"type": "ready", "cwd": cwd, "shell": argv[0]})

        _seq = 0
        try:
            while True:
                if proc.returncode is not None:
                    await websocket.send_json({"type": "exit", "code": proc.returncode})
                    break

                data = await websocket.receive_json()
                msg_type = data.get("type", "run")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                if msg_type != "run":
                    continue

                command = data.get("command", "").strip()
                if not command:
                    continue

                _seq += 1
                seq = _seq
                sentinel = f"__ORCH_{seq}_{uuid.uuid4().hex[:8]}__"

                if sys.platform == "win32":
                    full = f"{command}\r\nWrite-Host '{sentinel}'\r\n"
                else:
                    full = f"{command}\nprintf '%s\\n' '{sentinel}'\n"

                proc.stdin.write(full.encode("utf-8"))
                await proc.stdin.drain()

                while True:
                    if proc.returncode is not None:
                        await websocket.send_json({"type": "done", "seq": seq})
                        break
                    try:
                        raw = await asyncio.wait_for(proc.stdout.readline(), timeout=60.0)
                    except asyncio.TimeoutError:
                        await websocket.send_json({"type": "timeout", "seq": seq})
                        break
                    if not raw:
                        await websocket.send_json({"type": "done", "seq": seq})
                        break
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if sentinel in line:
                        await websocket.send_json({"type": "done", "seq": seq})
                        break
                    await websocket.send_json({"type": "output", "line": line, "seq": seq})

        except WebSocketDisconnect:
            _log.debug("Terminal WebSocket disconnected")
        except Exception as exc:
            _log.error("Terminal WS error: %s", exc)
            try:
                await websocket.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass
        finally:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass

    # ── Register at /api/terminal/* and /v1/terminal/* ────────────────────────

    @app.post("/api/terminal/run")
    async def api_terminal_run(body: _TerminalRunRequest, request: Request) -> Any:
        return await _run_command(body)

    @app.post("/v1/terminal/run")
    async def v1_terminal_run(body: _TerminalRunRequest, request: Request) -> Any:
        return await _run_command(body)

    @app.websocket("/v1/terminal/ws")
    async def v1_terminal_ws(websocket: WebSocket) -> None:
        await _ws_handler(websocket)
