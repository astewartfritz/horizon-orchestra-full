from __future__ import annotations

from pathlib import Path
from typing import Any

LANGUAGE_CONTEXTS: dict[str, dict[str, Any]] = {
    "rust": {
        "extensions": [".rs"],
        "build": "cargo build",
        "test": "cargo test",
        "lint": "cargo clippy -- -D warnings",
        "fmt": "cargo fmt --check",
        "run": "cargo run -- {args}",
        "add_dep": "cargo add {package}",
        "add_dev_dep": "cargo add --dev {package}",
        "manifest": "Cargo.toml",
        "detect_files": ["Cargo.toml"],
        "common_deps": ["serde", "tokio", "anyhow", "thiserror", "clap", "reqwest", "tracing"],
        "common_dev_deps": ["criterion", "assert_cmd", "predicates", "tempfile"],
        "emoji": "\U0001f980",
    },
    "typescript": {
        "extensions": [".ts", ".tsx", ".mts", ".cts"],
        "build": "npm run build",
        "test": "npm test",
        "lint": "npm run lint",
        "typecheck": "npx tsc --noEmit",
        "add_dep": "npm add {package}",
        "add_dev_dep": "npm add -D {package}",
        "manifest": "package.json",
        "detect_files": ["package.json", "tsconfig.json"],
        "common_deps": ["typescript", "vitest", "@types/node", "tsup"],
        "common_dev_deps": ["eslint", "prettier", "@eslint/js"],
        "emoji": "\U0001f596",
    },
    "python": {
        "extensions": [".py"],
        "build": "pip install -e .",
        "test": "pytest",
        "lint": "ruff check .",
        "fmt": "ruff format --check .",
        "run": "python -m {module} {args}",
        "add_dep": "pip install {package}",
        "manifest": "pyproject.toml",
        "detect_files": ["pyproject.toml", "setup.py", "setup.cfg"],
        "common_deps": ["pytest", "ruff", "mypy"],
        "emoji": "\U0001f40d",
    },
    "mojo": {
        "extensions": [".mojo", "\U0001f525"],
        "build": "mojo build src/main.mojo",
        "test": "mojo test tests/",
        "run": "mojo run src/main.mojo {args}",
        "manifest": "mojoproject.toml",
        "detect_files": ["mojoproject.toml", "*.mojo"],
        "common_deps": [],
        "emoji": "\U0001f525",
    },
}


class LanguageDetector:
    def __init__(self, workspace: str | Path = "."):
        self.workspace = Path(workspace).resolve()

    def detect(self) -> str | None:
        for lang, ctx in LANGUAGE_CONTEXTS.items():
            for fname in ctx["detect_files"]:
                if "*" in fname:
                    if list(self.workspace.glob(fname)):
                        return lang
                elif (self.workspace / fname).exists():
                    return lang
        return None

    def get_context(self, lang: str) -> str:
        ctx = LANGUAGE_CONTEXTS.get(lang)
        if not ctx:
            return ""
        lines = [f"Language: {lang} {ctx.get('emoji', '')}"]
        for key in ("build", "test", "lint", "fmt", "run", "typecheck", "add_dep", "add_dev_dep"):
            val = ctx.get(key)
            if val:
                lines.append(f"  {key}: {val}")
        if ctx.get("common_deps"):
            lines.append(f"  common_deps: {', '.join(ctx['common_deps'])}")
        if ctx.get("common_dev_deps"):
            lines.append(f"  common_dev_deps: {', '.join(ctx['common_dev_deps'])}")
        return "\n".join(lines)

    @staticmethod
    def language_name(lang: str) -> str:
        names = {"rust": "Rust", "typescript": "TypeScript", "python": "Python", "mojo": "Mojo"}
        return names.get(lang, lang.title())

    @staticmethod
    def format_context(lang: str) -> str:
        ctx = LANGUAGE_CONTEXTS.get(lang)
        if not ctx:
            return f"[Project: {lang}]"
        emoji = ctx.get("emoji", "")
        parts = [f"[Project: {lang} {emoji}]"]
        for key in ("build", "test", "lint"):
            if ctx.get(key):
                parts.append(f"  $ {ctx[key]}")
        return "\n".join(parts)
