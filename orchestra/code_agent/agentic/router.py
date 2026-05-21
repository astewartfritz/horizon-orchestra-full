"""Intent router — maps user requests to tool chains and workflows.

The agent uses this to figure out what tools to call for a given task.
"""

from __future__ import annotations

from typing import Any

from orchestra.code_agent.agentic.navigator import CapabilityRegistry


class IntentRouter:
    """Maps natural language intents to tool chains and capability paths."""

    def __init__(self):
        self.registry = CapabilityRegistry()
        self._routes: list[dict[str, Any]] = [
            {
                "patterns": ["read", "open", "show", "view", "list", "display", "find", "search", "grep", "glob"],
                "capability": "file_operations",
                "primary_tool": "read",
                "description": "Read and search files",
            },
            {
                "patterns": ["write", "create", "edit", "update", "modify", "change", "add", "delete", "remove", "rename"],
                "capability": "file_operations",
                "primary_tool": "write",
                "description": "Create and modify files",
            },
            {
                "patterns": ["run", "execute", "bash", "shell", "command", "terminal", "install", "build", "compile"],
                "capability": "shell_execution",
                "primary_tool": "bash",
                "description": "Run shell commands",
            },
            {
                "patterns": ["test", "unit test", "pytest", "integration", "coverage", "assert"],
                "capability": "code_intelligence",
                "primary_tool": "testgen",
                "description": "Generate and run tests",
            },
            {
                "patterns": ["review", "audit", "inspect", "check", "validate", "lint"],
                "capability": "code_intelligence",
                "primary_tool": "review",
                "description": "Review and audit code",
            },
            {
                "patterns": ["refactor", "transform", "rewrite", "restructure", "extract", "inline"],
                "capability": "code_intelligence",
                "primary_tool": "transform",
                "description": "Refactor and transform code",
            },
            {
                "patterns": ["commit", "push", "pull", "git", "branch", "merge", "pr", "pull request"],
                "capability": "git_operations",
                "primary_tool": "git",
                "description": "Git version control operations",
            },
            {
                "patterns": ["search", "browse", "web", "google", "research", "look up", "find information"],
                "capability": "web_interaction",
                "primary_tool": "websearch",
                "description": "Search and browse the web",
            },
            {
                "patterns": ["scaffold", "generate", "template", "project", "init", "new project", "boilerplate"],
                "capability": "scaffolding",
                "primary_tool": "scaffold",
                "description": "Generate project scaffolds",
            },
            {
                "patterns": ["learn", "remember", "save", "store", "recall", "skill"],
                "capability": "knowledge_management",
                "primary_tool": "skill",
                "description": "Manage knowledge and skills",
            },
        ]

    def route(self, task: str) -> list[dict[str, Any]]:
        """Route a task to the most relevant tool chains."""
        task_lower = task.lower()
        matches = []
        for route in self._routes:
            score = 0
            for pattern in route["patterns"]:
                if pattern in task_lower:
                    score += 1
                    if task_lower.startswith(pattern):
                        score += 2  # Bonus for starting with the pattern
            if score > 0:
                matches.append({
                    "route": route["capability"],
                    "primary_tool": route["primary_tool"],
                    "description": route["description"],
                    "score": score,
                    "all_tools": self.registry.get_tools_for(route["capability"]),
                })
        matches.sort(key=lambda x: -x["score"])
        return matches

    def suggest_workflow(self, task: str) -> list[str]:
        """Suggest a workflow (sequence of tools) based on the task."""
        routes = self.route(task)
        if not routes:
            return ["read", "grep", "analyze"]  # Default: explore first

        workflow = []
        seen = set()
        for r in routes:
            for tool in r.get("all_tools", []):
                if tool not in seen:
                    workflow.append(tool)
                    seen.add(tool)
        return workflow[:5]  # Max 5 steps
