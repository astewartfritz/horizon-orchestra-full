"""Connector base class and registry."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

__all__ = ["Connector", "ConnectorRegistry"]

log = logging.getLogger("orchestra.connectors")


class Connector(ABC):
    """Base class for all external service connectors."""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate. Returns True on success."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up auth state."""
        ...

    @abstractmethod
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a named action with params."""
        ...

    @abstractmethod
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas."""
        ...

    @property
    @abstractmethod
    def connected(self) -> bool:
        ...


class ConnectorRegistry:
    """Central registry for all connectors."""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.name] = connector
        log.info("Registered connector: %s", connector.name)

    def get(self, name: str) -> Connector | None:
        return self._connectors.get(name)

    @property
    def all(self) -> dict[str, Connector]:
        return dict(self._connectors)

    def register_tools(self, tool_registry: Any) -> None:
        """Inject all connected services' tools into an agent ToolRegistry."""
        for conn in self._connectors.values():
            if not conn.connected:
                continue
            for tool_def in conn.get_tool_definitions():
                fn = tool_def.get("function", {})
                tool_name = fn.get("name", "")
                if not tool_name:
                    continue

                _conn = conn
                _action = tool_name

                async def _handler(_c=_conn, _a=_action, **kwargs: Any) -> str:
                    result = await _c.execute(_a, kwargs)
                    return json.dumps(result)

                tool_registry.register(
                    name=tool_name,
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters", {}),
                    handler=_handler,
                )

    def list_connectors(self) -> list[dict[str, Any]]:
        return [
            {
                "name": c.name,
                "description": c.description,
                "connected": c.connected,
                "tools": [t["function"]["name"] for t in c.get_tool_definitions()],
            }
            for c in self._connectors.values()
        ]

    @classmethod
    def default(cls) -> "ConnectorRegistry":
        """Create a registry with all built-in connectors."""
        from .gmail import GmailConnector
        from .github import GitHubConnector
        from .slack import SlackConnector
        from .notion import NotionConnector
        from .linear import LinearConnector
        from .snowflake import SnowflakeConnector
        from .gcal import GoogleCalendarConnector
        from .gdrive import GoogleDriveConnector
        from .jira import JiraConnector
        from .hubspot import HubSpotConnector
        from .airtable import AirtableConnector
        from .stripe import StripeConnector
        from .aws import AWSConnector
        from .monday import MondayConnector
        from .mcp_bridge import MCPBridge

        reg = cls()
        reg.register(GmailConnector())
        reg.register(GitHubConnector())
        reg.register(SlackConnector())
        reg.register(NotionConnector())
        reg.register(LinearConnector())
        reg.register(SnowflakeConnector())
        reg.register(GoogleCalendarConnector())
        reg.register(GoogleDriveConnector())
        reg.register(JiraConnector())
        reg.register(HubSpotConnector())
        reg.register(AirtableConnector())
        reg.register(StripeConnector())
        reg.register(AWSConnector())
        reg.register(MondayConnector())
        reg.register(MCPBridge())
        return reg
