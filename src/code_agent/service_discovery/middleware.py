"""FastAPI middleware for automatic service registration and health reporting."""

from __future__ import annotations

import os
import socket
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from service_discovery.client import ServiceDiscoveryClient


class ServiceDiscoveryMiddleware:
    """FastAPI middleware that auto-registers this service and reports health.

    Usage:
        app = FastAPI()
        sd = ServiceDiscoveryMiddleware(app, "orchestra-api", 8000)
        sd.register()

    Adds:
      - /sd/health  — health + registration info
      - /sd/info    — service metadata
      - Heartbeat every request (optional)
    """

    def __init__(self, app: FastAPI, service_name: str, port: int,
                 tags: list[str] | None = None,
                 sd_client: ServiceDiscoveryClient | None = None,
                 heartbeat_on_request: bool = True,
                 instance_id: str | None = None):
        self.app = app
        self.service_name = service_name
        self.port = port
        self.tags = tags or []
        self.sd = sd_client or ServiceDiscoveryClient()
        self.heartbeat_on_request = heartbeat_on_request
        self._instance_id = instance_id or ""
        self._host = self._get_host()

    def _get_host(self) -> str:
        try:
            host = os.environ.get("HOSTNAME") or socket.gethostbyname(socket.gethostname())
            return host
        except Exception:
            return "127.0.0.1"

    def register(self, **kwargs) -> str:
        """Register this service instance. Returns instance_id."""
        self._instance_id = self.sd.register(
            self.service_name,
            self._host,
            self.port,
            tags=self.tags,
            **kwargs,
        )
        self._setup_routes()
        return self._instance_id

    def _setup_routes(self) -> None:
        @self.app.get("/sd/health")
        async def sd_health():
            return {
                "service": self.service_name,
                "instance_id": self._instance_id,
                "host": self._host,
                "port": self.port,
                "status": "up",
                "tags": self.tags,
            }

        @self.app.get("/sd/info")
        async def sd_info():
            stats = self.sd.get_stats()
            all_instances = self.sd.registry.get_all_instances()
            return {
                "self": {
                    "service": self.service_name,
                    "instance_id": self._instance_id,
                    "host": self._host,
                    "port": self.port,
                    "tags": self.tags,
                },
                "registry": stats,
                "known_services": {
                    name: [i.to_dict() for i in insts]
                    for name, insts in all_instances.items()
                },
            }

        @self.app.middleware("http")
        async def sd_heartbeat_middleware(request: Request, call_next):
            if self.heartbeat_on_request and self._instance_id:
                self.sd.heartbeat(self.service_name, self._instance_id)
            response = await call_next(request)
            return response


class ServiceDiscoveryRouter:
    """Adds service discovery endpoints to an existing FastAPI app without registration."""

    def __init__(self, sd_client: ServiceDiscoveryClient):
        self.sd = sd_client

    def mount_on(self, app: FastAPI, prefix: str = "") -> None:
        @app.get(f"{prefix}/sd/services")
        async def list_services():
            return {"services": self.sd.registry.get_services()}

        @app.get(f"{prefix}/sd/services/{{service_name}}")
        async def get_service(service_name: str):
            instances = self.sd.registry.get_instances(service_name)
            return {
                "service_name": service_name,
                "instance_count": len(instances),
                "instances": [i.to_dict() for i in instances],
            }

        @app.get(f"{prefix}/sd/resolve/{{service_name}}")
        async def resolve_service(service_name: str):
            inst, all_inst = self.sd.resolve(service_name)
            if not inst:
                return JSONResponse(
                    status_code=503,
                    content={"error": f"No healthy instances of {service_name}"},
                )
            return {
                "selected": inst.to_dict(),
                "available": [i.to_dict() for i in all_inst],
            }

        @app.get(f"{prefix}/sd/srv/{{service_name}}")
        async def srv_records(service_name: str):
            return {"records": self.sd.resolve_srv(service_name)}

        @app.post(f"{prefix}/sd/register")
        async def register_service(body: dict[str, Any]):
            inst_id = self.sd.register(
                body["service_name"],
                body["host"],
                body["port"],
                tags=body.get("tags", []),
            )
            return {"instance_id": inst_id}

        @app.post(f"{prefix}/sd/deregister")
        async def deregister_service(body: dict[str, Any]):
            ok = self.sd.deregister(body["service_name"], body["instance_id"])
            return {"ok": ok}

        @app.get(f"{prefix}/sd/stats")
        async def discovery_stats():
            return self.sd.get_stats()
