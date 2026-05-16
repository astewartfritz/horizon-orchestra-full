from __future__ import annotations

from pathlib import Path

from code_agent.tools.base import Tool, ToolResult, ToolSpec

try:
    import git as git_mod
    HAS_GIT = True
except ImportError:
    HAS_GIT = False


class GitTool(Tool):
    spec = ToolSpec(
        name="git",
        description="Run Git operations: status, diff, log, add, commit, branch, push, clone, etc.",
        parameters={
            "action": {
                "type": "string",
                "description": "Git operation: status, diff, log, add, commit, branch, checkout, push, pull, clone, init, remote",
            },
            "args": {
                "type": "string",
                "description": "Arguments for the action (e.g. file paths for add, commit message for commit)",
                "default": "",
            },
            "path": {
                "type": "string",
                "description": "Repository path (default: workspace)",
            },
        },
    )

    async def __call__(self, action: str, args: str = "", path: str | None = None) -> ToolResult:
        if not HAS_GIT:
            return ToolResult(error="GitPython is not installed. Install with: pip install GitPython")
        try:
            repo_path = Path(path) if path else Path.cwd()
            repo = git_mod.Repo(repo_path)

            match action:
                case "status":
                    return ToolResult(output=repo.git.status())
                case "diff":
                    target = args.strip() or "HEAD"
                    return ToolResult(output=repo.git.diff(target))
                case "log":
                    n = args.strip() or "10"
                    return ToolResult(output=repo.git.log(f"--oneline", f"-{n}"))
                case "add":
                    repo.index.add(args.split())
                    return ToolResult(output=f"Staged: {args}")
                case "commit":
                    repo.index.commit(args)
                    return ToolResult(output=f"Committed: {args}")
                case "branch":
                    return ToolResult(output=repo.git.branch())
                case "checkout":
                    repo.git.checkout(args)
                    return ToolResult(output=f"Checked out: {args}")
                case "push":
                    parts = args.split() or []
                    remote = parts[0] if len(parts) > 0 else "origin"
                    branch = parts[1] if len(parts) > 1 else repo.active_branch.name
                    repo.git.push(remote, branch)
                    return ToolResult(output=f"Pushed to {remote}/{branch}")
                case "pull":
                    parts = args.split() or []
                    remote = parts[0] if len(parts) > 0 else "origin"
                    repo.git.pull(remote)
                    return ToolResult(output=f"Pulled from {remote}")
                case "clone":
                    repo.git.clone(args, repo_path)
                    return ToolResult(output=f"Cloned into {repo_path}")
                case "init":
                    repo_path.mkdir(parents=True, exist_ok=True)
                    git_mod.Repo.init(repo_path)
                    return ToolResult(output=f"Initialized repo at {repo_path}")
                case _:
                    return ToolResult(error=f"Unknown git action: {action}")
        except Exception as e:
            return ToolResult(error=str(e))
