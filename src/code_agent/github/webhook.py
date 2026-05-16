from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

from fastapi import FastAPI, Request, HTTPException


class GitHubWebhookHandler:
    """Handle GitHub webhooks for auto-review of PRs and pushes."""

    def __init__(self, secret: str = ""):
        self.secret = secret
        self.app = FastAPI(title="GitHub Webhook Handler")
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.post("/webhook")
        async def webhook(request: Request):
            body = await request.body()
            signature = request.headers.get("X-Hub-Signature-256", "")
            event = request.headers.get("X-GitHub-Event", "")

            if self.secret and not self._verify_signature(body, signature):
                raise HTTPException(403, "Invalid signature")

            payload = json.loads(body)
            if event == "pull_request":
                asyncio.create_task(self._handle_pull_request(payload))
                return {"status": "processing", "event": event}
            elif event == "push":
                asyncio.create_task(self._handle_push(payload))
                return {"status": "processing", "event": event}
            else:
                return {"status": "ignored", "event": event}

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        if not signature:
            return False
        expected = hmac.new(
            self.secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    async def _handle_pull_request(self, payload: dict) -> None:
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        diff_url = pr.get("diff_url", "")
        title = pr.get("title", "")

        if action in ("opened", "synchronize"):
            from code_agent.agent import Agent
            from code_agent.config import AgentConfig

            agent = Agent(AgentConfig(name="PR-Reviewer"))
            review = await agent.run(
                f"Review the following pull request:\nTitle: {title}\n"
                f"Diff URL: {diff_url}\n\n"
                f"Provide a thorough code review covering bugs, security, "
                f"performance, and best practices."
            )

            # Post review as comment via GitHub API
            comments_url = pr.get("comments_url", "")
            if comments_url:
                import httpx
                async with httpx.AsyncClient() as client:
                    await client.post(comments_url, json={"body": review[:5000]})

    async def _handle_push(self, payload: dict) -> None:
        ref = payload.get("ref", "")
        commits = payload.get("commits", [])
        if not commits:
            return

        for commit in commits[:3]:
            message = commit.get("message", "")
            author = commit.get("author", {}).get("name", "")
            modified = commit.get("modified", [])

            if modified:
                from code_agent.agent import Agent
                from code_agent.config import AgentConfig
                agent = Agent(AgentConfig(name="Commit-Validator"))
                result = await agent.run(
                    f"Review these modified files in commit '{message[:80]}' by {author}:\n"
                    + "\n".join(f"  - {f}" for f in modified[:10])
                )

    def validate_config(self) -> dict[str, Any]:
        return {
            "secret_configured": bool(self.secret),
            "endpoints": ["/webhook"],
        }
