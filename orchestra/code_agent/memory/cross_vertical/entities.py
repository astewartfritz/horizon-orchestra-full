from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerticalRef:
    """A reference to a record in one of the domain verticals."""
    id: str
    entity_id: str
    vertical: str       # 'legal' | 'healthcare' | 'finance' | 'logistics'
    record_type: str    # 'client' | 'patient' | 'account' | 'shipment' | ...
    record_id: str
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class EntityFact:
    """A timestamped observation about an entity from any vertical."""
    id: str
    entity_id: str
    vertical: str
    fact_type: str      # 'matter' | 'claim' | 'transaction' | 'shipment' | ...
    content: dict[str, Any] = field(default_factory=dict)
    occurred_at: str = ""
    created_at: str = ""


@dataclass
class EntityRelation:
    """A typed, weighted relationship between two canonical entities."""
    id: str
    source_entity_id: str
    target_entity_id: str
    relation: str       # 'represents' | 'employed_by' | 'is_client_of' | ...
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class CanonicalEntity:
    """A unified cross-vertical entity (person, organization, or asset)."""
    id: str
    entity_type: str    # 'person' | 'organization' | 'asset'
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    # Populated by profile queries — not columns in the entities table
    vertical_refs: list[VerticalRef] = field(default_factory=list)
    facts: list[EntityFact] = field(default_factory=list)
    relations: list[EntityRelation] = field(default_factory=list)
