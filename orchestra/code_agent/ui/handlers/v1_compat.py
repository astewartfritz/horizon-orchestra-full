"""
/v1 compatibility shim for gui/orchestra-gui.

The MILES SPA (gui/orchestra-gui) was built against a /v1 REST API.
These endpoints bridge it to the code_agent server so the SPA
works without any JS changes.
"""
from __future__ import annotations

import collections
import logging
import os
import re
import time
import threading

from fastapi import FastAPI, Form, Header, Request
from fastapi.responses import JSONResponse, Response

from orchestra.code_agent.settings import settings as _settings

_log = logging.getLogger("orchestra.v1_compat")

# ---------------------------------------------------------------------------
# Brute-force protection — in-memory failed-login tracker
# ---------------------------------------------------------------------------
_LOCKOUT_WINDOW  = 900   # 15 min
_LOCKOUT_LIMIT   = 10    # max failed attempts before lockout
_failed: dict[str, list[float]] = collections.defaultdict(list)  # email -> [timestamps]
_failed_lock = threading.Lock()


def _record_failed(email: str) -> None:
    now = time.time()
    with _failed_lock:
        _failed[email] = [t for t in _failed[email] if now - t < _LOCKOUT_WINDOW]
        _failed[email].append(now)


def _is_locked_out(email: str) -> bool:
    now = time.time()
    with _failed_lock:
        recent = [t for t in _failed[email] if now - t < _LOCKOUT_WINDOW]
        _failed[email] = recent
        return len(recent) >= _LOCKOUT_LIMIT


def _clear_failed(email: str) -> None:
    with _failed_lock:
        _failed.pop(email, None)


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{1,63}$")


def _validate_credentials(email: str, password: str) -> str | None:
    """Return error message or None if valid."""
    if not email or not password:
        return "Email and password are required"
    if len(email) > 320:
        return "Email too long"
    if not _EMAIL_RE.match(email):
        return "Invalid email address"
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if len(password) > 128:
        return "Password too long"
    return None

def _jwt():
    from orchestra.code_agent.auth.jwt import JWTManager
    from orchestra.code_agent.settings import settings
    return JWTManager(secret=settings.jwt_secret)


def _safe_user(user: dict) -> dict:
    """Return user dict with sensitive fields stripped."""
    return {k: v for k, v in user.items() if k not in ("password_hash",)}


def _encode_local_token(user_id: str, role: str = "user", tier: str = "free") -> str:
    return _jwt().create_access_token(user_id, role=role, tier=tier, expires_in=604800)


def _decode_local_token(token: str) -> str | None:
    payload = _jwt().verify(token)
    if payload and payload.get("type") == "access":
        return payload.get("sub")
    return None

# Models surfaced to the GUI picker
_MODELS = [
    {"id": "claude-sonnet-4-6",           "name": "Claude Sonnet 4.6",         "provider": "anthropic"},
    {"id": "claude-3-5-sonnet-20241022",  "name": "Claude 3.5 Sonnet",         "provider": "anthropic"},
    {"id": "claude-3-opus-20240229",      "name": "Claude 3 Opus",             "provider": "anthropic"},
    {"id": "claude-haiku-4-5-20251001",   "name": "Claude Haiku 4.5",          "provider": "anthropic"},
    {"id": "gpt-4o",                      "name": "GPT-4o",                    "provider": "openai"},
]


def _wrap(data=None, error=None):
    return {"data": data, "error": error, "meta": {"ts": time.time()}}


async def _call_anthropic(prompt: str, system: str, model: str, temperature: float, max_tokens: int) -> str:
    """Call Anthropic directly. Returns response text or raises."""
    import anthropic  # type: ignore

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Map GUI model IDs to valid Anthropic model IDs
    _model_map = {
        "kimi-k2.5":            "claude-sonnet-4-6",
        "claude-opus":          "claude-3-opus-20240229",
        "gpt-5":                "claude-sonnet-4-6",
        "gemma-4":              "claude-sonnet-4-6",
        "claude-sonnet-4-6":   "claude-sonnet-4-6",
    }
    resolved = _model_map.get(model, model if model.startswith("claude") else "claude-sonnet-4-6")

    msgs = [{"role": "user", "content": prompt}]
    kwargs: dict = dict(model=resolved, messages=msgs, max_tokens=max_tokens or 2048)
    if system:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature

    resp = await client.messages.create(**kwargs)
    return resp.content[0].text if resp.content else ""


async def _call_openai(prompt: str, system: str, model: str, temperature: float, max_tokens: int) -> str:
    import httpx  # type: ignore

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model or "gpt-4o", "messages": messages,
                  "max_tokens": max_tokens or 1024, "temperature": temperature or 0.7},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def register_v1_compat_routes(app: FastAPI) -> None:
    """Register /v1/* compatibility endpoints."""

    from orchestra.code_agent.auth.user_store import UserStore
    from orchestra.code_agent.auth.password import PasswordHasher
    _pw = PasswordHasher()
    _store = UserStore.get()

    def _set_session_cookie(resp: Response, token: str) -> None:
        resp.set_cookie(key="session", value=token, httponly=True, max_age=604800,
                        samesite="lax", secure=_settings.env == "production")

    async def _extract_creds(request: Request) -> tuple[str, str, str]:
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            body = await request.json()
            return (
                body.get("name", ""),
                body.get("email", "").strip().lower(),
                body.get("password", ""),
            )
        form = await request.form()
        return (
            form.get("name", ""),
            form.get("email", "").strip().lower(),
            form.get("password", ""),
        )

    @app.post("/v1/auth/register")
    async def v1_register(request: Request):
        name, email, password = await _extract_creds(request)
        err = _validate_credentials(email, password)
        if err:
            return JSONResponse(_wrap(error=err), status_code=422)
        try:
            user = _store.create_user(email=email, password_hash=_pw.hash(password), name=name)
            access_token = _encode_local_token(user["id"], role=user.get("role","user"), tier=user.get("tier","free"))
            resp = JSONResponse(_wrap({"access_token": access_token, "token_type": "bearer", "user": _safe_user(user)}))
            _set_session_cookie(resp, access_token)
            return resp
        except ValueError as e:
            return JSONResponse(_wrap(error=str(e)), status_code=409)

    @app.post("/v1/auth/login")
    async def v1_login(request: Request):
        _, email, password = await _extract_creds(request)
        if not email or not password:
            return JSONResponse(_wrap(error="Email and password are required"), status_code=422)
        if len(email) > 320 or len(password) > 128:
            return JSONResponse(_wrap(error="Invalid credentials"), status_code=401)
        if _is_locked_out(email):
            return JSONResponse(_wrap(error="Too many failed attempts — try again in 15 minutes"), status_code=429)
        user = _store.get_user_by_email(email)
        if not user or not _pw.verify(password, user["password_hash"]):
            _record_failed(email)
            return JSONResponse(_wrap(error="Invalid email or password"), status_code=401)
        _clear_failed(email)
        access_token = _encode_local_token(user["id"], role=user.get("role","user"), tier=user.get("tier","free"))
        resp = JSONResponse(_wrap({"access_token": access_token, "token_type": "bearer", "user": _safe_user(user)}))
        _set_session_cookie(resp, access_token)
        return resp

    @app.get("/v1/auth/me")
    async def v1_me(request: Request, authorization: str = Header(default="")):
        token = (authorization.removeprefix("Bearer ").strip()
                 or request.cookies.get("session", ""))
        if not token:
            return JSONResponse(_wrap(error="Not authenticated"), status_code=401)
        user_id = _decode_local_token(token)
        if not user_id:
            return JSONResponse(_wrap(error="Invalid or expired token"), status_code=401)
        user = _store.get_user_by_id(user_id)
        if not user:
            return JSONResponse(_wrap(error="User not found"), status_code=404)
        return JSONResponse(_wrap(_safe_user(user)))

    @app.get("/v1/auth/validate")
    async def v1_validate(request: Request, authorization: str = Header(default="")):
        token = (authorization.removeprefix("Bearer ").strip()
                 or request.cookies.get("session", ""))
        user_id = _decode_local_token(token)
        if not user_id:
            return JSONResponse({"valid": False, "error": "Invalid or expired token"})
        user = _store.get_user_by_id(user_id)
        return JSONResponse({"valid": True, "user": _safe_user(user)})

    # ── Models ───────────────────────────────────────────────────────────────
    @app.get("/v1/models")
    async def v1_models():
        return JSONResponse(_wrap(_MODELS))

    # ── Query — direct LLM call ───────────────────────────────────────────────
    @app.post("/v1/query")
    async def v1_query(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(_wrap(error="Invalid JSON"), status_code=400)

        prompt      = body.get("prompt", "")
        model       = body.get("model", "claude-sonnet-4-6")
        system      = body.get("system", "")
        temperature = float(body.get("temperature", 0.7))
        max_tokens  = int(body.get("max_tokens", 2048))

        # Load .env so ANTHROPIC_API_KEY is available if set
        try:
            import pathlib, dotenv  # type: ignore
            dotenv.load_dotenv(pathlib.Path(__file__).resolve().parents[5] / ".env", override=False)
        except Exception:
            pass

        response_text = ""
        model_used = model
        error_msg = ""

        # Try Anthropic first
        try:
            response_text = await _call_anthropic(prompt, system, model, temperature, max_tokens)
            model_used = model
        except Exception as e_anth:
            _log.debug("Anthropic failed: %s", e_anth)
            # Try OpenAI
            try:
                response_text = await _call_openai(prompt, system, model, temperature, max_tokens)
                model_used = model
            except Exception as e_oai:
                _log.debug("OpenAI failed: %s", e_oai)
                error_msg = str(e_anth)
                response_text = (
                    "**No API key configured.**\n\n"
                    "To enable live AI responses, add your key to `.env` at the project root:\n\n"
                    "```\nANTHROPIC_API_KEY=sk-ant-...\n```\n\n"
                    "Then restart Orchestra."
                )

        return JSONResponse(_wrap({
            "response": response_text,
            "model_used": model_used,
            "error": error_msg or None,
        }))

    # ── Run — agentic task ───────────────────────────────────────────────────
    @app.post("/v1/run")
    async def v1_run(request: Request):
        """Bridge /v1/run to the code_agent agentic chat."""
        import uuid, asyncio, json
        from orchestra.code_agent.ui.handlers.chat import _active_tasks

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(_wrap(error="Invalid JSON"), status_code=400)

        task    = body.get("task", "")
        engine  = body.get("agent_type", "claude_code")
        context = body.get("context", {})
        workspace = context.get("cwd", "")

        if not task:
            return JSONResponse(_wrap(error="task is required"), status_code=400)

        task_id = str(uuid.uuid4())
        event_queue: asyncio.Queue = asyncio.Queue()
        _active_tasks[task_id] = {"queue": event_queue, "events": [], "done": False}

        async def _run():
            try:
                from orchestra.code_agent.nemotron.routes import _get_dispatch
                registry = _get_dispatch()._router._registry
                agent = registry.get(engine)
                if agent is None:
                    raise ValueError(f"Agent '{engine}' not registered")
                ag_result = await asyncio.wait_for(
                    agent.execute(task, context={"cwd": workspace or None}),
                    timeout=3600,
                )
                result = ag_result.output if ag_result.success else ag_result.error
            except Exception as e:
                result = f"Error: {e}"
            finally:
                entry = _active_tasks.get(task_id)
                if entry:
                    entry["done"] = True
                    entry["result"] = result
                await event_queue.put({"type": "done", "data": {"result": result}})
                await event_queue.put(None)

        import asyncio as _asyncio
        _asyncio.create_task(_run())
        return JSONResponse(_wrap({"task_id": task_id, "status": "running"}))

    # ── Password reset ────────────────────────────────────────────────────────
    @app.post("/v1/auth/forgot-password")
    async def v1_forgot_password(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        email = body.get("email", "").strip().lower()
        if not email or not _EMAIL_RE.match(email):
            return JSONResponse(_wrap(error="Valid email required"), status_code=422)
        user = _store.get_user_by_email(email)
        if user:
            from orchestra.code_agent.auth.email import EmailService, _reset_db
            svc = EmailService()
            code = svc.generate_code(6)
            _reset_db.create(user["id"], email, code, expires_in=3600)
            svc.send_password_reset(email, code, user.get("name", ""))
        # Always 200 — don't leak whether the email exists
        return JSONResponse(_wrap({"message": "If that email is registered, a reset code has been sent"}))

    @app.post("/v1/auth/reset-password")
    async def v1_reset_password(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        code = body.get("code", "").strip()
        new_password = body.get("password", "")
        if not code:
            return JSONResponse(_wrap(error="Reset code required"), status_code=422)
        if len(new_password) < 8:
            return JSONResponse(_wrap(error="Password must be at least 8 characters"), status_code=422)
        from orchestra.code_agent.auth.email import _reset_db
        user_id = _reset_db.consume(code)
        if not user_id:
            return JSONResponse(_wrap(error="Invalid or expired reset code"), status_code=400)
        _store.update_user(user_id, password_hash=_pw.hash(new_password))
        return JSONResponse(_wrap({"message": "Password updated — please log in"}))

    # ── Task status ──────────────────────────────────────────────────────────
    @app.get("/v1/tasks/{task_id}")
    async def v1_task_status(task_id: str):
        from orchestra.code_agent.ui.handlers.chat import _active_tasks
        entry = _active_tasks.get(task_id)
        if not entry:
            return JSONResponse(_wrap(error="Not found"), status_code=404)
        return JSONResponse(_wrap({
            "task_id": task_id,
            "done": entry.get("done", False),
            "result": entry.get("result"),
        }))
