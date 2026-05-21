from __future__ import annotations

import logging
import os
import secrets
import smtplib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from orchestra.code_agent.auth.password import PasswordHasher
from orchestra.code_agent.auth.user_store import UserStore

__all__ = [
    "EmailService",
    "PasswordResetDB",
    "_reset_db",
    "create_verification",
    "verify_email",
    "create_password_reset",
    "reset_password",
    "is_email_verified",
]

log = logging.getLogger("orchestra.email")


class EmailService:
    """SMTP email service with SendGrid-compatible fallback.

    Falls back to logging when SMTP is not configured — safe for development.
    """

    def __init__(self, smtp_host: str = "", smtp_port: int | None = None,
                 smtp_user: str = "", smtp_pass: str = "") -> None:
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST", "")
        self.smtp_port = smtp_port if smtp_port is not None else int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER", "")
        self.smtp_pass = smtp_pass or os.environ.get("SMTP_PASS", "")
        self.from_addr = os.environ.get("SMTP_FROM", self.smtp_user or "noreply@orchestra.app")
        self.app_name = os.environ.get("ORCHESTRA_APP_NAME", "Orchestra")
        self.app_url = os.environ.get("ORCHESTRA_APP_URL", "http://localhost:8000")
        self._configured = bool(self.smtp_host and self.smtp_user)

    @staticmethod
    def generate_code(length: int = 6) -> str:
        return str(secrets.randbelow(10 ** length)).zfill(length)

    def send_password_reset(self, email: str, code: str, name: str = "") -> bool:
        reset_url = f"{self.app_url}/reset-password?code={code}"
        subject = f"Reset your {self.app_name} password"
        body = (
            f"Hi {name or 'there'},\n\n"
            f"Someone requested a password reset for your {self.app_name} account.\n\n"
            f"Your reset code is: {code}\n\n"
            f"Or click this link: {reset_url}\n\n"
            f"This code expires in 1 hour. If you didn't request this, ignore this email.\n\n"
            f"— The {self.app_name} Team"
        )
        if self._configured:
            return self._smtp_send(email, subject, body)
        log.info("Password reset code for %s: %s", email, code)
        print(f"[email] Password reset for {email} — code: {code}  url: {reset_url}", flush=True)
        return True

    def send_verification(self, email: str, code: str, name: str = "") -> bool:
        subject = f"Verify your {self.app_name} email"
        body = (
            f"Hi {name or 'there'},\n\n"
            f"Your {self.app_name} verification code is: {code}\n\n"
            f"It expires in 24 hours.\n\n"
            f"— The {self.app_name} Team"
        )
        if self._configured:
            return self._smtp_send(email, subject, body)
        log.info("Verification code for %s: %s", email, code)
        print(f"[email] Verification for {email} — code: {code}", flush=True)
        return True

    def _smtp_send(self, to: str, subject: str, body: str) -> bool:
        try:
            msg = f"From: {self.from_addr}\r\nTo: {to}\r\nSubject: {subject}\r\n\r\n{body}"
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.from_addr, [to], msg)
            log.info("Email sent to %s: %s", to, subject)
            return True
        except Exception as exc:
            log.error("Failed to send email to %s: %s", to, exc)
            return False


class PasswordResetDB:
    """SQLite-backed password reset token store. Survives server restarts."""

    def __init__(self, db_path: str | Path = "") -> None:
        from orchestra.code_agent.settings import settings
        self._path = str(db_path or settings.billing_db_path)
        self._lock = threading.Lock()
        self._ensure_table()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path)
        c.row_factory = sqlite3.Row
        return c

    def _ensure_table(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS password_resets (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    used INTEGER DEFAULT 0,
                    created_at REAL NOT NULL
                )
            """)
            c.commit()

    def create(self, user_id: str, email: str, code: str, expires_in: int = 3600) -> str:
        import uuid
        reset_id = str(uuid.uuid4())
        now = time.time()
        with self._lock, self._conn() as c:
            # Invalidate any previous unused resets for this user
            c.execute("UPDATE password_resets SET used=1 WHERE user_id=? AND used=0", (user_id,))
            c.execute(
                "INSERT INTO password_resets (id, user_id, code, expires_at, used, created_at) VALUES (?,?,?,?,0,?)",
                (reset_id, user_id, code, now + expires_in, now),
            )
            c.commit()
        return reset_id

    def consume(self, code: str) -> str | None:
        """Validate code and mark used. Returns user_id or None."""
        now = time.time()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id, user_id, expires_at, used FROM password_resets WHERE code=?",
                (code,),
            ).fetchone()
            if not row:
                return None
            if row["used"] or row["expires_at"] < now:
                return None
            c.execute("UPDATE password_resets SET used=1 WHERE id=?", (row["id"],))
            c.commit()
            return row["user_id"]


_reset_db = PasswordResetDB()


# ---------------------------------------------------------------------------
# Legacy in-memory verification (email verification not yet DB-backed)
# ---------------------------------------------------------------------------

_verifications: dict[str, dict[str, Any]] = {}
_verified_users: set[str] = set()


def create_verification(user_id: str, email: str) -> str:
    svc = EmailService()
    code = svc.generate_code()
    _verifications[code] = {
        "user_id": user_id,
        "email": email,
        "expires_at": time.time() + 86400,
        "verified": False,
    }
    svc.send_verification(email, code)
    return code


def verify_email(code: str) -> bool:
    record = _verifications.get(code)
    if not record or time.time() > record["expires_at"]:
        return False
    record["verified"] = True
    _verified_users.add(record["user_id"])
    return True


def create_password_reset(user_id: str, email: str) -> str:
    svc = EmailService()
    code = svc.generate_code()
    _reset_db.create(user_id, email, code, expires_in=3600)
    svc.send_password_reset(email, code)
    return code


def reset_password(code: str, new_password: str) -> bool:
    user_id = _reset_db.consume(code)
    if not user_id:
        return False
    pw = PasswordHasher()
    hashed = pw.hash(new_password)
    UserStore.get().update_user(user_id, password_hash=hashed)
    return True


def is_email_verified(user_id: str) -> bool:
    return user_id in _verified_users
