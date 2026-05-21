from __future__ import annotations

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class WebFetchTool(Tool):
    spec = ToolSpec(
        name="webfetch",
        description="Fetch content from a URL and return it as markdown or text.",
        parameters={
            "url": {"type": "string", "description": "The URL to fetch"},
            "format": {
                "type": "string",
                "description": "Output format: markdown, text, or html",
                "default": "markdown",
            },
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
        },
    )

    async def __call__(self, url: str, format: str = "markdown", timeout: int = 30) -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx is not installed. Install with: pip install code-agent[server]")
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "CodeAgent/1.0"})
                resp.raise_for_status()
                content = resp.text
                if format == "text":
                    import re
                    content = re.sub(r"<[^>]+>", "", content)
                    content = re.sub(r"\s+", " ", content).strip()
                return ToolResult(output=content[:50000])
        except Exception as e:
            return ToolResult(error=str(e))


class WebSearchTool(Tool):
    spec = ToolSpec(
        name="websearch",
        description="Search the web for information. Returns summarized results from relevant pages.",
        parameters={
            "query": {"type": "string", "description": "Search query"},
            "num_results": {"type": "integer", "description": "Number of results to return", "default": 8},
        },
    )

    async def __call__(self, query: str, num_results: int = 8) -> ToolResult:
        if not HAS_HTTPX:
            return ToolResult(error="httpx is not installed.")
        try:
            url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "CodeAgent/1.0"})
                resp.raise_for_status()

                import re
                results = []
                for match in re.finditer(
                    r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                    resp.text, re.DOTALL
                ):
                    href = match.group(1)
                    title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
                    results.append(f"{title}\n  {href}")

                if results:
                    return ToolResult(output="\n".join(results[:num_results]))
                return ToolResult(output="(no search results found)")
        except Exception as e:
            return ToolResult(error=str(e))
