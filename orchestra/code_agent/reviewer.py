from __future__ import annotations

from orchestra.code_agent.config import LLMConfig
from orchestra.code_agent.llm.base import LLM, Message


REVIEW_PROMPT = """You are an expert code reviewer. Analyze the following code or diff and provide:
1. Summary of changes (if diff)
2. Potential bugs or issues
3. Security concerns
4. Code quality/style suggestions
5. Performance considerations

Be concise and actionable. Focus on the most important issues first.

Code/Changes:
```"""


class CodeReviewer:
    def __init__(self, llm_config: LLMConfig | None = None):
        cfg = llm_config or LLMConfig(model="gpt-4o-mini")
        self.llm = LLM(
            provider=cfg.provider,
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            max_tokens=cfg.max_tokens,
            temperature=0.2,
            timeout=cfg.timeout,
        )

    async def review(self, code_or_diff: str, context: str | None = None) -> str:
        messages = [Message(role="system", content=REVIEW_PROMPT)]
        if context:
            messages.append(
                Message(role="user", content=f"Context: {context}\n\n{code_or_diff}")
            )
        else:
            messages.append(Message(role="user", content=code_or_diff))

        response = await self.llm.chat(messages=messages)
        return response.content or "(no review generated)"

    async def review_file(self, file_path: str) -> str:
        from pathlib import Path

        p = Path(file_path)
        if not p.exists():
            return f"File not found: {file_path}"
        content = p.read_text("utf-8")

        ext = p.suffix
        lang_map = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript React",
            ".jsx": "JavaScript React",
            ".rs": "Rust",
            ".go": "Go",
            ".java": "Java",
            ".rb": "Ruby",
            ".c": "C",
            ".cpp": "C++",
            ".h": "C Header",
            ".cs": "C#",
            ".swift": "Swift",
            ".kt": "Kotlin",
            ".scala": "Scala",
        }
        lang = lang_map.get(ext, "")
        context = f"File: {p.name} ({lang})" if lang else f"File: {p.name}"

        return await self.review(content, context=context)

    async def review_diff(self, diff_text: str, repo_path: str | None = None) -> str:
        messages = [Message(
            role="system",
            content=("You are an expert code reviewer. Review this git diff and provide "
                     "actionable feedback on bugs, security issues, and code quality.")
        )]
        msg = f"```diff\n{diff_text}\n```"
        if repo_path:
            msg = f"Repository: {repo_path}\n\n{msg}"
        messages.append(Message(role="user", content=msg))

        response = await self.llm.chat(messages=messages)
        return response.content or "(no review generated)"

    async def review_pr(
        self, title: str, description: str, diff: str
    ) -> str:
        messages = [
            Message(
                role="system",
                content=("You are an expert code reviewer reviewing a pull request. "
                         "Analyze the changes and provide a thorough review.")
            ),
            Message(
                role="user",
                content=(
                    f"## PR Title: {title}\n"
                    f"## Description:\n{description}\n\n"
                    f"## Diff:\n```diff\n{diff[:10000]}\n```\n\n"
                    "Provide your review covering: correctness, security, "
                    "code quality, testing, and any blocking issues."
                ),
            ),
        ]
        response = await self.llm.chat(messages=messages)
        return response.content or "(no review generated)"
