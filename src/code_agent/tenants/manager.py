from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class User:
    id: str = ""
    name: str = ""
    email: str = ""
    role: str = "user"
    tenant_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Tenant:
    id: str = ""
    name: str = ""
    workspace: str = ""
    api_key: str = ""
    users: list[User] = field(default_factory=list)
    config_overrides: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "workspace": self.workspace,
                "users": [u.to_dict() for u in self.users],
                "config_overrides": self.config_overrides, "created_at": self.created_at}


class TenantManager:
    """Multi-tenant isolation: separate workspaces, configs, and storage per tenant."""

    def __init__(self, storage_path: str = ".agent-tenants"):
        self.path = Path(storage_path)
        self.path.mkdir(parents=True, exist_ok=True)

    def create_tenant(self, name: str, workspace: str = "") -> Tenant:
        tenant = Tenant(
            id=str(uuid.uuid4())[:8],
            name=name,
            workspace=workspace or f"./workspaces/{name.lower().replace(' ', '-')}",
            api_key=f"ca_{uuid.uuid4().hex[:24]}",
            created_at=__import__("datetime").datetime.utcnow().isoformat() + "Z",
        )
        self._save_tenant(tenant)
        Path(tenant.workspace).mkdir(parents=True, exist_ok=True)
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        f = self.path / f"{tenant_id}.json"
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text())
            return Tenant(
                id=data["id"], name=data["name"], workspace=data.get("workspace", ""),
                api_key=data.get("api_key", ""),
                users=[User(**u) for u in data.get("users", [])],
                config_overrides=data.get("config_overrides", {}),
                created_at=data.get("created_at", ""),
            )
        except (json.JSONDecodeError, KeyError):
            return None

    def get_by_api_key(self, api_key: str) -> Tenant | None:
        for f in self.path.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("api_key") == api_key:
                    return self.get_tenant(data["id"])
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def add_user(self, tenant_id: str, name: str, email: str = "", role: str = "user") -> User | None:
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return None
        user = User(id=str(uuid.uuid4())[:8], name=name, email=email, role=role, tenant_id=tenant_id)
        tenant.users.append(user)
        self._save_tenant(tenant)
        return user

    def list_tenants(self) -> list[dict[str, Any]]:
        tenants = []
        for f in self.path.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                tenants.append({"id": data["id"], "name": data["name"],
                               "users": len(data.get("users", [])),
                               "workspace": data.get("workspace", "")})
            except (json.JSONDecodeError, OSError):
                pass
        return tenants

    def delete_tenant(self, tenant_id: str) -> bool:
        f = self.path / f"{tenant_id}.json"
        if f.exists():
            f.unlink()
            return True
        return False

    def get_agent_config(self, tenant_id: str) -> dict[str, Any]:
        from code_agent.config import AgentConfig
        cfg = AgentConfig()
        base = {"max_iterations": cfg.max_iterations, "workspace": cfg.workspace,
                "llm": {"provider": cfg.llm.provider, "model": cfg.llm.model}}

        tenant = self.get_tenant(tenant_id)
        if tenant:
            base["workspace"] = tenant.workspace
            base.update(tenant.config_overrides)
        return base

    def _save_tenant(self, tenant: Tenant) -> None:
        f = self.path / f"{tenant.id}.json"
        f.write_text(json.dumps(tenant.to_dict(), indent=2))
