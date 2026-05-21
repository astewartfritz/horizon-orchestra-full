from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from orchestra.code_agent.ui.auth_html import LOGIN_HTML, SIGNUP_HTML, GETTING_STARTED_HTML, FORGOT_PASSWORD_HTML


def register_auth_web_routes(app: FastAPI) -> None:
    @app.get("/login", response_class=HTMLResponse)
    async def login_page():
        return LOGIN_HTML

    @app.get("/signup", response_class=HTMLResponse)
    async def signup_page():
        return SIGNUP_HTML

    @app.get("/getting-started", response_class=HTMLResponse)
    async def getting_started_page():
        return GETTING_STARTED_HTML

    @app.get("/forgot-password", response_class=HTMLResponse)
    async def forgot_password_page():
        return FORGOT_PASSWORD_HTML

    @app.get("/reset-password", response_class=HTMLResponse)
    async def reset_password_page():
        return FORGOT_PASSWORD_HTML

    @app.get("/logout")
    async def web_logout():
        resp = HTMLResponse("<script>window.location.href='/login'</script>")
        resp.delete_cookie(key="session", path="/")
        return resp
