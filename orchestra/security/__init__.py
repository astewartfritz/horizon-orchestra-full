from __future__ import annotations

"""Security package for Horizon Orchestra.

Exports both the hardening layer (orchestra.security.hardening)
and the full security policy / middleware layer (orchestra.security
top-level module).
"""

from .hardening import (
    SecurityHardening,
    AdversarialFilter,
    DDoSProtector,
    WAFRules,
    SecurityConfig,
    AuditLogger,
    RedTeamDefense,
    SecurityResult,
)

# Import from orchestra.security_ext — a thin re-export module that loads
# the root-level orchestra/security.py using the proper package context.
# We register it in sys.modules under a unique name to avoid collisions.
import sys as _sys
import importlib as _importlib

try:
    # Register orchestra/security.py as "orchestra._security_full" so
    # its relative imports resolve correctly inside the orchestra package.
    _pkg_name = "orchestra._security_full"
    if _pkg_name not in _sys.modules:
        import importlib.util as _ilu
        import os as _os
        _py = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "security.py")
        _spec = _ilu.spec_from_file_location(
            _pkg_name, _py,
            submodule_search_locations=[],
        )
        _sec_mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
        _sec_mod.__package__ = "orchestra"         # make relative imports work
        _sec_mod.__name__ = "orchestra._security_full"
        _sys.modules[_pkg_name] = _sec_mod
        # Also make it findable under the orchestra package namespace
        _sys.modules.setdefault("orchestra", _sys.modules.get("orchestra"))
        _spec.loader.exec_module(_sec_mod)         # type: ignore[union-attr]
    else:
        _sec_mod = _sys.modules[_pkg_name]  # type: ignore[assignment]

    PermissionPolicy = _sec_mod.PermissionPolicy
    PermissionGate = _sec_mod.PermissionGate
    InputSanitizer = _sec_mod.InputSanitizer
    OutputMonitor = _sec_mod.OutputMonitor
    RateLimiter = _sec_mod.RateLimiter
    SecurityMiddleware = _sec_mod.SecurityMiddleware
    SecurityDecision = _sec_mod.SecurityDecision
    InjectionAlert = _sec_mod.InjectionAlert
    SanitizeResult = _sec_mod.SanitizeResult
    SecurityAlert = _sec_mod.SecurityAlert
    PIIMatch = _sec_mod.PIIMatch

    strict_policy = _sec_mod.strict_policy
    standard_policy = _sec_mod.standard_policy
    permissive_policy = _sec_mod.permissive_policy
    safety_critical_policy = _sec_mod.safety_critical_policy

except Exception as _e:
    import logging as _logging
    _logging.getLogger("orchestra.security").warning("Could not load security.py: %s", _e)
    PermissionPolicy = None  # type: ignore[assignment,misc]
    PermissionGate = None  # type: ignore[assignment,misc]
    InputSanitizer = None  # type: ignore[assignment,misc]
    OutputMonitor = None  # type: ignore[assignment,misc]
    RateLimiter = None  # type: ignore[assignment,misc]
    SecurityMiddleware = None  # type: ignore[assignment,misc]
    SecurityDecision = None  # type: ignore[assignment,misc]
    InjectionAlert = None  # type: ignore[assignment,misc]
    SanitizeResult = None  # type: ignore[assignment,misc]
    SecurityAlert = None  # type: ignore[assignment,misc]
    PIIMatch = None  # type: ignore[assignment,misc]
    strict_policy = None  # type: ignore[assignment]
    standard_policy = None  # type: ignore[assignment]
    permissive_policy = None  # type: ignore[assignment]
    safety_critical_policy = None  # type: ignore[assignment]


__all__ = [
    # Hardening layer
    "SecurityHardening",
    "AdversarialFilter",
    "DDoSProtector",
    "WAFRules",
    "SecurityConfig",
    "AuditLogger",
    "RedTeamDefense",
    "SecurityResult",
    # Policy / middleware layer
    "PermissionPolicy",
    "PermissionGate",
    "InputSanitizer",
    "OutputMonitor",
    "RateLimiter",
    "SecurityMiddleware",
    "SecurityDecision",
    "InjectionAlert",
    "SanitizeResult",
    "SecurityAlert",
    "PIIMatch",
    # Policy factories
    "strict_policy",
    "standard_policy",
    "permissive_policy",
    "safety_critical_policy",
]
