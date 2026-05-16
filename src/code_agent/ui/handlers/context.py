from __future__ import annotations

from fastapi import FastAPI, Request

from code_agent.context.manager import ContextManager
from code_agent.ui.html import render_context_html


def register_context_routes(app: FastAPI, ctx_mgr: ContextManager) -> None:
    @app.get("/api/context")
    async def get_context():
        from code_agent.context.display import render_rich_context
        cd = render_rich_context(ctx_mgr)
        cd["entries_list"] = [
            {"content": e.get("content", ""), "tier": e.get("tier", "normal"), "source": e.get("source", ""), "tokens": e.get("tokens", 0)}
            for e in ctx_mgr._entries[-50:]
        ]
        return render_context_html(cd)

    @app.post("/api/context/add")
    async def add_context(req: Request):
        body = await req.json()
        content = body.get("content", "")
        tier = body.get("tier", "normal")
        source = body.get("source", "")
        if content:
            ctx_mgr.add(content, tier=tier, source=source)
        from code_agent.context.display import render_rich_context
        cd = render_rich_context(ctx_mgr)
        cd["entries_list"] = [
            {"content": e.get("content", ""), "tier": e.get("tier", "normal"), "source": e.get("source", ""), "tokens": e.get("tokens", 0)}
            for e in ctx_mgr._entries[-50:]
        ]
        return render_context_html(cd)

    @app.post("/api/context/add-demo")
    async def add_demo_context():
        ctx_mgr.add("System: You are a helpful AI coding agent.", tier="critical", source="system")
        ctx_mgr.add("User: Build a web scraper for news sites.", tier="important", source="user")
        ctx_mgr.add("Scraped https://example.com (120KB HTML, 200 links)", tier="normal", source="webfetch")
        ctx_mgr.add("Analyzed 15 Python files in src/", tier="normal", source="analyze")
        ctx_mgr.add("Search results: web scraping best practices", tier="normal", source="websearch")
        ctx_mgr.add("Debug log: Connection timeout on retry 2", tier="low", source="log")
        ctx_mgr.add("Cache hit for get_page_content: 2.3ms", tier="low", source="cache")
        from code_agent.context.display import render_rich_context
        cd = render_rich_context(ctx_mgr)
        cd["entries_list"] = [
            {"content": e.get("content", ""), "tier": e.get("tier", "normal"), "source": e.get("source", ""), "tokens": e.get("tokens", 0)}
            for e in ctx_mgr._entries[-50:]
        ]
        return render_context_html(cd)

    @app.post("/api/context/clear")
    async def clear_context():
        ctx_mgr.clear()
        from code_agent.context.display import render_rich_context
        cd = render_rich_context(ctx_mgr)
        cd["entries_list"] = []
        return render_context_html(cd)
