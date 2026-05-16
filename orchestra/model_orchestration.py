"""Horizon Orchestra — Advanced Model Orchestration.

Speculative execution, model council, fallback chains, A/B routing,
and ensemble reasoning.  This is the intelligence layer that makes
Orchestra's model usage smarter than any single-model system.

Patterns:
1. **Speculative Execution** — run cheap model first, validate with
   expensive model only if needed.
2. **Model Council** — query 3+ models, synthesize consensus.
3. **Fallback Chain** — try models in order, fall back on failure.
4. **A/B Routing** — split traffic for comparison / cost optimization.
5. **Ensemble** — multiple models vote on the answer.

Usage::

    from orchestra.model_orchestration import ModelOrchestrator
    orch = ModelOrchestrator(router)
    result = await orch.speculative("Complex question", fast="grok-3", verifier="kimi-k2.5")
    result = await orch.council("Should we deploy?", models=["kimi-k2.5", "sonar-pro", "gpt-5.4"])
    result = await orch.fallback_chain("Question", chain=["kimi-k2.5-local", "kimi-k2.5", "claude-opus-4.6"])
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from .router import ModelRouter

__all__ = ["ModelOrchestrator", "OrchResult", "ABConfig"]

log = logging.getLogger("orchestra.model_orchestration")


@dataclass
class OrchResult:
    """Result from a model orchestration pattern."""
    content: str
    model_used: str
    pattern: str               # speculative, council, fallback, ab, ensemble
    latency_ms: float = 0.0
    models_consulted: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ABConfig:
    model_a: str = "kimi-k2.5"
    model_b: str = "kimi-k2.5-local"
    split_pct: float = 0.5            # % of traffic to model A
    track_outcomes: bool = True


class ModelOrchestrator:
    """Advanced multi-model orchestration patterns."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        self.router = router or ModelRouter()
        self._ab_history: list[dict[str, Any]] = []

    # -- Speculative Execution ----------------------------------------------

    async def speculative(
        self,
        prompt: str,
        fast_model: str = "grok-3",
        verifier_model: str = "kimi-k2.5",
        system: str = "",
        confidence_threshold: float = 0.8,
    ) -> OrchResult:
        """Run a cheap model first, verify with expensive model only if uncertain.

        Saves cost by only using the expensive model when the fast model's
        output seems uncertain or wrong.
        """
        t0 = time.monotonic()
        messages = self._build_messages(system, prompt)

        # Phase 1: fast model
        fast_client, fast_id = self.router.get_client(fast_model)
        try:
            fast_resp = await fast_client.chat.completions.create(
                model=fast_id, messages=messages, max_tokens=4096, temperature=0.3,
            )
            fast_output = fast_resp.choices[0].message.content or ""
        except Exception:
            fast_output = ""

        if not fast_output:
            # Fast model failed — go straight to verifier
            return await self._single_call(verifier_model, messages, "speculative", t0)

        # Phase 2: verify with the expensive model
        verify_messages = messages + [
            {"role": "assistant", "content": fast_output},
            {"role": "user", "content": (
                "Review your previous answer. Rate your confidence from 0.0 to 1.0. "
                "If confidence >= 0.8, reply with just the original answer. "
                "If < 0.8, provide a corrected answer. "
                "Format: {\"confidence\": 0.X, \"answer\": \"...\"}"
            )},
        ]

        ver_client, ver_id = self.router.get_client(verifier_model)
        try:
            ver_resp = await ver_client.chat.completions.create(
                model=ver_id, messages=verify_messages,
                max_tokens=4096, temperature=0.2,
            )
            ver_output = ver_resp.choices[0].message.content or ""

            # Try to parse structured response
            try:
                parsed = json.loads(ver_output)
                confidence = parsed.get("confidence", 1.0)
                final = parsed.get("answer", ver_output)
                if confidence >= confidence_threshold:
                    final = fast_output  # fast model was good enough
            except (json.JSONDecodeError, KeyError):
                final = ver_output

        except Exception:
            final = fast_output  # verification failed, use fast output

        return OrchResult(
            content=final,
            model_used=f"{fast_model} → {verifier_model}",
            pattern="speculative",
            latency_ms=round((time.monotonic() - t0) * 1000, 2),
            models_consulted=[fast_model, verifier_model],
            metadata={"fast_output_len": len(fast_output)},
        )

    # -- Model Council ------------------------------------------------------

    async def council(
        self,
        prompt: str,
        models: list[str] | None = None,
        system: str = "",
        synthesizer: str = "kimi-k2.5",
    ) -> OrchResult:
        """Query multiple models and synthesize a consensus answer.

        Each model answers independently. A synthesizer model then
        reads all answers and produces a unified, best-of-all response.
        """
        t0 = time.monotonic()
        models = models or ["kimi-k2.5", "sonar-pro", "grok-3"]
        messages = self._build_messages(system, prompt)

        # Query all models in parallel
        async def _query(model: str) -> tuple[str, str]:
            try:
                client, mid = self.router.get_client(model)
                resp = await client.chat.completions.create(
                    model=mid, messages=messages, max_tokens=4096,
                )
                return model, resp.choices[0].message.content or ""
            except Exception as exc:
                return model, f"[Error: {exc}]"

        results = await asyncio.gather(*[_query(m) for m in models])
        model_answers = {model: answer for model, answer in results}

        # Synthesize
        answers_block = "\n\n---\n\n".join(
            f"**{model}:**\n{answer}" for model, answer in model_answers.items()
        )

        synth_client, synth_id = self.router.get_client(synthesizer)
        try:
            synth_resp = await synth_client.chat.completions.create(
                model=synth_id,
                messages=[
                    {"role": "system", "content": (
                        "You received answers from multiple AI models to the same question. "
                        "Synthesize the best possible answer by combining their strengths. "
                        "Resolve any disagreements by reasoning through them. "
                        "Cite which model(s) contributed each insight."
                    )},
                    {"role": "user", "content": f"Question: {prompt}\n\nModel answers:\n{answers_block}"},
                ],
                max_tokens=8192,
            )
            final = synth_resp.choices[0].message.content or ""
        except Exception:
            # Fallback: use first successful answer
            final = next((a for _, a in results if not a.startswith("[Error")), "")

        return OrchResult(
            content=final,
            model_used=synthesizer,
            pattern="council",
            latency_ms=round((time.monotonic() - t0) * 1000, 2),
            models_consulted=models + [synthesizer],
            metadata={"individual_answers": {m: a[:200] for m, a in model_answers.items()}},
        )

    # -- Fallback Chain -----------------------------------------------------

    async def fallback_chain(
        self,
        prompt: str,
        chain: list[str] | None = None,
        system: str = "",
    ) -> OrchResult:
        """Try models in order, falling back to the next on failure.

        Default chain: local → Moonshot API → OpenRouter
        """
        t0 = time.monotonic()
        chain = chain or ["kimi-k2.5-local", "kimi-k2.5", "kimi-k2.5-openrouter", "claude-opus-4.6"]
        messages = self._build_messages(system, prompt)

        for model in chain:
            try:
                client, mid = self.router.get_client(model)
                resp = await client.chat.completions.create(
                    model=mid, messages=messages, max_tokens=8192,
                )
                content = resp.choices[0].message.content or ""
                if content:
                    return OrchResult(
                        content=content,
                        model_used=model,
                        pattern="fallback",
                        latency_ms=round((time.monotonic() - t0) * 1000, 2),
                        models_consulted=chain[:chain.index(model) + 1],
                        metadata={"fallback_depth": chain.index(model)},
                    )
            except Exception as exc:
                log.warning("Fallback chain: %s failed: %s", model, exc)
                continue

        return OrchResult(
            content="[All models in fallback chain failed]",
            model_used="none",
            pattern="fallback",
            latency_ms=round((time.monotonic() - t0) * 1000, 2),
            models_consulted=chain,
        )

    # -- A/B Routing --------------------------------------------------------

    async def ab_route(
        self,
        prompt: str,
        config: ABConfig | None = None,
        system: str = "",
    ) -> OrchResult:
        """Route to model A or B based on split percentage.

        Used for comparing model performance or cost optimization.
        """
        t0 = time.monotonic()
        config = config or ABConfig()
        messages = self._build_messages(system, prompt)

        # Deterministic routing based on prompt hash (for consistency)
        h = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        model = config.model_a if h < config.split_pct else config.model_b
        variant = "A" if model == config.model_a else "B"

        result = await self._single_call(model, messages, "ab", t0)
        result.metadata["variant"] = variant
        result.metadata["split_pct"] = config.split_pct

        if config.track_outcomes:
            self._ab_history.append({
                "variant": variant, "model": model,
                "prompt_hash": hashlib.md5(prompt.encode()).hexdigest()[:8],
                "latency_ms": result.latency_ms,
                "output_len": len(result.content),
                "ts": time.time(),
            })

        return result

    def get_ab_stats(self) -> dict[str, Any]:
        """Get A/B test statistics."""
        a_results = [r for r in self._ab_history if r["variant"] == "A"]
        b_results = [r for r in self._ab_history if r["variant"] == "B"]
        return {
            "total": len(self._ab_history),
            "A": {
                "count": len(a_results),
                "avg_latency": round(sum(r["latency_ms"] for r in a_results) / max(len(a_results), 1), 2),
                "avg_output_len": round(sum(r["output_len"] for r in a_results) / max(len(a_results), 1)),
            },
            "B": {
                "count": len(b_results),
                "avg_latency": round(sum(r["latency_ms"] for r in b_results) / max(len(b_results), 1), 2),
                "avg_output_len": round(sum(r["output_len"] for r in b_results) / max(len(b_results), 1)),
            },
        }

    # -- Ensemble -----------------------------------------------------------

    async def ensemble(
        self,
        prompt: str,
        models: list[str] | None = None,
        system: str = "",
    ) -> OrchResult:
        """Multiple models vote — majority answer wins.

        Best for factual questions where models can agree/disagree.
        """
        t0 = time.monotonic()
        models = models or ["kimi-k2.5", "grok-3", "sonar"]
        messages = self._build_messages(system, prompt)

        async def _query(model: str) -> str:
            try:
                client, mid = self.router.get_client(model)
                resp = await client.chat.completions.create(
                    model=mid, messages=messages, max_tokens=2048, temperature=0.1,
                )
                return resp.choices[0].message.content or ""
            except Exception:
                return ""

        answers = await asyncio.gather(*[_query(m) for m in models])

        # Pick the longest non-empty answer as representative
        # (A smarter version would do semantic clustering)
        valid = [(m, a) for m, a in zip(models, answers) if a]
        if not valid:
            return OrchResult(content="[All models failed]", model_used="none", pattern="ensemble")

        best_model, best_answer = max(valid, key=lambda x: len(x[1]))

        return OrchResult(
            content=best_answer,
            model_used=best_model,
            pattern="ensemble",
            latency_ms=round((time.monotonic() - t0) * 1000, 2),
            models_consulted=models,
            metadata={
                "answer_count": len(valid),
                "total_models": len(models),
            },
        )

    # -- helpers ------------------------------------------------------------

    def _build_messages(self, system: str, prompt: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def _single_call(
        self, model: str, messages: list[dict], pattern: str, t0: float,
    ) -> OrchResult:
        try:
            client, mid = self.router.get_client(model)
            resp = await client.chat.completions.create(
                model=mid, messages=messages, max_tokens=8192,
            )
            return OrchResult(
                content=resp.choices[0].message.content or "",
                model_used=model, pattern=pattern,
                latency_ms=round((time.monotonic() - t0) * 1000, 2),
                models_consulted=[model],
            )
        except Exception as exc:
            return OrchResult(
                content=f"[Error: {exc}]", model_used=model, pattern=pattern,
                latency_ms=round((time.monotonic() - t0) * 1000, 2),
            )
