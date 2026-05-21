"""GitHub repo connection routes for the Orchestra UI."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

import httpx

_GH_API = "https://api.github.com"
_token_cache: dict[str, str] = {}  # session-local; real auth uses GITHUB_TOKEN env


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Orchestra/1.0",
    }


def _get_token(request: Request) -> str:
    return (
        request.headers.get("X-GitHub-Token", "")
        or os.environ.get("GITHUB_TOKEN", "")
    )


def register_github_routes(app: Any) -> None:
    router = APIRouter(prefix="/api/github")

    @router.get("/status")
    async def github_status(request: Request):
        token = _get_token(request)
        if not token:
            return {"connected": False, "user": None}
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{_GH_API}/user", headers=_headers(token))
                if r.status_code == 200:
                    u = r.json()
                    return {
                        "connected": True,
                        "user": {
                            "login": u.get("login"),
                            "name": u.get("name"),
                            "avatar_url": u.get("avatar_url"),
                            "public_repos": u.get("public_repos", 0),
                        },
                    }
        except Exception:
            pass
        return {"connected": False, "user": None}

    @router.get("/repos")
    async def list_repos(
        request: Request,
        page: int = 1,
        per_page: int = 30,
        sort: str = "pushed",
    ):
        token = _get_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="No GitHub token. Set GITHUB_TOKEN env var or pass X-GitHub-Token header.")
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{_GH_API}/user/repos",
                headers=_headers(token),
                params={"sort": sort, "per_page": per_page, "page": page, "affiliation": "owner,collaborator"},
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            repos = r.json()
            return {
                "repos": [
                    {
                        "id": repo["id"],
                        "full_name": repo["full_name"],
                        "name": repo["name"],
                        "description": repo.get("description") or "",
                        "private": repo.get("private", False),
                        "language": repo.get("language") or "",
                        "stargazers_count": repo.get("stargazers_count", 0),
                        "pushed_at": repo.get("pushed_at") or "",
                        "default_branch": repo.get("default_branch", "main"),
                        "clone_url": repo.get("clone_url", ""),
                        "html_url": repo.get("html_url", ""),
                    }
                    for repo in repos
                ],
                "page": page,
            }

    @router.get("/repos/{owner}/{repo}/branches")
    async def list_branches(owner: str, repo: str, request: Request):
        token = _get_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="No GitHub token")
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{_GH_API}/repos/{owner}/{repo}/branches",
                headers=_headers(token),
                params={"per_page": 50},
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            return {"branches": [b["name"] for b in r.json()]}

    @router.get("/repos/{owner}/{repo}/tree")
    async def repo_tree(owner: str, repo: str, request: Request, branch: str = ""):
        token = _get_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="No GitHub token")
        async with httpx.AsyncClient(timeout=15) as c:
            # Get default branch if not specified
            if not branch:
                rr = await c.get(f"{_GH_API}/repos/{owner}/{repo}", headers=_headers(token))
                branch = rr.json().get("default_branch", "main") if rr.status_code == 200 else "main"
            r = await c.get(
                f"{_GH_API}/repos/{owner}/{repo}/git/trees/{branch}",
                headers=_headers(token),
                params={"recursive": "1"},
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            tree = r.json().get("tree", [])
            # Return compact tree — paths only, max 300
            return {
                "branch": branch,
                "files": [
                    {"path": item["path"], "type": item["type"], "size": item.get("size", 0)}
                    for item in tree[:300]
                    if item["type"] in ("blob", "tree")
                ],
            }

    @router.post("/clone")
    async def clone_repo(body: dict[str, Any], request: Request):
        """Clone a GitHub repo to a local path and set it as workspace."""
        import asyncio, shutil
        token = _get_token(request)
        clone_url = body.get("clone_url", "")
        dest = body.get("dest", "")
        if not clone_url or not dest:
            raise HTTPException(status_code=400, detail="clone_url and dest are required")

        # Inject token into URL for private repos
        if token and clone_url.startswith("https://github.com/"):
            clone_url = clone_url.replace("https://github.com/", f"https://x-token:{token}@github.com/")

        if not shutil.which("git"):
            raise HTTPException(status_code=503, detail="git not found on PATH")

        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", clone_url, dest,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=stderr.decode()[:500])
        return {"cloned": True, "path": dest}

    app.include_router(router)
