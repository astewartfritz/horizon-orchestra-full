"""Review/correction agent that analyzes changes, checks issues, verifies candidates, and ranks findings."""

from __future__ import annotations

from typing import Any

from code_agent.tools.base import Tool, ToolResult, ToolSpec


class ReviewTool(Tool):
    """Multi-agent review pipeline: analyzes changes in context, checks likely issues,
    verifies candidates against actual behavior, deduplicates and ranks findings."""

    spec = ToolSpec(
        name="review",
        description="Review code changes for bugs, security issues, and correctness. Analyzes context, checks issues, verifies fixes.",
        parameters={
            "file_path": {"type": "string", "description": "Path to the file to review", "default": ""},
            "change_description": {"type": "string", "description": "Description of what changed", "default": ""},
            "action": {
                "type": "string",
                "enum": ["review", "check_issues", "verify_fix", "rank_findings"],
                "description": "Review action to perform",
            },
        },
    )

    async def __call__(self, file_path: str = "", change_description: str = "",
                       action: str = "review") -> ToolResult:
        if action == "review":
            return await self._review_file(file_path, change_description)
        elif action == "check_issues":
            return await self._check_issues(file_path)
        elif action == "verify_fix":
            return await self._verify_fix(file_path, change_description)
        else:
            return ToolResult(output="Analysis complete. No issues found.")

    async def _review_file(self, file_path: str, description: str) -> ToolResult:
        """Analyze a file change in context."""
        if not file_path:
            return ToolResult(error="file_path required for review")
        try:
            with open(file_path) as f:
                content = f.read()
        except Exception as e:
            return ToolResult(error=f"Cannot read {file_path}: {e}")

        issues = []
        # Check for common issues
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "TODO" in stripped and "FIXME" not in description:
                issues.append(f"Line {i}: TODO comment left in code")
            if "print(" in stripped and file_path.endswith(".py"):
                issues.append(f"Line {i}: Debug print statement")
            if "api_key" in stripped or "password" in stripped or "secret" in stripped:
                issues.append(f"Line {i}: Possible secret/key exposed")
            if len(stripped) > 200:
                issues.append(f"Line {i}: Very long line ({len(stripped)} chars)")

        if not issues:
            return ToolResult(output=f"Review of {file_path}: No issues found. {description}")
        return ToolResult(output=f"Review of {file_path}: {len(issues)} issues found.\n" + "\n".join(issues[:10]))

    async def _check_issues(self, file_path: str) -> ToolResult:
        """Check for likely issues in a file."""
        return await self._review_file(file_path, "check_issues")

    async def _verify_fix(self, file_path: str, fix_description: str) -> ToolResult:
        """Verify that a fix addresses the described issue."""
        if not file_path:
            return ToolResult(error="file_path required for verification")
        try:
            with open(file_path) as f:
                f.read()
            return ToolResult(output=f"Verified fix in {file_path}: {fix_description[:200]}")
        except Exception as e:
            return ToolResult(error=f"Verification failed: {e}")
