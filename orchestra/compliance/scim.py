"""
SCIM 2.0 User/Group Provisioning (RFC 7644).

Full SCIM 2.0 implementation for enterprise IdP integration
(Okta, Azure AD, OneLogin). Provides user and group lifecycle
management with ETag-based conflict detection and bearer token
validation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

__all__ = [
    "SCIMUser",
    "SCIMGroup",
    "SCIMPatch",
    "SCIMPatchOp",
    "SCIMListResponse",
    "SCIMProvider",
    "SCIMError",
    "SCIMFilterParser",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SCIMError(Exception):
    """RFC 7644 §3.12 – SCIM error response."""

    def __init__(self, status: int, detail: str, scim_type: str | None = None):
        self.status = status
        self.detail = detail
        self.scim_type = scim_type
        super().__init__(detail)

    def to_dict(self) -> dict:
        body: dict = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "detail": self.detail,
            "status": str(self.status),
        }
        if self.scim_type:
            body["scimType"] = self.scim_type
        return body


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SCIMMeta:
    """SCIM resource metadata (§3.1)."""
    resource_type: str = "User"
    created: str = ""
    last_modified: str = ""
    location: str = ""
    version: str = ""  # ETag

    def to_dict(self) -> dict:
        return {
            "resourceType": self.resource_type,
            "created": self.created,
            "lastModified": self.last_modified,
            "location": self.location,
            "version": self.version,
        }


@dataclass
class SCIMName:
    """SCIM user name component."""
    formatted: str = ""
    family_name: str = ""
    given_name: str = ""
    middle_name: str = ""
    honorific_prefix: str = ""
    honorific_suffix: str = ""

    def to_dict(self) -> dict:
        return {
            "formatted": self.formatted,
            "familyName": self.family_name,
            "givenName": self.given_name,
            "middleName": self.middle_name,
            "honorificPrefix": self.honorific_prefix,
            "honorificSuffix": self.honorific_suffix,
        }


@dataclass
class SCIMEmail:
    """SCIM email value."""
    value: str = ""
    type: str = "work"
    primary: bool = False

    def to_dict(self) -> dict:
        return {"value": self.value, "type": self.type, "primary": self.primary}


@dataclass
class SCIMUser:
    """SCIM 2.0 User resource (RFC 7643 §4.1)."""
    id: str = ""
    external_id: str = ""
    user_name: str = ""
    name: SCIMName = field(default_factory=SCIMName)
    emails: List[SCIMEmail] = field(default_factory=list)
    groups: List[Dict[str, str]] = field(default_factory=list)
    active: bool = True
    meta: SCIMMeta = field(default_factory=lambda: SCIMMeta(resource_type="User"))
    display_name: str = ""
    locale: str = ""
    timezone: str = ""
    title: str = ""
    department: str = ""

    def to_dict(self) -> dict:
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "id": self.id,
            "externalId": self.external_id,
            "userName": self.user_name,
            "name": self.name.to_dict(),
            "emails": [e.to_dict() for e in self.emails],
            "groups": self.groups,
            "active": self.active,
            "displayName": self.display_name,
            "locale": self.locale,
            "timezone": self.timezone,
            "title": self.title,
            "department": self.department,
            "meta": self.meta.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SCIMUser":
        """Parse a SCIM JSON payload into a SCIMUser."""
        name_data = data.get("name", {})
        name = SCIMName(
            formatted=name_data.get("formatted", ""),
            family_name=name_data.get("familyName", ""),
            given_name=name_data.get("givenName", ""),
            middle_name=name_data.get("middleName", ""),
            honorific_prefix=name_data.get("honorificPrefix", ""),
            honorific_suffix=name_data.get("honorificSuffix", ""),
        )
        emails = [
            SCIMEmail(
                value=e.get("value", ""),
                type=e.get("type", "work"),
                primary=e.get("primary", False),
            )
            for e in data.get("emails", [])
        ]
        meta_data = data.get("meta", {})
        meta = SCIMMeta(
            resource_type=meta_data.get("resourceType", "User"),
            created=meta_data.get("created", ""),
            last_modified=meta_data.get("lastModified", ""),
            location=meta_data.get("location", ""),
            version=meta_data.get("version", ""),
        )
        return cls(
            id=data.get("id", ""),
            external_id=data.get("externalId", ""),
            user_name=data.get("userName", ""),
            name=name,
            emails=emails,
            groups=data.get("groups", []),
            active=data.get("active", True),
            meta=meta,
            display_name=data.get("displayName", ""),
            locale=data.get("locale", ""),
            timezone=data.get("timezone", ""),
            title=data.get("title", ""),
            department=data.get("department", ""),
        )


@dataclass
class SCIMGroupMember:
    """Member reference within a SCIM Group."""
    value: str = ""
    display: str = ""
    ref: str = ""

    def to_dict(self) -> dict:
        return {"value": self.value, "display": self.display, "$ref": self.ref}


@dataclass
class SCIMGroup:
    """SCIM 2.0 Group resource (RFC 7643 §4.2)."""
    id: str = ""
    display_name: str = ""
    members: List[SCIMGroupMember] = field(default_factory=list)
    external_id: str = ""
    meta: SCIMMeta = field(default_factory=lambda: SCIMMeta(resource_type="Group"))

    def to_dict(self) -> dict:
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "id": self.id,
            "displayName": self.display_name,
            "members": [m.to_dict() for m in self.members],
            "externalId": self.external_id,
            "meta": self.meta.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SCIMGroup":
        members = [
            SCIMGroupMember(
                value=m.get("value", ""),
                display=m.get("display", ""),
                ref=m.get("$ref", ""),
            )
            for m in data.get("members", [])
        ]
        meta_data = data.get("meta", {})
        meta = SCIMMeta(
            resource_type=meta_data.get("resourceType", "Group"),
            created=meta_data.get("created", ""),
            last_modified=meta_data.get("lastModified", ""),
            location=meta_data.get("location", ""),
            version=meta_data.get("version", ""),
        )
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            members=members,
            external_id=data.get("externalId", ""),
            meta=meta,
        )


@dataclass
class SCIMPatchOp:
    """Single SCIM PATCH operation (RFC 7644 §3.5.2)."""
    op: str = "replace"  # add | remove | replace
    path: str = ""
    value: Any = None

    def to_dict(self) -> dict:
        d: dict = {"op": self.op}
        if self.path:
            d["path"] = self.path
        if self.value is not None:
            d["value"] = self.value
        return d


@dataclass
class SCIMPatch:
    """SCIM PatchOp request (RFC 7644 §3.5.2)."""
    schemas: List[str] = field(
        default_factory=lambda: ["urn:ietf:params:scim:api:messages:2.0:PatchOp"]
    )
    operations: List[SCIMPatchOp] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SCIMPatch":
        ops = []
        for op_data in data.get("Operations", data.get("operations", [])):
            ops.append(
                SCIMPatchOp(
                    op=op_data.get("op", "replace"),
                    path=op_data.get("path", ""),
                    value=op_data.get("value"),
                )
            )
        return cls(
            schemas=data.get("schemas", []),
            operations=ops,
        )


@dataclass
class SCIMListResponse:
    """SCIM ListResponse (RFC 7644 §3.4.2)."""
    total_results: int = 0
    start_index: int = 1
    items_per_page: int = 100
    resources: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": self.total_results,
            "startIndex": self.start_index,
            "itemsPerPage": self.items_per_page,
            "Resources": self.resources,
        }


# ---------------------------------------------------------------------------
# SCIM Filter Parser (basic: eq, sw, and)
# ---------------------------------------------------------------------------

class SCIMFilterParser:
    """
    Parse basic SCIM filter expressions (RFC 7644 §3.4.2.2).

    Supported operators: eq, sw, co, and.
    Example: 'userName eq "john@example.com" and active eq "true"'
    """

    _PATTERN = re.compile(
        r'(\w[\w.]*)\s+(eq|sw|co|ne|gt|ge|lt|le)\s+"([^"]*)"',
        re.IGNORECASE,
    )
    _AND = re.compile(r"\s+and\s+", re.IGNORECASE)

    def __init__(self, filter_str: str):
        self.filter_str = filter_str
        self.clauses: List[Tuple[str, str, str]] = self._parse()

    def _parse(self) -> List[Tuple[str, str, str]]:
        """Return list of (attr, operator, value) tuples."""
        if not self.filter_str:
            return []
        clauses = []
        parts = self._AND.split(self.filter_str)
        for part in parts:
            m = self._PATTERN.search(part.strip())
            if m:
                clauses.append((m.group(1), m.group(2).lower(), m.group(3)))
        return clauses

    def match(self, resource: dict) -> bool:
        """Test whether a SCIM resource matches all filter clauses."""
        for attr, op, value in self.clauses:
            actual = self._resolve_attr(resource, attr)
            if actual is None:
                return False
            actual_str = str(actual).lower() if not isinstance(actual, bool) else str(actual).lower()
            value_lower = value.lower()
            if op == "eq":
                if actual_str != value_lower:
                    return False
            elif op == "sw":
                if not actual_str.startswith(value_lower):
                    return False
            elif op == "co":
                if value_lower not in actual_str:
                    return False
            elif op == "ne":
                if actual_str == value_lower:
                    return False
            elif op == "gt":
                if actual_str <= value_lower:
                    return False
            elif op == "ge":
                if actual_str < value_lower:
                    return False
            elif op == "lt":
                if actual_str >= value_lower:
                    return False
            elif op == "le":
                if actual_str > value_lower:
                    return False
        return True

    @staticmethod
    def _resolve_attr(resource: dict, attr: str) -> Any:
        """Resolve a dotted attribute path in a SCIM resource dict."""
        parts = attr.split(".")
        current: Any = resource
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current


# ---------------------------------------------------------------------------
# ETag helpers
# ---------------------------------------------------------------------------

def _compute_etag(data: dict) -> str:
    """Compute a weak ETag from resource dict."""
    raw = json.dumps(data, sort_keys=True, default=str).encode()
    return f'W/"{hashlib.sha256(raw).hexdigest()[:16]}"'


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Bearer Token Validator
# ---------------------------------------------------------------------------

class BearerTokenValidator:
    """
    Validate bearer tokens for IdP SCIM calls.

    Supports static tokens and pluggable async validators.
    """

    def __init__(
        self,
        static_tokens: List[str] | None = None,
        validator_fn: Callable[[str], bool] | None = None,
    ):
        self._static_tokens: set[str] = set(static_tokens or [])
        self._validator_fn = validator_fn

    async def validate(self, authorization: str) -> bool:
        """Validate an Authorization header value."""
        if not authorization:
            return False
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        token = parts[1].strip()
        if token in self._static_tokens:
            return True
        if self._validator_fn:
            result = self._validator_fn(token)
            if asyncio.iscoroutine(result):
                return await result
            return bool(result)
        return False

    def add_token(self, token: str) -> None:
        """Register a static bearer token."""
        self._static_tokens.add(token)

    def remove_token(self, token: str) -> None:
        """Revoke a static bearer token."""
        self._static_tokens.discard(token)


# ---------------------------------------------------------------------------
# SCIM Provider
# ---------------------------------------------------------------------------

class SCIMProvider:
    """
    Full SCIM 2.0 provider for enterprise IdP integration.

    Manages user and group lifecycle with ETag-based conflict detection,
    bearer token validation, and GDPR-aware deletion cascading.
    """

    def __init__(
        self,
        base_url: str = "/scim/v2",
        bearer_tokens: List[str] | None = None,
        gdpr_processor: Any | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._users: Dict[str, SCIMUser] = {}
        self._groups: Dict[str, SCIMGroup] = {}
        self._user_etags: Dict[str, str] = {}
        self._group_etags: Dict[str, str] = {}
        self._token_validator = BearerTokenValidator(static_tokens=bearer_tokens)
        self._gdpr_processor = gdpr_processor
        self._deletion_callbacks: List[Callable] = []

    # -- Deletion callback support (GDPR cascade) --------------------------

    def on_user_deleted(self, callback: Callable) -> None:
        """Register a callback triggered when a user is deleted."""
        self._deletion_callbacks.append(callback)

    # -- User operations ----------------------------------------------------

    async def create_user(self, scim_user: SCIMUser) -> SCIMUser:
        """Create a new SCIM user. Returns the created user with server-assigned id."""
        if not scim_user.user_name:
            raise SCIMError(400, "userName is required", "invalidValue")

        # Check uniqueness
        for existing in self._users.values():
            if existing.user_name.lower() == scim_user.user_name.lower():
                raise SCIMError(409, f"User with userName '{scim_user.user_name}' already exists", "uniqueness")

        if not scim_user.id:
            scim_user.id = str(uuid.uuid4())

        now = _now_iso()
        scim_user.meta.created = now
        scim_user.meta.last_modified = now
        scim_user.meta.location = f"{self.base_url}/Users/{scim_user.id}"
        scim_user.meta.resource_type = "User"

        etag = _compute_etag(scim_user.to_dict())
        scim_user.meta.version = etag
        self._users[scim_user.id] = scim_user
        self._user_etags[scim_user.id] = etag
        return scim_user

    async def get_user(self, user_id: str) -> SCIMUser | None:
        """Retrieve a SCIM user by ID. Returns None if not found."""
        return self._users.get(user_id)

    async def update_user(self, user_id: str, patch: SCIMPatch, if_match: str = "") -> SCIMUser:
        """Apply a SCIM PATCH to a user. Supports add/remove/replace operations."""
        user = self._users.get(user_id)
        if not user:
            raise SCIMError(404, f"User '{user_id}' not found")

        # ETag conflict detection
        if if_match and self._user_etags.get(user_id, "") != if_match:
            raise SCIMError(412, "ETag mismatch — resource was modified", "mutability")

        user_dict = user.to_dict()
        for op in patch.operations:
            user_dict = self._apply_patch_op(user_dict, op)

        updated = SCIMUser.from_dict(user_dict)
        updated.id = user_id
        updated.meta.last_modified = _now_iso()
        updated.meta.location = f"{self.base_url}/Users/{user_id}"

        etag = _compute_etag(updated.to_dict())
        updated.meta.version = etag
        self._users[user_id] = updated
        self._user_etags[user_id] = etag
        return updated

    async def delete_user(self, user_id: str) -> None:
        """
        Delete a SCIM user. Triggers GDPR cascade if processor is attached.
        Also removes user from all groups.
        """
        if user_id not in self._users:
            raise SCIMError(404, f"User '{user_id}' not found")

        user = self._users.pop(user_id)
        self._user_etags.pop(user_id, None)

        # Remove from all groups
        for group in self._groups.values():
            group.members = [m for m in group.members if m.value != user_id]

        # GDPR cascade
        if self._gdpr_processor:
            try:
                await self._gdpr_processor.submit_request(
                    user_id=user_id,
                    request_type="delete",
                    email=user.emails[0].value if user.emails else "",
                )
            except Exception:
                pass  # Best-effort GDPR cascade

        # Fire deletion callbacks
        for cb in self._deletion_callbacks:
            try:
                result = cb(user_id, user)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    async def list_users(
        self,
        filter_str: str = "",
        start_index: int = 1,
        count: int = 100,
    ) -> SCIMListResponse:
        """List users with optional SCIM filter, pagination."""
        all_users = [u.to_dict() for u in self._users.values()]

        if filter_str:
            parser = SCIMFilterParser(filter_str)
            all_users = [u for u in all_users if parser.match(u)]

        total = len(all_users)
        # SCIM uses 1-based indexing
        start = max(0, start_index - 1)
        page = all_users[start : start + count]

        return SCIMListResponse(
            total_results=total,
            start_index=start_index,
            items_per_page=len(page),
            resources=page,
        )

    # -- Group operations ---------------------------------------------------

    async def create_group(self, group: SCIMGroup) -> SCIMGroup:
        """Create a new SCIM group."""
        if not group.display_name:
            raise SCIMError(400, "displayName is required", "invalidValue")

        if not group.id:
            group.id = str(uuid.uuid4())

        now = _now_iso()
        group.meta.created = now
        group.meta.last_modified = now
        group.meta.location = f"{self.base_url}/Groups/{group.id}"
        group.meta.resource_type = "Group"

        etag = _compute_etag(group.to_dict())
        group.meta.version = etag
        self._groups[group.id] = group
        self._group_etags[group.id] = etag
        return group

    async def get_group(self, group_id: str) -> SCIMGroup | None:
        """Retrieve a SCIM group by ID."""
        return self._groups.get(group_id)

    async def update_group(self, group_id: str, patch: SCIMPatch, if_match: str = "") -> SCIMGroup:
        """Apply a SCIM PATCH to a group."""
        group = self._groups.get(group_id)
        if not group:
            raise SCIMError(404, f"Group '{group_id}' not found")

        if if_match and self._group_etags.get(group_id, "") != if_match:
            raise SCIMError(412, "ETag mismatch — resource was modified", "mutability")

        group_dict = group.to_dict()
        for op in patch.operations:
            group_dict = self._apply_patch_op(group_dict, op)

        updated = SCIMGroup.from_dict(group_dict)
        updated.id = group_id
        updated.meta.last_modified = _now_iso()
        updated.meta.location = f"{self.base_url}/Groups/{group_id}"

        etag = _compute_etag(updated.to_dict())
        updated.meta.version = etag
        self._groups[group_id] = updated
        self._group_etags[group_id] = etag
        return updated

    async def delete_group(self, group_id: str) -> None:
        """Delete a SCIM group."""
        if group_id not in self._groups:
            raise SCIMError(404, f"Group '{group_id}' not found")
        self._groups.pop(group_id)
        self._group_etags.pop(group_id, None)

    async def list_groups(
        self,
        filter_str: str = "",
        start_index: int = 1,
        count: int = 100,
    ) -> SCIMListResponse:
        """List groups with optional SCIM filter, pagination."""
        all_groups = [g.to_dict() for g in self._groups.values()]

        if filter_str:
            parser = SCIMFilterParser(filter_str)
            all_groups = [g for g in all_groups if parser.match(g)]

        total = len(all_groups)
        start = max(0, start_index - 1)
        page = all_groups[start : start + count]

        return SCIMListResponse(
            total_results=total,
            start_index=start_index,
            items_per_page=len(page),
            resources=page,
        )

    # -- Patch operation application ----------------------------------------

    @staticmethod
    def _apply_patch_op(resource: dict, op: SCIMPatchOp) -> dict:
        """Apply a single SCIM patch operation to a resource dict."""
        operation = op.op.lower()
        path = op.path
        value = op.value

        if operation == "add":
            if path:
                parts = path.split(".")
                target = resource
                for p in parts[:-1]:
                    target = target.setdefault(p, {})
                key = parts[-1]
                if isinstance(target.get(key), list) and isinstance(value, list):
                    target[key].extend(value)
                elif isinstance(target.get(key), list) and isinstance(value, dict):
                    target[key].append(value)
                else:
                    target[key] = value
            elif isinstance(value, dict):
                resource.update(value)
        elif operation == "replace":
            if path:
                parts = path.split(".")
                target = resource
                for p in parts[:-1]:
                    if p in target:
                        target = target[p]
                    else:
                        target[p] = {}
                        target = target[p]
                target[parts[-1]] = value
            elif isinstance(value, dict):
                resource.update(value)
        elif operation == "remove":
            if path:
                parts = path.split(".")
                target = resource
                for p in parts[:-1]:
                    if p in target:
                        target = target[p]
                    else:
                        break
                else:
                    key = parts[-1]
                    # Handle member removal with value filter
                    if isinstance(target.get(key), list) and value:
                        target[key] = [
                            m for m in target[key]
                            if not (isinstance(m, dict) and m.get("value") == value)
                        ]
                    else:
                        target.pop(key, None)
        return resource

    # -- Route registration -------------------------------------------------

    def register_routes(self, app: Any) -> None:
        """
        Mount /scim/v2/* endpoints on a FastAPI app.

        Registers routes for:
          GET/POST /scim/v2/Users
          GET/PATCH/DELETE /scim/v2/Users/{id}
          GET/POST /scim/v2/Groups
          GET/PATCH/DELETE /scim/v2/Groups/{id}
          GET /scim/v2/ServiceProviderConfig
          GET /scim/v2/ResourceTypes
          GET /scim/v2/Schemas
        """
        try:
            from fastapi import Request
            from fastapi.responses import JSONResponse
        except ImportError:
            raise RuntimeError("FastAPI is required for SCIM route registration")

        base = self.base_url

        async def _auth_check(request: Request) -> bool:
            auth = request.headers.get("Authorization", "")
            return await self._token_validator.validate(auth)

        # -- Users --

        @app.post(f"{base}/Users")
        async def scim_create_user(request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            data = await request.json()
            user = SCIMUser.from_dict(data)
            try:
                created = await self.create_user(user)
            except SCIMError as e:
                return JSONResponse(e.to_dict(), e.status)
            return JSONResponse(created.to_dict(), 201, headers={"ETag": created.meta.version})

        @app.get(f"{base}/Users")
        async def scim_list_users(request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            filter_str = request.query_params.get("filter", "")
            start = int(request.query_params.get("startIndex", "1"))
            count = int(request.query_params.get("count", "100"))
            result = await self.list_users(filter_str, start, count)
            return JSONResponse(result.to_dict())

        @app.get(f"{base}/Users/{{user_id}}")
        async def scim_get_user(user_id: str, request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            user = await self.get_user(user_id)
            if not user:
                return JSONResponse(SCIMError(404, "User not found").to_dict(), 404)
            return JSONResponse(user.to_dict(), headers={"ETag": user.meta.version})

        @app.patch(f"{base}/Users/{{user_id}}")
        async def scim_patch_user(user_id: str, request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            data = await request.json()
            patch = SCIMPatch.from_dict(data)
            if_match = request.headers.get("If-Match", "")
            try:
                updated = await self.update_user(user_id, patch, if_match)
            except SCIMError as e:
                return JSONResponse(e.to_dict(), e.status)
            return JSONResponse(updated.to_dict(), headers={"ETag": updated.meta.version})

        @app.delete(f"{base}/Users/{{user_id}}")
        async def scim_delete_user(user_id: str, request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            try:
                await self.delete_user(user_id)
            except SCIMError as e:
                return JSONResponse(e.to_dict(), e.status)
            return JSONResponse(None, 204)

        # -- Groups --

        @app.post(f"{base}/Groups")
        async def scim_create_group(request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            data = await request.json()
            group = SCIMGroup.from_dict(data)
            try:
                created = await self.create_group(group)
            except SCIMError as e:
                return JSONResponse(e.to_dict(), e.status)
            return JSONResponse(created.to_dict(), 201, headers={"ETag": created.meta.version})

        @app.get(f"{base}/Groups")
        async def scim_list_groups(request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            filter_str = request.query_params.get("filter", "")
            start = int(request.query_params.get("startIndex", "1"))
            count = int(request.query_params.get("count", "100"))
            result = await self.list_groups(filter_str, start, count)
            return JSONResponse(result.to_dict())

        @app.get(f"{base}/Groups/{{group_id}}")
        async def scim_get_group(group_id: str, request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            group = await self.get_group(group_id)
            if not group:
                return JSONResponse(SCIMError(404, "Group not found").to_dict(), 404)
            return JSONResponse(group.to_dict(), headers={"ETag": group.meta.version})

        @app.patch(f"{base}/Groups/{{group_id}}")
        async def scim_patch_group(group_id: str, request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            data = await request.json()
            patch = SCIMPatch.from_dict(data)
            if_match = request.headers.get("If-Match", "")
            try:
                updated = await self.update_group(group_id, patch, if_match)
            except SCIMError as e:
                return JSONResponse(e.to_dict(), e.status)
            return JSONResponse(updated.to_dict(), headers={"ETag": updated.meta.version})

        @app.delete(f"{base}/Groups/{{group_id}}")
        async def scim_delete_group(group_id: str, request: Request):
            if not await _auth_check(request):
                return JSONResponse(SCIMError(401, "Unauthorized").to_dict(), 401)
            try:
                await self.delete_group(group_id)
            except SCIMError as e:
                return JSONResponse(e.to_dict(), e.status)
            return JSONResponse(None, 204)

        # -- Discovery endpoints --

        @app.get(f"{base}/ServiceProviderConfig")
        async def scim_service_provider_config():
            return JSONResponse({
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
                "documentationUri": "https://docs.horizon-orchestra.ai/scim",
                "patch": {"supported": True},
                "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
                "filter": {"supported": True, "maxResults": 200},
                "changePassword": {"supported": False},
                "sort": {"supported": False},
                "etag": {"supported": True},
                "authenticationSchemes": [
                    {
                        "type": "oauthbearertoken",
                        "name": "OAuth Bearer Token",
                        "description": "Authentication scheme using OAuth 2.0 Bearer Token",
                    }
                ],
            })

        @app.get(f"{base}/ResourceTypes")
        async def scim_resource_types():
            return JSONResponse({
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                "totalResults": 2,
                "Resources": [
                    {
                        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                        "id": "User",
                        "name": "User",
                        "endpoint": f"{base}/Users",
                        "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
                    },
                    {
                        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
                        "id": "Group",
                        "name": "Group",
                        "endpoint": f"{base}/Groups",
                        "schema": "urn:ietf:params:scim:schemas:core:2.0:Group",
                    },
                ],
            })

        @app.get(f"{base}/Schemas")
        async def scim_schemas():
            return JSONResponse({
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
                "totalResults": 2,
                "Resources": [
                    {
                        "id": "urn:ietf:params:scim:schemas:core:2.0:User",
                        "name": "User",
                        "description": "SCIM 2.0 User Schema",
                    },
                    {
                        "id": "urn:ietf:params:scim:schemas:core:2.0:Group",
                        "name": "Group",
                        "description": "SCIM 2.0 Group Schema",
                    },
                ],
            })
