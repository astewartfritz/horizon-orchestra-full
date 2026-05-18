from __future__ import annotations

import os
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from code_agent.config import AgentConfig
from code_agent.context.manager import ContextManager
from code_agent.session import SessionManager
from code_agent.ui.html import UI_HTML
from code_agent.ui.create import CREATE_HTML
from code_agent.ui.finance import FINANCE_HTML, FINANCE_APP_HTML
from code_agent.ui.logistics import LOGISTICS_HTML, LOGISTICS_APP_HTML
from code_agent.ui.build_orchestrator import BUILD_BRAND_HTML, BUILD_DASHBOARD_HTML
from code_agent.ui.handlers.chat import register_chat_routes
from code_agent.ui.handlers.sessions import register_session_routes
from code_agent.ui.handlers.context import register_context_routes
from code_agent.ui.handlers.skills import register_skills_routes
from code_agent.ui.handlers.prince import register_prince_routes


def create_ui_app(agent_config: AgentConfig | None = None) -> FastAPI:
    if not HAS_FASTAPI:
        raise ImportError("fastapi is required. Install with: pip install code-agent[server]")

    app = FastAPI(title="Orchestra")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    # Cloud-configurable paths
    _ws = os.environ.get("ORCHESTRA_WORKSPACE") or str(Path.cwd().resolve())
    _session_dir = os.environ.get("ORCHESTRA_SESSION_DIR") or str(Path(_ws) / ".agent-sessions")
    sessions = SessionManager(path=_session_dir)
    ctx_mgr = ContextManager()
    workspace = _ws

    # Auto-seed skills on first run
    try:
        from code_agent.skills.base import SkillLibrary
        if SkillLibrary().count() == 0:
            from code_agent.skills.seed import seed_library
            n = seed_library()
            if n:
                import logging as _lg
                _lg.getLogger("orchestra").info("Auto-seeded %d skills", n)
    except Exception:
        pass

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return UI_HTML

    @app.get("/create", response_class=HTMLResponse)
    async def create_page():
        return CREATE_HTML

    @app.get("/finance", response_class=HTMLResponse)
    async def finance_page():
        return FINANCE_HTML

    @app.get("/finance/app", response_class=HTMLResponse)
    async def finance_app():
        return FINANCE_APP_HTML

    @app.get("/logistics", response_class=HTMLResponse)
    async def logistics_page():
        return LOGISTICS_HTML

    @app.get("/logistics/app", response_class=HTMLResponse)
    async def logistics_app():
        return LOGISTICS_APP_HTML

    @app.get("/build", response_class=HTMLResponse)
    async def build_page():
        return BUILD_BRAND_HTML

    @app.get("/build/app", response_class=HTMLResponse)
    async def build_app():
        return BUILD_DASHBOARD_HTML

    _ALLOWED_MANIFESTS = {"Cargo.toml", "package.json", "pyproject.toml", "mojoproject.toml",
                          "tsconfig.json", "setup.py", "setup.cfg", "Cargo.lock"}

    for _mf in _ALLOWED_MANIFESTS:
        @app.head("/" + _mf)
        async def _check_mf(_f=_mf):
            if (Path(workspace) / _f).exists():
                from fastapi.responses import Response
                return Response(status_code=200)
            raise HTTPException(status_code=404)

    register_session_routes(app, sessions)
    register_context_routes(app, ctx_mgr)
    register_chat_routes(app, sessions, ctx_mgr, agent_config, workspace)
    register_skills_routes(app)
    register_prince_routes(app)
    # Orchestra Finance API
    try:
        from code_agent.finance.routes import register_finance_routes
        register_finance_routes(app)
    except Exception:
        pass
    try:
        from code_agent.logistics.routes import register_logistics_routes
        register_logistics_routes(app)
    except Exception:
        pass
    try:
        from code_agent.build_orchestrator.routes import register_build_routes
        register_build_routes(app)
    except Exception:
        pass
    try:
        from code_agent.orchestrator.router.routes import register_router_orchestrator_routes
        register_router_orchestrator_routes(app)
    except Exception:
        pass
    try:
        from code_agent.scaling.routes import register_scaling_routes
        register_scaling_routes(app, redis_url="redis://localhost:6379/0")
    except Exception:
        pass
    try:
        from code_agent.agentmesh.routes import register_agentmesh_routes
        register_agentmesh_routes(app)
    except Exception:
        pass
    try:
        from code_agent.teams.routes import register_teams_routes
        register_teams_routes(app)
    except Exception:
        pass
    try:
        from code_agent.channels.gateway_routes import register_channel_gateway_routes
        register_channel_gateway_routes(app)
    except Exception:
        pass
    try:
        from code_agent.workflow_v2.routes import register_workflow_v2_routes
        register_workflow_v2_routes(app)
    except Exception:
        pass
    try:
        from code_agent.reasoning.routes import register_reasoning_routes
        register_reasoning_routes(app)
    except Exception:
        pass
    try:
        from code_agent.monitor.routes import register_monitor_routes
        register_monitor_routes(app)
    except Exception:
        pass
    try:
        from code_agent.telemetry.routes import register_telemetry_routes
        register_telemetry_routes(app)
    except Exception:
        pass
    try:
        from code_agent.nemotron.routes import register_nemotron_routes
        register_nemotron_routes(app)
    except Exception:
        pass
    # Multi-channel webhooks (Python-native adapters)
    from code_agent.channels import MessageRouter, register_channel_webhooks
    _router = MessageRouter(agent_config)
    register_channel_webhooks(app, _router)
    # TypeScript channels bridge (Slack, Telegram, WhatsApp, Discord, iMessage, Email via TS server)
    from code_agent.channels.bridge import register_channel_bridge_routes
    register_channel_bridge_routes(app)

    # PWA manifest
    from fastapi.responses import JSONResponse

    @app.get("/manifest.json")
    async def manifest():
        return JSONResponse({
            "name": "Orchestra",
            "short_name": "Orchestra",
            "description": "Autonomous AI software engineering assistant",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0d1117",
            "theme_color": "#0d1117",
            "orientation": "portrait",
            "categories": ["developer-tools", "ai"],
            "icons": [{
                "src": "/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }, {
                "src": "/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
            }, {
                "src": "/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
            }],
        })

    # PWA icon (inline SVG)
    @app.get("/icon.svg")
    async def icon_svg():
        from fastapi.responses import Response
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="20" fill="#0d1117"/><text x="50" y="62" font-family="system-ui" font-size="36" font-weight="700" fill="#58a6ff" text-anchor="middle">O</text><circle cx="75" cy="28" r="6" fill="#3fb950"/></svg>'
        return Response(content=svg, media_type="image/svg+xml")

    # PWA icons (minimal PNG placeholders — real icons should be generated)
    @app.get("/icon-192.png")
    @app.get("/icon-512.png")
    async def icon_png():
        from fastapi.responses import Response
        # 1x1 transparent PNG
        return Response(content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\x15\xc4\x89\x00\x00\x00\x00IEND\xae\x42\x60\x82", media_type="image/png")

    # Service worker for offline support
    @app.get("/sw.js")
    async def service_worker():
        sw = """self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.url.includes('/api/')) return;
  e.respondWith((async () => {
    try { return await fetch(e.request); } catch { return new Response('Offline', {status:503}); }
  })());
});"""
        from fastapi.responses import Response
        return Response(content=sw, media_type="application/javascript")

    return app
