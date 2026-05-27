"""Lightweight hooks called from vertical stores after writes.

All hooks are fire-and-forget: failures are caught and logged so they
never interrupt or roll back the calling vertical operation.
"""
from __future__ import annotations

import logging

from .resolver import EntityResolver
from .store import CrossVerticalStore

_log = logging.getLogger(__name__)
_store: CrossVerticalStore | None = None


def _get_store() -> CrossVerticalStore:
    global _store
    if _store is None:
        _store = CrossVerticalStore()
    return _store


def _resolver() -> EntityResolver:
    return EntityResolver(_get_store())


# ── Legal ─────────────────────────────────────────────────────────────────────

def on_legal_client_created(client) -> None:
    try:
        store = _get_store()
        company = getattr(client, "company", None)
        entity_type = "organization" if company else "person"
        canonical_name = company or client.name
        extra = {"legal_contact_name": client.name} if company else {}
        entity, conf = _resolver()._resolve(
            entity_type=entity_type,
            name=canonical_name,
            email=getattr(client, "email", None),
            phone=getattr(client, "phone", None),
            extra_metadata=extra,
        )
        store.link_vertical_record(
            entity_id=entity.id,
            vertical="legal",
            record_type="client",
            record_id=client.id,
            confidence=conf,
            evidence={"name": client.name, "email": getattr(client, "email", None)},
        )
    except Exception:
        _log.exception("cv_hook: on_legal_client_created failed")


def on_legal_matter_created(matter) -> None:
    try:
        store = _get_store()
        entity = store.find_entity_for_record("legal", "client", matter.client_id)
        if not entity:
            return
        store.record_fact(
            entity_id=entity.id,
            vertical="legal",
            fact_type="matter",
            content={
                "matter_id": matter.id,
                "matter_number": matter.matter_number,
                "title": matter.title,
                "matter_type": matter.matter_type,
                "status": matter.status,
                "hourly_rate": matter.hourly_rate,
            },
            occurred_at=getattr(matter, "opened_date", None),
        )
    except Exception:
        _log.exception("cv_hook: on_legal_matter_created failed")


def on_legal_invoice_created(invoice) -> None:
    try:
        store = _get_store()
        entity = store.find_entity_for_record("legal", "client", invoice.client_id)
        if not entity:
            return
        store.record_fact(
            entity_id=entity.id,
            vertical="legal",
            fact_type="invoice",
            content={
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "subtotal": invoice.subtotal,
                "total": invoice.total,
                "status": invoice.status,
            },
            occurred_at=getattr(invoice, "issue_date", None),
        )
    except Exception:
        _log.exception("cv_hook: on_legal_invoice_created failed")


# ── Healthcare ────────────────────────────────────────────────────────────────

def on_healthcare_patient_created(patient) -> None:
    try:
        store = _get_store()
        name = f"{patient.first_name} {patient.last_name}".strip()
        entity, conf = _resolver().resolve_person(
            name=name,
            email=getattr(patient, "email", None),
            phone=getattr(patient, "phone", None),
            extra_metadata={"dob": getattr(patient, "dob", None)},
        )
        store.link_vertical_record(
            entity_id=entity.id,
            vertical="healthcare",
            record_type="patient",
            record_id=patient.id,
            confidence=conf,
            evidence={"name": name, "email": getattr(patient, "email", None)},
        )
    except Exception:
        _log.exception("cv_hook: on_healthcare_patient_created failed")


def on_healthcare_encounter_created(encounter) -> None:
    try:
        store = _get_store()
        entity = store.find_entity_for_record("healthcare", "patient", encounter.patient_id)
        if not entity:
            return
        soap = getattr(encounter, "soap", None)
        icd10 = []
        cpt = []
        if soap:
            icd10 = [
                c.code if hasattr(c, "code") else str(c)
                for c in (getattr(soap, "icd10_codes", None) or [])
            ]
            cpt = [
                c.code if hasattr(c, "code") else str(c)
                for c in (getattr(soap, "cpt_codes", None) or [])
            ]
        store.record_fact(
            entity_id=entity.id,
            vertical="healthcare",
            fact_type="encounter",
            content={
                "encounter_id": encounter.id,
                "provider": encounter.provider,
                "icd10_codes": icd10,
                "cpt_codes": cpt,
            },
            occurred_at=getattr(encounter, "date", None),
        )
    except Exception:
        _log.exception("cv_hook: on_healthcare_encounter_created failed")


def on_healthcare_claim_created(claim) -> None:
    try:
        store = _get_store()
        entity = store.find_entity_for_record("healthcare", "patient", claim.patient_id)
        if not entity:
            return
        store.record_fact(
            entity_id=entity.id,
            vertical="healthcare",
            fact_type="claim",
            content={
                "claim_id": claim.id,
                "diagnosis_codes": getattr(claim, "diagnosis_codes", []),
                "total_charge": getattr(claim, "total_charge", 0.0),
                "status": claim.status,
                "insurance_name": getattr(claim, "insurance_name", ""),
            },
            occurred_at=getattr(claim, "date_of_service", None),
        )
    except Exception:
        _log.exception("cv_hook: on_healthcare_claim_created failed")


# ── Finance ───────────────────────────────────────────────────────────────────

def on_finance_account_created(account) -> None:
    try:
        store = _get_store()
        entity, conf = _resolver().resolve_organization(
            name=account.name,
            extra_metadata={
                "account_code": getattr(account, "code", None),
                "account_type": getattr(account, "type", None),
            },
        )
        store.link_vertical_record(
            entity_id=entity.id,
            vertical="finance",
            record_type="account",
            record_id=account.id,
            confidence=conf,
            evidence={"name": account.name},
        )
    except Exception:
        _log.exception("cv_hook: on_finance_account_created failed")


def on_finance_transaction_created(transaction) -> None:
    try:
        store = _get_store()
        for entry in getattr(transaction, "entries", []):
            entity = store.find_entity_for_record(
                "finance", "account", entry.account_id
            )
            if not entity:
                continue
            store.record_fact(
                entity_id=entity.id,
                vertical="finance",
                fact_type="transaction",
                content={
                    "transaction_id": transaction.id,
                    "description": transaction.description,
                    "amount": entry.amount,
                    "direction": entry.direction,
                    "tags": getattr(transaction, "tags", []),
                },
                occurred_at=getattr(transaction, "date", None),
            )
    except Exception:
        _log.exception("cv_hook: on_finance_transaction_created failed")


# ── Logistics ─────────────────────────────────────────────────────────────────

def on_logistics_shipment_created(status) -> None:
    try:
        store = _get_store()
        carrier_name = getattr(status, "carrier", "Unknown")
        entity, conf = _resolver().resolve_organization(
            name=carrier_name,
            extra_metadata={"role": "carrier"},
        )
        store.link_vertical_record(
            entity_id=entity.id,
            vertical="logistics",
            record_type="shipment",
            record_id=status.tracking_number,
            confidence=conf,
            evidence={"carrier": carrier_name},
        )
        mode = status.mode
        store.record_fact(
            entity_id=entity.id,
            vertical="logistics",
            fact_type="shipment",
            content={
                "tracking_number": status.tracking_number,
                "mode": mode.value if hasattr(mode, "value") else str(mode),
                "origin": status.origin,
                "destination": status.destination,
                "current_status": status.current_status,
            },
            occurred_at=getattr(status, "estimated_delivery", None),
        )
    except Exception:
        _log.exception("cv_hook: on_logistics_shipment_created failed")
