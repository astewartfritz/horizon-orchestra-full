"""
Email notification system — digest, compliance alerts, billing summaries.

Backends: SMTP (primary), Resend API (if RESEND_API_KEY is set),
          SendGrid (if SENDGRID_API_KEY is set). Falls back to logging in dev.

Environment variables:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
  RESEND_API_KEY
  SENDGRID_API_KEY
  EMAIL_FROM_NAME     (default: "Orchestra")
  EMAIL_FROM_ADDRESS  (default: SMTP_FROM or noreply@orchestra.ai)
  ORCHESTRA_ENV       (production | development)
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

_log = logging.getLogger("orchestra.email")
_DB_PATH = Path.home() / ".orchestra_notifications.db"
_lock = threading.Lock()


@dataclass
class EmailNotification:
    id: str
    user_id: str
    to_email: str
    subject: str
    notification_type: str   # digest | compliance_alert | billing | invite | breach_alert
    status: str              # queued | sent | failed
    sent_at: float | None
    error: str
    created_at: float


# ── DB ────────────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_notifications (
                id                TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL DEFAULT '',
                to_email          TEXT NOT NULL,
                subject           TEXT NOT NULL,
                notification_type TEXT NOT NULL DEFAULT 'general',
                status            TEXT NOT NULL DEFAULT 'queued',
                sent_at           REAL,
                error             TEXT NOT NULL DEFAULT '',
                created_at        REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON email_notifications(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_status ON email_notifications(status)")


# ── Sending backends ──────────────────────────────────────────────────────────

def _from_address() -> str:
    return os.environ.get("EMAIL_FROM_ADDRESS", "") or os.environ.get("SMTP_FROM", "noreply@orchestra.ai")


def _from_name() -> str:
    return os.environ.get("EMAIL_FROM_NAME", "Orchestra")


def _send_smtp(to: str, subject: str, html: str, text: str) -> None:
    host = os.environ.get("SMTP_HOST", "")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    from_addr = _from_address()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{_from_name()} <{from_addr}>"
    msg["To"] = to
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(host, port, timeout=15) as server:
        server.ehlo()
        server.starttls()
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, [to], msg.as_string())


def _send_resend(to: str, subject: str, html: str, text: str) -> None:
    import urllib.request
    import json as _json
    api_key = os.environ["RESEND_API_KEY"]
    payload = _json.dumps({
        "from": f"{_from_name()} <{_from_address()}>",
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Resend API error: {resp.status}")


def _send_sendgrid(to: str, subject: str, html: str, text: str) -> None:
    import urllib.request
    import json as _json
    api_key = os.environ["SENDGRID_API_KEY"]
    payload = _json.dumps({
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": _from_address(), "name": _from_name()},
        "subject": subject,
        "content": [{"type": "text/plain", "value": text}, {"type": "text/html", "value": html}],
    }).encode()
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"SendGrid API error: {resp.status}")


def _dispatch(to: str, subject: str, html: str, text: str) -> None:
    """Try backends in order: Resend → SendGrid → SMTP → log."""
    if os.environ.get("RESEND_API_KEY"):
        _send_resend(to, subject, html, text)
        return
    if os.environ.get("SENDGRID_API_KEY"):
        _send_sendgrid(to, subject, html, text)
        return
    if os.environ.get("SMTP_HOST"):
        _send_smtp(to, subject, html, text)
        return
    # Dev fallback — log instead of send
    _log.info("EMAIL [dev stub] to=%s subject=%r", to, subject)


def send_email(
    to: str,
    subject: str,
    html: str,
    text: str = "",
    user_id: str = "",
    notification_type: str = "general",
) -> EmailNotification:
    """Send an email and record the attempt in the DB."""
    now = time.time()
    nid = str(uuid.uuid4())
    notif = EmailNotification(
        id=nid, user_id=user_id, to_email=to, subject=subject,
        notification_type=notification_type,
        status="queued", sent_at=None, error="", created_at=now,
    )
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO email_notifications VALUES(?,?,?,?,?,?,?,?,?)",
            (nid, user_id, to, subject, notification_type, "queued", None, "", now),
        )
    try:
        if not text:
            import re
            text = re.sub(r"<[^>]+>", "", html)
        _dispatch(to, subject, html, text)
        with _lock, _db() as conn:
            conn.execute(
                "UPDATE email_notifications SET status='sent', sent_at=? WHERE id=?",
                (time.time(), nid),
            )
        notif.status = "sent"
        notif.sent_at = time.time()
    except Exception as exc:
        err = str(exc)
        _log.warning("Email send failed to %s: %s", to, err)
        with _lock, _db() as conn:
            conn.execute(
                "UPDATE email_notifications SET status='failed', error=? WHERE id=?",
                (err, nid),
            )
        notif.status = "failed"
        notif.error = err
    return notif


# ── Template helpers ──────────────────────────────────────────────────────────

def _base_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{title}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f6f8fa;margin:0;padding:24px}}
.wrap{{max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e1e4e8}}
.header{{background:#0d1117;padding:24px 32px;color:#e6edf3}}
.header h1{{font-size:18px;font-weight:700;margin:0}}
.body{{padding:28px 32px;color:#24292f;line-height:1.6}}
.footer{{background:#f6f8fa;border-top:1px solid #e1e4e8;padding:16px 32px;font-size:12px;color:#6e7781}}
.btn{{display:inline-block;padding:10px 20px;background:#0366d6;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;font-size:14px}}
.alert{{background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:12px 16px;margin:16px 0}}
.alert-danger{{background:#ffe0e0;border-color:#f85149}}
table{{width:100%;border-collapse:collapse;margin:16px 0}}
th{{text-align:left;font-size:12px;color:#6e7781;border-bottom:2px solid #e1e4e8;padding:8px 0}}
td{{padding:10px 0;border-bottom:1px solid #f1f3f5;font-size:14px}}
</style></head><body>
<div class="wrap">
<div class="header"><h1>Orchestra</h1></div>
<div class="body">{body}</div>
<div class="footer">Orchestra · You received this email because you are a member. <a href="#unsubscribe">Unsubscribe</a></div>
</div></body></html>"""


def send_invite_email(to: str, org_name: str, invite_token: str, base_url: str, user_id: str = "") -> EmailNotification:
    accept_url = f"{base_url}/api/orgs/invites/{invite_token}/accept"
    body = f"""<p>You've been invited to join <strong>{org_name}</strong> on Orchestra.</p>
<p>Click below to accept the invitation (expires in 7 days):</p>
<p><a class="btn" href="{accept_url}">Accept invitation</a></p>
<p style="margin-top:20px;font-size:13px;color:#6e7781">Or copy this link: {accept_url}</p>"""
    return send_email(
        to=to,
        subject=f"You're invited to join {org_name} on Orchestra",
        html=_base_html(f"Invitation to {org_name}", body),
        user_id=user_id,
        notification_type="invite",
    )


def send_compliance_alert(
    to: str,
    alert_title: str,
    alert_body: str,
    severity: str = "warning",
    user_id: str = "",
) -> EmailNotification:
    cls = "alert-danger" if severity == "critical" else "alert"
    body = f"""<p>A compliance event requires your attention:</p>
<div class="{cls}"><strong>{alert_title}</strong><p style="margin:8px 0 0">{alert_body}</p></div>
<p><a class="btn" href="/admin#compliance">View compliance dashboard</a></p>"""
    return send_email(
        to=to,
        subject=f"[Orchestra Compliance] {alert_title}",
        html=_base_html("Compliance Alert", body),
        user_id=user_id,
        notification_type="compliance_alert",
    )


def send_billing_summary(
    to: str,
    period: str,
    plan: str,
    amount: str,
    next_billing: str,
    usage_items: list[dict],
    user_id: str = "",
) -> EmailNotification:
    rows = "".join(
        f"<tr><td>{item.get('label','')}</td><td style='text-align:right'>{item.get('value','')}</td></tr>"
        for item in usage_items
    )
    body = f"""<h2 style="font-size:16px;margin:0 0 16px">Billing summary — {period}</h2>
<p>Plan: <strong>{plan}</strong> · Next billing: {next_billing} · Amount: <strong>{amount}</strong></p>
<table><thead><tr><th>Item</th><th style="text-align:right">Usage</th></tr></thead>
<tbody>{rows}</tbody></table>
<p><a class="btn" href="/settings#billing">Manage billing</a></p>"""
    return send_email(
        to=to,
        subject=f"[Orchestra] Billing summary for {period}",
        html=_base_html("Billing Summary", body),
        user_id=user_id,
        notification_type="billing",
    )


def send_weekly_digest(
    to: str,
    user_name: str,
    conversations: int,
    tokens: int,
    top_activity: list[str],
    user_id: str = "",
) -> EmailNotification:
    activity_html = "".join(f"<li>{a}</li>" for a in top_activity[:5])
    body = f"""<p>Hi {user_name or 'there'},</p>
<p>Here's your Orchestra activity digest for this week:</p>
<table>
  <tr><td>Conversations</td><td><strong>{conversations}</strong></td></tr>
  <tr><td>Tokens used</td><td><strong>{tokens:,}</strong></td></tr>
</table>
{"<h3>Recent activity</h3><ul>" + activity_html + "</ul>" if top_activity else ""}
<p><a class="btn" href="/app">Open Orchestra</a></p>"""
    return send_email(
        to=to,
        subject="Your weekly Orchestra digest",
        html=_base_html("Weekly Digest", body),
        user_id=user_id,
        notification_type="digest",
    )


def send_breach_alert(
    to: str,
    org_name: str,
    breach_title: str,
    discovered_at: float,
    deadline_at: float,
    user_id: str = "",
) -> EmailNotification:
    import time as _t
    disc = _t.strftime("%Y-%m-%d %H:%M UTC", _t.gmtime(discovered_at))
    ddl = _t.strftime("%Y-%m-%d %H:%M UTC", _t.gmtime(deadline_at))
    body = f"""<div class="alert-danger">
<strong>GDPR Art. 33 — 72-hour notification deadline</strong>
<p style="margin:8px 0 0">A personal data breach has been recorded for <strong>{org_name}</strong>.</p>
</div>
<table>
  <tr><td>Breach</td><td>{breach_title}</td></tr>
  <tr><td>Discovered</td><td>{disc}</td></tr>
  <tr><td>Notify supervisory authority by</td><td><strong style="color:#d73a49">{ddl}</strong></td></tr>
</table>
<p><a class="btn" href="/admin#compliance">Open breach workflow</a></p>"""
    return send_email(
        to=to,
        subject=f"[URGENT] GDPR breach notification required — {org_name}",
        html=_base_html("Data Breach Alert", body),
        user_id=user_id,
        notification_type="breach_alert",
    )


# ── Notification log ──────────────────────────────────────────────────────────

def list_notifications(user_id: str, limit: int = 50) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM email_notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
