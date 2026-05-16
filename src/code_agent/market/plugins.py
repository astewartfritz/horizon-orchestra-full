from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


BUILTIN_PLUGINS = [
    {
        "name": "docker-sandbox",
        "description": "Run commands in isolated Docker containers",
        "url": "",
        "version": "0.1.0",
        "type": "tool",
    },
    {
        "name": "code-analyzer",
        "description": "Deep AST-based code analysis",
        "url": "",
        "version": "0.1.0",
        "type": "tool",
    },
    {
        "name": "test-generator",
        "description": "Auto-generate unit tests from source code",
        "url": "",
        "version": "0.1.0",
        "type": "tool",
    },
    {
        "name": "file-watcher",
        "description": "Watch files and trigger actions on changes",
        "url": "",
        "version": "0.1.0",
        "type": "tool",
    },
    {
        "name": "web-scraper",
        "description": "Scrape and extract content from web pages",
        "url": "",
        "version": "0.1.0",
        "type": "tool",
    },
    {
        "name": "git-manager",
        "description": "Advanced git operations and branch management",
        "url": "",
        "version": "0.1.0",
        "type": "tool",
    },
    {
        "name": "secret-scanner",
        "description": "Scan for secrets and credentials in codebase",
        "url": "",
        "version": " ",
        "type": "tool",
    },
    {
        "name": "multi-lang",
        "description": "Analyze code across Python, JS, TS, Rust, Go, Java",
        "url": "",
        "version": "0.1.0",
        "type": "tool",
    },
]


class PluginMarket:
    """Discover and install community plugins."""

    def __init__(self, registry_url: str = ""):
        self.registry_url = registry_url
        self._cache: list[dict[str, Any]] = []

    def list_builtin(self) -> list[dict[str, Any]]:
        return list(BUILTIN_PLUGINS)

    async def fetch_remote(self) -> list[dict[str, Any]]:
        if not self.registry_url:
            return []

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.registry_url)
                if resp.status_code == 200:
                    self._cache = resp.json()
                    return self._cache
        except Exception:
            pass
        return []

    def search(self, query: str, source: str = "all") -> list[dict[str, Any]]:
        q = query.lower()
        results = []

        if source in ("all", "builtin"):
            for p in BUILTIN_PLUGINS:
                if q in p["name"].lower() or q in p["description"].lower():
                    results.append({**p, "_source": "builtin"})

        if source in ("all", "remote"):
            for p in self._cache:
                if q in p.get("name", "").lower() or q in p.get("description", "").lower():
                    results.append({**p, "_source": "remote"})

        return results

    def install(self, plugin_name: str, target_dir: str = ".agent-plugins") -> dict[str, Any]:
        info = None
        for p in BUILTIN_PLUGINS:
            if p["name"] == plugin_name:
                info = p
                break

        if not info:
            return {"success": False, "error": f"Plugin '{plugin_name}' not found"}

        out = Path(target_dir)
        out.mkdir(parents=True, exist_ok=True)

        meta_file = out / f"{plugin_name}.json"
        meta_file.write_text(json.dumps(info, indent=2))

        return {"success": True, "message": f"Installed {plugin_name} to {target_dir}/"}

    def list_installed(self, plugin_dir: str = ".agent-plugins") -> list[dict[str, Any]]:
        results = []
        d = Path(plugin_dir)
        if d.exists():
            for f in d.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    results.append(data)
                except (json.JSONDecodeError, OSError):
                    pass
        return results
