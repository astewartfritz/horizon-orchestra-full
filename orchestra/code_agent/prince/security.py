"""Prince security boundary and connector governance.

Extends beyond the browser into isolated execution and connector governance.
Admins control which connectors are available; users authorize the services they actually use.
"""
from __future__ import annotations

from typing import Any

from orchestra.code_agent.frontier.connectors import ConnectorRegistry


class PrinceSecurity:
    """Security boundary for Prince action-oriented execution.

    Admins control connector availability; users authorize individual services.
    """

    def __init__(self, connector_registry: ConnectorRegistry):
        self.registry = connector_registry
        self._admin_allowlist: set[str] = set()
        self._user_authorized: dict[str, set[str]] = {}  # user → set of connector names

    def admin_allow(self, connector_name: str) -> None:
        self._admin_allowlist.add(connector_name)

    def admin_disallow(self, connector_name: str) -> None:
        self._admin_allowlist.discard(connector_name)

    def user_authorize(self, user: str, connector_name: str) -> None:
        self._user_authorized.setdefault(user, set()).add(connector_name)

    def user_revoke(self, user: str, connector_name: str) -> None:
        self._user_authorized.get(user, set()).discard(connector_name)

    def check_access(self, user: str, connector_name: str) -> bool:
        if connector_name not in self._admin_allowlist:
            return False
        if user not in self._user_authorized:
            return False
        return connector_name in self._user_authorized[user]

    def available_connectors(self, user: str) -> list[dict[str, Any]]:
        results = []
        for c in self.registry.list():
            if c["name"] in self._admin_allowlist:
                authorized = c["name"] in self._user_authorized.get(user, set())
                results.append({**c, "authorized": authorized})
        return results
