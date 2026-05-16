"""OpenJarvis — Model Council.

Runs multiple frontier models in parallel on the same prompt, then
synthesises their responses into a consensus answer with divergence analysis.

Mirrors Perplexity Computer's Model Council feature: query GPT-5.4,
Claude Opus 4.6, and Gemini / Gemma models simultaneously, then use an
orchestrator model to synthesise where they agree, disagree, and what
each uniquely contributes.

Usage::

    from openjarvis.intelligence.model_council import ModelCouncil, CouncilConfig

    council = ModelCouncil(router=HybridRouter())
    result = await council.deliberate(
        prompt="Should we migrate our PostgreSQL to DynamoDB?",
        models=["claude-opus-4.6-openrouter", "gemma-4-31b", "kimi-k2.5"],
        orchestrator="claude-opus-4.6-openrouter",
    )
    print(result.consensus)
    print(result.divergence_points)
    print(result.unique_insights)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from openjarvis.intelligence.hybrid_router import HybridRouter

__all__ = [
    "CouncilConfig",
    "ModelVote",
    "CouncilResult",
    "ModelCouncil",
    "CouncilError",
    "council_deliberate",
    "register_council_tools",
]

log = logging.getLogger("openjarvis.intelligence.model_council")

_DEFAULT_COUNCIL_PREFERENCE = [
    "claude-opus-4.6-openrouter",
    "gemma-4-31b",
    "kimi-k2.5",
    "brain4",
    "brain3",
    "gpt-5.4",
    "kimi-k2.5-openrouter",
    "gemma-4-31b-openrouter",
    "claude-sonnet-4.6-openrouter",
    "sonar-pro",
    "sonar-reasoning-pro",
    "grok-3",
    "brain2",
]


class CouncilError(RuntimeError):
    """Raised when the council cannot reach a result (e.g. all models failed
    or ``require_consensus=True`` and models strongly disagree)."""


@dataclass
class CouncilConfig:
    """Configuration for a council deliberation."""

    models: list[str]
    orchestrator: str = ""
    temperature: float = 0.6
    max_tokens: int = 4096
    timeout_seconds: int = 120
    include_model_labels: bool = True
    voting_mode: bool = False
    require_consensus: bool = False


@dataclass
class ModelVote:
    """A single model's response within a council deliberation."""

    model: str
    response: str
    latency_seconds: float
    tokens_used: int = 0
    error: str = ""


@dataclass
class CouncilResult:
    """The synthesised output of a full council deliberation."""

    prompt: str
    votes: list[ModelVote]
    consensus: str
    divergence_points: list[str]
    unique_insights: dict[str, list[str]]
    agreement_score: float
    orchestrator: str
    total_latency_seconds: float
    fastest_model: str
    most_tokens_model: str

    @property
    def successful_votes(self) -> list[ModelVote]:
        return [v for v in self.votes if not v.error]

    @property
    def failed_models(self) -> list[str]:
        return [v.model for v in self.votes if v.error]

    def to_markdown(self) -> str:
        lines: list[str] = [
            f"# Model Council Report",
            f"",
            f"**Prompt:** {self.prompt}",
            f"",
            f"**Orchestrator:** `{self.orchestrator}`  |  "
            f"**Agreement score:** {self.agreement_score:.2f}  |  "
            f"**Total latency:** {self.total_latency_seconds:.1f}s",
            f"",
        ]

        lines.append("## Individual Responses")
        lines.append("")
        for vote in self.votes:
            status = "✓" if not vote.error else "✗"
            lines.append(
                f"### {status} `{vote.model}` "
                f"({vote.latency_seconds:.1f}s, {vote.tokens_used} tokens)"
            )
            if vote.error:
                lines.append(f"*Error:* {vote.error}")
            else:
                lines.append(vote.response)
            lines.append("")

        lines.append("## Synthesis")
        lines.append("")
        lines.append(self.consensus)
        lines.append("")

        if self.divergence_points:
            lines.append("## Points of Divergence")
            lines.append("")
            for point in self.divergence_points:
                lines.append(f"- {point}")
            lines.append("")

        if self.unique_insights:
            lines.append("## Unique Contributions")
            lines.append("")
            for model_name, insights in self.unique_insights.items():
                for insight in insights:
                    lines.append(f"- **`{model_name}`**: {insight}")
            lines.append("")

        if self.failed_models:
            lines.append("## Failed Models")
            lines.append("")
            for m in self.failed_models:
                lines.append(f"- `{m}`")
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "votes": [
                {
                    "model": v.model,
                    "response": v.response,
                    "latency_seconds": v.latency_seconds,
                    "tokens_used": v.tokens_used,
                    "error": v.error,
                }
                for v in self.votes
            ],
            "consensus": self.consensus,
            "divergence_points": self.divergence_points,
            "unique_insights": self.unique_insights,
            "agreement_score": self.agreement_score,
            "orchestrator": self.orchestrator,
            "total_latency_seconds": self.total_latency_seconds,
            "fastest_model": self.fastest_model,
            "most_tokens_model": self.most_tokens_model,
            "successful_votes": len(self.successful_votes),
            "failed_models": self.failed_models,
        }


class ModelCouncil:
    """Run multiple models in parallel and synthesise their responses.

    The council pattern:

    1. All models receive the same prompt simultaneously via
       :func:`asyncio.gather`.
    2. Each model's response is collected with timing information.
    3. The *orchestrator* model reads all responses and synthesises:

       - Points of consensus
       - Points of divergence
       - Unique insights per model
       - A final synthesised recommendation

    4. An agreement score is computed via Jaccard similarity on trigrams
       across all successful responses.

    Example::

        council = ModelCouncil()
        result = await council.deliberate(
            "Is Rust ready for production backend services?",
            models=["claude-opus-4.6-openrouter", "gemma-4-31b", "kimi-k2.5"],
        )
    """

    SYNTHESIS_PROMPT = """\
You are synthesising responses from {n_models} AI models on the same task.

Task that was posed to all models:
---
{original_prompt}
---

Responses from each model:
{model_responses}

Your job:
1. **Consensus**: What do all (or most) models agree on? Synthesise into a clear final answer.
2. **Divergence**: Where do models meaningfully disagree? List specific points.
3. **Unique Insights**: What did each model contribute that others missed?
4. **Recommendation**: Given the above, what is the best overall answer?

Format your response as:

## Consensus
{shared conclusions}

## Points of Divergence
- {point 1}: Model A says X, Model B says Y
- ...

## Unique Contributions
- {model_name}: {unique insight}
- ...

## Final Recommendation
{synthesised best answer}"""

    def __init__(self, router: HybridRouter | None = None) -> None:
        self.router = router or HybridRouter()

    async def deliberate(
        self,
        prompt: str,
        models: list[str] | None = None,
        orchestrator: str = "",
        system_prompt: str = "",
        config: CouncilConfig | None = None,
    ) -> CouncilResult:
        """Run all models in parallel, then synthesise.

        Args:
            prompt: The question or task to pose to every council member.
            models: Model names to query. If *None*, falls back to
                :meth:`get_default_council`.
            orchestrator: Model that synthesises the votes. Defaults to the
                first entry of *models* (or default council).
            system_prompt: Optional system prompt forwarded to every model,
                including the orchestrator.
            config: Full :class:`CouncilConfig` (overrides the individual
                keyword arguments when provided).

        Returns:
            A :class:`CouncilResult` containing individual votes, synthesis,
            divergence analysis, and metadata.

        Raises:
            :class:`CouncilError`: When *require_consensus* is set and the
                agreement score falls below 0.2, or when no models succeed.
        """
        start = time.monotonic()

        if config is None:
            resolved_models = models or self.get_default_council()
            resolved_orchestrator = orchestrator or resolved_models[0]
            config = CouncilConfig(
                models=resolved_models,
                orchestrator=resolved_orchestrator,
            )
        else:
            if models:
                config = CouncilConfig(
                    models=models,
                    orchestrator=config.orchestrator or (models[0] if models else ""),
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    timeout_seconds=config.timeout_seconds,
                    include_model_labels=config.include_model_labels,
                    voting_mode=config.voting_mode,
                    require_consensus=config.require_consensus,
                )

        if not config.orchestrator:
            config = CouncilConfig(
                models=config.models,
                orchestrator=config.models[0],
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout_seconds=config.timeout_seconds,
                include_model_labels=config.include_model_labels,
                voting_mode=config.voting_mode,
                require_consensus=config.require_consensus,
            )

        log.info(
            "Council deliberation started: %d models, orchestrator=%r",
            len(config.models),
            config.orchestrator,
        )

        query_tasks = [
            self._query_model(model, prompt, system_prompt, config)
            for model in config.models
        ]
        votes: list[ModelVote] = list(await asyncio.gather(*query_tasks))

        successful = [v for v in votes if not v.error]
        if not successful:
            raise CouncilError(
                "All council models failed. Check API keys and model names.\n"
                + "\n".join(f"  {v.model}: {v.error}" for v in votes)
            )

        log.info(
            "Council phase 1 complete: %d/%d models succeeded",
            len(successful),
            len(votes),
        )

        if config.voting_mode:
            consensus = "\n\n---\n\n".join(
                f"**{v.model}**:\n{v.response}" for v in successful
            )
            divergence: list[str] = []
            unique: dict[str, list[str]] = {}
        else:
            consensus, divergence, unique = await self._synthesize(
                votes=successful,
                original_prompt=prompt,
                orchestrator=config.orchestrator,
                config=config,
            )

        agreement_score = self._compute_agreement_score(successful)

        if config.require_consensus and agreement_score < 0.2:
            raise CouncilError(
                f"Models strongly disagree (agreement_score={agreement_score:.3f} < 0.2). "
                "Set require_consensus=False to allow disagreement."
            )

        total_latency = time.monotonic() - start

        fastest_model = min(successful, key=lambda v: v.latency_seconds).model
        most_tokens_model = max(successful, key=lambda v: v.tokens_used).model

        result = CouncilResult(
            prompt=prompt,
            votes=votes,
            consensus=consensus,
            divergence_points=divergence,
            unique_insights=unique,
            agreement_score=agreement_score,
            orchestrator=config.orchestrator,
            total_latency_seconds=total_latency,
            fastest_model=fastest_model,
            most_tokens_model=most_tokens_model,
        )

        log.info(
            "Council complete: agreement=%.2f, latency=%.1fs, fastest=%r",
            agreement_score,
            total_latency,
            fastest_model,
        )
        return result

    async def _query_model(
        self,
        model: str,
        prompt: str,
        system_prompt: str,
        config: CouncilConfig,
    ) -> ModelVote:
        """Query a single model and return a :class:`ModelVote`.

        Never raises — all errors are captured in ``ModelVote.error``.
        """
        start = time.monotonic()
        log.debug("Querying council member: %r", model)

        try:
            client, model_id = self.router.get_client(model)

            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model_id,
                    messages=messages,
                    max_tokens=config.max_tokens,
                    temperature=config.temperature,
                ),
                timeout=config.timeout_seconds,
            )

            content = response.choices[0].message.content or ""
            tokens = 0
            if response.usage:
                tokens = getattr(response.usage, "total_tokens", 0) or (
                    getattr(response.usage, "prompt_tokens", 0)
                    + getattr(response.usage, "completion_tokens", 0)
                )

            latency = time.monotonic() - start
            log.debug("Council member %r responded in %.2fs (%d tokens)", model, latency, tokens)

            return ModelVote(
                model=model,
                response=content,
                latency_seconds=latency,
                tokens_used=tokens,
            )

        except asyncio.TimeoutError:
            latency = time.monotonic() - start
            msg = f"Timed out after {config.timeout_seconds}s"
            log.warning("Council member %r: %s", model, msg)
            return ModelVote(model=model, response="", latency_seconds=latency, error=msg)

        except Exception as exc:
            latency = time.monotonic() - start
            msg = str(exc)
            log.warning("Council member %r failed: %s", model, msg)
            return ModelVote(model=model, response="", latency_seconds=latency, error=msg)

    async def _synthesize(
        self,
        votes: list[ModelVote],
        original_prompt: str,
        orchestrator: str,
        config: CouncilConfig,
    ) -> tuple[str, list[str], dict[str, list[str]]]:
        """Ask the orchestrator to synthesise all successful votes."""
        response_parts: list[str] = []
        for vote in votes:
            label = vote.model if config.include_model_labels else f"Model {votes.index(vote) + 1}"
            response_parts.append(f"### {label}\n{vote.response}")

        model_responses_block = "\n\n".join(response_parts)

        synthesis_user_prompt = self.SYNTHESIS_PROMPT.format(
            n_models=len(votes),
            original_prompt=original_prompt,
            model_responses=model_responses_block,
        )

        log.debug("Running synthesis via orchestrator: %r", orchestrator)

        synthesis_vote = await self._query_model(
            model=orchestrator,
            prompt=synthesis_user_prompt,
            system_prompt=(
                "You are an expert analyst whose job is to synthesise multiple AI model "
                "responses into a clear consensus answer with identified divergences."
            ),
            config=config,
        )

        if synthesis_vote.error:
            log.error("Orchestrator %r failed during synthesis: %s", orchestrator, synthesis_vote.error)
            consensus = "\n\n---\n\n".join(
                f"**{v.model}**:\n{v.response}" for v in votes
            )
            return consensus, [], {}

        raw = synthesis_vote.response
        consensus = raw

        divergence_points = _extract_section_bullets(raw, "Points of Divergence")
        unique_insights_raw = _extract_section_bullets(raw, "Unique Contributions")

        unique_insights: dict[str, list[str]] = {}
        for item in unique_insights_raw:
            match = re.match(r"[`'\"]?([^`'\":]+)[`'\"]?\s*:\s*(.*)", item)
            if match:
                model_key = match.group(1).strip()
                insight = match.group(2).strip()
                unique_insights.setdefault(model_key, []).append(insight)
            else:
                unique_insights.setdefault("__other__", []).append(item)

        rec = _extract_section_text(raw, "Final Recommendation")
        if rec:
            consensus = rec

        return consensus, divergence_points, unique_insights

    def _compute_agreement_score(self, votes: list[ModelVote]) -> float:
        """Estimate agreement via token overlap between responses.

        Uses Jaccard similarity on trigrams across all successful responses.
        """
        if len(votes) < 2:
            return 1.0

        trigram_sets: list[set[tuple[str, ...]]] = []
        for vote in votes:
            tokens = re.findall(r"\b\w+\b", vote.response.lower())
            if len(tokens) < 3:
                trigram_sets.append(set())
            else:
                trigram_sets.append({
                    (tokens[i], tokens[i + 1], tokens[i + 2])
                    for i in range(len(tokens) - 2)
                })

        scores: list[float] = []
        for i in range(len(trigram_sets)):
            for j in range(i + 1, len(trigram_sets)):
                a, b = trigram_sets[i], trigram_sets[j]
                if not a and not b:
                    scores.append(1.0)
                elif not a or not b:
                    scores.append(0.0)
                else:
                    intersection = len(a & b)
                    union = len(a | b)
                    scores.append(intersection / union if union else 0.0)

        return sum(scores) / len(scores) if scores else 0.0

    async def vote(
        self,
        prompt: str,
        options: list[str],
        models: list[str] | None = None,
    ) -> tuple[str, dict[str, int]]:
        """Simple majority-vote mode."""
        resolved_models = models or self.get_default_council()
        options_str = ", ".join(options)
        vote_prompt = (
            f"{prompt}\n\n"
            f"Choose exactly ONE of the following options and respond with "
            f"ONLY that option label (no explanation): {options_str}"
        )

        config = CouncilConfig(
            models=resolved_models,
            orchestrator=resolved_models[0],
            voting_mode=True,
        )

        query_tasks = [
            self._query_model(m, vote_prompt, "", config)
            for m in resolved_models
        ]
        raw_votes: list[ModelVote] = list(await asyncio.gather(*query_tasks))

        counts: dict[str, int] = {opt: 0 for opt in options}
        for vote in raw_votes:
            if vote.error:
                continue
            response_upper = vote.response.strip().upper()
            for opt in options:
                if opt.upper() in response_upper:
                    counts[opt] = counts.get(opt, 0) + 1
                    break

        winning = max(counts, key=lambda k: counts[k]) if counts else options[0]
        log.info("Vote result: %r wins with %d/%d votes", winning, counts.get(winning, 0), len(raw_votes))
        return winning, counts

    async def debate(
        self,
        topic: str,
        rounds: int = 2,
        models: list[str] | None = None,
    ) -> list[CouncilResult]:
        """Multi-round debate where models can respond to each other."""
        resolved_models = models or self.get_default_council()
        results: list[CouncilResult] = []

        for round_num in range(1, rounds + 1):
            if round_num == 1:
                prompt = topic
            else:
                prev = results[-1]
                prev_responses = "\n\n".join(
                    f"**{v.model}** (round {round_num - 1}):\n{v.response}"
                    for v in prev.successful_votes
                )
                prompt = (
                    f"This is round {round_num} of a debate on: {topic}\n\n"
                    f"Previous round responses:\n{prev_responses}\n\n"
                    f"You may refine your position, address counter-arguments, "
                    f"or highlight where you agree or disagree with the other models."
                )

            log.info("Debate round %d/%d", round_num, rounds)
            result = await self.deliberate(
                prompt=prompt,
                models=resolved_models,
                orchestrator=resolved_models[0],
            )
            results.append(result)

        return results

    def get_default_council(self) -> list[str]:
        """Return the best available 3-model council from the router."""
        available = self.available_models
        available_set = set(available)

        selected: list[str] = []
        for model in _DEFAULT_COUNCIL_PREFERENCE:
            if model in available_set:
                selected.append(model)
            if len(selected) == 3:
                break

        if not selected:
            selected = available[:3]

        if not selected:
            selected = ["claude-opus-4.6-openrouter", "gemma-4-31b", "kimi-k2.5"]

        log.debug("Default council resolved to: %s", selected)
        return selected

    @property
    def available_models(self) -> list[str]:
        """Return all model names in the router that have a resolvable API key."""
        return self.router.available_models


def _extract_section_text(text: str, section_heading: str) -> str:
    pattern = re.compile(
        r"##\s+" + re.escape(section_heading) + r"\s*\n(.*?)(?=\n##\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _extract_section_bullets(text: str, section_heading: str) -> list[str]:
    section = _extract_section_text(text, section_heading)
    if not section:
        return []
    bullets: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "• ")):
            bullets.append(stripped[2:].strip())
        elif re.match(r"^\d+\.\s", stripped):
            bullets.append(re.sub(r"^\d+\.\s+", "", stripped))
    return bullets


_default_council: ModelCouncil | None = None


def _get_default_council_instance(router: HybridRouter | None = None) -> ModelCouncil:
    global _default_council
    if _default_council is None:
        _default_council = ModelCouncil(router=router)
    return _default_council


async def council_deliberate(
    prompt: str,
    models: str = "",
    orchestrator: str = "",
) -> str:
    """Agent-callable wrapper around :meth:`ModelCouncil.deliberate`.

    Args:
        prompt: The question or task to pose to the council.
        models: Comma-separated model names, or ``""`` to use the default
            council (best available 3 models).
        orchestrator: Model to use for synthesis. Defaults to the first
            council member.

    Returns:
        JSON string with keys ``consensus``, ``divergence_points``,
        ``agreement_score``, ``fastest_model``, and ``failed_models``.
    """
    council = _get_default_council_instance()
    model_list: list[str] | None = (
        [m.strip() for m in models.split(",") if m.strip()]
        if models.strip()
        else None
    )

    try:
        result = await council.deliberate(
            prompt=prompt,
            models=model_list,
            orchestrator=orchestrator or "",
        )
        return json.dumps({
            "consensus": result.consensus,
            "divergence_points": result.divergence_points,
            "agreement_score": result.agreement_score,
            "fastest_model": result.fastest_model,
            "failed_models": result.failed_models,
            "successful_models": [v.model for v in result.successful_votes],
        }, ensure_ascii=False)
    except CouncilError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        log.exception("council_deliberate tool raised unexpectedly")
        return json.dumps({"error": f"Unexpected error: {exc}"})


def register_council_tools(
    tool_registry: Any,
    router: HybridRouter | None = None,
) -> None:
    """Register :func:`council_deliberate` as an agent tool."""
    global _default_council
    _default_council = ModelCouncil(router=router)

    description = (
        "Query multiple frontier AI models in parallel on the same prompt, "
        "then synthesise their responses into a consensus answer with divergence "
        "analysis.  Pass models= as a comma-separated list or leave empty for "
        "the default 3-model council."
    )

    try:
        tool_registry.register(
            "council_deliberate",
            council_deliberate,
            description,
        )
        log.info("Registered council_deliberate tool (named interface)")
        return
    except TypeError:
        pass

    try:
        tool_registry.register(council_deliberate)
        log.info("Registered council_deliberate tool (positional interface)")
    except Exception as exc:
        log.error("Failed to register council_deliberate tool: %s", exc)
        raise
