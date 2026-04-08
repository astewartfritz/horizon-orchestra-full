"""
orchestra/briefing_scheduler.py
────────────────────────────────
Cron-based daily delivery engine for Orchestra Enterprise briefings.

Responsibilities:
  - Load all active Enterprise customer briefing configs
  - Schedule a daily cron job per config (APScheduler)
  - On trigger: run BriefingMonitor → send email via Gmail connector
  - Push in-app notification on breaking news
  - Track delivery history to orchestra/data/briefing_logs/
  - Expose start(), stop(), add_config(), remove_config() interface

Integration points:
  - arch_e.py registers BriefingScheduler at startup
  - agent_loop.py tools call add_config() / remove_config()
  - notification system for breaking news alerts
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from .briefing_config import BriefingConfig
from .briefing_monitor import BriefingMonitor, BriefingResult

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# APScheduler (optional dep — graceful no-op if absent)
# ──────────────────────────────────────────────

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    log.warning(
        "APScheduler not installed. Install with: pip install apscheduler\n"
        "Briefing scheduler will run in manual-trigger mode only."
    )


# ──────────────────────────────────────────────
# Delivery log
# ──────────────────────────────────────────────

@dataclass
class DeliveryLog:
    customer_id: str
    briefing_name: str
    subject: str
    recipients: list[str]
    delivered_at: str
    has_breaking: bool
    breaking_summary: Optional[str]
    success: bool
    error: Optional[str] = None

    def save(self, log_dir: str = "orchestra/data/briefing_logs"):
        path = Path(log_dir) / self.customer_id
        path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fp = path / f"{ts}.json"
        fp.write_text(json.dumps(self.__dict__, indent=2))
        return fp


# ──────────────────────────────────────────────
# Email sender (Gmail SMTP + API fallback)
# ──────────────────────────────────────────────

class EmailSender:
    """
    Sends email via:
    1. Gmail connector (Orchestra's gcal/Gmail integration) — primary
    2. SMTP — fallback when connector unavailable
    """

    def __init__(
        self,
        gmail_connector=None,      # Orchestra's Gmail connector instance
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
    ):
        self.connector = gmail_connector
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password

    async def send(
        self,
        to: list[str],
        subject: str,
        body: str,
    ) -> tuple[bool, Optional[str]]:
        """Returns (success, error_message)."""
        # Primary: Gmail connector
        if self.connector:
            return await self._send_via_connector(to, subject, body)
        # Fallback: SMTP
        if self.smtp_host and self.smtp_user:
            return self._send_via_smtp(to, subject, body)
        return False, "No email transport configured (Gmail connector or SMTP)"

    async def _send_via_connector(
        self, to: list[str], subject: str, body: str
    ) -> tuple[bool, Optional[str]]:
        """Use Orchestra's Gmail connector (gcal send_email tool)."""
        try:
            # Delegate to the connector's send_email method
            await self.connector.send_email(
                action="send",
                to=to,
                cc=[],
                bcc=[],
                subject=subject,
                body=body,
            )
            return True, None
        except Exception as exc:
            log.error(f"Gmail connector send failed: {exc}")
            # Fall through to SMTP
            if self.smtp_host and self.smtp_user:
                return self._send_via_smtp(to, subject, body)
            return False, str(exc)

    def _send_via_smtp(
        self, to: list[str], subject: str, body: str
    ) -> tuple[bool, Optional[str]]:
        """SMTP fallback."""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.smtp_user
            msg["To"] = ", ".join(to)
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, to, msg.as_string())
            return True, None
        except Exception as exc:
            log.error(f"SMTP send failed: {exc}")
            return False, str(exc)


# ──────────────────────────────────────────────
# Notification pusher
# ──────────────────────────────────────────────

class NotificationPusher:
    """
    Sends in-app breaking news notifications via Orchestra's
    notification system. Wraps the existing notifications module.
    """

    def __init__(self, notifications=None):
        self.notifications = notifications

    async def push_breaking(
        self,
        customer_id: str,
        title: str,
        body: str,
        url: Optional[str] = None,
    ) -> None:
        if self.notifications:
            await self.notifications.send(
                customer_id=customer_id,
                title=title,
                body=body,
                url=url,
                priority="high",
            )
        else:
            log.info(f"[BREAKING — {customer_id}] {title}: {body}")


# ──────────────────────────────────────────────
# Briefing Scheduler
# ──────────────────────────────────────────────

class BriefingScheduler:
    """
    Manages per-customer daily briefing cron jobs.
    Integrates with APScheduler for production scheduling.
    """

    REQUIRED_TIER = "enterprise"

    def __init__(
        self,
        moonshot_key: str,
        sonar_key: str,
        email_sender: Optional[EmailSender] = None,
        notification_pusher: Optional[NotificationPusher] = None,
        config_dir: str = "orchestra/data/briefings",
    ):
        self.monitor = BriefingMonitor(moonshot_key, sonar_key)
        self.sender = email_sender or EmailSender()
        self.notifier = notification_pusher or NotificationPusher()
        self.config_dir = config_dir
        self._configs: dict[str, BriefingConfig] = {}  # customer_id → config
        self._scheduler: Optional[object] = None       # APScheduler instance

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler and load all saved configs."""
        self._load_all_configs()
        if HAS_APSCHEDULER:
            self._scheduler = AsyncIOScheduler()
            for config in self._configs.values():
                if config.enabled:
                    self._schedule_job(config)
            self._scheduler.start()
            log.info(
                f"BriefingScheduler started with {len(self._configs)} configs"
            )
        else:
            log.warning("APScheduler not available — manual triggers only")

    def stop(self) -> None:
        if self._scheduler and HAS_APSCHEDULER:
            self._scheduler.shutdown(wait=False)
        log.info("BriefingScheduler stopped")

    # ── Config management ─────────────────────────────────────────────────────

    def add_config(
        self, config: BriefingConfig, customer_tier: str
    ) -> None:
        """Register a new briefing config. Tier-gated to Enterprise."""
        config.validate_tier(customer_tier)
        errors = config.validate()
        if errors:
            raise ValueError(f"Invalid config: {'; '.join(errors)}")

        self._configs[config.customer_id] = config
        config.save(self.config_dir)

        if self._scheduler and HAS_APSCHEDULER and config.enabled:
            self._schedule_job(config)

        log.info(f"Briefing config added for customer {config.customer_id}")

    def remove_config(self, customer_id: str) -> bool:
        """Remove and unschedule a customer's briefing."""
        if customer_id not in self._configs:
            return False
        if self._scheduler and HAS_APSCHEDULER:
            job_id = f"briefing_{customer_id}"
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        del self._configs[customer_id]
        # Remove saved config file
        fp = Path(self.config_dir) / f"{customer_id}.json"
        if fp.exists():
            fp.unlink()
        log.info(f"Briefing config removed for customer {customer_id}")
        return True

    def update_config(
        self, config: BriefingConfig, customer_tier: str
    ) -> None:
        """Update an existing config and reschedule."""
        self.remove_config(config.customer_id)
        self.add_config(config, customer_tier)

    def get_config(self, customer_id: str) -> Optional[BriefingConfig]:
        return self._configs.get(customer_id)

    def list_configs(self) -> list[dict]:
        return [
            {
                "customer_id": c.customer_id,
                "briefing_name": c.briefing_name,
                "topics": len(c.topics),
                "recipients": c.delivery.recipients,
                "schedule": c.delivery.cron_expression,
                "enabled": c.enabled,
            }
            for c in self._configs.values()
        ]

    # ── Manual trigger ────────────────────────────────────────────────────────

    async def trigger_now(self, customer_id: str) -> BriefingResult:
        """Manually trigger a briefing for a customer (for testing/on-demand)."""
        config = self._configs.get(customer_id)
        if not config:
            raise KeyError(f"No briefing config found for customer {customer_id}")
        return await self._run_and_deliver(config)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _schedule_job(self, config: BriefingConfig) -> None:
        if not (self._scheduler and HAS_APSCHEDULER):
            return
        job_id = f"briefing_{config.customer_id}"
        # Remove existing job if present
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass

        trigger = CronTrigger.from_crontab(config.delivery.cron_expression)
        self._scheduler.add_job(
            func=self._run_and_deliver,
            trigger=trigger,
            args=[config],
            id=job_id,
            name=f"Briefing: {config.briefing_name} ({config.customer_id})",
            replace_existing=True,
            misfire_grace_time=300,  # 5 min grace window
        )
        log.info(
            f"Scheduled briefing '{config.briefing_name}' "
            f"for {config.customer_id} at cron: {config.delivery.cron_expression}"
        )

    async def _run_and_deliver(self, config: BriefingConfig) -> BriefingResult:
        """Core execution: monitor → compose → send email → notify."""
        log.info(
            f"Running briefing '{config.briefing_name}' "
            f"for customer {config.customer_id}"
        )
        dl = DeliveryLog(
            customer_id=config.customer_id,
            briefing_name=config.briefing_name,
            subject="",
            recipients=config.delivery.recipients,
            delivered_at=datetime.now(timezone.utc).isoformat(),
            has_breaking=False,
            breaking_summary=None,
            success=False,
        )

        try:
            # 1. Run monitor
            result = await self.monitor.run(config)
            dl.subject = result.subject
            dl.has_breaking = result.has_breaking_news
            dl.breaking_summary = result.breaking_summary

            # 2. Send email
            success, error = await self.sender.send(
                to=config.delivery.recipients,
                subject=result.subject,
                body=result.body,
            )
            dl.success = success
            dl.error = error

            if not success:
                log.error(
                    f"Email delivery failed for {config.customer_id}: {error}"
                )

            # 3. Push breaking news notification
            if result.has_breaking_news and result.breaking_summary:
                await self.notifier.push_breaking(
                    customer_id=config.customer_id,
                    title=f"Breaking: {config.briefing_name}",
                    body=result.breaking_summary[:200],
                )

            log.info(
                f"Briefing delivered to {config.delivery.recipients} | "
                f"breaking={result.has_breaking_news}"
            )
            return result

        except Exception as exc:
            dl.success = False
            dl.error = str(exc)
            log.error(f"Briefing run failed for {config.customer_id}: {exc}")
            raise
        finally:
            dl.save()

    def _load_all_configs(self) -> None:
        """Load all saved configs from disk at startup."""
        path = Path(self.config_dir)
        if not path.exists():
            return
        for fp in path.glob("*.json"):
            try:
                config = BriefingConfig.from_json(fp.read_text())
                self._configs[config.customer_id] = config
                log.info(f"Loaded briefing config for {config.customer_id}")
            except Exception as exc:
                log.warning(f"Failed to load config {fp}: {exc}")
