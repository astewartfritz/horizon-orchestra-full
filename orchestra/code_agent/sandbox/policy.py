"""Sandbox security policy — resource limits, network isolation, filesystem restrictions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceLimits:
    memory: str = "512m"
    cpu_count: float = 1.0
    pids_limit: int = 100
    disk_size: str = "1g"
    readonly_root: bool = True
    max_timeout: int = 300


@dataclass
class SandboxProfile:
    name: str
    image: str
    description: str
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    network_isolated: bool = True
    allowed_commands: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)


class SandboxPolicy:
    """Defines what sandboxes can and cannot do — network, resources, filesystem."""

    def __init__(self, profile: SandboxProfile | None = None):
        self.profile = profile or self._default_profile()
        self.resource_limits = self.profile.limits
        self.network_isolated = self.profile.network_isolated

    def _default_profile(self) -> SandboxProfile:
        return SandboxProfile(
            name="default",
            image="python:3.11-slim",
            description="Default sandbox — Python, restricted network, read-only root",
            limits=ResourceLimits(),
            network_isolated=True,
            allowed_commands=["python3", "pip", "node", "npm", "cargo", "rustc", "go", "make"],
        )

    def get_image_for(self, language: str) -> str:
        images = {
            "python": "python:3.11-slim",
            "node": "node:20-slim",
            "typescript": "node:20-slim",
            "rust": "rust:1.75-slim",
            "go": "golang:1.22-alpine",
            "mojo": "modular/mojo:latest",
        }
        return images.get(language, self.profile.image)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.name,
            "image": self.profile.image,
            "limits": {
                "memory": self.resource_limits.memory,
                "cpu": self.resource_limits.cpu_count,
                "pids": self.resource_limits.pids_limit,
                "disk": self.resource_limits.disk_size,
                "readonly_root": self.resource_limits.readonly_root,
            },
            "network_isolated": self.network_isolated,
        }
