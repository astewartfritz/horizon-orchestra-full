from __future__ import annotations

from typing import Any

from code_agent.security.scanner import SecretScanner
from code_agent.tools.base import Tool, ToolResult, ToolSpec


class SecurityAuditTool(Tool):
    spec = ToolSpec(
        name="security_audit",
        description="Scan code for secrets, API keys, tokens, and credentials. Helps prevent accidental exposure.",
        parameters={
            "path": {"type": "string", "description": "Directory or file to scan", "default": "."},
            "pattern": {"type": "string", "description": "Glob pattern", "default": "**/*"},
            "git_history": {"type": "boolean", "description": "Also scan git commit history", "default": False},
            "action": {"type": "string", "description": "scan, summary", "default": "scan"},
        },
    )

    async def __call__(
        self, path: str = ".", pattern: str = "**/*",
        git_history: bool = False, action: str = "scan",
    ) -> ToolResult:
        try:
            scanner = SecretScanner(path)
            results = scanner.scan_directory(pattern)

            if git_history:
                results.extend(scanner.scan_git_history())

            if action == "summary":
                by_severity: dict[str, int] = {}
                by_type: dict[str, int] = {}
                for r in results:
                    by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
                    by_type[r.pattern_name] = by_type.get(r.pattern_name, 0) + 1

                lines = [
                    f"Scan complete: {len(results)} potential secrets found\n",
                    "By severity:",
                ]
                for sev, cnt in sorted(by_severity.items()):
                    lines.append(f"  {sev}: {cnt}")
                lines.append("\nBy type:")
                for pname, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
                    lines.append(f"  {pname}: {cnt}")
                return ToolResult(output="\n".join(lines))

            if not results:
                return ToolResult(output="No secrets found.")

            lines = [f"Found {len(results)} potential secrets:\n"]
            for r in results[:50]:
                lines.append(f"  [{r.severity:7}] {r.file}:{r.line} ({r.pattern_name})")
                lines.append(f"          {r.match[:60]}")
            if len(results) > 50:
                lines.append(f"\n... and {len(results) - 50} more")
            return ToolResult(output="\n".join(lines))

        except Exception as e:
            return ToolResult(error=str(e))
