from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .graph import CrossVerticalGraph
from .resolver import EntityResolver
from .store import CrossVerticalStore

_store: CrossVerticalStore | None = None


def _get_store() -> CrossVerticalStore:
    global _store
    if _store is None:
        _store = CrossVerticalStore()
    return _store


# ── Request/Response models ───────────────────────────────────────────────────

class CreateEntityBody(BaseModel):
    entity_type: str                    # 'person' | 'organization' | 'asset'
    canonical_name: str
    aliases: list[str] = []
    metadata: dict[str, Any] = {}


class AddRelationBody(BaseModel):
    relation: str
    weight: float = 1.0
    metadata: dict[str, Any] = {}


class ResolveBody(BaseModel):
    entity_type: str = "person"
    name: str
    email: str | None = None
    phone: str | None = None
    metadata: dict[str, Any] = {}


# ── Route registration ────────────────────────────────────────────────────────

def register_cross_vertical_routes(app: FastAPI) -> None:

    @app.get("/api/memory/entities")
    def list_entities(
        entity_type: str | None = Query(None),
        name: str | None = Query(None),
        email: str | None = Query(None),
        phone: str | None = Query(None),
    ):
        store = _get_store()
        if name or email or phone:
            return store.search_entities(
                name=name, email=email, phone=phone, entity_type=entity_type
            )
        return store.list_entities(entity_type=entity_type)

    @app.post("/api/memory/entities")
    def create_entity(body: CreateEntityBody):
        store = _get_store()
        return store.upsert_entity(
            entity_type=body.entity_type,
            canonical_name=body.canonical_name,
            aliases=body.aliases,
            metadata=body.metadata,
        )

    @app.post("/api/memory/entities/resolve")
    def resolve_entity(body: ResolveBody):
        store = _get_store()
        resolver = EntityResolver(store)
        entity, confidence = resolver._resolve(
            entity_type=body.entity_type,
            name=body.name,
            email=body.email,
            phone=body.phone,
            extra_metadata=body.metadata or None,
        )
        return {"entity": entity, "confidence": confidence}

    @app.get("/api/memory/entities/{entity_id}")
    def get_entity_profile(entity_id: str):
        graph = CrossVerticalGraph(_get_store())
        profile = graph.get_profile(entity_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Entity not found")
        return profile

    @app.get("/api/memory/entities/{entity_id}/network")
    def get_entity_network(entity_id: str, depth: int = Query(2, ge=1, le=4)):
        store = _get_store()
        if not store.get_entity(entity_id):
            raise HTTPException(status_code=404, detail="Entity not found")
        return CrossVerticalGraph(store).get_network(entity_id, depth=depth)

    @app.get("/api/memory/entities/{entity_id}/facts")
    def get_entity_facts(
        entity_id: str,
        vertical: str | None = Query(None),
        fact_type: str | None = Query(None),
    ):
        store = _get_store()
        if not store.get_entity(entity_id):
            raise HTTPException(status_code=404, detail="Entity not found")
        return store.get_facts(entity_id, vertical=vertical, fact_type=fact_type)

    @app.post("/api/memory/entities/{source_id}/relations/{target_id}")
    def add_relation(source_id: str, target_id: str, body: AddRelationBody):
        store = _get_store()
        if not store.get_entity(source_id):
            raise HTTPException(status_code=404, detail="Source entity not found")
        if not store.get_entity(target_id):
            raise HTTPException(status_code=404, detail="Target entity not found")
        return store.add_relation(
            source_id=source_id,
            target_id=target_id,
            relation=body.relation,
            weight=body.weight,
            metadata=body.metadata,
        )

    @app.get("/api/memory/entities/{source_id}/connections/{target_id}")
    def find_connection(
        source_id: str, target_id: str, max_depth: int = Query(4, ge=1, le=6)
    ):
        store = _get_store()
        paths = CrossVerticalGraph(store).find_connection(
            source_id, target_id, max_depth=max_depth
        )
        return {
            "paths_found": len(paths),
            "paths": [
                {
                    "nodes": [
                        {"id": n.id, "name": n.canonical_name, "type": n.entity_type}
                        for n in p.nodes
                    ],
                    "edges": [
                        {"relation": e.relation, "weight": e.weight}
                        for e in p.edges
                    ],
                    "total_weight": p.total_weight,
                }
                for p in paths
            ],
        }

    @app.get("/api/memory/stats")
    def get_stats():
        return _get_store().stats()
