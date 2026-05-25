"""
Concurrent session hardening — enforce per-user session limits.

HIPAA §164.312(a)(2)(iii) addresses automatic logoff; this module closes
the complementary threat: an attacker reusing a stolen token after the
legitimate user has established additional sessions.

Every authenticated request registers its JWT ID (jti). When a user
exceeds MAX_CONCURRENT_SESSIONS, the oldest sessions are evicted and
any subsequent request presenting an evicted token receives a 401.

Optional: SESSION_BIND_IP=true rejects requests where the IP doesn't
match the IP the session was first used from — useful for high-assurance
healthcare and legal workflows.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

_DB_PATH = Path.home() / ".orchestra_sessions.db"
_lock = threading.Lock()
_MAX_SESSIONS = int(os.environ.get("MAX_CONCURRENT_SESSIONS", "5"))
_BIND_IP = os.environ.get("SESSION_BIND_IP", "").lower() in ("1", "true", "yes")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS active_sessions (
                jti         TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                created_at  REAL NOT NULL,
                last_seen   REAL NOT NULL,
                ip_address  TEXT NOT NULL DEFAULT '',
                user_agent  TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'active'
            );
            CREATE INDEX IF NOT EXISTS idx_sess_user   ON active_sessions(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_sess_status ON active_sessions(status);
        """)


def register_session(
    jti: str,
    user_id: str,
    ip_address: str = "",
    user_agent: str = "",
) -> bool:
    """
    Register a new session or refresh an existing one.

    Returns True if the session is valid (active or just created).
    Returns False if the session was previously evicted or revoked.
    On a new session, enforces the concurrent-session limit by evicting
    the oldest active sessions for the user.
    """
    now = time.time()
    with _lock, _db() as conn:
        row = conn.execute(
            "SELECT status FROM active_sessions WHERE jti=?", (jti,)
        ).fetchone()

        if row is not None:
            if row["status"] != "active":
                return False
            conn.execute(
                "UPDATE active_sessions SET last_seen=? WHERE jti=?", (now, jti)
            )
            return True

        # New session — insert first, then evict overflow
        conn.execute(
            "INSERT INTO active_sessions"
            "(jti, user_id, created_at, last_seen, ip_address, user_agent, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active')",
            (jti, user_id, now, now, ip_address, user_agent),
        )
        rows = conn.execute(
            "SELECT jti FROM active_sessions "
            "WHERE user_id=? AND status='active' ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        if len(rows) > _MAX_SESSIONS:
            to_evict = [r["jti"] for r in rows[_MAX_SESSIONS:]]
            placeholders = ",".join("?" * len(to_evict))
            conn.execute(
                f"UPDATE active_sessions SET status='evicted' WHERE jti IN ({placeholders})",
                to_evict,
            )
    return True


def get_bound_ip(jti: str) -> str | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT ip_address FROM active_sessions WHERE jti=?", (jti,)
        ).fetchone()
    return row["ip_address"] if row else None


def revoke(jti: str) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE active_sessions SET status='revoked' WHERE jti=?", (jti,)
        )


def revoke_all(user_id: str) -> int:
    with _lock, _db() as conn:
        c = conn.execute(
            "UPDATE active_sessions SET status='revoked' "
            "WHERE user_id=? AND status='active'",
            (user_id,),
        )
    return c.rowcount


def list_sessions(user_id: str) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT jti, user_id, created_at, last_seen, ip_address, user_agent, status "
            "FROM active_sessions WHERE user_id=? ORDER BY last_seen DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


class SessionHardeningMiddleware:
    """
    ASGI middleware: enforce per-user concurrent session limits and optional
    IP binding. Runs on every authenticated HTTP request.
    """

    def __init__(self, app) -> None:
        self.app = app
        init_db()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode("utf-8", errors="replace")
        cookie_raw = headers.get(b"cookie", b"").decode("utf-8", errors="replace")

        token = auth.removeprefix("Bearer ").strip()
        if not token:
            for part in cookie_raw.split(";"):
                k, _, v = part.strip().partition("=")
                if k.strip() == "session":
                    token = v.strip()
                    break

        if token:
            try:
                from orchestra.code_agent.ui.handlers.v1_compat import _jwt
                payload = _jwt().verify(token)
                if payload and payload.get("type") == "access":
                    jti = payload.get("jti", "")
                    user_id = payload.get("sub", "")
                    if jti and user_id:
                        client = scope.get("client")
                        ip = client[0] if client else ""

                        if _BIND_IP:
                            bound = get_bound_ip(jti)
                            if bound and bound != ip:
                                await _reject(scope, receive, send,
                                              "Session IP mismatch — please re-authenticate.")
                                return

                        ua = headers.get(b"user-agent", b"").decode("utf-8", errors="replace")
                        valid = register_session(jti, user_id, ip_address=ip, user_agent=ua)
                        if not valid:
                            await _reject(scope, receive, send,
                                          "Session limit exceeded — please re-authenticate.")
                            return
            except Exception:
                pass

        await self.app(scope, receive, send)


async def _reject(scope, receive, send, message: str) -> None:
    body = f'{{"error":"{message}"}}'.encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body, "more_body": False})
