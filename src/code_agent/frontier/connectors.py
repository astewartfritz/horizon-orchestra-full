from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Connector:
    name: str
    provider: str  # google, microsoft, custom
    auth_type: str  # oauth2, api_key, enterprise
    scopes: list[str] = field(default_factory=list)
    client_id: str = ""
    client_secret: str = ""
    token: str = ""
    refresh_token: str = ""
    base_url: str = ""
    enabled: bool = True


class ConnectorRegistry:
    """Manages connectors for the Prince action-oriented execution system.

    Built-in integrations like Google and Microsoft use provider auth flows.
    Custom remote connectors support OAuth 2.0 or enterprise-managed API keys.
    UI intent is translated into scoped tool access, not broad raw account access.
    """

    def __init__(self, storage_path: str = ".agent-connectors"):
        self._storage = storage_path
        self._connectors: dict[str, Connector] = {}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._storage):
                with open(self._storage) as f:
                    data = json.load(f)
                    for name, c in data.items():
                        self._connectors[name] = Connector(**c)
        except Exception:
            pass

    def _save(self) -> None:
        try:
            data = {k: v.__dict__ for k, v in self._connectors.items()}
            with open(self._storage, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def register(self, name: str, provider: str, auth_type: str = "oauth2",
                 scopes: list[str] | None = None, **kwargs) -> Connector:
        c = Connector(name=name, provider=provider, auth_type=auth_type,
                      scopes=scopes or [], **kwargs)
        self._connectors[name] = c
        self._save()
        return c

    def get(self, name: str) -> Connector | None:
        return self._connectors.get(name)

    def list(self) -> list[dict[str, Any]]:
        return [{"name": n, "provider": c.provider, "auth_type": c.auth_type,
                 "scopes": c.scopes, "enabled": c.enabled}
                for n, c in self._connectors.items()]

    def remove(self, name: str) -> bool:
        if name in self._connectors:
            del self._connectors[name]
            self._save()
            return True
        return False

    def authorize(self, name: str, token: str, refresh_token: str = "") -> bool:
        c = self._connectors.get(name)
        if not c:
            return False
        c.token = token
        c.refresh_token = refresh_token
        self._save()
        return True

    def revoke(self, name: str) -> bool:
        c = self._connectors.get(name)
        if not c:
            return False
        c.token = ""
        c.refresh_token = ""
        self._save()
        return True


class OAuthConnector:
    """Handles OAuth 2.0 flow for provider auth (Google, Microsoft, etc.)."""

    PROVIDERS = {
        "google": {
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "scopes": ["openid", "email", "https://www.googleapis.com/auth/drive.readonly"],
        },
        "microsoft": {
            "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            "scopes": ["User.Read", "Files.Read.All"],
        },
        "github": {
            "auth_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "scopes": ["repo", "user"],
        },
    }

    def __init__(self, client_id: str = "", client_secret: str = "",
                 redirect_uri: str = "http://localhost:8000/api/auth/callback"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_auth_url(self, provider: str, state: str = "") -> str:
        info = self.PROVIDERS.get(provider)
        if not info:
            raise ValueError(f"Unknown provider: {provider}")
        import urllib.parse
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(info["scopes"]),
            "state": state,
        }
        return f"{info['auth_url']}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, provider: str, code: str) -> dict[str, str]:
        info = self.PROVIDERS.get(provider)
        if not info:
            raise ValueError(f"Unknown provider: {provider}")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(info["token_url"], data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                })
                data = r.json()
                return {
                    "token": data.get("access_token", ""),
                    "refresh_token": data.get("refresh_token", ""),
                }
        except Exception as e:
            return {"error": str(e)}

    async def refresh_token(self, provider: str, refresh_token: str) -> dict[str, str]:
        info = self.PROVIDERS.get(provider)
        if not info:
            raise ValueError(f"Unknown provider: {provider}")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(info["token_url"], data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                })
                data = r.json()
                return {"token": data.get("access_token", "")}
        except Exception as e:
            return {"error": str(e)}


class APIKeyConnector:
    """Simple API key-based connector for enterprise services."""

    def __init__(self, registry: ConnectorRegistry):
        self.registry = registry

    def register(self, name: str, api_key: str, base_url: str = "",
                 provider: str = "custom") -> Connector:
        return self.registry.register(
            name=name, provider=provider, auth_type="api_key",
            token=api_key, base_url=base_url,
        )
