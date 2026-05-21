from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentRole(str, Enum):
    CUSTOMER_SERVICE = "customer_service"
    ANALYTICS = "analytics"
    DEVELOPER = "developer"
    ADMIN = "admin"
    SYSTEM = "system"


class AgentType(str, Enum):
    AI = "ai"
    HUMAN = "human"
    HYBRID = "hybrid"


class Intent(str, Enum):
    ORDER_STATUS_CHECK = "order_status_check"
    DATA_QUERY = "data_query"
    ANALYSIS = "analysis"
    REPORT_GENERATION = "report_generation"
    TROUBLESHOOTING = "troubleshooting"
    CONFIGURATION = "configuration"
    NOTIFICATION = "notification"
    UNKNOWN = "unknown"


@dataclass
class ContextRecord:
    context_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600)
    data: dict[str, Any] = field(default_factory=dict)
    turn_count: int = 0


@dataclass
class AgentTokenClaims:
    agent_id: str
    agent_role: AgentRole = AgentRole.SYSTEM
    agent_type: AgentType = AgentType.AI
    issued_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600)
    permissions: list[str] = field(default_factory=lambda: ["read"])
    owner_id: str = ""
    purpose: str = ""


@dataclass
class RateLimitPolicy:
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10


@dataclass
class StalenessPolicy:
    max_age_seconds: float = 300.0
    allow_stale: bool = False
