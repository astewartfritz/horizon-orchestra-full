"""ASGI middleware: inject a 30-minute idle-logout timer into all HTML responses.

For healthcare and legal compliance (HIPAA session timeouts, privilege protection).
The timer resets on any user interaction and redirects to /logout on expiry.
"""
from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

# Idle timeout in seconds — configurable via env var
_IDLE_SECONDS = int(os.environ.get("SESSION_IDLE_TIMEOUT", "1800"))  # 30 min default

_IDLE_SCRIPT = f"""<script>
(function(){{
  var _idle={_IDLE_SECONDS}*1000, _t;
  function _reset(){{clearTimeout(_t);_t=setTimeout(function(){{
    document.cookie='session=;Max-Age=0;path=/';
    window.location.href='/login?reason=idle';
  }},_idle);}}
  ['mousedown','mousemove','keydown','touchstart','scroll','click'].forEach(function(e){{
    document.addEventListener(e,_reset,{{passive:true}});
  }});
  _reset();
}})();
</script></body>"""

_BODY_CLOSE = b"</body>"


class IdleTimeoutMiddleware:
    """Inject idle-timeout script before </body> in HTML responses."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_type = ""
        body_chunks: list[bytes] = []

        start_message: dict = {}

        async def patched_send(message: dict) -> None:
            nonlocal content_type

            if message["type"] == "http.response.start":
                # Extract content-type from headers list — ASGI headers are (bytes, bytes) tuples
                for name, value in message.get("headers", []):
                    if name.lower() == b"content-type":
                        content_type = value.decode("utf-8", errors="replace")
                        break
                if "text/html" in content_type:
                    # Buffer start message — we must remove Content-Length so uvicorn
                    # doesn't close the connection when we inject extra bytes into the body
                    new_headers = [
                        (n, v) for n, v in message.get("headers", [])
                        if n.lower() != b"content-length"
                    ]
                    start_message.update({**message, "headers": new_headers})
                else:
                    await send(message)

            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                more = message.get("more_body", False)

                if "text/html" in content_type:
                    # Buffer all chunks; inject into the final assembled body
                    body_chunks.append(body)
                    if not more:
                        full = b"".join(body_chunks)
                        script_bytes = _IDLE_SCRIPT.encode("utf-8")
                        if _BODY_CLOSE in full:
                            full = full.replace(_BODY_CLOSE, script_bytes, 1)
                        else:
                            full += script_bytes
                        # Now send the buffered start message (without Content-Length) then body
                        await send(start_message)
                        await send({"type": "http.response.body", "body": full, "more_body": False})
                    # While more chunks are coming, buffer silently — send when done
                else:
                    await send(message)

            else:
                await send(message)

        await self.app(scope, receive, patched_send)


def register_idle_timeout_middleware(app: Any) -> None:
    from starlette.middleware import Middleware
    app.add_middleware(IdleTimeoutMiddleware)
