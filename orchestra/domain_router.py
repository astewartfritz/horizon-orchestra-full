"""Horizon Orchestra — Multi-Domain Intelligent Router.

Routes tasks to the optimal model and security policy based on the
task's domain (coding, research, creative, data analysis, safety-critical).

Each domain defines:

- Primary model preference (best model for this task type)
- Fallback model chain
- Required security policy level
- Tool surface restrictions
- Thinking effort recommendation
- Cost ceiling

Usage::

    from orchestra.domain_router import DomainRouter, TaskClassification
    from orchestra.router import ModelRouter

    dr = DomainRouter(router=ModelRouter())
    classification = await dr.classify("Refactor the payment service")
    # -> TaskClassification(domain="coding", confidence=0.85, ...)
    route = dr.route(classification)
    # -> DomainRoute(model="claude-opus-4.6", effort="high", policy_name="strict", ...)

    # Or in one call (sync heuristic path):
    route = dr.route_task("Write a blog post about quantum computing")
    # -> DomainRoute(model="claude-opus-4.6", effort="medium", policy_name="permissive", ...)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from orchestra.router import ModelRouter

__all__ = [
    "TaskClassification",
    "DomainRoute",
    "DomainRouter",
    "DOMAIN_CONFIGS",
]

log = logging.getLogger("orchestra.domain_router")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TaskClassification:
    """Result of classifying a task string into a domain.

    Attributes:
        domain: One of ``"coding"``, ``"research"``, ``"creative"``,
            ``"data_analysis"``, ``"safety_critical"``, or ``"general"``.
        confidence: Score in [0.0, 1.0] reflecting classification certainty.
        subdomain: Optional finer-grained label (e.g. ``"refactoring"``
            for a coding task).
        reasoning: Human-readable explanation of why this domain was chosen.
        requires_vision: True when the task description mentions images or
            visual content.
        requires_audio: True when the task description mentions audio or
            speech content.
        requires_tools: List of tool names explicitly referenced in the task.
        estimated_complexity: One of ``"low"``, ``"medium"``, ``"high"``,
            or ``"extreme"``.
    """

    domain: str  # "coding" | "research" | "creative" | "data_analysis" | "safety_critical" | "general"
    confidence: float  # 0.0 – 1.0
    subdomain: str = ""
    reasoning: str = ""
    requires_vision: bool = False
    requires_audio: bool = False
    requires_tools: list[str] = field(default_factory=list)
    estimated_complexity: str = "medium"  # "low" | "medium" | "high" | "extreme"


@dataclass
class DomainRoute:
    """Fully resolved routing decision for a classified task.

    Attributes:
        model: Registry key of the chosen model (from :data:`DEFAULT_MODELS`).
        effort: Thinking effort level — ``"low"``, ``"medium"``, ``"high"``,
            or ``"max"``.
        policy_name: Security / guardrail policy — ``"strict"``,
            ``"standard"``, ``"permissive"``, or ``"safety_critical"``.
        allowed_tools: Whitelist of tool names, or ``None`` for no restriction.
        max_iterations: Agentic loop cap.
        temperature: Sampling temperature for generation.
        thinking_budget: Token budget for extended thinking (where supported).
        fallback_models: Ordered list of alternative model keys.
        reasoning: Human-readable explanation of the routing decision.
    """

    model: str
    effort: str  # "low" | "medium" | "high" | "max"
    policy_name: str  # "strict" | "standard" | "permissive" | "safety_critical"
    allowed_tools: list[str] | None  # None = all tools permitted
    max_iterations: int = 300
    temperature: float = 0.6
    thinking_budget: int = 16_384
    fallback_models: list[str] = field(default_factory=list)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Domain configuration registry
# ---------------------------------------------------------------------------

DOMAIN_CONFIGS: dict[str, dict[str, Any]] = {
    "coding": {
        "primary_models": ["opencode", "claude-opus-4.6", "gemma-4-31b", "kimi-k2.5"],
        "effort": "high",
        "policy": "strict",  # code execution can be dangerous
        "max_iterations": 300,
        "temperature": 0.3,
        "thinking_budget": 32_768,
        "tool_preferences": ["opencode_task", "execute_code", "file_read", "file_write", "web_search", "science_analyze", "science_pubchem_search"],
        "description": (
            "Software engineering: implementation, refactoring, debugging, "
            "code review, architecture design"
        ),
    },
    "research": {
        "primary_models": ["claude-opus-4.6", "sonar-reasoning-pro", "claude-sonnet-4.6"],
        "effort": "high",
        "policy": "standard",
        "max_iterations": 200,
        "temperature": 0.5,
        "thinking_budget": 24_576,
        "tool_preferences": ["web_search", "fetch_url", "file_write", "memory_search", "science_analyze", "science_pubchem_search", "science_literature_review", "science_docking", "science_generate_report"],
        "description": (
            "Deep research: multi-source analysis, fact-finding, "
            "literature review, competitive intelligence"
        ),
    },
    "creative": {
        "primary_models": ["claude-opus-4.6", "claude-sonnet-4.6", "kimi-k2.5"],
        "effort": "medium",
        "policy": "permissive",
        "max_iterations": 100,
        "temperature": 0.9,
        "thinking_budget": 8_192,
        "tool_preferences": ["web_search", "file_write"],
        "description": (
            "Creative writing, brainstorming, content generation, "
            "blog posts, marketing copy, storytelling"
        ),
    },
    "data_analysis": {
        "primary_models": ["claude-sonnet-4.6", "gemma-4-31b", "claude-opus-4.6"],
        "effort": "high",
        "policy": "standard",
        "max_iterations": 200,
        "temperature": 0.2,
        "thinking_budget": 16_384,
        "tool_preferences": ["execute_code", "file_read", "file_write"],
        "description": (
            "Data processing, visualization, statistical analysis, "
            "SQL queries, pandas/NumPy workflows"
        ),
    },
    "safety_critical": {
        "primary_models": ["claude-opus-4.6"],  # only the highest-capability model
        "effort": "max",
        "policy": "safety_critical",
        "max_iterations": 100,
        "temperature": 0.1,
        "thinking_budget": 65_536,
        "tool_preferences": ["web_search", "fetch_url", "memory_search"],
        "description": (
            "Financial, medical, legal, compliance tasks requiring "
            "maximum accuracy, auditability, and caution"
        ),
    },
    "general": {
        "primary_models": ["claude-sonnet-4.6", "gemma-4-26b-moe", "kimi-k2.5"],
        "effort": "medium",
        "policy": "standard",
        "max_iterations": 200,
        "temperature": 0.6,
        "thinking_budget": 16_384,
        "tool_preferences": None,  # all tools available
        "description": (
            "General-purpose tasks, conversation, summarization, "
            "question answering, translation"
        ),
    },
}


# ---------------------------------------------------------------------------
# Keyword heuristics for fast classification
# ---------------------------------------------------------------------------

# Each entry maps a domain name to a set of lowercase trigger strings.
# Scores accumulate as matched keywords are found in the task text.
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "coding": [
        "refactor", "refactoring", "debug", "debugging", "implement", "implementation",
        "api", "function", "class", "bug", "fix", "test", "unit test", "integration test",
        "deploy", "deployment", "pr", "pull request", "commit", "merge", "branch",
        "code", "codebase", "repository", "repo", "module", "package", "library",
        "algorithm", "data structure", "complexity", "performance", "optimize",
        "lint", "format", "type hint", "annotation", "docstring", "interface",
        "endpoint", "rest", "graphql", "grpc", "microservice", "docker", "kubernetes",
        "ci/cd", "pipeline", "build", "compile", "syntax", "runtime", "exception",
        "stack trace", "traceback", "import", "dependency", "requirements.txt",
        "pyproject", "setup.py", "makefile", "shell script", "bash script",
        "write a function", "write a class", "write a script",
    ],
    "research": [
        "research", "analyze", "analyse", "analysis", "compare", "comparison",
        "investigate", "study", "survey", "literature", "find out", "what is",
        "how does", "explain", "overview", "summary of", "report", "findings",
        "evidence", "source", "citation", "reference", "paper", "journal",
        "academic", "thesis", "hypothesis", "methodology", "framework",
        "industry", "market", "trend", "competitor", "benchmarks", "review",
        "deep dive", "comprehensive", "thorough", "fact", "fact-check",
    ],
    "creative": [
        "write", "story", "blog", "blog post", "poem", "poetry", "creative",
        "brainstorm", "draft", "content", "essay", "narrative", "fiction",
        "script", "screenplay", "dialogue", "character", "plot", "setting",
        "metaphor", "tone", "voice", "style", "headline", "slogan", "tagline",
        "marketing copy", "advertisement", "social media post", "tweet",
        "caption", "describe", "imagine", "envision", "creative writing",
        "make up", "invent", "generate ideas", "ideate",
    ],
    "data_analysis": [
        "data", "dataset", "dataframe", "csv", "excel", "spreadsheet",
        "chart", "graph", "plot", "visualize", "visualization", "dashboard",
        "sql", "query", "database", "table", "schema", "join", "aggregate",
        "statistics", "statistical", "mean", "median", "standard deviation",
        "correlation", "regression", "distribution", "histogram", "boxplot",
        "pandas", "numpy", "matplotlib", "seaborn", "plotly", "tableau",
        "etl", "pipeline", "transform", "clean", "missing values", "outlier",
        "machine learning", "model training", "prediction", "classification",
        "clustering", "feature engineering", "cross-validation",
    ],
    "safety_critical": [
        "financial", "finance", "investment", "portfolio", "trading", "stock",
        "tax", "irs", "gaap", "ifrs", "sec", "compliance", "regulatory",
        "audit", "due diligence", "risk assessment", "insurance", "liability",
        "medical", "health", "diagnosis", "symptom", "prescription", "drug",
        "treatment", "clinical", "hipaa", "phi", "patient", "dosage",
        "legal", "law", "lawsuit", "contract", "agreement", "clause",
        "gdpr", "ccpa", "privacy", "confidential", "attorney", "counsel",
        "court", "jurisdiction", "settlement", "binding", "indemnify",
        "life-critical", "safety", "critical system", "pacemaker", "aviation",
    ],
}

# Subdomain keyword maps (only for domains that have obvious sub-categories)
_SUBDOMAIN_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "coding": {
        "refactoring": ["refactor", "restructure", "clean up", "simplify", "reorganize"],
        "debugging": ["debug", "bug", "fix", "error", "traceback", "exception", "crash"],
        "api_design": ["api", "endpoint", "rest", "graphql", "interface", "schema"],
        "testing": ["test", "unit test", "integration test", "pytest", "coverage"],
        "devops": ["deploy", "docker", "kubernetes", "ci/cd", "pipeline", "build"],
    },
    "data_analysis": {
        "visualization": ["chart", "graph", "plot", "visualize", "dashboard"],
        "sql": ["sql", "query", "database", "join", "aggregate"],
        "ml": ["machine learning", "model", "training", "prediction", "classification"],
        "etl": ["etl", "pipeline", "transform", "clean", "ingest"],
    },
}

# Complexity signals
_COMPLEXITY_HIGH = [
    "complex", "large", "enterprise", "scalable", "production", "million", "billion",
    "multi-", "distributed", "concurrent", "parallel", "real-time", "critical",
    "comprehensive", "full", "entire", "all", "complete",
]
_COMPLEXITY_LOW = [
    "simple", "quick", "small", "basic", "just", "only", "single", "one-liner",
    "tiny", "minimal", "brief", "short",
]

# Modality signals
_VISION_KEYWORDS = [
    "image", "photo", "picture", "screenshot", "diagram", "chart", "figure",
    "visual", "draw", "render", "pixel", "thumbnail", "icon", "logo",
]
_AUDIO_KEYWORDS = [
    "audio", "sound", "speech", "voice", "transcribe", "podcast", "recording",
    "microphone", "speaker", "listen", "hear",
]

# Tool mention heuristics
_TOOL_PATTERNS: dict[str, list[str]] = {
    "web_search": ["search the web", "look up", "google", "find on the internet"],
    "execute_code": ["run", "execute", "eval", "notebook"],
    "file_read": ["read file", "open file", "load file"],
    "file_write": ["save", "write to file", "create file", "output to"],
    "memory_search": ["remember", "recall", "memory", "previous context"],
}


# ---------------------------------------------------------------------------
# DomainRouter
# ---------------------------------------------------------------------------


class DomainRouter:
    """Multi-domain routing layer that maps tasks to model + policy combinations.

    Parameters:
        router: A :class:`~orchestra.router.ModelRouter` instance providing
            the model registry.
        custom_domains: Optional mapping of additional domain configs that
            will be merged with :data:`DOMAIN_CONFIGS` (custom entries win
            on key conflicts).

    Example::

        router = ModelRouter()
        dr = DomainRouter(router=router)

        # Async classification + routing
        classification = await dr.classify("Debug the segfault in the C++ parser")
        route = dr.route(classification)
        print(route.model, route.effort)  # claude-opus-4.6  high

        # Sync one-shot convenience
        route = dr.route_task("Summarize this quarterly earnings report")
    """

    def __init__(
        self,
        router: ModelRouter,
        custom_domains: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._router = router
        self._domains: dict[str, dict[str, Any]] = dict(DOMAIN_CONFIGS)
        if custom_domains:
            self._domains.update(custom_domains)
            log.debug("Merged %d custom domain(s) into domain registry", len(custom_domains))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def classify(self, task: str, context: str = "") -> TaskClassification:
        """Classify *task* into a domain using fast keyword heuristics.

        This method is intentionally free of LLM calls — it scores domains
        by counting keyword matches in the combined ``task + context`` text.
        Classification typically completes in under 1 ms.

        Parameters:
            task: The user's task description or prompt.
            context: Optional additional context (e.g. conversation history
                summary, file contents) to improve classification accuracy.

        Returns:
            A :class:`TaskClassification` with ``domain``, ``confidence``,
            ``subdomain``, and metadata flags.
        """
        combined = (task + " " + context).lower()
        return self._classify_text(combined, task)

    def route(
        self,
        classification: TaskClassification,
        cost_ceiling: float | None = None,
    ) -> DomainRoute:
        """Select the best model and config for a classified task.

        Parameters:
            classification: Output of :meth:`classify`.
            cost_ceiling: Maximum acceptable cost in $/1M output tokens.
                Models exceeding this threshold are skipped. ``None`` means
                no ceiling.

        Returns:
            A :class:`DomainRoute` with model, effort, policy, and iteration
            caps appropriate for the classified domain.
        """
        domain_key = classification.domain
        cfg = self._domains.get(domain_key, self._domains["general"])

        primary_models: list[str] = list(cfg["primary_models"])

        # If task requires vision, only keep models with vision support
        if classification.requires_vision:
            primary_models = [
                m for m in primary_models
                if self._router.models.get(m) and self._router.models[m].supports_vision
            ] or primary_models  # fall back to full list if nothing matches

        # If task requires audio, only keep models with audio support
        if classification.requires_audio:
            primary_models = [
                m for m in primary_models
                if self._router.models.get(m) and self._router.models[m].supports_audio
            ] or primary_models

        chosen = self._select_available_model(primary_models, cost_ceiling)

        # Build fallback chain (all primaries except the chosen one, then general)
        fallbacks = [m for m in primary_models if m != chosen]
        if domain_key != "general":
            general_cfg = self._domains["general"]
            for m in general_cfg["primary_models"]:
                if m not in fallbacks and m != chosen:
                    fallbacks.append(m)

        # Adjust effort based on estimated complexity
        effort = cfg["effort"]
        if classification.estimated_complexity == "extreme":
            effort = "max"
        elif classification.estimated_complexity == "low" and effort == "high":
            effort = "medium"

        # Thinking budget scales with effort
        thinking_budget = cfg.get("thinking_budget", 16_384)
        if effort == "max":
            thinking_budget = max(thinking_budget, 65_536)
        elif effort == "low":
            thinking_budget = min(thinking_budget, 4_096)

        route_reasoning = (
            f"Domain '{domain_key}' (confidence={classification.confidence:.2f}). "
            f"Complexity={classification.estimated_complexity}. "
            f"Chosen model '{chosen}' from preference list {primary_models}."
        )
        if cost_ceiling is not None:
            route_reasoning += f" Cost ceiling: ${cost_ceiling}/1M out tokens."

        log.debug(
            "Routed domain=%r complexity=%r -> model=%r effort=%r policy=%r",
            domain_key, classification.estimated_complexity, chosen, effort, cfg["policy"],
        )

        return DomainRoute(
            model=chosen,
            effort=effort,
            policy_name=cfg["policy"],
            allowed_tools=cfg.get("tool_preferences"),
            max_iterations=cfg["max_iterations"],
            temperature=cfg["temperature"],
            thinking_budget=thinking_budget,
            fallback_models=fallbacks,
            reasoning=route_reasoning,
        )

    def route_task(
        self,
        task: str,
        context: str = "",
        cost_ceiling: float | None = None,
    ) -> DomainRoute:
        """Classify and route *task* in a single synchronous call.

        Uses the same keyword-heuristic classifier as :meth:`classify` but
        without requiring ``await``, making it convenient in synchronous
        contexts.

        Parameters:
            task: The user's task description or prompt.
            context: Optional additional context.
            cost_ceiling: Maximum acceptable cost in $/1M output tokens.

        Returns:
            A fully resolved :class:`DomainRoute`.
        """
        combined = (task + " " + context).lower()
        classification = self._classify_text(combined, task)
        return self.route(classification, cost_ceiling=cost_ceiling)

    def _select_available_model(
        self,
        model_preferences: list[str],
        cost_ceiling: float | None,
    ) -> str:
        """Pick the first available model from *model_preferences*.

        A model is considered "available" when:
        - Its registry key exists in ``self._router.models``.
        - Its required API key environment variable is set (or no key needed).
        - Its ``cost_output`` is within *cost_ceiling* (if provided).

        Falls back to the router's cheapest available model if none qualify.

        Parameters:
            model_preferences: Ordered list of model registry keys to try.
            cost_ceiling: Maximum $/1M output tokens, or ``None`` for no limit.

        Returns:
            The selected model registry key.
        """
        for model_name in model_preferences:
            cfg = self._router.models.get(model_name)
            if cfg is None:
                log.debug("Model %r not in registry, skipping", model_name)
                continue
            if cfg.api_key_env and not os.environ.get(cfg.api_key_env):
                log.debug("Model %r missing API key %r, skipping", model_name, cfg.api_key_env)
                continue
            if cost_ceiling is not None and cfg.cost_output > cost_ceiling:
                log.debug(
                    "Model %r cost_output=%.2f exceeds ceiling=%.2f, skipping",
                    model_name, cfg.cost_output, cost_ceiling,
                )
                continue
            log.debug("Selected model %r from preference list", model_name)
            return model_name

        log.warning(
            "No preferred model available for preferences=%r cost_ceiling=%r; "
            "falling back to cheapest available.",
            model_preferences, cost_ceiling,
        )
        return self._router._cheapest_available()

    def list_domains(self) -> list[dict[str, Any]]:
        """Return all domain configs as a list of serialisable dicts.

        Each dict contains the domain ``name``, ``description``,
        ``primary_models``, ``effort``, ``policy``, ``max_iterations``,
        ``temperature``, and ``tool_preferences``.

        Returns:
            List of domain metadata dicts, one per registered domain.
        """
        return [
            {
                "name": domain_name,
                "description": cfg.get("description", ""),
                "primary_models": cfg.get("primary_models", []),
                "effort": cfg.get("effort", "medium"),
                "policy": cfg.get("policy", "standard"),
                "max_iterations": cfg.get("max_iterations", 200),
                "temperature": cfg.get("temperature", 0.6),
                "thinking_budget": cfg.get("thinking_budget", 16_384),
                "tool_preferences": cfg.get("tool_preferences"),
            }
            for domain_name, cfg in self._domains.items()
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify_text(self, combined_lower: str, original_task: str) -> TaskClassification:
        """Core keyword-scoring classification logic.

        Parameters:
            combined_lower: Lowercased concatenation of task + context.
            original_task: The raw (un-lowercased) task string, used for
                subdomain keyword matching and display purposes.

        Returns:
            A :class:`TaskClassification`.
        """
        scores: dict[str, float] = {domain: 0.0 for domain in _DOMAIN_KEYWORDS}

        # Score each domain by counting unique keyword hits
        matched_per_domain: dict[str, list[str]] = {d: [] for d in _DOMAIN_KEYWORDS}
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in combined_lower:
                    scores[domain] += 1.0
                    matched_per_domain[domain].append(kw)

        # safety_critical gets a strong bonus because false negatives are costly
        scores["safety_critical"] *= 1.5

        total_score = sum(scores.values())

        if total_score == 0.0:
            # No keywords matched — default to "general" with low confidence
            return TaskClassification(
                domain="general",
                confidence=0.1,
                subdomain="",
                reasoning="No domain keywords matched; defaulting to general.",
                requires_vision=self._has_vision_signal(combined_lower),
                requires_audio=self._has_audio_signal(combined_lower),
                requires_tools=self._detect_tools(combined_lower),
                estimated_complexity=self._estimate_complexity(combined_lower),
            )

        # Pick the top-scoring domain
        best_domain = max(scores, key=lambda d: scores[d])
        best_score = scores[best_domain]
        confidence = min(best_score / max(total_score, 1.0) * 2.5, 1.0)
        # Clamp: single-keyword matches shouldn't appear 100% confident
        if best_score <= 2.0:
            confidence = min(confidence, 0.6)
        elif best_score <= 5.0:
            confidence = min(confidence, 0.85)

        # Subdomain detection
        subdomain = self._detect_subdomain(best_domain, combined_lower)

        # Build human-readable reasoning
        top_keywords = matched_per_domain[best_domain][:5]
        reasoning = (
            f"Domain '{best_domain}' scored {best_score:.0f} pts "
            f"(total={total_score:.0f}). "
            f"Matched keywords: {top_keywords}."
        )

        return TaskClassification(
            domain=best_domain,
            confidence=round(confidence, 3),
            subdomain=subdomain,
            reasoning=reasoning,
            requires_vision=self._has_vision_signal(combined_lower),
            requires_audio=self._has_audio_signal(combined_lower),
            requires_tools=self._detect_tools(combined_lower),
            estimated_complexity=self._estimate_complexity(combined_lower),
        )

    @staticmethod
    def _detect_subdomain(domain: str, text: str) -> str:
        """Return the best-matching subdomain label for *domain*, or ``""``.

        Parameters:
            domain: The classified top-level domain.
            text: Lowercased combined task + context text.

        Returns:
            Subdomain label string, or empty string if none found.
        """
        subdomain_map = _SUBDOMAIN_KEYWORDS.get(domain, {})
        best_sub = ""
        best_count = 0
        for sub_name, keywords in subdomain_map.items():
            count = sum(1 for kw in keywords if kw in text)
            if count > best_count:
                best_count = count
                best_sub = sub_name
        return best_sub

    @staticmethod
    def _has_vision_signal(text: str) -> bool:
        """Return True if *text* mentions visual/image content."""
        return any(kw in text for kw in _VISION_KEYWORDS)

    @staticmethod
    def _has_audio_signal(text: str) -> bool:
        """Return True if *text* mentions audio/speech content."""
        return any(kw in text for kw in _AUDIO_KEYWORDS)

    @staticmethod
    def _detect_tools(text: str) -> list[str]:
        """Return a list of tool names referenced in *text*.

        Parameters:
            text: Lowercased combined task text.

        Returns:
            Deduplicated list of matched tool names.
        """
        detected: list[str] = []
        for tool_name, patterns in _TOOL_PATTERNS.items():
            if any(p in text for p in patterns):
                detected.append(tool_name)
        return detected

    @staticmethod
    def _estimate_complexity(text: str) -> str:
        """Estimate task complexity from linguistic signals.

        Parameters:
            text: Lowercased combined task text.

        Returns:
            One of ``"low"``, ``"medium"``, ``"high"``, or ``"extreme"``.
        """
        high_hits = sum(1 for kw in _COMPLEXITY_HIGH if kw in text)
        low_hits = sum(1 for kw in _COMPLEXITY_LOW if kw in text)
        # Word count as a proxy for task scope
        word_count = len(text.split())

        if high_hits >= 3 or word_count > 200:
            return "extreme"
        if high_hits >= 1 or word_count > 80:
            return "high"
        if low_hits >= 1 or word_count < 15:
            return "low"
        return "medium"
