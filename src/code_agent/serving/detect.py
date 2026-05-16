from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from code_agent.serving.base import ProviderConfig
from code_agent.serving.factory import ProviderFactory


@dataclass
class ProviderStatus:
    provider: str
    available: bool
    models: list[str] = field(default_factory=list)
    default_model: str = ""
    api_key_configured: bool = False
    api_reachable: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "models": self.models,
            "default_model": self.default_model,
            "api_key_configured": self.api_key_configured,
            "api_reachable": self.api_reachable,
        }


class ProviderDetector:
    @staticmethod
    def check_openai() -> ProviderStatus:
        has_key = bool(os.environ.get("OPENAI_API_KEY"))
        return ProviderStatus(
            provider="openai",
            available=has_key,
            models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"] if has_key else [],
            default_model="gpt-4o" if has_key else "",
            api_key_configured=has_key,
            api_reachable=has_key,
        )

    @staticmethod
    def check_anthropic() -> ProviderStatus:
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        return ProviderStatus(
            provider="anthropic",
            available=has_key,
            models=["claude-sonnet-4-20250514", "claude-3-haiku"] if has_key else [],
            default_model="claude-sonnet-4-20250514" if has_key else "",
            api_key_configured=has_key,
            api_reachable=has_key,
        )

    @staticmethod
    async def check_ollama() -> ProviderStatus:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    default = "qwen2.5:7b" if any("qwen2.5" in m for m in models) else (models[0] if models else "")
                    return ProviderStatus(
                        provider="ollama",
                        available=True,
                        models=models,
                        default_model=default or "llama3.1",
                        api_reachable=True,
                    )
        except Exception as e:
            return ProviderStatus(
                provider="ollama",
                available=False,
                error=str(e),
            )
        return ProviderStatus(provider="ollama", available=False)

    @staticmethod
    def check_vllm() -> ProviderStatus:
        try:
            import vllm
            has_vllm = True
            ver = getattr(vllm, "__version__", "unknown")
        except ImportError:
            has_vllm = False
        import torch
        has_gpu = torch.cuda.is_available() if has_vllm else False
        return ProviderStatus(
            provider="vllm",
            available=has_vllm and has_gpu,
            models=["auto"] if (has_vllm and has_gpu) else [],
            default_model="Qwen/Qwen2.5-7B-Instruct" if (has_vllm and has_gpu) else "",
            api_reachable=has_vllm,
            error="" if (has_vllm and has_gpu) else
                ("vLLM not installed" if not has_vllm else "No GPU detected (torch.cuda.is_available()=False)"),
        )

    @staticmethod
    async def detect_best() -> tuple[str, str]:
        ollama = await ProviderDetector.check_ollama()
        if ollama.available:
            return ("ollama", ollama.default_model or "qwen2.5:7b")

        vllm = ProviderDetector.check_vllm()
        if vllm.available:
            return ("vllm", vllm.default_model)

        openai = ProviderDetector.check_openai()
        if openai.available:
            return ("openai", "gpt-4o")

        anthropic = ProviderDetector.check_anthropic()
        if anthropic.available:
            return ("anthropic", "claude-sonnet-4-20250514")

        return ("ollama", "qwen2.5:7b")

    @staticmethod
    async def summary() -> str:
        import asyncio
        openai = ProviderDetector.check_openai()
        anthropic = ProviderDetector.check_anthropic()
        ollama = await ProviderDetector.check_ollama()
        vllm = ProviderDetector.check_vllm()

        lines = ["Provider Status:", "=" * 50]
        for status in [openai, anthropic, ollama, vllm]:
            icon = "\u2705" if status.available else "\u274c"
            api = "\u2705" if status.api_reachable else "\u274c"
            lines.append(f"\n{icon} {status.provider.upper()}")
            lines.append(f"   Available:  {status.available}")
            lines.append(f"   API Key:    {'\u2705' if status.api_key_configured else '\u274c'}")
            lines.append(f"   Reachable:  {api}")
            if status.models:
                lines.append(f"   Models:     {', '.join(status.models[:5])}")
            if status.default_model:
                lines.append(f"   Default:    {status.default_model}")
            if status.error:
                lines.append(f"   Error:      {status.error}")

        best_provider, best_model = await ProviderDetector.detect_best()
        lines.append(f"\n{'=' * 50}")
        lines.append(f"Best available: {best_provider}/{best_model}")
        return "\n".join(lines)
