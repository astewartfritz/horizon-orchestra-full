from __future__ import annotations

from .entities import CanonicalEntity
from .store import CrossVerticalStore, _name_similarity, _normalize_phone

# Confidence thresholds for individual signal types
_CONF_EMAIL = 0.95
_CONF_PHONE = 0.90
_CONF_NAME = 0.72

# Minimum total confidence to accept an existing entity as a match
_ACCEPT_THRESHOLD = 0.72


class EntityResolver:
    """Resolves incoming vertical records to canonical entities.

    Finds the best-matching existing entity by scoring email, phone, and
    name signals. Creates a new entity when no match clears the threshold.
    """

    def __init__(self, store: CrossVerticalStore) -> None:
        self._store = store

    def resolve_person(
        self,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        extra_metadata: dict | None = None,
    ) -> tuple[CanonicalEntity, float]:
        """Return (canonical_entity, match_confidence). Creates if no match."""
        return self._resolve("person", name, email, phone, extra_metadata)

    def resolve_organization(
        self,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        extra_metadata: dict | None = None,
    ) -> tuple[CanonicalEntity, float]:
        return self._resolve("organization", name, email, phone, extra_metadata)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _resolve(
        self,
        entity_type: str,
        name: str,
        email: str | None,
        phone: str | None,
        extra_metadata: dict | None,
    ) -> tuple[CanonicalEntity, float]:
        best: CanonicalEntity | None = None
        best_conf = 0.0

        for candidate in self._store.list_entities(entity_type):
            conf, _ = self._score(candidate, name, email, phone)
            if conf > best_conf:
                best_conf = conf
                best = candidate

        if best is not None and best_conf >= _ACCEPT_THRESHOLD:
            # Enrich the match with any new signals
            meta = best.metadata.copy()
            if email and not meta.get("email"):
                meta["email"] = email
            if phone and not meta.get("phone"):
                meta["phone"] = phone
            if extra_metadata:
                meta.update(extra_metadata)
            aliases = best.aliases[:]
            if name != best.canonical_name and name not in aliases:
                aliases.append(name)
            self._store.upsert_entity(
                entity_type=entity_type,
                canonical_name=best.canonical_name,
                aliases=aliases,
                metadata=meta,
                entity_id=best.id,
            )
            return self._store.get_entity(best.id), best_conf  # type: ignore[return-value]

        # No match — create new canonical entity
        meta: dict = {}
        if email:
            meta["email"] = email
        if phone:
            meta["phone"] = phone
        if extra_metadata:
            meta.update(extra_metadata)
        entity = self._store.upsert_entity(
            entity_type=entity_type,
            canonical_name=name,
            metadata=meta,
        )
        return entity, 1.0

    def _score(
        self,
        candidate: CanonicalEntity,
        name: str,
        email: str | None,
        phone: str | None,
    ) -> tuple[float, dict]:
        evidence: dict[str, float] = {}
        confidence = 0.0

        if email and candidate.metadata.get("email"):
            if candidate.metadata["email"].lower() == email.lower():
                evidence["email"] = _CONF_EMAIL
                confidence = max(confidence, _CONF_EMAIL)

        if phone and candidate.metadata.get("phone"):
            cand_phone = _normalize_phone(candidate.metadata["phone"])
            if cand_phone and cand_phone == _normalize_phone(phone):
                evidence["phone"] = _CONF_PHONE
                confidence = max(confidence, _CONF_PHONE)

        all_names = [candidate.canonical_name] + candidate.aliases
        best_sim = max(_name_similarity(n, name) for n in all_names)
        if best_sim > 0.82:
            name_conf = _CONF_NAME * best_sim
            evidence["name"] = name_conf
            confidence = max(confidence, name_conf)

        if len(evidence) >= 2:
            confidence = min(confidence + 0.05, 0.99)

        return confidence, evidence
