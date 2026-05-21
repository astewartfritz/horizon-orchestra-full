from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.agent import Agent
from orchestra.code_agent.config import AgentConfig


@dataclass
class OptimizedPrompt:
    original: str = ""
    optimized: str = ""
    improvements: list[str] = field(default_factory=list)
    score: float = 0.0


OPTIMIZATION_RULES = [
    "Be specific about the desired output format.",
    "Include relevant context: file paths, code snippets, error messages.",
    "Break complex requests into numbered steps.",
    "Specify constraints (languages, frameworks, conventions).",
    "Use action verbs: 'create', 'fix', 'explain', 'refactor', 'optimize'.",
    "Set expectations: 'write code only', 'explain briefly', 'provide alternatives'.",
    "Include negative examples if helpful: 'don't use deprecated APIs'.",
]


class PromptOptimizer:
    """Analyze and improve prompts for better LLM results."""

    def __init__(self):
        self.rules = OPTIMIZATION_RULES

    def analyze(self, prompt: str) -> dict[str, Any]:
        issues = []
        suggestions = []

        if len(prompt) < 20:
            issues.append("very_short")
            suggestions.append("Add more context about what you want")
        if "?" not in prompt and ":" not in prompt:
            issues.append("no_clear_request")
            suggestions.append("Use a question or imperative to make your request clear")
        if len(prompt.split("\n")) < 2 and len(prompt) > 50:
            issues.append("no_structure")
            suggestions.append("Break into paragraphs for readability")
        if "code" in prompt.lower() and "```" not in prompt:
            issues.append("code_without_fences")
            suggestions.append("Use ```code fences for code snippets")
        if prompt.count(".") < 2 and len(prompt) > 30:
            issues.append("run_on")
            suggestions.append("Use multiple sentences to separate ideas")
        if any(w in prompt.lower() for w in ["do it", "make it", "fix it"]):
            issues.append("vague_action")
            suggestions.append("Be specific: what exactly should be done?")

        return {
            "issues": issues,
            "suggestions": suggestions,
            "length": len(prompt),
            "word_count": len(prompt.split()),
            "score": max(0.0, 1.0 - len(issues) * 0.15),
        }

    def optimize(self, prompt: str) -> OptimizedPrompt:
        result = OptimizedPrompt(original=prompt)
        analysis = self.analyze(prompt)
        result.score = analysis["score"]
        result.improvements = analysis["suggestions"]

        optimized = prompt.strip()
        if "very_short" in analysis["issues"]:
            optimized += "\n\n[Provide more context about what you want to achieve, the relevant files, and expected output format.]"
        if "no_structure" in analysis["issues"]:
            optimized = "\n".join(
                f"{i+1}. {line.strip()}" if line.strip() and not line.strip().startswith(("- ", "* ", "1. "))
                else line
                for i, line in enumerate(optimized.split("\n"))
            )
        if "code_without_fences" in analysis["issues"]:
            optimized += "\n\nUse ```language\n...code...\n``` for any code examples."

        result.optimized = optimized
        return result

    async def auto_optimize(self, prompt: str) -> OptimizedPrompt:
        basic = self.optimize(prompt)

        agent = Agent(AgentConfig(name="PromptOptimizer"))
        improved = await agent.run(
            f"Improve this prompt for an AI coding assistant. "
            f"Make it more specific, structured, and actionable.\n\n"
            f"Original prompt:\n{prompt}\n\n"
            f"Return ONLY the improved prompt, no explanation."
        )
        basic.optimized = improved
        basic.improvements.append("AI-optimized for clarity and specificity")
        basic.score = 0.95

        return basic
