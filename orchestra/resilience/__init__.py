"""
orchestra.resilience — World-class resilience and error recovery system.

Provides comprehensive error taxonomy, circuit breakers, recovery graphs,
adaptive retry, stream healing, fallback chains, and a unified
``@resilient`` middleware decorator.
"""
from __future__ import annotations

from .adaptive_retry import AdaptiveRetryManager, JitterStrategy, RetryDecision, RetryPolicy
from .circuit_breaker import AdaptiveThreshold, BreakerLevel, CircuitBreaker, CircuitState
from .error_taxonomy import ERROR_REGISTRY, ErrorCategory, ErrorSpec, ErrorTaxonomy
from .fallback_chain import (
    DegradationEstimate,
    FallbackChain,
    FallbackResult,
    FallbackScenario,
    FallbackTarget,
)
from .recovery_graph import RecoveryEdge, RecoveryGraph, RecoveryNode, RecoveryPath, RecoveryResult
from .resilience_middleware import (
    ResilientCall,
    ResilientConfig,
    ResilientOutcome,
    clear_outcome_log,
    configure_resilience,
    get_outcome_log,
    resilient,
)
from .stream_healer import BreakType, StreamHealer, StreamState

__all__ = [
    # error_taxonomy
    "ErrorCategory",
    "ErrorSpec",
    "ERROR_REGISTRY",
    "ErrorTaxonomy",
    # circuit_breaker
    "CircuitState",
    "AdaptiveThreshold",
    "BreakerLevel",
    "CircuitBreaker",
    # recovery_graph
    "RecoveryNode",
    "RecoveryEdge",
    "RecoveryPath",
    "RecoveryResult",
    "RecoveryGraph",
    # adaptive_retry
    "JitterStrategy",
    "RetryPolicy",
    "RetryDecision",
    "AdaptiveRetryManager",
    # stream_healer
    "BreakType",
    "StreamState",
    "StreamHealer",
    # fallback_chain
    "FallbackScenario",
    "FallbackTarget",
    "FallbackResult",
    "DegradationEstimate",
    "FallbackChain",
    # resilience_middleware
    "ResilientConfig",
    "ResilientOutcome",
    "ResilientCall",
    "resilient",
    "get_outcome_log",
    "clear_outcome_log",
    "configure_resilience",
]
