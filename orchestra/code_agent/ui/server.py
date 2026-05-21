from __future__ import annotations

import logging
import os
from pathlib import Path

_log = logging.getLogger("orchestra.server")

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from orchestra.code_agent.settings import settings as _settings
from orchestra.code_agent.config import AgentConfig
from orchestra.code_agent.context.manager import ContextManager
from orchestra.code_agent.session import SessionManager
from orchestra.code_agent.ui.html import UI_HTML
from orchestra.code_agent.ui.create import CREATE_HTML
from orchestra.code_agent.ui.finance import FINANCE_HTML, FINANCE_APP_HTML
from orchestra.code_agent.ui.healthcare import HEALTHCARE_HTML, HEALTHCARE_APP_HTML
from orchestra.code_agent.ui.settings_page import SETTINGS_PAGE_HTML
from orchestra.code_agent.ui.logistics import LOGISTICS_HTML, LOGISTICS_APP_HTML
from orchestra.code_agent.ui.legal import LEGAL_HTML, LEGAL_APP_HTML
from orchestra.code_agent.ui.build_orchestrator import BUILD_BRAND_HTML, BUILD_DASHBOARD_HTML
from orchestra.code_agent.ui.handlers.chat import register_chat_routes
from orchestra.code_agent.ui.handlers.sessions import register_session_routes
from orchestra.code_agent.ui.handlers.v1_compat import register_v1_compat_routes
from orchestra.code_agent.ui.handlers.auth_web import register_auth_web_routes
from orchestra.code_agent.ui.handlers.context import register_context_routes
from orchestra.code_agent.ui.handlers.skills import register_skills_routes
from orchestra.code_agent.ui.handlers.prince import register_prince_routes


def create_ui_app(agent_config: AgentConfig | None = None) -> FastAPI:
    if not HAS_FASTAPI:
        raise ImportError("fastapi is required. Install with: pip install code-agent[server]")

    app = FastAPI(title="Orchestra", version="0.8.0",
                  description="Agentic AI orchestration platform with multi-model routing, security middleware, agent-aware API headers, billing, and AI-for-science.",
                  contact={"name": "Orchestra Team", "url": "https://github.com/anomalyco/Orchestra_Full"},
                  license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
                  docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # Observability — install before any routes so everything is captured
    try:
        from orchestra.code_agent.observability import (
            ObservabilityMiddleware, install_handler, register_log_routes,
        )
        app.add_middleware(ObservabilityMiddleware)
        install_handler()
        register_log_routes(app)
    except Exception as _e:
        _log.warning("Observability middleware unavailable: %s", _e)

    # Sentry error tracking — graceful if DSN or sentry_sdk is missing
    try:
        from orchestra.code_agent.monitor.sentry import register_sentry
        register_sentry(app)
    except Exception as _e:
        _log.debug("Sentry not configured: %s", _e)

    # HTTP rate limiting — before CSRF and route handlers
    try:
        from orchestra.code_agent.ui.handlers.rate_limit import register_rate_limit_middleware
        register_rate_limit_middleware(app)
    except Exception as _e:
        import logging as _lg
        _lg.getLogger("orchestra").warning("rate_limit middleware failed: %s", _e)

    # CSRF protection — after CORS, before all route handlers
    try:
        from orchestra.code_agent.ui.handlers.csrf import register_csrf_middleware
        register_csrf_middleware(app)
    except ImportError:
        pass

    # Agent-aware security middleware — capability auth, PII redaction,
    # audit trail, anomaly detection, human-in-the-loop approval.
    try:
        from orchestra.code_agent.security.middleware import register_security
        register_security(app)
    except Exception as _e:
        _log.warning("Security middleware unavailable: %s", _e)

    # Agent-specific API headers — context IDs, intent, role, identity,
    # tokens, data freshness, rate-limit and error recovery headers.
    try:
        from orchestra.code_agent.agent_headers.middleware import (
            register_agent_headers_middleware,
        )
        register_agent_headers_middleware(app)
    except Exception as _e:
        _log.debug("Agent headers middleware unavailable: %s", _e)

    # Database migrations — run at startup, idempotent
    try:
        from orchestra.code_agent.db import run_startup_migrations
        run_startup_migrations()
    except Exception as _e:
        import logging as _lg
        _lg.getLogger("orchestra").warning("DB migrations failed: %s", _e)

    # Health check endpoints — machine-readable + ECS-compatible
    try:
        from orchestra.code_agent.health.routes import register_health_routes
        register_health_routes(app)
    except Exception as _e:
        _log.warning("Health routes unavailable: %s", _e)

    # Prometheus /metrics endpoint
    try:
        from orchestra.code_agent.monitor.routes import register_monitor_routes
        register_monitor_routes(app)
    except Exception as _e:
        _log.debug("Monitor routes unavailable: %s", _e)

    # Structured JSON logging
    try:
        from orchestra.code_agent.logging.json import setup_json_logging
        if os.environ.get("ORCHESTRA_JSON_LOGS", "").lower() in ("1", "true", "yes"):
            setup_json_logging()
    except Exception as _e:
        _log.debug("JSON logging setup failed: %s", _e)

    # SLA monitoring routes
    try:
        from orchestra.code_agent.sla.routes import register_sla_routes
        register_sla_routes(app)
    except Exception as _e:
        _log.debug("SLA routes unavailable: %s", _e)

    # Redis-backed rate limiting (graceful fallback to in-memory)
    try:
        from orchestra.middleware.rate_limit import RateLimitMiddleware
        import asyncio
        _redis_url = os.environ.get("REDIS_URL", "")
        if _redis_url:
            _rl = asyncio.get_event_loop().run_until_complete(
                RateLimitMiddleware.create(redis_url=_redis_url)
            )
            app.state.rate_limiter = _rl
    except Exception:
        pass

    # ADK — Agent Development Kit API routes
    try:
        from orchestra.code_agent.adk.routes import register_adk_routes
        register_adk_routes(app)
    except Exception:
        pass

    # Cloud-configurable paths
    _ws = os.environ.get("ORCHESTRA_WORKSPACE") or str(Path.cwd().resolve())
    _session_dir = os.environ.get("ORCHESTRA_SESSION_DIR") or str(Path(_ws) / ".agent-sessions")
    sessions = SessionManager(path=_session_dir)
    ctx_mgr = ContextManager()
    workspace = _ws

    # Auto-seed skills on first run
    try:
        from orchestra.code_agent.skills.base import SkillLibrary
        if SkillLibrary().count() == 0:
            from orchestra.code_agent.skills.seed import seed_library
            n = seed_library()
            if n:
                import logging as _lg
                _lg.getLogger("orchestra").info("Auto-seeded %d skills", n)
    except Exception:
        pass

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return UI_HTML

    @app.get("/app", response_class=HTMLResponse)
    async def app_page():
        return UI_HTML

    @app.get("/create", response_class=HTMLResponse)
    async def create_page():
        return CREATE_HTML

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page():
        return SETTINGS_PAGE_HTML

    @app.get("/healthcare", response_class=HTMLResponse)
    async def healthcare_page():
        return HEALTHCARE_HTML

    @app.get("/healthcare/app", response_class=HTMLResponse)
    async def healthcare_app():
        return HEALTHCARE_APP_HTML

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

    @app.get("/legal", response_class=HTMLResponse)
    async def legal_page():
        return LEGAL_HTML

    @app.get("/legal/app", response_class=HTMLResponse)
    async def legal_app():
        return LEGAL_APP_HTML

    @app.get("/build", response_class=HTMLResponse)
    async def build_page():
        return BUILD_BRAND_HTML

    @app.get("/build/app", response_class=HTMLResponse)
    async def build_app():
        return BUILD_DASHBOARD_HTML

    @app.get("/api/admin/migrations")
    async def migration_status():
        from orchestra.code_agent.db import MigrationEngine
        from orchestra.code_agent.settings import settings as _s
        engine = MigrationEngine(db_url=f"sqlite:///{_s.billing_db_path}")
        applied = set(engine.status())
        from orchestra.code_agent.db.migrations import _MIGRATIONS
        return {"migrations": [
            {"version": m.version, "name": m.name, "applied": m.version in applied}
            for m in _MIGRATIONS
        ]}

    @app.get("/api/admin/readiness")
    async def readiness_check():
        import time as _time
        checks: list[dict] = []

        def _check(name: str, passed: bool, detail: str = "") -> None:
            checks.append({"name": name, "passed": passed, "detail": detail})

        # Security
        _check("jwt_secret_set", bool(_settings.jwt_secret and len(_settings.jwt_secret) >= 32),
               "JWT_SECRET must be at least 32 chars")
        _check("api_key_encryption_set", bool(_settings.api_key_encryption_key and len(_settings.api_key_encryption_key) >= 32),
               "API_KEY_ENCRYPTION_KEY must be at least 32 chars")
        _check("cors_not_wildcard_in_prod",
               _settings.env != "production" or "*" not in _settings.cors_origins,
               "CORS_ORIGINS must not be wildcard in production")
        _check("env_set", _settings.env in ("development", "production"),
               f"ORCHESTRA_ENV={_settings.env!r}")
        _check("rate_limiting_on", _settings.rate_limit_enabled, "Set RATE_LIMIT_ENABLED=true")

        # API keys
        _check("anthropic_key_available",
               bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY not set in env")
        _check("openai_key_available",
               bool(os.environ.get("OPENAI_API_KEY")), "OPENAI_API_KEY not set in env (optional)")

        # Database
        try:
            from orchestra.code_agent.db import MigrationEngine
            from orchestra.code_agent.db.migrations import _MIGRATIONS
            engine = MigrationEngine(db_url=f"sqlite:///{_settings.billing_db_path}")
            applied = set(engine.status())
            all_applied = len(applied) >= len(_MIGRATIONS)
            _check("migrations_applied", all_applied,
                   f"{len(applied)}/{len(_MIGRATIONS)} applied")
        except Exception as _e:
            _check("migrations_applied", False, str(_e))

        # Billing
        _check("stripe_configured", bool(os.environ.get("STRIPE_SECRET_KEY")),
               "STRIPE_SECRET_KEY not set")

        # Observability
        _check("sentry_configured", bool(os.environ.get("SENTRY_DSN")), "SENTRY_DSN not set (optional)")
        _check("json_logging", os.environ.get("ORCHESTRA_JSON_LOGS", "").lower() in ("1", "true", "yes"),
               "Set ORCHESTRA_JSON_LOGS=true in production")

        passed = sum(1 for c in checks if c["passed"])
        total = len(checks)
        score = round(passed / total * 100) if total else 0

        return {
            "score": score,
            "passed": passed,
            "total": total,
            "env": _settings.env,
            "ts": _time.time(),
            "checks": checks,
        }

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
    try:
        from orchestra.code_agent.ui.handlers.github import register_github_routes
        register_github_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.ui.handlers.runs import register_runs_routes, RunStore
        RunStore.get()  # init DB
        register_runs_routes(app)
    except Exception:
        pass
    # Server-side API key storage (replaces localStorage)
    try:
        from orchestra.code_agent.api_keys import register_api_key_routes, ApiKeyStore
        ApiKeyStore.get()  # init DB
        register_api_key_routes(app)
    except Exception as _e:
        import logging as _lg
        _lg.getLogger("orchestra").warning("api_keys init failed: %s", _e)

    # Billing — Stripe integration
    try:
        from orchestra.code_agent.billing.routes import register_billing_routes
        from orchestra.code_agent.billing.store import SubscriptionStore
        SubscriptionStore.get()  # initialise DB
        register_billing_routes(app)
    except Exception:
        pass

    # MCP Gateway — load .mcp.json and register API routes
    try:
        from orchestra.code_agent.mcp.registry import MCPRegistry
        from orchestra.code_agent.mcp.routes import register_mcp_routes
        _mcp_config = Path(__file__).parent.parent.parent.parent / ".mcp.json"
        MCPRegistry.get().load(_mcp_config if _mcp_config.exists() else None)
        register_mcp_routes(app)
    except Exception:
        pass

    # Orchestra Finance API
    try:
        from orchestra.code_agent.finance.routes import register_finance_routes
        register_finance_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.logistics.routes import register_logistics_routes
        register_logistics_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.healthcare.routes import register_healthcare_routes
        register_healthcare_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.legal.routes import register_legal_routes
        register_legal_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.self_improve.routes import register_self_improve_routes
        register_self_improve_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.build_orchestrator.routes import register_build_routes
        register_build_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.orchestrator.router.routes import register_router_orchestrator_routes
        register_router_orchestrator_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.scaling.routes import register_scaling_routes
        register_scaling_routes(app, redis_url="redis://localhost:6379/0")
    except Exception:
        pass
    try:
        from orchestra.code_agent.agentmesh.routes import register_agentmesh_routes
        register_agentmesh_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.teams.routes import register_teams_routes
        register_teams_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.channels.gateway_routes import register_channel_gateway_routes
        register_channel_gateway_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.workflow_v2.routes import register_workflow_v2_routes
        register_workflow_v2_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.reasoning.routes import register_reasoning_routes
        register_reasoning_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.monitor.routes import register_monitor_routes
        register_monitor_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.telemetry.routes import register_telemetry_routes
        register_telemetry_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.nemotron.routes import register_nemotron_routes
        register_nemotron_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.council.routes import register_council_routes
        register_council_routes(app)
    except Exception:
        pass
    try:
        from orchestra_science.server.routes import register_science_routes
        register_science_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.rl.routes import register_rl_routes
        register_rl_routes(app)
    except Exception:
        pass
    try:
        from orchestra.code_agent.dashboard.routes import register_dashboard_routes
        register_dashboard_routes(app)
    except Exception:
        pass
    # Multi-channel webhooks (Python-native adapters)
    from orchestra.code_agent.channels import MessageRouter, register_channel_webhooks
    _router = MessageRouter(agent_config)
    register_channel_webhooks(app, _router)
    # TypeScript channels bridge (Slack, Telegram, WhatsApp, Discord, iMessage, Email via TS server)
    from orchestra.code_agent.channels.bridge import register_channel_bridge_routes
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

    # Web auth pages — login, signup, getting started (HTMX, cookie-based)
    register_auth_web_routes(app)

    # v1 compat shim — powers gui/orchestra-gui (MILES SPA)
    register_v1_compat_routes(app)

    # Mount the full MILES SPA at /miles/ — must come after all explicit routes
    _gui_dir = Path(__file__).parent.parent.parent.parent / "gui" / "orchestra-gui"
    if _gui_dir.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/miles", StaticFiles(directory=str(_gui_dir), html=True), name="miles-spa")

    return app
