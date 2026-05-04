"""Horizon Orchestra — Deployment Manager.

Auto-deploy generated sites, apps, and APIs to cloud hosting.
Supports S3 static hosting, Vercel, Cloudflare Pages, and
Docker container deployment.

Usage::

    from orchestra.deploy import DeployManager
    mgr = DeployManager()
    url = await mgr.deploy_static("./dist", provider="s3", bucket="my-sites")
    url = await mgr.deploy_container("./Dockerfile", provider="fly")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["DeployManager", "Deployment", "DeployConfig"]

log = logging.getLogger("orchestra.deploy")


@dataclass
class DeployConfig:
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    cloudflare_token: str = ""
    cloudflare_account_id: str = ""
    vercel_token: str = ""
    fly_token: str = ""
    default_provider: str = "s3"


@dataclass
class Deployment:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    provider: str = ""
    url: str = ""
    status: str = "pending"       # pending, deploying, live, failed
    project_path: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class DeployManager:
    """Multi-provider deployment manager."""

    def __init__(self, config: DeployConfig | None = None) -> None:
        self.config = config or DeployConfig()
        self._deployments: list[Deployment] = []

    async def deploy_static(
        self,
        project_path: str,
        entry_point: str = "index.html",
        site_name: str = "",
        provider: str = "",
    ) -> Deployment:
        """Deploy a static site (HTML/CSS/JS)."""
        provider = provider or self.config.default_provider
        deployment = Deployment(provider=provider, project_path=project_path, status="deploying")
        self._deployments.append(deployment)

        try:
            if provider == "s3":
                deployment.url = await self._deploy_s3(project_path, site_name)
            elif provider == "cloudflare":
                deployment.url = await self._deploy_cloudflare(project_path, site_name)
            elif provider == "vercel":
                deployment.url = await self._deploy_vercel(project_path, site_name)
            else:
                raise ValueError(f"Unknown provider: {provider}")

            deployment.status = "live"
            log.info("Deployed to %s: %s", provider, deployment.url)
        except Exception as exc:
            deployment.status = "failed"
            deployment.error = str(exc)
            log.error("Deployment failed: %s", exc)

        return deployment

    async def deploy_container(
        self,
        project_path: str,
        app_name: str = "",
        provider: str = "fly",
    ) -> Deployment:
        """Deploy a containerized application."""
        deployment = Deployment(provider=provider, project_path=project_path, status="deploying")
        self._deployments.append(deployment)

        try:
            if provider == "fly":
                deployment.url = await self._deploy_fly(project_path, app_name)
            else:
                raise ValueError(f"Unknown container provider: {provider}")
            deployment.status = "live"
        except Exception as exc:
            deployment.status = "failed"
            deployment.error = str(exc)

        return deployment

    # -- S3 static hosting --------------------------------------------------

    async def _deploy_s3(self, project_path: str, site_name: str) -> str:
        bucket = self.config.s3_bucket
        if not bucket:
            raise ValueError("S3 bucket not configured (set s3_bucket in DeployConfig)")

        prefix = site_name or f"site-{uuid.uuid4().hex[:6]}"
        path = Path(project_path)

        try:
            import boto3
            s3 = boto3.client("s3", region_name=self.config.s3_region)

            # Upload all files
            for file in path.rglob("*"):
                if file.is_file():
                    key = f"{prefix}/{file.relative_to(path)}"
                    content_type = self._guess_content_type(file.suffix)
                    s3.upload_file(
                        str(file), bucket, key,
                        ExtraArgs={"ContentType": content_type},
                    )

            # Return URL
            region = self.config.s3_region
            return f"https://{bucket}.s3.{region}.amazonaws.com/{prefix}/index.html"
        except ImportError:
            # Fallback: use AWS CLI
            proc = await asyncio.create_subprocess_shell(
                f"aws s3 sync {project_path} s3://{bucket}/{prefix}/ --region {self.config.s3_region}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"aws s3 sync failed: {stderr.decode()[:500]}")
            return f"https://{bucket}.s3.{self.config.s3_region}.amazonaws.com/{prefix}/index.html"

    # -- Cloudflare Pages ---------------------------------------------------

    async def _deploy_cloudflare(self, project_path: str, site_name: str) -> str:
        token = self.config.cloudflare_token or os.environ.get("CLOUDFLARE_API_TOKEN", "")
        account = self.config.cloudflare_account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not token or not account:
            raise ValueError("Cloudflare token and account_id required")

        name = site_name or f"horizon-{uuid.uuid4().hex[:6]}"

        # Use Wrangler CLI
        proc = await asyncio.create_subprocess_shell(
            f"CLOUDFLARE_API_TOKEN={token} npx wrangler pages deploy {project_path} "
            f"--project-name={name} --branch=main",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode()

        # Extract URL from output
        for line in output.split("\n"):
            if "https://" in line and ".pages.dev" in line:
                return line.strip()

        return f"https://{name}.pages.dev"

    # -- Vercel -------------------------------------------------------------

    async def _deploy_vercel(self, project_path: str, site_name: str) -> str:
        token = self.config.vercel_token or os.environ.get("VERCEL_TOKEN", "")
        if not token:
            raise ValueError("Vercel token required")

        proc = await asyncio.create_subprocess_shell(
            f"cd {project_path} && npx vercel --prod --yes --token={token}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode().strip()
        # Vercel outputs the URL on the last line
        return output.split("\n")[-1].strip()

    # -- Fly.io containers --------------------------------------------------

    async def _deploy_fly(self, project_path: str, app_name: str) -> str:
        token = self.config.fly_token or os.environ.get("FLY_API_TOKEN", "")
        if not token:
            raise ValueError("Fly.io token required")

        name = app_name or f"horizon-{uuid.uuid4().hex[:6]}"

        proc = await asyncio.create_subprocess_shell(
            f"cd {project_path} && FLY_API_TOKEN={token} flyctl deploy --app {name} --remote-only",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Fly deploy failed: {stderr.decode()[:500]}")
        return f"https://{name}.fly.dev"

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _guess_content_type(suffix: str) -> str:
        types = {
            ".html": "text/html", ".css": "text/css", ".js": "application/javascript",
            ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
            ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2",
            ".map": "application/json", ".txt": "text/plain", ".md": "text/markdown",
        }
        return types.get(suffix.lower(), "application/octet-stream")

    def list_deployments(self) -> list[dict[str, Any]]:
        return [
            {"id": d.id, "provider": d.provider, "url": d.url, "status": d.status,
             "created_at": d.created_at, "error": d.error}
            for d in self._deployments
        ]
