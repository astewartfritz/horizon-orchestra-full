from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROMPTS: dict[str, dict[str, Any]] = {
    "refactor": {
        "name": "Refactor Code",
        "description": "Refactor a file or function for better structure",
        "prompt": "Refactor the following code to improve readability, maintainability, and performance while preserving the exact same behavior:\n\n{code}",
        "variables": ["code"],
    },
    "explain": {
        "name": "Explain Code",
        "description": "Get a detailed explanation of code",
        "prompt": "Explain what the following code does in detail, including:\n1. Overall purpose\n2. Key functions/classes\n3. Data flow\n4. Edge cases\n\n```\n{code}\n```",
        "variables": ["code"],
    },
    "add-tests": {
        "name": "Add Tests",
        "description": "Generate unit tests for code",
        "prompt": "Write comprehensive unit tests for the following code. Include:\n- Normal cases\n- Edge cases\n- Error cases\n- Mock external dependencies\n\n```python\n{code}\n```\n\nUse pytest style.",
        "variables": ["code"],
    },
    "fix-bug": {
        "name": "Fix Bug",
        "description": "Debug and fix an issue in code",
        "prompt": "The following code has a bug. Identify the issue and provide a fix.\n\nError/Behavior: {error}\n\nCode:\n```\n{code}\n```",
        "variables": ["code", "error"],
    },
    "optimize": {
        "name": "Optimize Performance",
        "description": "Optimize code for speed or memory",
        "prompt": "Optimize the following code for better performance. Focus on:\n- Time complexity\n- Memory usage\n- I/O efficiency\n- Caching opportunities\n\n```\n{code}\n```",
        "variables": ["code"],
    },
    "add-docs": {
        "name": "Add Documentation",
        "description": "Generate docstrings and comments",
        "prompt": "Add comprehensive documentation to the following code:\n- Module-level docstring\n- Function/class docstrings (Google style)\n- Inline comments for complex logic\n\n```python\n{code}\n```",
        "variables": ["code"],
    },
    "security-audit": {
        "name": "Security Audit",
        "description": "Audit code for vulnerabilities",
        "prompt": "Perform a security audit of the following code. Check for:\n- Injection vulnerabilities (SQL, command, XSS)\n- Insecure deserialization\n- Hardcoded secrets/credentials\n- Path traversal\n- Race conditions\n- Insecure crypto\n\n```\n{code}\n```",
        "variables": ["code"],
    },
    "add-type-hints": {
        "name": "Add Type Hints",
        "description": "Add Python type hints to code",
        "prompt": "Add type hints to the following Python code using modern typing syntax:\n\n```python\n{code}\n```\n\nReturn the complete file with type hints added.",
        "variables": ["code"],
    },
    "code-review": {
        "name": "Code Review",
        "description": "Full code review of a file or diff",
        "prompt": "Review the following code changes for:\n1. Correctness\n2. Security issues\n3. Code quality\n4. Performance\n5. Test coverage\n\n```diff\n{diff}\n```",
        "variables": ["diff"],
    },
    "summarize": {
        "name": "Summarize Changes",
        "description": "Summarize git changes for commit messages",
        "prompt": "Summarize the following git diff into a concise commit message:\n\n```diff\n{diff}\n```",
        "variables": ["diff"],
    },
    "scaffold-api": {
        "name": "Scaffold API",
        "description": "Generate a FastAPI endpoint",
        "prompt": "Create a FastAPI endpoint for {endpoint_name}. Include:\n- Pydantic models for request/response\n- Input validation\n- Error handling\n- Docstrings\n- Type hints",
        "variables": ["endpoint_name"],
    },
    "migrate": {
        "name": "Migrate Code",
        "description": "Migrate code between languages or frameworks",
        "prompt": "Migrate the following code from {from_framework} to {to_framework}:\n\n```\n{code}\n```",
        "variables": ["code", "from_framework", "to_framework"],
    },
}


def register_prompt(name: str, data: dict[str, Any]) -> None:
    PROMPTS[name] = data


def get_prompt(name: str, variables: dict[str, str] | None = None) -> str | None:
    entry = PROMPTS.get(name)
    if not entry:
        return None
    prompt = entry["prompt"]
    if variables:
        prompt = prompt.format(**variables)
    return prompt


class PromptLibrary:
    def __init__(self, path: str | None = None):
        self._prompts = dict(PROMPTS)
        if path:
            self.load_from(path)

    def get(self, name: str, **kwargs: str) -> str | None:
        entry = self._prompts.get(name)
        if not entry:
            return None
        prompt = entry["prompt"]
        if kwargs:
            try:
                prompt = prompt.format(**kwargs)
            except KeyError:
                pass
        return prompt

    def list(self) -> list[dict[str, Any]]:
        return [
            {"name": k, "description": v["description"], "variables": v.get("variables", [])}
            for k, v in self._prompts.items()
        ]

    def add(self, name: str, description: str, prompt: str, variables: list[str] | None = None) -> None:
        self._prompts[name] = {
            "name": name,
            "description": description,
            "prompt": prompt,
            "variables": variables or [],
        }

    def load_from(self, path: str) -> int:
        p = Path(path)
        if p.is_file():
            data = json.loads(p.read_text("utf-8"))
        else:
            count = 0
            for f in p.glob("*.json"):
                data = json.loads(f.read_text("utf-8"))
                self._prompts.update(data)
                count += len(data)
            return count
        self._prompts.update(data)
        return len(data)

    def save_to(self, path: str) -> None:
        Path(path).write_text(json.dumps(self._prompts, indent=2), "utf-8")
