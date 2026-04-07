"""JSON Schema definitions and API error codes for Horizon Orchestra.

Provides:
- Standardised error codes and messages for every failure mode
- OpenAPI-compatible JSON Schema definitions for all request/response types
- Schema validation helper that works with or without Pydantic
- Error response builder with consistent envelope format

Usage::

    from orchestra.api.schemas import (
        ErrorCode, api_error, validate_request,
        OPENAPI_SCHEMAS, get_schema,
    )

    # Raise a standardised error
    raise api_error(ErrorCode.AUTH_TOKEN_EXPIRED, status=401)

    # Validate a request body
    errors = validate_request(body, "RunRequest")
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ErrorCode",
    "APIError",
    "api_error",
    "validate_request",
    "OPENAPI_SCHEMAS",
    "get_schema",
    "ERROR_CATALOG",
]


# ---------------------------------------------------------------------------
# Error codes — every failure mode gets a unique code
# ---------------------------------------------------------------------------

class ErrorCode(str, Enum):
    """Canonical error codes for the Horizon Orchestra API.

    Format: ``CATEGORY_SPECIFIC_ERROR``.  Clients can match on the
    code string to build localised error messages without parsing
    the human-readable ``message`` field.
    """

    # Auth (1xxx)
    AUTH_MISSING_TOKEN       = "AUTH_MISSING_TOKEN"
    AUTH_TOKEN_EXPIRED       = "AUTH_TOKEN_EXPIRED"
    AUTH_TOKEN_INVALID       = "AUTH_TOKEN_INVALID"
    AUTH_WRONG_PASSWORD      = "AUTH_WRONG_PASSWORD"
    AUTH_USER_NOT_FOUND      = "AUTH_USER_NOT_FOUND"
    AUTH_EMAIL_EXISTS        = "AUTH_EMAIL_EXISTS"
    AUTH_INSUFFICIENT_ROLE   = "AUTH_INSUFFICIENT_ROLE"

    # Billing (2xxx)
    BILLING_TIER_INVALID     = "BILLING_TIER_INVALID"
    BILLING_LIMIT_REACHED    = "BILLING_LIMIT_REACHED"
    BILLING_PAYMENT_FAILED   = "BILLING_PAYMENT_FAILED"
    BILLING_SUB_NOT_FOUND    = "BILLING_SUB_NOT_FOUND"
    BILLING_ARCH_DENIED      = "BILLING_ARCH_DENIED"

    # Validation (3xxx)
    VALIDATION_FAILED        = "VALIDATION_FAILED"
    VALIDATION_MISSING_FIELD = "VALIDATION_MISSING_FIELD"
    VALIDATION_INVALID_TYPE  = "VALIDATION_INVALID_TYPE"
    VALIDATION_OUT_OF_RANGE  = "VALIDATION_OUT_OF_RANGE"

    # Execution (4xxx)
    EXEC_TASK_FAILED         = "EXEC_TASK_FAILED"
    EXEC_TIMEOUT             = "EXEC_TIMEOUT"
    EXEC_MODEL_UNAVAILABLE   = "EXEC_MODEL_UNAVAILABLE"
    EXEC_TOOL_FAILED         = "EXEC_TOOL_FAILED"
    EXEC_SANDBOX_ERROR       = "EXEC_SANDBOX_ERROR"

    # Rate limiting (5xxx)
    RATE_LIMIT_EXCEEDED      = "RATE_LIMIT_EXCEEDED"

    # Resource (6xxx)
    RESOURCE_NOT_FOUND       = "RESOURCE_NOT_FOUND"
    RESOURCE_CONFLICT        = "RESOURCE_CONFLICT"
    RESOURCE_GONE            = "RESOURCE_GONE"

    # Connector (7xxx)
    CONNECTOR_NOT_FOUND      = "CONNECTOR_NOT_FOUND"
    CONNECTOR_AUTH_FAILED    = "CONNECTOR_AUTH_FAILED"
    CONNECTOR_OFFLINE        = "CONNECTOR_OFFLINE"

    # Browser / Frontier (8xxx)
    FRONTIER_TASK_NOT_FOUND  = "FRONTIER_TASK_NOT_FOUND"
    FRONTIER_URL_BLOCKED     = "FRONTIER_URL_BLOCKED"
    FRONTIER_APPROVAL_NEEDED = "FRONTIER_APPROVAL_NEEDED"
    FRONTIER_SANDBOX_FULL    = "FRONTIER_SANDBOX_FULL"

    # Server (9xxx)
    SERVER_INTERNAL          = "SERVER_INTERNAL"
    SERVER_UNAVAILABLE       = "SERVER_UNAVAILABLE"
    SERVER_DEPENDENCY_DOWN   = "SERVER_DEPENDENCY_DOWN"


# Human-readable messages + default HTTP status for each error code
ERROR_CATALOG: dict[ErrorCode, dict[str, Any]] = {
    ErrorCode.AUTH_MISSING_TOKEN:     {"status": 401, "message": "Authorization header is missing or empty."},
    ErrorCode.AUTH_TOKEN_EXPIRED:     {"status": 401, "message": "Authentication token has expired. Please refresh."},
    ErrorCode.AUTH_TOKEN_INVALID:     {"status": 401, "message": "Authentication token is invalid or malformed."},
    ErrorCode.AUTH_WRONG_PASSWORD:    {"status": 401, "message": "Incorrect password."},
    ErrorCode.AUTH_USER_NOT_FOUND:    {"status": 404, "message": "User not found."},
    ErrorCode.AUTH_EMAIL_EXISTS:      {"status": 409, "message": "An account with this email already exists."},
    ErrorCode.AUTH_INSUFFICIENT_ROLE: {"status": 403, "message": "Insufficient permissions for this action."},

    ErrorCode.BILLING_TIER_INVALID:   {"status": 400, "message": "Invalid pricing tier."},
    ErrorCode.BILLING_LIMIT_REACHED:  {"status": 429, "message": "Billing limit reached. Upgrade your plan."},
    ErrorCode.BILLING_PAYMENT_FAILED: {"status": 402, "message": "Payment failed. Please update your payment method."},
    ErrorCode.BILLING_SUB_NOT_FOUND:  {"status": 404, "message": "No active subscription found."},
    ErrorCode.BILLING_ARCH_DENIED:    {"status": 403, "message": "Architecture not available on your current tier."},

    ErrorCode.VALIDATION_FAILED:       {"status": 422, "message": "Request validation failed."},
    ErrorCode.VALIDATION_MISSING_FIELD:{"status": 422, "message": "Required field is missing."},
    ErrorCode.VALIDATION_INVALID_TYPE: {"status": 422, "message": "Field has an invalid type."},
    ErrorCode.VALIDATION_OUT_OF_RANGE: {"status": 422, "message": "Value is out of allowed range."},

    ErrorCode.EXEC_TASK_FAILED:       {"status": 500, "message": "Task execution failed."},
    ErrorCode.EXEC_TIMEOUT:           {"status": 504, "message": "Task execution timed out."},
    ErrorCode.EXEC_MODEL_UNAVAILABLE: {"status": 503, "message": "Requested model is currently unavailable."},
    ErrorCode.EXEC_TOOL_FAILED:       {"status": 500, "message": "Tool execution failed during task."},
    ErrorCode.EXEC_SANDBOX_ERROR:     {"status": 500, "message": "Sandbox execution environment error."},

    ErrorCode.RATE_LIMIT_EXCEEDED:    {"status": 429, "message": "Too many requests. Please slow down."},

    ErrorCode.RESOURCE_NOT_FOUND:     {"status": 404, "message": "Requested resource not found."},
    ErrorCode.RESOURCE_CONFLICT:      {"status": 409, "message": "Resource conflict — already exists."},
    ErrorCode.RESOURCE_GONE:          {"status": 410, "message": "Resource has been deleted."},

    ErrorCode.CONNECTOR_NOT_FOUND:    {"status": 404, "message": "Connector not found."},
    ErrorCode.CONNECTOR_AUTH_FAILED:  {"status": 401, "message": "Connector authentication failed."},
    ErrorCode.CONNECTOR_OFFLINE:      {"status": 503, "message": "Connector service is offline."},

    ErrorCode.FRONTIER_TASK_NOT_FOUND:  {"status": 404, "message": "Browser task not found."},
    ErrorCode.FRONTIER_URL_BLOCKED:     {"status": 403, "message": "URL is blocked by Frontier safety policy."},
    ErrorCode.FRONTIER_APPROVAL_NEEDED: {"status": 428, "message": "Action requires user approval."},
    ErrorCode.FRONTIER_SANDBOX_FULL:    {"status": 503, "message": "All browser sandboxes are in use. Try again shortly."},

    ErrorCode.SERVER_INTERNAL:        {"status": 500, "message": "Internal server error."},
    ErrorCode.SERVER_UNAVAILABLE:     {"status": 503, "message": "Service temporarily unavailable."},
    ErrorCode.SERVER_DEPENDENCY_DOWN: {"status": 502, "message": "A required dependency is unreachable."},
}


# ---------------------------------------------------------------------------
# APIError
# ---------------------------------------------------------------------------

class APIError(Exception):
    """Structured API error with code, message, status, and detail."""

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        status: int = 0,
        detail: dict[str, Any] | None = None,
    ) -> None:
        catalog = ERROR_CATALOG.get(code, {"status": 500, "message": "Unknown error"})
        self.code = code
        self.message = message or catalog["message"]
        self.status = status or catalog["status"]
        self.detail = detail or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the standard API error envelope."""
        return {
            "data": None,
            "error": {
                "code": self.code.value,
                "message": self.message,
                "detail": self.detail,
            },
            "meta": {"status": self.status},
        }


def api_error(
    code: ErrorCode,
    message: str = "",
    status: int = 0,
    detail: dict[str, Any] | None = None,
) -> APIError:
    """Create an APIError (convenience function)."""
    return APIError(code, message, status, detail)


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

def validate_request(body: dict[str, Any], schema_name: str) -> list[str]:
    """Validate a request body against a named schema.

    Returns a list of error strings (empty = valid).  Works without
    Pydantic by checking required fields and basic types against the
    OPENAPI_SCHEMAS definition.
    """
    schema = OPENAPI_SCHEMAS.get(schema_name)
    if schema is None:
        return [f"Unknown schema: {schema_name}"]

    errors: list[str] = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field_name in required:
        if field_name not in body:
            errors.append(f"Missing required field: {field_name}")

    for field_name, value in body.items():
        if field_name not in properties:
            continue
        prop = properties[field_name]
        expected_type = prop.get("type", "")

        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"Field '{field_name}' must be a string, got {type(value).__name__}")
        elif expected_type == "integer" and not isinstance(value, int):
            errors.append(f"Field '{field_name}' must be an integer, got {type(value).__name__}")
        elif expected_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"Field '{field_name}' must be a number, got {type(value).__name__}")
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(f"Field '{field_name}' must be a boolean, got {type(value).__name__}")
        elif expected_type == "array" and not isinstance(value, list):
            errors.append(f"Field '{field_name}' must be an array, got {type(value).__name__}")
        elif expected_type == "object" and not isinstance(value, dict):
            errors.append(f"Field '{field_name}' must be an object, got {type(value).__name__}")

        # Range checks
        if "minimum" in prop and isinstance(value, (int, float)):
            if value < prop["minimum"]:
                errors.append(f"Field '{field_name}' must be >= {prop['minimum']}")
        if "maximum" in prop and isinstance(value, (int, float)):
            if value > prop["maximum"]:
                errors.append(f"Field '{field_name}' must be <= {prop['maximum']}")
        if "maxLength" in prop and isinstance(value, str):
            if len(value) > prop["maxLength"]:
                errors.append(f"Field '{field_name}' exceeds max length ({prop['maxLength']})")
        if "enum" in prop and value not in prop["enum"]:
            errors.append(f"Field '{field_name}' must be one of: {prop['enum']}")

    return errors


def get_schema(name: str) -> dict[str, Any] | None:
    """Look up an OpenAPI schema by name."""
    return OPENAPI_SCHEMAS.get(name)


# ---------------------------------------------------------------------------
# OpenAPI-compatible JSON Schemas for every request/response type
# ---------------------------------------------------------------------------

OPENAPI_SCHEMAS: dict[str, dict[str, Any]] = {
    # -- Auth ----------------------------------------------------------------
    "RegisterRequest": {
        "type": "object",
        "required": ["email", "name", "password"],
        "properties": {
            "email":    {"type": "string", "format": "email", "maxLength": 320},
            "name":     {"type": "string", "maxLength": 200},
            "password": {"type": "string", "minLength": 8, "maxLength": 128},
        },
    },
    "LoginRequest": {
        "type": "object",
        "required": ["email", "password"],
        "properties": {
            "email":    {"type": "string", "format": "email"},
            "password": {"type": "string"},
        },
    },
    "RefreshRequest": {
        "type": "object",
        "required": ["refresh_token"],
        "properties": {
            "refresh_token": {"type": "string"},
        },
    },
    "AuthResponse": {
        "type": "object",
        "properties": {
            "user_id":       {"type": "string"},
            "email":         {"type": "string"},
            "name":          {"type": "string"},
            "token":         {"type": "string"},
            "refresh_token": {"type": "string"},
            "tier":          {"type": "string", "enum": ["free", "pro", "team", "max"]},
        },
    },
    "UserProfile": {
        "type": "object",
        "properties": {
            "user_id":    {"type": "string"},
            "email":      {"type": "string"},
            "name":       {"type": "string"},
            "tier":       {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
        },
    },

    # -- Task Execution ------------------------------------------------------
    "RunRequest": {
        "type": "object",
        "required": ["task"],
        "properties": {
            "task":         {"type": "string", "maxLength": 50000},
            "agent_type":   {"type": "string", "enum": ["monolithic", "rag", "swarm", "mcp", "production"], "default": "monolithic"},
            "architecture": {"type": "string", "enum": ["A", "B", "C", "D", "E"]},
            "context":      {"type": "object", "default": {}},
            "model":        {"type": "string", "default": "kimi-k2.5"},
            "stream":       {"type": "boolean", "default": False},
        },
    },
    "RunResponse": {
        "type": "object",
        "properties": {
            "result":       {"type": "string"},
            "tool_calls":   {"type": "integer"},
            "tokens_used":  {"type": "integer"},
            "duration_ms":  {"type": "number"},
            "architecture": {"type": "string"},
        },
    },

    # -- Query ---------------------------------------------------------------
    "QueryRequest": {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt":      {"type": "string", "maxLength": 100000},
            "model":       {"type": "string", "default": "kimi-k2.5"},
            "system":      {"type": "string", "maxLength": 10000, "default": ""},
            "temperature": {"type": "number", "minimum": 0.0, "maximum": 2.0, "default": 0.7},
            "max_tokens":  {"type": "integer", "minimum": 1, "maximum": 262144, "default": 2048},
        },
    },
    "QueryResponse": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "model":   {"type": "string"},
            "usage":   {
                "type": "object",
                "properties": {
                    "input_tokens":  {"type": "integer"},
                    "output_tokens": {"type": "integer"},
                },
            },
        },
    },

    # -- Billing -------------------------------------------------------------
    "CheckoutRequest": {
        "type": "object",
        "required": ["tier", "success_url", "cancel_url"],
        "properties": {
            "tier":        {"type": "string", "enum": ["pro", "team", "max"]},
            "success_url": {"type": "string", "format": "uri"},
            "cancel_url":  {"type": "string", "format": "uri"},
        },
    },
    "PortalRequest": {
        "type": "object",
        "required": ["return_url"],
        "properties": {
            "return_url": {"type": "string", "format": "uri"},
        },
    },
    "Subscription": {
        "type": "object",
        "properties": {
            "tier":                 {"type": "string"},
            "status":               {"type": "string", "enum": ["active", "past_due", "canceled", "trialing"]},
            "current_period_end":   {"type": "string", "format": "date-time"},
            "cancel_at_period_end": {"type": "boolean"},
        },
    },
    "UsageData": {
        "type": "object",
        "properties": {
            "requests_used_today":     {"type": "integer"},
            "tokens_used_this_month":  {"type": "integer"},
            "agents_active":           {"type": "integer"},
            "storage_used_mb":         {"type": "number"},
        },
    },
    "Invoice": {
        "type": "object",
        "properties": {
            "id":           {"type": "string"},
            "amount":       {"type": "number"},
            "currency":     {"type": "string"},
            "status":       {"type": "string"},
            "period_start": {"type": "string", "format": "date-time"},
            "period_end":   {"type": "string", "format": "date-time"},
            "pdf_url":      {"type": "string", "format": "uri"},
        },
    },

    # -- Memory --------------------------------------------------------------
    "MemorySearchRequest": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query":   {"type": "string", "maxLength": 5000},
            "limit":   {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
            "filters": {"type": "object", "default": {}},
        },
    },
    "MemoryStoreRequest": {
        "type": "object",
        "required": ["content"],
        "properties": {
            "content":  {"type": "string", "maxLength": 50000},
            "metadata": {"type": "object", "default": {}},
            "tags":     {"type": "array", "items": {"type": "string"}, "default": []},
        },
    },
    "MemoryEntry": {
        "type": "object",
        "properties": {
            "id":         {"type": "string"},
            "content":    {"type": "string"},
            "category":   {"type": "string"},
            "score":      {"type": "number"},
            "created_at": {"type": "string", "format": "date-time"},
        },
    },

    # -- Files ---------------------------------------------------------------
    "FileInfo": {
        "type": "object",
        "properties": {
            "filename":     {"type": "string"},
            "size_bytes":   {"type": "integer"},
            "content_type": {"type": "string"},
            "uploaded_at":  {"type": "string", "format": "date-time"},
        },
    },
    "ShareLink": {
        "type": "object",
        "properties": {
            "url":        {"type": "string", "format": "uri"},
            "expires_at": {"type": "string", "format": "date-time"},
        },
    },

    # -- Push Notifications --------------------------------------------------
    "PushRegisterRequest": {
        "type": "object",
        "required": ["device_token", "platform", "device_id"],
        "properties": {
            "device_token": {"type": "string"},
            "platform":     {"type": "string", "enum": ["apns", "fcm"]},
            "device_id":    {"type": "string"},
        },
    },
    "PushSendRequest": {
        "type": "object",
        "required": ["user_id", "title", "body"],
        "properties": {
            "user_id": {"type": "string"},
            "title":   {"type": "string", "maxLength": 200},
            "body":    {"type": "string", "maxLength": 2000},
            "data":    {"type": "object", "default": {}},
        },
    },

    # -- Frontier Browser ----------------------------------------------------
    "FrontierSubmitRequest": {
        "type": "object",
        "required": ["description"],
        "properties": {
            "description":     {"type": "string", "maxLength": 10000},
            "start_url":       {"type": "string", "format": "uri"},
            "max_steps":       {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            "timeout_seconds": {"type": "number", "minimum": 10, "maximum": 3600, "default": 300},
        },
    },
    "FrontierTask": {
        "type": "object",
        "properties": {
            "task_id":        {"type": "string"},
            "description":    {"type": "string"},
            "status":         {"type": "string", "enum": ["queued", "running", "paused", "completed", "failed", "cancelled"]},
            "result":         {"type": "string"},
            "extracted_data": {"type": "object"},
            "pages_visited":  {"type": "array", "items": {"type": "string"}},
            "error":          {"type": "string"},
        },
    },

    # -- Architecture Billing ------------------------------------------------
    "CostEstimate": {
        "type": "object",
        "properties": {
            "architecture":      {"type": "string"},
            "total_units":       {"type": "number"},
            "multiplier":        {"type": "number"},
            "within_tier_limits":{"type": "boolean"},
            "breakdown":         {"type": "object"},
            "warnings":          {"type": "array", "items": {"type": "string"}},
        },
    },
    "ArchitectureAccess": {
        "type": "object",
        "properties": {
            "allowed":         {"type": "boolean"},
            "reason":          {"type": "string"},
            "tier":            {"type": "string"},
            "architecture":    {"type": "string"},
            "upgrade_options": {"type": "array", "items": {"type": "string"}},
        },
    },

    # -- Streaming events ----------------------------------------------------
    "StreamEvent": {
        "type": "object",
        "required": ["type", "data"],
        "properties": {
            "type":      {"type": "string", "enum": [
                "token", "tool_call", "tool_result", "thinking", "final_answer",
                "error", "billing_update", "billing_complete", "heartbeat",
            ]},
            "data":      {"type": "object"},
            "timestamp": {"type": "number"},
        },
    },

    # -- Standard API envelope -----------------------------------------------
    "ApiResponse": {
        "type": "object",
        "properties": {
            "data":  {},
            "error": {
                "oneOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "code":    {"type": "string"},
                            "message": {"type": "string"},
                            "detail":  {"type": "object"},
                        },
                    },
                ],
            },
            "meta": {
                "type": "object",
                "properties": {
                    "request_id":  {"type": "string"},
                    "duration_ms": {"type": "number"},
                },
            },
        },
    },

    # -- Health check --------------------------------------------------------
    "HealthResponse": {
        "type": "object",
        "properties": {
            "status":     {"type": "string", "enum": ["healthy", "degraded", "unhealthy"]},
            "version":    {"type": "string"},
            "uptime_s":   {"type": "number"},
            "modules":    {"type": "integer"},
            "checks":     {"type": "object"},
        },
    },
}
