from __future__ import annotations

import re
from pathlib import Path
from typing import Any


COMMON_TASKS = [
    "Review the code in {path} for bugs and security issues",
    "Write tests for {path} using pytest",
    "Refactor {path} to improve code quality",
    "Generate documentation for {path}",
    "Analyze the dependency graph of {path}",
    "Fix all linting errors in {path}",
    "Add type hints to {path}",
    "Optimize the performance of {path}",
    "Create a new Python package called {name}",
    "Explain how {path} works",
    "Find and fix the bug in {path}",
    "Add error handling to {path}",
    "Migrate {path} from sync to async",
    "Set up CI/CD pipeline for the project",
    "Create a Dockerfile for the project",
]

FILE_BASED_TASKS = [
    "Analyze {path} and suggest improvements",
    "Add docstrings to all functions in {path}",
    "Generate a test file for {path}",
    "Find any security vulnerabilities in {path}",
    "Explain the architecture of {path}",
    "Refactor {path} to use modern patterns",
    "Find dead code in {path}",
    "Add logging to {path}",
    "Convert {path} to use type hints",
]

PROJECT_TASKS = [
    "Analyze the project structure",
    "Generate a README for the project",
    "Check for outdated dependencies",
    "Run code quality analysis",
    "Generate architecture documentation",
    "Set up linting and formatting config",
    "Create a contribution guide",
    "Audit project for security issues",
]


class TaskCompleter:
    """Suggest tasks to run based on context."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace)

    def suggest(self, context: str = "") -> list[dict[str, Any]]:
        suggestions = []

        if not context:
            # General suggestions
            for task in COMMON_TASKS[:5]:
                suggestions.append({
                    "task": task.replace("{path}", "the project").replace("{name}", "my-package"),
                    "category": "common",
                })
            return suggestions

        context_lower = context.lower()

        if "test" in context_lower or "pytest" in context_lower:
            py_files = list(self.workspace.glob("src/**/*.py"))[:5]
            for f in py_files:
                suggestions.append({
                    "task": f"Write tests for {f.relative_to(self.workspace)}",
                    "category": "testing",
                })
            suggestions.append({
                "task": "Run all tests and report results",
                "category": "testing",
            })

        if "doc" in context_lower or "readme" in context_lower:
            suggestions.append({
                "task": "Generate project documentation",
                "category": "documentation",
            })

        if "bug" in context_lower or "fix" in context_lower or "error" in context_lower:
            suggestions.append({
                "task": "Find and fix bugs in the codebase",
                "category": "debugging",
            })

        if "refactor" in context_lower or "clean" in context_lower:
            suggestions.append({
                "task": "Refactor code for better structure",
                "category": "refactoring",
            })

        if "security" in context_lower or "vuln" in context_lower:
            suggestions.append({
                "task": "Audit project for security vulnerabilities",
                "category": "security",
            })

        if "dep" in context_lower or "update" in context_lower:
            suggestions.append({
                "task": "Check for outdated dependencies and update them",
                "category": "maintenance",
            })

        if not suggestions:
            suggestions.append({
                "task": "Analyze the project and provide a summary",
                "category": "general",
            })

        return suggestions[:8]

    def complete_partial(self, partial: str) -> list[str]:
        partial_lower = partial.lower()
        all_tasks = COMMON_TASKS + FILE_BASED_TASKS + PROJECT_TASKS
        matches = []
        for task in all_tasks:
            task_lower = task.lower()
            if partial_lower in task_lower:
                matches.append(task)
        return matches[:10]
