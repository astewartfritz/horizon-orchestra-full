"""Data models for service discovery."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ServiceStatus(Enum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"
    DRAINING = "draining"


@dataclass
class ServiceInstance:
    """A registered service instance with metadata."""

    service_name: str            # "orchestra-api", "llm-ollama", "channel-slack"
    host: str                    # "10.0.1.5" or "service-name.namespace.svc.cluster.local"
    port: int                    # 8000
    instance_id: str = ""        # Auto-generated UUID
    status: ServiceStatus = ServiceStatus.UP
    tags: list[str] = field(default_factory=list)       # ["v1", "production", "gpu"]
    metadata: dict[str, str] = field(default_factory=dict)
    region: str = "default"
    zone: str = "default"
    priority: int = 1            # Lower = preferred
    weight: int = 1              # For weighted load balancing
    registered_at: float = 0.0
    last_heartbeat: float = 0.0
    ttl_seconds: float = 30.0   # Expiry if no heartbeat

    def __post_init__(self):
        if not self.instance_id:
            self.instance_id = uuid.uuid4().hex[:12]
        if not self.registered_at:
            self.registered_at = time.time()
        if self.last_heartbeat <= 0:
            self.last_heartbeat = time.time()

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return time.time() - self.last_heartbeat > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "host": self.host,
            "port": self.port,
            "instance_id": self.instance_id,
            "status": self.status.value,
            "tags": self.tags,
            "metadata": self.metadata,
            "region": self.region,
            "zone": self.zone,
            "priority": self.priority,
            "weight": self.weight,
            "address": self.address,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
        }


@dataclass
class ServiceHealth:
    """Result of a health check on a service instance."""
    instance_id: str
    service_name: str
    status: ServiceStatus
    latency_ms: float = 0.0
    error: str = ""
    checked_at: float = 0.0

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = time.time()
