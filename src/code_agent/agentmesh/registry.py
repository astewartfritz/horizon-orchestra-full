import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class AgentType(str, Enum):
    GENERAL = "general"
    SPECIALIST = "specialist"
    REASONER = "reasoner"
    CODER = "coder"
    RESEARCHER = "researcher"
    VALIDATOR = "validator"
    PLANNER = "planner"
    CREATOR = "creator"
    ANALYST = "analyst"
    COORDINATOR = "coordinator"


class AgentStatus(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"
    PAUSED = "paused"
    SHUTDOWN = "shutdown"


@dataclass
class AgentInfo:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    agent_type: AgentType = AgentType.GENERAL
    capabilities: list[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.OFFLINE
    llm_model: str = ""
    max_concurrent_tasks: int = 1
    current_tasks: int = 0
    total_tasks_completed: int = 0
    avg_response_time: float = 0.0
    error_rate: float = 0.0
    last_heartbeat: float = 0.0
    metadata: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def is_available(self) -> bool:
        return (
            self.status == AgentStatus.ONLINE
            and self.current_tasks < self.max_concurrent_tasks
        )

    @property
    def load_pct(self) -> float:
        if self.max_concurrent_tasks == 0:
            return 1.0
        return self.current_tasks / self.max_concurrent_tasks


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentInfo] = {}
        self._capability_index: dict[str, set[str]] = {}
        self._type_index: dict[str, set[str]] = {}
        self._tag_index: dict[str, set[str]] = {}
        self._on_register: list[Callable] = []
        self._on_unregister: list[Callable] = []
        self._on_status_change: list[Callable] = []

    def register(self, info: AgentInfo) -> str:
        self._agents[info.id] = info
        for cap in info.capabilities:
            self._capability_index.setdefault(cap, set()).add(info.id)
        self._type_index.setdefault(info.agent_type.value, set()).add(info.id)
        for tag in info.tags:
            self._tag_index.setdefault(tag, set()).add(info.id)
        for cb in self._on_register:
            cb(info)
        return info.id

    def unregister(self, agent_id: str) -> bool:
        info = self._agents.pop(agent_id, None)
        if not info:
            return False
        for cap in info.capabilities:
            self._capability_index.get(cap, set()).discard(agent_id)
        self._type_index.get(info.agent_type.value, set()).discard(agent_id)
        for tag in info.tags:
            self._tag_index.get(tag, set()).discard(agent_id)
        for cb in self._on_unregister:
            cb(info)
        return True

    def get(self, agent_id: str) -> AgentInfo | None:
        return self._agents.get(agent_id)

    def discover_by_capability(self, capability: str, available_only: bool = True) -> list[AgentInfo]:
        ids = self._capability_index.get(capability, set())
        agents = [self._agents[a_id] for a_id in ids if a_id in self._agents]
        if available_only:
            agents = [a for a in agents if a.is_available()]
        return sorted(agents, key=lambda a: a.load_pct)

    def discover_by_type(self, agent_type: AgentType, available_only: bool = True) -> list[AgentInfo]:
        ids = self._type_index.get(agent_type.value, set())
        agents = [self._agents[a_id] for a_id in ids if a_id in self._agents]
        if available_only:
            agents = [a for a in agents if a.is_available()]
        return sorted(agents, key=lambda a: a.load_pct)

    def discover_by_tag(self, tag: str, available_only: bool = True) -> list[AgentInfo]:
        ids = self._tag_index.get(tag, set())
        agents = [self._agents[a_id] for a_id in ids if a_id in self._agents]
        if available_only:
            agents = [a for a in agents if a.is_available()]
        return sorted(agents, key=lambda a: a.load_pct)

    def discover_multi_capability(self, capabilities: list[str], require_all: bool = True) -> list[AgentInfo]:
        candidates = None
        for cap in capabilities:
            ids = self._capability_index.get(cap, set())
            if candidates is None:
                candidates = ids
            elif require_all:
                candidates = candidates & ids
            else:
                candidates = candidates | ids
        if candidates is None:
            return []
        agents = [self._agents[a_id] for a_id in candidates if a_id in self._agents and self._agents[a_id].is_available()]
        return sorted(agents, key=lambda a: a.load_pct)

    def heartbeat(self, agent_id: str, status: AgentStatus | None = None) -> bool:
        info = self._agents.get(agent_id)
        if not info:
            return False
        info.last_heartbeat = time.time()
        if status:
            old = info.status
            info.status = status
            if old != status:
                for cb in self._on_status_change:
                    cb(info, old, status)
        return True

    def list_agents(self) -> list[AgentInfo]:
        return list(self._agents.values())

    def list_by_status(self, status: AgentStatus) -> list[AgentInfo]:
        return [a for a in self._agents.values() if a.status == status]

    def available_count(self) -> int:
        return sum(1 for a in self._agents.values() if a.is_available())

    def on_register(self, cb: Callable):
        self._on_register.append(cb)

    def on_unregister(self, cb: Callable):
        self._on_unregister.append(cb)

    def on_status_change(self, cb: Callable):
        self._on_status_change.append(cb)

    def evict_stale(self, max_age: float = 60.0) -> list[str]:
        now = time.time()
        stale = [a_id for a_id, info in self._agents.items() if now - info.last_heartbeat > max_age]
        for a_id in stale:
            self.unregister(a_id)
        return stale
