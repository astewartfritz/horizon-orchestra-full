from .entities import CanonicalEntity, EntityFact, EntityRelation, VerticalRef
from .graph import CrossVerticalGraph, EntityPath
from .hooks import (
    on_finance_account_created,
    on_finance_transaction_created,
    on_healthcare_claim_created,
    on_healthcare_encounter_created,
    on_healthcare_patient_created,
    on_legal_client_created,
    on_legal_invoice_created,
    on_legal_matter_created,
    on_logistics_shipment_created,
)
from .resolver import EntityResolver
from .routes import register_cross_vertical_routes
from .store import CrossVerticalStore

__all__ = [
    "CanonicalEntity", "EntityFact", "EntityRelation", "VerticalRef",
    "CrossVerticalStore", "EntityResolver",
    "CrossVerticalGraph", "EntityPath",
    "register_cross_vertical_routes",
    "on_legal_client_created", "on_legal_matter_created", "on_legal_invoice_created",
    "on_healthcare_patient_created", "on_healthcare_encounter_created",
    "on_healthcare_claim_created",
    "on_finance_account_created", "on_finance_transaction_created",
    "on_logistics_shipment_created",
]
