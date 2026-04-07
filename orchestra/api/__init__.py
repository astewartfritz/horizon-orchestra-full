from __future__ import annotations

"""API package for Horizon Orchestra.

Modules:
- ``server`` — FastAPI production server (29 routes)
- ``schemas`` — JSON Schema definitions, error codes, request validation
"""

from .server import ProductionAPI, APIConfig, create_production_app
from .schemas import (
    ErrorCode,
    APIError,
    api_error,
    validate_request,
    OPENAPI_SCHEMAS,
    get_schema,
    ERROR_CATALOG,
)

__all__ = [
    # Server
    "ProductionAPI",
    "APIConfig",
    "create_production_app",
    # Schemas
    "ErrorCode",
    "APIError",
    "api_error",
    "validate_request",
    "OPENAPI_SCHEMAS",
    "get_schema",
    "ERROR_CATALOG",
]
