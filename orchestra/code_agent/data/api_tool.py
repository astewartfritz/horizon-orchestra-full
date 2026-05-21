from __future__ import annotations

import json
from typing import Any

import httpx

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class ApiTool(Tool):
    spec = ToolSpec(
        name="api",
        description="Make HTTP requests to external APIs (GET, POST, PUT, DELETE, PATCH). Supports JSON, form data, file uploads, and custom headers.",
        parameters={
            "url": {"type": "string", "description": "Request URL"},
            "method": {"type": "string", "description": "HTTP method (GET, POST, PUT, DELETE, PATCH)", "default": "GET"},
            "headers": {"type": "string", "description": "JSON object of custom headers", "default": "{}"},
            "body": {"type": "string", "description": "Request body (JSON string, form data, or raw)", "default": ""},
            "content_type": {"type": "string", "description": "Content-Type override", "default": ""},
            "timeout": {"type": "integer", "description": "Request timeout in seconds", "default": 30},
            "follow_redirects": {"type": "boolean", "description": "Follow redirects", "default": True},
        },
    )

    async def __call__(
        self, url: str, method: str = "GET",
        headers: str = "{}", body: str = "",
        content_type: str = "", timeout: int = 30,
        follow_redirects: bool = True,
    ) -> ToolResult:
        try:
            parsed_headers: dict[str, str] = json.loads(headers) if headers else {}
            if content_type and "Content-Type" not in parsed_headers:
                parsed_headers["Content-Type"] = content_type

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                follow_redirects=follow_redirects,
            ) as client:
                method_upper = method.upper()
                kwargs: dict[str, Any] = {"headers": parsed_headers}

                if method_upper in ("POST", "PUT", "PATCH"):
                    ct = parsed_headers.get("Content-Type", "")
                    if "application/json" in ct or not body.startswith("{"):
                        kwargs["content"] = body
                    else:
                        try:
                            kwargs["json"] = json.loads(body)
                        except json.JSONDecodeError:
                            kwargs["content"] = body

                resp = await client.request(method_upper, url, **kwargs)
                resp_content = resp.text
                if len(resp_content) > 100000:
                    resp_content = resp_content[:100000] + "\n...(truncated)"

                summary = f"{resp.status_code} {method_upper} {url}\n"
                headers_out = dict(resp.headers)
                summary += f"Headers: {json.dumps({k: headers_out[k] for k in list(headers_out)[:10]})}\n\n"

                try:
                    parsed = json.loads(resp_content)
                    summary += json.dumps(parsed, indent=2)[:8000]
                except (json.JSONDecodeError, ValueError):
                    summary += resp_content[:8000]

                return ToolResult(output=summary)

        except httpx.TimeoutException:
            return ToolResult(error=f"Request timed out after {timeout}s")
        except httpx.HTTPError as e:
            return ToolResult(error=f"HTTP error: {e}")
        except Exception as e:
            return ToolResult(error=str(e))
