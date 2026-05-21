from __future__ import annotations

import logging
import os
import secrets
import smtplib
import time
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.auth.password import PasswordHasher
from orchestra.code_agent.auth.user_store import UserStore

__all__ = [
    "EmailService",
    "create_verification",
    "verify_email",
    "create_password_reset",
    "reset_password",
    "is_email_verified",
]

log = logging.getLogger("orchestra.email")

# In-memory stores (replace with DB tables in production)
_verifications: dict[str, dict[str, Any]] = {}
_resets: dict[str, dict[str, Any]] = {}
_verified_users: set[str] = set()


class EmailService:
    """SMTP email service for verification and password reset emails.

    Falls back to logging when SMTP is not configured — safe for
    development and testing.
    """

    def __init__(
        self,
        smtp_host: str = "",
        smtp_port: int | None = None,
        smtp_user: str = "",
        smtp_pass: str = "",
    ) -> None:
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST", "")
        self.smtp_port = (
            smtp_port if smtp_port is not None
            else int(os.environ.get("SMTP_PORT", "587"))
        )
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER", "")
        self.smtp_pass = smtp_pass or os.environ.get("SMTP_PASS", "")
        self._configured = bool(self.smtp_host and self.smtp_user)

    def send_verification(self, email: str, code: str, name: str = "") -> bool:
        """Send a verification email. Returns True on success."""
        if self._configured:
            return self._smtp_send(email, f"Your verification code: {code}",
                                   f"Hi {name or 'there'},\n\nYour verification code is: {code}\n\nIt expires in 24 hours.")
        log.info("Would send verification email to %s with code %s", email, code)
        print(f"[email] Verification code for {email}: {code}", flush=True)
        return True

    def send_password_reset(self, email: str, code: str, name: str = "") -> bool:
        """Send a password reset email. Returns True on success."""
        if self._configured:
            return self._smtp_send(email, f"Your password reset code: {code}",
                                   f"Hi {name or 'there'},\n\nYour password reset code is: {code}\n\nIt expires in 1 hour.")
        log.info("Would send password reset email to %s with code %s", email, code)
        print(f"[email] Password reset code for {email}: {code}", flush=True)
        return True

    @staticmethod
    def generate_code(length: int = 6) -> str:
        """Generate a numeric verification code."""
        return str(secrets.randbelow(10**length)).zfill(length)

    def _smtp_send(self, to: str, subject: str, body: str) -> bool:
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                msg = f"Subject: {subject}\n\n{body}"
                server.sendmail(self.smtp_user, [to], msg)
            log.info("Email sent to %s: %s", to, subject)
            return True
        except Exception as exc:
            log.error("Failed to send email to %s: %s", to, exc)
            return False


_EMAIL_SERVICE = EmailService()


def create_verification(user_id: str, email: str) -> str:
    """Create a verification record, send code, return the code."""
    code = _EMAIL_SERVICE.generate_code()
    _verifications[code] = {
        "user_id": user_id,
        "email": email,
        "expires_at": time.time() + 86400,  # 24 hours
        "verified": False,
    }
    _EMAIL_SERVICE.send_verification(email, code)
    return code


def verify_email(code: str) -> bool:
    """Verify an email with a code. Returns True if valid and not expired."""
    record = _verifications.get(code)
    if not record:
        return False
    if time.time() > record["expires_at"]:
        return False
    record["verified"] = True
    _verified_users.add(record["user_id"])
    return True


def create_password_reset(user_id: str, email: str) -> str:
    """Create a password reset record, send code, return the code."""
    code = _EMAIL_SERVICE.generate_code()
    _resets[code] = {
        "user_id": user_id,
        "email": email,
        "expires_at": time.time() + 3600,  # 1 hour
        "used": False,
    }
    _EMAIL_SERVICE.send_password_reset(email, code)
    return code


def reset_password(code: str, new_password: str) -> bool:
    """Reset a password using a reset code. Returns True on success."""
    record = _resets.get(code)
    if not record:
        return False
    if time.time() > record["expires_at"]:
        return False
    if record["used"]:
        return False

    pw = PasswordHasher()
    hashed = pw.hash(new_password)
    store = UserStore.get()
    store.update_user(record["user_id"], password_hash=hashed)
    record["used"] = True
    return True


def is_email_verified(user_id: str) -> bool:
    """Check if a user has completed email verification."""
    return user_id in _verified_users
