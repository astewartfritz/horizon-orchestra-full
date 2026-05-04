"""
orchestra/briefing_config.py
─────────────────────────────
Per-user briefing configuration for Orchestra Enterprise daily briefings.
Stores topic groups, delivery schedules, and email targets per customer.
Tier-gated: Enterprise ($499/mo) only.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────

@dataclass
class BriefingTopic:
    """A single monitored topic with search queries."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""                          # Display name, e.g. "Iran Conflict"
    queries: list[str] = field(default_factory=list)  # Search queries to run
    priority: str = "normal"               # "normal" | "high" | "breaking"
    breaking_keywords: list[str] = field(default_factory=list)  # Triggers notification

    @classmethod
    def create(cls, name: str, queries: list[str],
               breaking_keywords: list[str] | None = None) -> "BriefingTopic":
        return cls(
            name=name,
            queries=queries,
            breaking_keywords=breaking_keywords or [],
        )


@dataclass
class BriefingSection:
    """A named section in the briefing email mapping to one or more topics."""
    header: str          # e.g. "F-15 CREW RESCUE UPDATE"
    topic_ids: list[str] # References to BriefingTopic.id
    max_bullets: int = 5 # Max bullet points in this section


@dataclass
class DeliveryConfig:
    """Email delivery settings."""
    recipients: list[str] = field(default_factory=list)
    subject_template: str = "{briefing_name} — {date}"
    send_hour_utc: int = 13          # 13:00 UTC = 8:00 AM CDT
    send_minute_utc: int = 0
    cron_expression: str = "0 13 * * *"  # Daily at 13:00 UTC
    timezone_label: str = "CDT"


@dataclass
class BriefingConfig:
    """
    Complete briefing configuration for one customer.
    Stored as JSON at orchestra/data/briefings/{customer_id}.json
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str = ""
    briefing_name: str = "Daily Intelligence Briefing"
    topics: list[BriefingTopic] = field(default_factory=list)
    sections: list[BriefingSection] = field(default_factory=list)
    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)
    enabled: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── Tier enforcement ──────────────────────────────────────────────────────

    REQUIRED_TIER: str = "enterprise"
    MAX_TOPICS: int = 20        # Enterprise: up to 20 topic groups
    MAX_RECIPIENTS: int = 10    # Up to 10 email recipients

    def validate_tier(self, customer_tier: str) -> None:
        if customer_tier.lower() != self.REQUIRED_TIER:
            raise PermissionError(
                f"Daily Briefings require the Enterprise plan ($499/mo). "
                f"Current tier: {customer_tier}. "
                f"Upgrade at horizon-orchestra.com/billing."
            )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if len(self.topics) > self.MAX_TOPICS:
            errors.append(f"Too many topics ({len(self.topics)}); max {self.MAX_TOPICS}")
        if len(self.delivery.recipients) > self.MAX_RECIPIENTS:
            errors.append(f"Too many recipients; max {self.MAX_RECIPIENTS}")
        for r in self.delivery.recipients:
            if not re.match(r"[^@]+@[^@]+\.[^@]+", r):
                errors.append(f"Invalid email: {r}")
        if not 0 <= self.delivery.send_hour_utc <= 23:
            errors.append("send_hour_utc must be 0-23")
        # Validate cron expression (5 fields)
        parts = self.delivery.cron_expression.split()
        if len(parts) != 5:
            errors.append("cron_expression must have 5 fields")
        return errors

    # ── Topic helpers ─────────────────────────────────────────────────────────

    def add_topic(self, topic: BriefingTopic) -> None:
        if len(self.topics) >= self.MAX_TOPICS:
            raise ValueError(f"Max {self.MAX_TOPICS} topics allowed on Enterprise")
        self.topics.append(topic)
        self._touch()

    def remove_topic(self, topic_id: str) -> bool:
        before = len(self.topics)
        self.topics = [t for t in self.topics if t.id != topic_id]
        self._touch()
        return len(self.topics) < before

    def get_topic(self, topic_id: str) -> Optional[BriefingTopic]:
        return next((t for t in self.topics if t.id == topic_id), None)

    def get_all_queries(self) -> list[tuple[str, str]]:
        """Returns [(topic_name, query), ...] for all active topics."""
        return [
            (t.name, q)
            for t in self.topics
            for q in t.queries
        ]

    # ── Persistence ───────────────────────────────────────────────────────────

    def _touch(self):
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "BriefingConfig":
        topics = [BriefingTopic(**t) for t in data.pop("topics", [])]
        sections = [BriefingSection(**s) for s in data.pop("sections", [])]
        delivery = DeliveryConfig(**data.pop("delivery", {}))
        return cls(topics=topics, sections=sections, delivery=delivery, **data)

    @classmethod
    def from_json(cls, raw: str) -> "BriefingConfig":
        return cls.from_dict(json.loads(raw))

    def save(self, data_dir: str = "orchestra/data/briefings") -> Path:
        path = Path(data_dir)
        path.mkdir(parents=True, exist_ok=True)
        fp = path / f"{self.customer_id}.json"
        fp.write_text(self.to_json())
        return fp

    @classmethod
    def load(cls, customer_id: str,
             data_dir: str = "orchestra/data/briefings") -> Optional["BriefingConfig"]:
        fp = Path(data_dir) / f"{customer_id}.json"
        if not fp.exists():
            return None
        return cls.from_json(fp.read_text())


# ──────────────────────────────────────────────
# Factory helpers
# ──────────────────────────────────────────────

def create_default_config(customer_id: str, recipients: list[str],
                           briefing_name: str = "Daily Intelligence Briefing",
                           send_hour_utc: int = 13) -> BriefingConfig:
    """Build a default Enterprise briefing config for a new customer."""
    delivery = DeliveryConfig(
        recipients=recipients,
        send_hour_utc=send_hour_utc,
        cron_expression=f"0 {send_hour_utc} * * *",
    )
    return BriefingConfig(
        customer_id=customer_id,
        briefing_name=briefing_name,
        delivery=delivery,
    )
