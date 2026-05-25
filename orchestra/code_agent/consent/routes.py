"""Consent document trail API."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import Depends, FastAPI, HTTPException, Request

from orchestra.code_agent.consent import store
from orchestra.code_agent.rbac.deps import require_perm
from orchestra.code_agent.rbac.roles import Perm


def register_consent_routes(app: FastAPI) -> None:
    store.init_db()

    @app.get("/api/consent/types")
    async def document_types():
        return store.DOCUMENT_TYPES

    @app.post("/api/consent/sign")
    async def sign_document(body: dict, request: Request):
        """
        Record a signed consent document.

        Required body fields:
          doc_type, doc_version, content, resource_id, resource_type, signer_user_id
        """
        required = ("doc_type", "doc_version", "content", "resource_id", "resource_type", "signer_user_id")
        missing = [k for k in required if not body.get(k)]
        if missing:
            raise HTTPException(400, f"Missing required fields: {missing}")
        if body["doc_type"] not in store.DOCUMENT_TYPES:
            raise HTTPException(400, f"Unknown doc_type. Valid: {list(store.DOCUMENT_TYPES)}")

        doc = store.record_consent(
            doc_type=body["doc_type"],
            doc_version=body["doc_version"],
            content=body["content"],
            resource_id=body["resource_id"],
            resource_type=body["resource_type"],
            signer_user_id=body["signer_user_id"],
            signer_name=body.get("signer_name", ""),
            signer_ip=request.client.host if request.client else "",
            signer_ua=request.headers.get("user-agent", ""),
            expiry_days=body.get("expiry_days"),
            metadata=body.get("metadata"),
        )
        return asdict(doc)

    @app.get("/api/consent/documents")
    async def list_documents(
        resource_id: str = "",
        resource_type: str = "",
        signer_user_id: str = "",
        doc_type: str = "",
        status: str = "",
        limit: int = 100,
        _uid=Depends(require_perm(Perm.CONSENT_MANAGE)),
    ):
        docs = store.list_consents(
            resource_id=resource_id,
            resource_type=resource_type,
            signer_user_id=signer_user_id,
            doc_type=doc_type,
            status=status,
            limit=limit,
        )
        return [asdict(d) for d in docs]

    @app.get("/api/consent/documents/{consent_id}")
    async def get_document(
        consent_id: str,
        _uid=Depends(require_perm(Perm.CONSENT_MANAGE)),
    ):
        doc = store.get_consent(consent_id)
        if not doc:
            raise HTTPException(404, "Consent document not found")
        return asdict(doc)

    @app.post("/api/consent/documents/{consent_id}/revoke")
    async def revoke_document(
        consent_id: str,
        body: dict,
        _uid=Depends(require_perm(Perm.CONSENT_MANAGE)),
    ):
        doc = store.revoke_consent(
            consent_id,
            revoked_by=body.get("revoked_by", ""),
            reason=body.get("reason", ""),
        )
        if not doc:
            raise HTTPException(404, "Consent document not found")
        return asdict(doc)

    @app.get("/api/consent/check")
    async def check_consent(resource_id: str, doc_type: str):
        """Check whether a resource has an active, non-expired consent of a given type."""
        if doc_type not in store.DOCUMENT_TYPES:
            raise HTTPException(400, f"Unknown doc_type")
        return {
            "resource_id": resource_id,
            "doc_type": doc_type,
            "has_active_consent": store.has_active_consent(resource_id, doc_type),
        }
