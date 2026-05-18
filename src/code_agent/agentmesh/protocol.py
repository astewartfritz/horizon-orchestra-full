import uuid
import time
from dataclasses import dataclass, field
from enum import Enum


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    BROADCAST = "broadcast"
    DELEGATE = "delegate"
    DELEGATE_RESULT = "delegate_result"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    DISCOVER = "discover"
    DISCOVER_RESPONSE = "discover_response"
    STATUS = "status"
    SHUTDOWN = "shutdown"


@dataclass
class MeshMessage:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sender_id: str = ""
    target_id: str = ""
    target_capability: str = ""
    message_type: MessageType = MessageType.REQUEST
    content: str = ""
    metadata: dict = field(default_factory=dict)
    parent_id: str = ""
    trace_id: str = ""
    timestamp: float = field(default_factory=time.time)
    ttl: int = 30

    def is_broadcast(self) -> bool:
        return self.message_type == MessageType.BROADCAST or (
            not self.target_id and not self.target_capability
        )
