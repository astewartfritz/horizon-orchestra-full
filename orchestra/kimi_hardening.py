"""
kimi_hardening.py — Robust Kimi K2.5 orchestration layer.

Makes the backbone model bulletproof with retries, validation,
health monitoring, token budgeting, and model fallbacks.
"""
from __future__ import annotations

__all__ = [
    "KimiConfig",
    "TokenBudget",
    "ValidationResult",
    "ResponseValidator",
    "HealthStatus",
    "ModelHealthMonitor",
    "HardenedResponse",
    "KimiHardened",
    "ErrorClass",
]

import asyncio
import json
import logging
import math
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class KimiConfig:
    """Runtime configuration for the hardened Kimi client."""

    max_retries: int = 3
    retry_delay_base: float = 1.0
    retry_delay_max: float = 30.0
    token_budget_per_request: int = 16_384
    total_token_budget_per_session: int = 500_000
    response_timeout: int = 120
    enable_response_validation: bool = True
    health_check_interval: int = 60  # seconds
    fallback_models: list[str] = field(
        default_factory=lambda: [
            "kimi-k2.5-openrouter",
            "kimi-k2.5-together",
            "claude-opus-4.6",
        ]
    )


# ---------------------------------------------------------------------------
# Token Budget
# ---------------------------------------------------------------------------


@dataclass
class _TokenCounts:
    input: int = 0
    output: int = 0


class TokenBudget:
    """Per-session token tracker with budget enforcement."""

    def __init__(self, total_budget: int) -> None:
        self._budget = total_budget
        self._used = _TokenCounts()
        logger.debug("TokenBudget initialised with budget=%d", total_budget)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consume(self, input_tokens: int, output_tokens: int) -> bool:
        """Deduct tokens.  Returns *False* if budget is already exhausted."""
        total_used = self._used.input + self._used.output
        total_new = input_tokens + output_tokens
        if total_used + total_new > self._budget:
            logger.warning(
                "Token budget exhausted: used=%d new=%d budget=%d",
                total_used,
                total_new,
                self._budget,
            )
            return False
        self._used.input += input_tokens
        self._used.output += output_tokens
        logger.debug(
            "Tokens consumed: input=%d output=%d  total_used=%d/%d",
            input_tokens,
            output_tokens,
            self._used.input + self._used.output,
            self._budget,
        )
        return True

    def remaining(self) -> dict[str, Any]:
        """Return budget statistics."""
        total_used = self._used.input + self._used.output
        pct_used = (total_used / self._budget * 100) if self._budget else 0.0
        return {
            "total_budget": self._budget,
            "total_used": total_used,
            "remaining": self._budget - total_used,
            "pct_used": round(pct_used, 2),
            "input_used": self._used.input,
            "output_used": self._used.output,
        }

    def reset(self) -> None:
        """Reset all counters to zero."""
        self._used = _TokenCounts()
        logger.info("TokenBudget reset.")


# ---------------------------------------------------------------------------
# Response Validation
# ---------------------------------------------------------------------------

_REFUSAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bI cannot\b",
        r"\bI'm unable\b",
        r"\bI am unable\b",
        r"\bI can't\b",
        r"\bAs an AI\b",
        r"\bI won't be able\b",
        r"\bI will not be able\b",
    ]
]

_TRUNCATION_MARKERS: list[str] = [
    "[truncated]",
    "... (truncated)",
    "<truncated>",
    "[...continued",
    "// ... rest of",
    "# ... rest of",
]


@dataclass
class ValidationResult:
    """Outcome of a response validation pass."""

    valid: bool
    issues: list[str] = field(default_factory=list)
    confidence: float = 1.0  # 0.0–1.0
    auto_retry_recommended: bool = False


class ResponseValidator:
    """Validates LLM responses for quality and completeness."""

    def validate(
        self,
        response_text: str,
        expected_format: str = "",
    ) -> ValidationResult:
        """
        Validate *response_text* against a set of heuristic rules.

        Args:
            response_text: The raw text returned by the model.
            expected_format: Optional hint.  Supported values:
                ``"json"`` — checks for valid JSON.
                ``"code"`` — checks that code blocks are opened and closed.

        Returns:
            A :class:`ValidationResult`.
        """
        issues: list[str] = []
        confidence = 1.0

        # 1. Non-empty
        if not response_text or not response_text.strip():
            return ValidationResult(
                valid=False,
                issues=["Response is empty"],
                confidence=0.0,
                auto_retry_recommended=True,
            )

        stripped = response_text.strip()

        # 2. Minimum length for non-trivial content
        if len(stripped) <= 10:
            issues.append(f"Response is suspiciously short ({len(stripped)} chars)")
            confidence -= 0.3
            # Still flag as retry-worthy but don't hard-fail yet

        # 3. Truncation markers
        lower = stripped.lower()
        for marker in _TRUNCATION_MARKERS:
            if marker.lower() in lower:
                issues.append(f"Truncation marker detected: '{marker}'")
                confidence -= 0.4

        # 4. Refusal patterns
        for pat in _REFUSAL_PATTERNS:
            if pat.search(stripped):
                issues.append(f"Refusal pattern detected: '{pat.pattern}'")
                confidence -= 0.5

        # 5. JSON validity
        if expected_format == "json":
            try:
                # Strip markdown fences if present
                json_text = self._strip_fences(stripped, "json")
                json.loads(json_text)
            except json.JSONDecodeError as exc:
                issues.append(f"Invalid JSON: {exc}")
                confidence -= 0.5

        # 6. Code block completeness
        if expected_format == "code":
            open_count = stripped.count("```")
            if open_count % 2 != 0:
                issues.append("Unbalanced code fences — response may be truncated")
                confidence -= 0.4

        confidence = max(0.0, min(1.0, confidence))
        valid = len(issues) == 0
        auto_retry = not valid and confidence < 0.6

        result = ValidationResult(
            valid=valid,
            issues=issues,
            confidence=confidence,
            auto_retry_recommended=auto_retry,
        )
        if not valid:
            logger.debug("ValidationResult issues=%s confidence=%.2f", issues, confidence)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_fences(text: str, lang: str = "") -> str:
        pattern = rf"```{lang}\s*(.*?)```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else text


# ---------------------------------------------------------------------------
# Model Health Monitor
# ---------------------------------------------------------------------------

_TEST_MESSAGES = [{"role": "user", "content": "Respond with exactly the word PONG."}]


@dataclass
class HealthStatus:
    """Snapshot of a model's health at a point in time."""

    model: str
    healthy: bool
    latency_ms: float
    error: Optional[str] = None
    checked_at: float = field(default_factory=time.time)


class ModelHealthMonitor:
    """
    Periodically checks models and caches their health status.

    Call :meth:`start_monitor` to launch a background asyncio task.
    """

    def __init__(self, config: KimiConfig) -> None:
        self._config = config
        self._cache: dict[str, HealthStatus] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_health(self, model: str, router: Any) -> HealthStatus:
        """
        Send a minimal test prompt to *model* and record latency.

        Args:
            model: The model identifier to probe.
            router: The LLM router / client that exposes ``chat()``.

        Returns:
            A fresh :class:`HealthStatus`.
        """
        t0 = time.monotonic()
        try:
            resp = await asyncio.wait_for(
                router.chat(
                    messages=_TEST_MESSAGES,
                    model=model,
                    max_tokens=10,
                ),
                timeout=15.0,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            content = _extract_content(resp)
            healthy = bool(content and content.strip())
            status = HealthStatus(
                model=model,
                healthy=healthy,
                latency_ms=round(latency_ms, 1),
                error=None if healthy else "Empty response from health probe",
            )
        except asyncio.TimeoutError:
            status = HealthStatus(
                model=model,
                healthy=False,
                latency_ms=(time.monotonic() - t0) * 1000,
                error="Health-check timed out",
            )
        except Exception as exc:  # noqa: BLE001
            status = HealthStatus(
                model=model,
                healthy=False,
                latency_ms=(time.monotonic() - t0) * 1000,
                error=str(exc),
            )

        self._cache[model] = status
        logger.debug("HealthStatus for %s: %s", model, status)
        return status

    async def get_healthy_model(
        self,
        preferred: str,
        fallbacks: list[str],
        router: Any,
    ) -> str:
        """
        Return the first model in ``[preferred] + fallbacks`` that is healthy.

        Falls back to *preferred* if none pass the check (fail-open).
        """
        candidates = [preferred] + list(fallbacks)
        for model in candidates:
            cached = self._cache.get(model)
            age = time.time() - cached.checked_at if cached else math.inf
            if cached and age < self._config.health_check_interval:
                if cached.healthy:
                    logger.debug("Using cached healthy model: %s", model)
                    return model
                # Cached as unhealthy — skip without re-checking
                continue
            # No fresh cache — probe now
            status = await self.check_health(model, router)
            if status.healthy:
                return model
        logger.warning("No healthy model found; falling back to preferred '%s'", preferred)
        return preferred

    def start_monitor(self, models: list[str], router: Any) -> None:
        """Launch a background task that periodically checks all *models*."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(
            self._monitor_loop(models, router),
            name="model-health-monitor",
        )
        logger.info("ModelHealthMonitor started for models=%s", models)

    def stop_monitor(self) -> None:
        """Cancel the background monitoring task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("ModelHealthMonitor stopped.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _monitor_loop(self, models: list[str], router: Any) -> None:
        while self._running:
            for model in models:
                try:
                    await self.check_health(model, router)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Health-check error for %s: %s", model, exc)
            await asyncio.sleep(self._config.health_check_interval)


# ---------------------------------------------------------------------------
# Error Classification
# ---------------------------------------------------------------------------


class ErrorClass(str, Enum):
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    SERVER_ERROR = "SERVER_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNKNOWN = "UNKNOWN"


def _classify_error(exc: Exception) -> ErrorClass:
    msg = str(exc).lower()
    code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if code in (429,) or "rate limit" in msg or "too many requests" in msg:
        return ErrorClass.RATE_LIMIT
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in msg or "timed out" in msg:
        return ErrorClass.TIMEOUT
    if code in (500, 502, 503) or "server error" in msg or "bad gateway" in msg:
        return ErrorClass.SERVER_ERROR
    if code in (401, 403) or "unauthorized" in msg or "forbidden" in msg or "auth" in msg:
        return ErrorClass.AUTH_ERROR
    if code in (400, 422) or "invalid" in msg or "bad request" in msg:
        return ErrorClass.INVALID_REQUEST
    return ErrorClass.UNKNOWN


def _should_retry(exc: Exception) -> bool:
    cls = _classify_error(exc)
    return cls in (ErrorClass.RATE_LIMIT, ErrorClass.TIMEOUT, ErrorClass.SERVER_ERROR)


# ---------------------------------------------------------------------------
# Hardened Response
# ---------------------------------------------------------------------------


@dataclass
class HardenedResponse:
    """Rich response envelope returned by :class:`KimiHardened`."""

    content: str
    model_used: str
    attempts: int
    total_latency_ms: float
    input_tokens: int
    output_tokens: int
    fallback_used: bool
    validation: ValidationResult
    error: str = ""


# ---------------------------------------------------------------------------
# Main Hardened Wrapper
# ---------------------------------------------------------------------------


class KimiHardened:
    """
    Drop-in wrapper around any LLM router that adds:

    * Exponential-backoff retry
    * Token-budget enforcement
    * Response validation with auto-retry
    * Model health checking with automatic fallover
    """

    def __init__(self, config: KimiConfig, router: Any) -> None:
        self._config = config
        self._router = router
        self.token_budget = TokenBudget(config.total_token_budget_per_session)
        self.validator = ResponseValidator()
        self.health = ModelHealthMonitor(config)
        logger.info("KimiHardened initialised. fallback_models=%s", config.fallback_models)

    # ------------------------------------------------------------------
    # Primary call
    # ------------------------------------------------------------------

    async def call(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        model: str = "kimi-k2.5",
        **kwargs: Any,
    ) -> HardenedResponse:
        """
        Make a hardened LLM call.

        Workflow
        --------
        1. Check token budget.
        2. Resolve a healthy model (preferred → fallbacks).
        3. Retry with exponential back-off.
        4. Validate the response; auto-retry with a follow-up if needed.
        5. Deduct tokens and return :class:`HardenedResponse`.
        """
        t_start = time.monotonic()

        # 1. Budget check (rough estimate before the actual call)
        remaining = self.token_budget.remaining()
        if remaining["remaining"] <= 0:
            logger.error("Token budget exhausted — refusing call.")
            validation = ValidationResult(valid=False, issues=["Token budget exhausted"])
            return HardenedResponse(
                content="",
                model_used=model,
                attempts=0,
                total_latency_ms=0.0,
                input_tokens=0,
                output_tokens=0,
                fallback_used=False,
                validation=validation,
                error="Token budget exhausted",
            )

        # 2. Get the healthiest model
        resolved_model = await self.health.get_healthy_model(
            preferred=model,
            fallbacks=self._config.fallback_models,
            router=self._router,
        )
        fallback_used = resolved_model != model

        # 3. Retry loop
        last_exc: Optional[Exception] = None
        raw_content = ""
        input_tokens = 0
        output_tokens = 0
        attempts = 0
        expected_format = kwargs.pop("expected_format", "")

        for attempt in range(self._config.max_retries + 1):
            attempts = attempt + 1
            delay = self._exponential_backoff(attempt)
            if attempt > 0:
                logger.info(
                    "Retry %d/%d for model=%s (delay=%.2fs)",
                    attempt,
                    self._config.max_retries,
                    resolved_model,
                    delay,
                )
                await asyncio.sleep(delay)

            try:
                call_kwargs: dict[str, Any] = dict(kwargs)
                if tools:
                    call_kwargs["tools"] = tools

                resp = await asyncio.wait_for(
                    self._router.chat(
                        messages=messages,
                        model=resolved_model,
                        **call_kwargs,
                    ),
                    timeout=self._config.response_timeout,
                )
                raw_content = _extract_content(resp)
                input_tokens = _extract_usage(resp, "input")
                output_tokens = _extract_usage(resp, "output")
                last_exc = None
                break

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                cls = _classify_error(exc)
                logger.warning("LLM call failed (attempt=%d): [%s] %s", attempt + 1, cls.value, exc)
                if not _should_retry(exc):
                    logger.error("Non-retryable error — aborting. class=%s", cls.value)
                    break

        # 4. Validation + optional follow-up retry
        validation = ValidationResult(valid=True)
        if self._config.enable_response_validation and last_exc is None:
            validation = self.validator.validate(raw_content, expected_format)

            if not validation.valid and validation.auto_retry_recommended:
                logger.info("Validation failed — attempting follow-up completion retry.")
                follow_up_messages = list(messages) + [
                    {"role": "assistant", "content": raw_content},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response appears incomplete or did not meet"
                            " the required format. Please complete your response fully."
                        ),
                    },
                ]
                try:
                    resp2 = await asyncio.wait_for(
                        self._router.chat(
                            messages=follow_up_messages,
                            model=resolved_model,
                            **kwargs,
                        ),
                        timeout=self._config.response_timeout,
                    )
                    raw_content = _extract_content(resp2)
                    input_tokens += _extract_usage(resp2, "input")
                    output_tokens += _extract_usage(resp2, "output")
                    attempts += 1
                    validation = self.validator.validate(raw_content, expected_format)
                except Exception as exc2:  # noqa: BLE001
                    logger.error("Follow-up retry also failed: %s", exc2)

        # 5. Deduct tokens
        self.token_budget.consume(input_tokens, output_tokens)

        total_latency = (time.monotonic() - t_start) * 1000
        error_str = str(last_exc) if last_exc else ""

        return HardenedResponse(
            content=raw_content,
            model_used=resolved_model,
            attempts=attempts,
            total_latency_ms=round(total_latency, 1),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            fallback_used=fallback_used,
            validation=validation,
            error=error_str,
        )

    # ------------------------------------------------------------------
    # Fallback chaining
    # ------------------------------------------------------------------

    async def call_with_fallback(
        self,
        messages: list[dict[str, str]],
        models: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> HardenedResponse:
        """
        Try each model in *models* (defaults to config fallback_models) in
        order and return the first successful response.
        """
        candidates = models or self._config.fallback_models
        last_response: Optional[HardenedResponse] = None
        for model in candidates:
            response = await self.call(messages=messages, model=model, **kwargs)
            last_response = response
            if not response.error and response.validation.valid:
                return response
            logger.warning(
                "Model %s failed or validation invalid — trying next. error=%s",
                model,
                response.error,
            )
        # Return whatever we got from the last attempt
        assert last_response is not None
        return last_response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _exponential_backoff(self, attempt: int) -> float:
        """Delay = base * 2^attempt + jitter, clamped to max."""
        base = self._config.retry_delay_base * (2 ** attempt)
        jitter = random.uniform(0, base * 0.25)
        return min(base + jitter, self._config.retry_delay_max)

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        return _should_retry(exc)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_content(resp: Any) -> str:
    """Best-effort extraction of text content from various response shapes."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        # OpenAI-style
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
                        import logging as _log; _log.getLogger('kimi_hardening').debug('Suppressed exception', exc_info=True)
        return resp.get("content", "") or resp.get("text", "") or ""
    # Object with .choices
    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
                import logging as _log; _log.getLogger('kimi_hardening').debug('Suppressed exception', exc_info=True)
    # Object with .content
    try:
        return resp.content or ""
    except AttributeError:
                import logging as _log; _log.getLogger('kimi_hardening').debug('Suppressed exception', exc_info=True)
    return str(resp)


def _extract_usage(resp: Any, kind: str) -> int:
    """Extract token usage (input/output) from a response object."""
    try:
        usage = resp.usage if hasattr(resp, "usage") else resp.get("usage", {})
        if kind == "input":
            return getattr(usage, "prompt_tokens", None) or usage.get("prompt_tokens", 0)
        if kind == "output":
            return getattr(usage, "completion_tokens", None) or usage.get("completion_tokens", 0)
    except Exception:  # noqa: BLE001
        pass
    return 0
