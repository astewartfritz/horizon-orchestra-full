"""Test that the auth web handler can be registered on a FastAPI app."""
from __future__ import annotations

import os
import pytest
try:
    from fastapi import FastAPI
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestAuthWebRoutes:
    def setup_method(self):
        from orchestra.code_agent.auth.user_store import UserStore
        UserStore._reset()

    def test_register_auth_web_routes(self):
        from orchestra.code_agent.ui.handlers.auth_web import register_auth_web_routes
        app = FastAPI()
        register_auth_web_routes(app)
        routes = [r.path for r in app.routes]
        assert "/login" in routes
        assert "/signup" in routes
        assert "/getting-started" in routes
        assert "/logout" in routes

    def test_v1_compat_auth_routes(self):
        from orchestra.code_agent.ui.handlers.v1_compat import register_v1_compat_routes
        app = FastAPI()
        register_v1_compat_routes(app)
        routes = [r.path for r in app.routes]
        assert "/v1/auth/register" in routes
        assert "/v1/auth/login" in routes
        assert "/v1/auth/me" in routes
        assert "/v1/auth/validate" in routes

    def test_server_creates(self):
        from orchestra.code_agent.ui.server import create_ui_app
        from orchestra.code_agent.auth.user_store import UserStore
        UserStore._reset()
        app = create_ui_app()
        routes = [r.path for r in app.routes]
        assert "/login" in routes
        assert "/signup" in routes
        assert "/getting-started" in routes
        assert "/app" in routes

    def test_user_store_works(self):
        import tempfile
        from orchestra.code_agent.auth.user_store import UserStore
        from orchestra.code_agent.auth.password import PasswordHasher
        UserStore._reset()
        db = os.path.join(tempfile.gettempdir(), "test_auth_web.db")
        store = UserStore(db)
        pw = PasswordHasher()
        h = pw.hash("test1234")
        user = store.create_user("test@test.com", h, name="Tester")
        assert user["email"] == "test@test.com"
        fetched = store.get_user_by_email("test@test.com")
        assert fetched["id"] == user["id"]
        assert pw.verify("test1234", fetched["password_hash"])
        assert not pw.verify("wrong", fetched["password_hash"])
        assert store.count_users() == 1
        store.delete_user(user["id"])
        assert store.count_users() == 0
        UserStore._reset()
