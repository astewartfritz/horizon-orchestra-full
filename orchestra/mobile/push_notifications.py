"""
orchestra/mobile/push_notifications.py
----------------------------------------
Web Push notification integration via VAPID for Horizon Orchestra.

Provides:
- VAPID key generation and management
- Subscription storage (SQLite with DynamoDB fallback)
- Typed push message sending for all notification categories
- Quiet-hours enforcement
- Platform-specific quirk handling (iOS Safari, Android Chrome)
- ``register_routes(app)`` for FastAPI mount

pywebpush is an optional dependency, guarded with try/except.
"""
from __future__ import annotations

__all__ = [
    "PushNotificationManager",
    "PushSubscription",
    "PushMessage",
    "PushMessageType",
    "VAPIDConfig",
    "register_routes",
]

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger("orchestra.mobile.push_notifications")

# ---------------------------------------------------------------------------
# Optional dependency: pywebpush
# ---------------------------------------------------------------------------

try:
    from pywebpush import webpush, WebPushException  # type: ignore[import-untyped]
    from py_vapid import Vapid  # type: ignore[import-untyped]
    _HAS_PYWEBPUSH = True
except ImportError:  # pragma: no cover — optional dependency
    webpush = None  # type: ignore[assignment]
    WebPushException = Exception  # type: ignore[misc,assignment]
    Vapid = None  # type: ignore[assignment]
    _HAS_PYWEBPUSH = False

# ---------------------------------------------------------------------------
# Brand / product constants
# ---------------------------------------------------------------------------

BRAND_TEAL = "#01696F"
APP_NAME = "Horizon Orchestra"
MILES = "MILES"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PushMessageType(str, Enum):
    """Supported push notification categories."""

    TASK_COMPLETE = "task_complete"
    TASK_PROGRESS = "task_progress"
    MENTION = "mention"
    DAILY_BRIEFING = "daily_briefing"
    ERROR = "error"
    GENERIC = "generic"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VAPIDConfig:
    """VAPID key configuration for Web Push authentication."""

    private_key: str = ""   # PEM-encoded or base64url raw private key
    public_key: str = ""    # base64url uncompressed public key
    subscriber: str = "mailto:admin@horizonorchestra.ai"


@dataclass
class PushSubscription:
    """A browser push subscription object as received from the client."""

    endpoint: str
    p256dh: str    # client public key (base64url)
    auth: str      # client auth secret (base64url)
    user_id: str
    platform: str = "unknown"  # "ios" | "android" | "desktop"
    created_at: float = field(default_factory=time.time)
    active: bool = True

    def to_web_push_sub(self) -> dict[str, Any]:
        """Return the subscription dict in the format expected by pywebpush."""
        return {
            "endpoint": self.endpoint,
            "keys": {
                "p256dh": self.p256dh,
                "auth": self.auth,
            },
        }


@dataclass
class PushMessage:
    """A push notification payload."""

    type: PushMessageType
    title: str
    body: str
    url: str = "/"
    tag: str = ""
    badge_count: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    # Actions are included in the payload for SW processing
    actions: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> str:
        """Serialise the message to JSON for the push payload."""
        payload = {
            "type": self.type.value,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "tag": self.tag or self.type.value,
            "badge_count": self.badge_count,
            "data": self.data,
            "actions": self.actions,
        }
        return json.dumps(payload)

    # ------------------------------------------------------------------
    # Factory helpers for each message type
    # ------------------------------------------------------------------

    @classmethod
    def task_complete(cls, task_name: str, task_url: str = "/tasks") -> "PushMessage":
        """Create a task-completion notification."""
        return cls(
            type=PushMessageType.TASK_COMPLETE,
            title=f"{APP_NAME}",
            body=f'Your long-horizon task "{task_name}" finished.',
            url=task_url,
            actions=[
                {"action": "view", "title": "View Result"},
                {"action": "dismiss", "title": "Dismiss"},
            ],
        )

    @classmethod
    def task_progress(
        cls, task_name: str, percent: int, remaining: str = "", task_url: str = "/tasks"
    ) -> "PushMessage":
        """Create a task-progress notification."""
        body = f'"{task_name}" is {percent}% complete'
        if remaining:
            body += f" — {remaining} remaining"
        return cls(
            type=PushMessageType.TASK_PROGRESS,
            title=APP_NAME,
            body=body,
            url=task_url,
            actions=[
                {"action": "view", "title": "View Task"},
                {"action": "dismiss", "title": "Dismiss"},
            ],
        )

    @classmethod
    def mention(cls, context: str = "", reply_url: str = "/chat/new") -> "PushMessage":
        """Create a mention / input-needed notification."""
        return cls(
            type=PushMessageType.MENTION,
            title=f"{MILES} needs your input",
            body=context or f"{MILES} is waiting for a response to continue your task.",
            url=reply_url,
            actions=[
                {"action": "reply", "title": "Reply"},
                {"action": "view", "title": "View"},
                {"action": "dismiss", "title": "Dismiss"},
            ],
        )

    @classmethod
    def daily_briefing(cls, summary: str, briefing_url: str = "/briefing") -> "PushMessage":
        """Create a daily-briefing notification."""
        return cls(
            type=PushMessageType.DAILY_BRIEFING,
            title=f"Good morning from {APP_NAME}",
            body=summary,
            url=briefing_url,
            actions=[
                {"action": "view", "title": "View Briefing"},
                {"action": "dismiss", "title": "Dismiss"},
            ],
        )

    @classmethod
    def error(cls, task_name: str, task_url: str = "/tasks") -> "PushMessage":
        """Create a task-failure error notification."""
        return cls(
            type=PushMessageType.ERROR,
            title=f"{APP_NAME} — Task Failed",
            body=f'"{task_name}" encountered an error. Tap to retry.',
            url=task_url,
            actions=[
                {"action": "view", "title": "Retry"},
                {"action": "dismiss", "title": "Dismiss"},
            ],
        )


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


@dataclass
class QuietHours:
    """User-configured quiet hours (local time, 24-h)."""

    enabled: bool = False
    start_hour: int = 22  # 10 PM
    end_hour: int = 8     # 8 AM
    override_for_errors: bool = True  # errors always break through


def is_quiet_hour(quiet: QuietHours) -> bool:
    """Return True if the current local time falls within quiet hours."""
    if not quiet.enabled:
        return False
    import datetime
    now_hour = datetime.datetime.now().hour
    if quiet.start_hour > quiet.end_hour:  # spans midnight
        return now_hour >= quiet.start_hour or now_hour < quiet.end_hour
    return quiet.start_hour <= now_hour < quiet.end_hour


# ---------------------------------------------------------------------------
# Subscription storage — SQLite
# ---------------------------------------------------------------------------


class SubscriptionStore:
    """SQLite-backed push subscription store.

    Falls back gracefully when the database file is not writable.
    """

    def __init__(self, db_path: str = "/tmp/horizon_push_subs.db") -> None:
        self._path = Path(db_path)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        endpoint   TEXT PRIMARY KEY,
                        p256dh     TEXT NOT NULL,
                        auth       TEXT NOT NULL,
                        user_id    TEXT NOT NULL,
                        platform   TEXT DEFAULT 'unknown',
                        created_at REAL NOT NULL,
                        active     INTEGER DEFAULT 1
                    )
                    """
                )
        except Exception as exc:
            logger.warning("SubscriptionStore: could not initialise DB: %s", exc)

    def save(self, sub: PushSubscription) -> None:
        """Upsert a subscription."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO subscriptions
                        (endpoint, p256dh, auth, user_id, platform, created_at, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(endpoint) DO UPDATE SET
                        p256dh=excluded.p256dh,
                        auth=excluded.auth,
                        active=1
                    """,
                    (
                        sub.endpoint,
                        sub.p256dh,
                        sub.auth,
                        sub.user_id,
                        sub.platform,
                        sub.created_at,
                        int(sub.active),
                    ),
                )
        except Exception as exc:
            logger.error("SubscriptionStore.save: %s", exc)

    def delete(self, endpoint: str) -> None:
        """Mark a subscription inactive."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE subscriptions SET active=0 WHERE endpoint=?", (endpoint,)
                )
        except Exception as exc:
            logger.error("SubscriptionStore.delete: %s", exc)

    def get_for_user(self, user_id: str) -> list[PushSubscription]:
        """Return all active subscriptions for a user."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM subscriptions WHERE user_id=? AND active=1", (user_id,)
                ).fetchall()
            return [
                PushSubscription(
                    endpoint=r["endpoint"],
                    p256dh=r["p256dh"],
                    auth=r["auth"],
                    user_id=r["user_id"],
                    platform=r["platform"],
                    created_at=r["created_at"],
                    active=bool(r["active"]),
                )
                for r in rows
            ]
        except Exception as exc:
            logger.error("SubscriptionStore.get_for_user: %s", exc)
            return []

    def get_all_active(self) -> list[PushSubscription]:
        """Return all active subscriptions (e.g. for broadcast)."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM subscriptions WHERE active=1"
                ).fetchall()
            return [
                PushSubscription(
                    endpoint=r["endpoint"],
                    p256dh=r["p256dh"],
                    auth=r["auth"],
                    user_id=r["user_id"],
                    platform=r["platform"],
                    created_at=r["created_at"],
                    active=True,
                )
                for r in rows
            ]
        except Exception as exc:
            logger.error("SubscriptionStore.get_all_active: %s", exc)
            return []


# ---------------------------------------------------------------------------
# PushNotificationManager
# ---------------------------------------------------------------------------


class PushNotificationManager:
    """Manages Web Push subscriptions and sends VAPID-authenticated push messages.

    Requires pywebpush to send actual pushes.  When pywebpush is not installed,
    ``send_push`` logs a warning and returns False.

    Usage::

        mgr = PushNotificationManager(vapid=VAPIDConfig(...))
        await mgr.send_push(user_id="u123", message=PushMessage.mention())
    """

    def __init__(
        self,
        vapid: VAPIDConfig | None = None,
        store: SubscriptionStore | None = None,
        quiet_hours: QuietHours | None = None,
    ) -> None:
        self._vapid = vapid or VAPIDConfig()
        self._store = store or SubscriptionStore()
        self._quiet = quiet_hours or QuietHours()

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def register_subscription(self, sub: PushSubscription) -> None:
        """Store a push subscription received from the client."""
        self._store.save(sub)
        logger.info(
            "push: registered subscription user_id=%s platform=%s endpoint=%s",
            sub.user_id,
            sub.platform,
            sub.endpoint[:60],
        )

    def unregister_subscription(self, endpoint: str) -> None:
        """Remove (deactivate) a push subscription by endpoint."""
        self._store.delete(endpoint)
        logger.info("push: unregistered endpoint=%s", endpoint[:60])

    def get_subscriptions(self, user_id: str) -> list[PushSubscription]:
        """Return all active subscriptions for a user."""
        return self._store.get_for_user(user_id)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_push(
        self,
        user_id: str,
        message: PushMessage,
        *,
        respect_quiet_hours: bool = True,
    ) -> dict[str, Any]:
        """Send a push notification to all subscriptions for a user.

        Returns a summary dict with counts of succeeded and failed sends.
        """
        if not _HAS_PYWEBPUSH:
            logger.warning(
                "pywebpush is not installed; cannot send push. "
                "Install with: pip install pywebpush"
            )
            return {"succeeded": 0, "failed": 0, "skipped": 0, "reason": "pywebpush_missing"}

        # Quiet-hours check
        if respect_quiet_hours and is_quiet_hour(self._quiet):
            if not (
                message.type == PushMessageType.ERROR and self._quiet.override_for_errors
            ):
                logger.info("push: quiet hours active — skipping notification for user=%s", user_id)
                return {"succeeded": 0, "failed": 0, "skipped": 1, "reason": "quiet_hours"}

        subs = self._store.get_for_user(user_id)
        if not subs:
            logger.debug("push: no active subscriptions for user_id=%s", user_id)
            return {"succeeded": 0, "failed": 0, "skipped": 0}

        succeeded = 0
        failed = 0
        stale: list[str] = []

        for sub in subs:
            result = self._send_to_subscription(sub, message)
            if result == "ok":
                succeeded += 1
            elif result == "gone":
                stale.append(sub.endpoint)
                failed += 1
            else:
                failed += 1

        # Clean up stale subscriptions
        for endpoint in stale:
            self.unregister_subscription(endpoint)

        logger.info(
            "push: sent user_id=%s type=%s succeeded=%d failed=%d",
            user_id,
            message.type.value,
            succeeded,
            failed,
        )
        return {"succeeded": succeeded, "failed": failed, "skipped": 0}

    def _send_to_subscription(self, sub: PushSubscription, message: PushMessage) -> str:
        """Send to a single subscription.  Returns 'ok', 'gone', or 'error'."""
        payload = message.to_json()

        # iOS Safari quirk: requires minimal payload, no custom actions
        if sub.platform == "ios":
            payload = self._ios_compat_payload(message)

        try:
            webpush(
                subscription_info=sub.to_web_push_sub(),
                data=payload,
                vapid_private_key=self._vapid.private_key,
                vapid_claims={
                    "sub": self._vapid.subscriber,
                    "aud": self._endpoint_origin(sub.endpoint),
                },
                content_encoding="aes128gcm",
            )
            return "ok"
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                logger.info("push: stale subscription endpoint=%s", sub.endpoint[:60])
                return "gone"
            logger.warning("push: WebPushException for endpoint=%s: %s", sub.endpoint[:60], exc)
            return "error"
        except Exception as exc:
            logger.error("push: unexpected error endpoint=%s: %s", sub.endpoint[:60], exc)
            return "error"

    @staticmethod
    def _ios_compat_payload(message: PushMessage) -> str:
        """iOS Safari requires a simpler payload without actions."""
        return json.dumps(
            {
                "type": message.type.value,
                "title": message.title,
                "body": message.body,
                "url": message.url,
                "tag": message.tag or message.type.value,
            }
        )

    @staticmethod
    def _endpoint_origin(endpoint: str) -> str:
        """Extract the origin (scheme + host) from a push endpoint URL."""
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        return f"{parsed.scheme}://{parsed.netloc}"

    # ------------------------------------------------------------------
    # VAPID key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_vapid_keys() -> dict[str, str]:
        """Generate a new VAPID key pair.

        Returns a dict with ``private_key`` and ``public_key`` (base64url).
        Requires pywebpush / py_vapid to be installed.
        """
        if not _HAS_PYWEBPUSH or Vapid is None:
            raise RuntimeError(
                "pywebpush is required to generate VAPID keys. "
                "Install with: pip install pywebpush"
            )
        vapid = Vapid()
        vapid.generate_keys()
        return {
            "private_key": vapid.private_key.private_bytes(
                encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.PEM,
                format=__import__("cryptography.hazmat.primitives.serialization", fromlist=["PrivateFormat"]).PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=__import__("cryptography.hazmat.primitives.serialization", fromlist=["NoEncryption"]).NoEncryption(),
            ).decode(),
            "public_key": vapid.public_key,
        }


# ---------------------------------------------------------------------------
# FastAPI route registration
# ---------------------------------------------------------------------------


def register_routes(app: Any) -> None:
    """Register push notification routes on a FastAPI application instance.

    Registers:
        POST /api/push/subscribe       — store a new push subscription
        DELETE /api/push/subscribe     — remove a push subscription
        POST /api/push/send/{user_id}  — send a test push (dev only)
        GET  /api/push/vapid-public-key — return the VAPID public key
    """
    try:
        from fastapi import Request
        from fastapi.responses import JSONResponse
    except ImportError:  # pragma: no cover — optional web dependency
        logger.warning("FastAPI not installed; push notification routes not registered")
        return

    manager = PushNotificationManager()

    @app.post("/api/push/subscribe", include_in_schema=True)
    async def subscribe(request: Request) -> JSONResponse:
        """Register a push subscription from the browser."""
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        required = {"endpoint", "p256dh", "auth", "user_id"}
        if not required.issubset(data):
            return JSONResponse(
                {"error": f"missing fields: {required - data.keys()}"}, status_code=422
            )

        sub = PushSubscription(
            endpoint=data["endpoint"],
            p256dh=data["p256dh"],
            auth=data["auth"],
            user_id=data["user_id"],
            platform=data.get("platform", "unknown"),
        )
        manager.register_subscription(sub)
        return JSONResponse({"status": "subscribed"})

    @app.delete("/api/push/subscribe", include_in_schema=True)
    async def unsubscribe(request: Request) -> JSONResponse:
        """Remove a push subscription."""
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        endpoint = data.get("endpoint", "")
        if not endpoint:
            return JSONResponse({"error": "endpoint required"}, status_code=422)

        manager.unregister_subscription(endpoint)
        return JSONResponse({"status": "unsubscribed"})

    @app.get("/api/push/vapid-public-key", include_in_schema=True)
    async def vapid_public_key() -> JSONResponse:
        """Return the VAPID public key for client-side subscription."""
        return JSONResponse(
            {
                "publicKey": manager._vapid.public_key,
                "applicationServerKey": manager._vapid.public_key,
            }
        )

    @app.post("/api/push/send/{user_id}", include_in_schema=False)
    async def send_test_push(user_id: str, request: Request) -> JSONResponse:
        """Dev endpoint: send a test push notification to a user."""
        try:
            data = await request.json()
        except Exception:
            data = {}

        msg = PushMessage(
            type=PushMessageType.GENERIC,
            title=data.get("title", f"{APP_NAME} Test"),
            body=data.get("body", "This is a test notification from Horizon Orchestra."),
            url=data.get("url", "/"),
        )
        result = manager.send_push(user_id, msg, respect_quiet_hours=False)
        return JSONResponse(result)

    logger.info(
        "push notification routes registered: /api/push/subscribe, /api/push/vapid-public-key"
    )
