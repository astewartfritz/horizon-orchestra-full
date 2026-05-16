from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NemoclawConfig:
    provider: str = "ollama"
    model: str = "nemotron-mini"
    timeout: int = 30
    confidence_threshold: float = 0.5
    cache_size: int = 100
    enabled: bool = True


@dataclass
class NemoclawCheck:
    passed: bool
    severity: str = "warning"
    message: str = ""
    reasoning: str = ""
    confidence: float = 1.0
    category: str = "general"
    latency_ms: float = 0.0

    @property
    def label(self) -> str:
        return "BLOCK" if self.severity == "block" else "WARN" if self.severity == "warning" else "PASS"


NEMOCLAW_SYSTEM_PROMPT = """You are a safety guardrail system. Your job is to evaluate whether a given action is safe, appropriate, and non-destructive. You must respond with ONLY valid JSON in the exact format shown below. No other text.

Evaluate the action based on these criteria:
- Is this destructive or could cause data loss?
- Does it modify critical system/config files?
- Does it expose secrets or credentials?
- Is it appropriate for the context?
- Does it follow security best practices?

Response format:
{
  "passed": true/false,
  "severity": "pass" / "warning" / "block",
  "reasoning": "Brief explanation of the verdict",
  "confidence": 0.0-1.0,
  "category": "destructive" / "secrets" / "config" / "general" / "safe"
}"""


class Nemoclaw:
    def __init__(self, config: NemoclawConfig | None = None):
        self.config = config or NemoclawConfig()
        self._provider = None
        self._cache: dict[str, NemoclawCheck] = {}
        self._stats: dict[str, Any] = {
            "total_checks": 0,
            "blocks": 0,
            "warnings": 0,
            "passes": 0,
            "cache_hits": 0,
            "total_latency_ms": 0,
        }

    def _cache_key(self, action: str, context: dict[str, Any]) -> str:
        return f"{action}:{json.dumps(context, sort_keys=True, default=str)[:200]}"

    def _get_llm(self):
        if self._provider is not None:
            return self._provider
        from code_agent.llm.base import LLM
        self._provider = LLM(
            provider=self.config.provider,
            model=self.config.model,
            timeout=self.config.timeout,
        )
        return self._provider

    async def _ask_llm(self, action: str, context: dict[str, Any]) -> dict[str, Any]:
        llm = self._get_llm()
        from code_agent.llm.base import Message
        user_prompt = f"Action: {action}\n\nContext:\n{json.dumps(context, indent=2, default=str)}"
        try:
            resp = await llm.chat(
                messages=[
                    Message(role="system", content=NEMOCLAW_SYSTEM_PROMPT),
                    Message(role="user", content=user_prompt),
                ],
            )
            content = resp.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                content = content.rsplit("```", 1)[0]
            return json.loads(content)
        except Exception:
            return {"passed": True, "severity": "pass", "reasoning": "LLM check failed, allowing by default", "confidence": 0.0, "category": "general"}

    async def check(self, action: str, context: dict[str, Any] | None = None) -> NemoclawCheck:
        if not self.config.enabled:
            return NemoclawCheck(passed=True, severity="pass", message="Nemoclaw disabled", confidence=1.0)
        ctx = context or {}
        key = self._cache_key(action, ctx)
        if key in self._cache:
            self._stats["cache_hits"] += 1
            return self._cache[key]
        start = time.perf_counter()
        result = await self._ask_llm(action, ctx)
        latency = (time.perf_counter() - start) * 1000
        passed = result.get("passed", True)
        severity = result.get("severity", "pass")
        if severity not in ("pass", "warning", "block"):
            severity = "pass"
        if severity == "block":
            passed = False
        check = NemoclawCheck(
            passed=passed,
            severity=severity,
            message=result.get("reasoning", ""),
            reasoning=result.get("reasoning", ""),
            confidence=result.get("confidence", 0.5),
            category=result.get("category", "general"),
            latency_ms=round(latency, 1),
        )
        self._cache[key] = check
        if len(self._cache) > self.config.cache_size:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._stats["total_checks"] += 1
        self._stats["total_latency_ms"] += latency
        if check.severity == "block":
            self._stats["blocks"] += 1
        elif check.severity == "warning":
            self._stats["warnings"] += 1
        else:
            self._stats["passes"] += 1
        return check

    async def check_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> NemoclawCheck:
        action = f"tool_call: {tool_name}"
        context = {"arguments": tool_args}
        return await self.check(action, context)

    async def check_command(self, command: str) -> NemoclawCheck:
        action = "command"
        context = {"command": command}
        return await self.check(action, context)

    async def check_file_write(self, file_path: str, content: str) -> NemoclawCheck:
        action = "file_write"
        context = {"file_path": file_path, "content_preview": content[:500]}
        return await self.check(action, context)

    async def check_output(self, output: str, tool_name: str = "") -> NemoclawCheck:
        action = f"tool_output: {tool_name}" if tool_name else "output"
        context = {"output_preview": output[:500]}
        return await self.check(action, context)

    def stats(self) -> dict[str, Any]:
        avg_latency = 0.0
        if self._stats["total_checks"] > 0:
            avg_latency = round(self._stats["total_latency_ms"] / self._stats["total_checks"], 1)
        return {
            **self._stats,
            "avg_latency_ms": avg_latency,
            "cache_size": len(self._cache),
            "provider": self.config.provider,
            "model": self.config.model,
            "enabled": self.config.enabled,
        }

    def clear_cache(self) -> int:
        n = len(self._cache)
        self._cache.clear()
        return n

    async def health(self) -> dict[str, Any]:
        try:
            start = time.perf_counter()
            check = await self.check("health_check", {"test": True})
            latency = (time.perf_counter() - start) * 1000
            return {
                "healthy": check.passed,
                "latency_ms": round(latency, 1),
                "provider": self.config.provider,
                "model": self.config.model,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}
