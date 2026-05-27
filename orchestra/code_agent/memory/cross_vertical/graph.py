from __future__ import annotations

from dataclasses import dataclass, field

from .entities import CanonicalEntity, EntityRelation
from .store import CrossVerticalStore


@dataclass
class EntityPath:
    nodes: list[CanonicalEntity]
    edges: list[EntityRelation]
    total_weight: float = field(default=0.0)


class CrossVerticalGraph:
    """Traversal queries that span multiple domain verticals."""

    def __init__(self, store: CrossVerticalStore) -> None:
        self._store = store

    # ── Profile ───────────────────────────────────────────────────────────────

    def get_profile(self, entity_id: str) -> dict | None:
        """Full cross-vertical profile: identity + vertical records + facts + relations."""
        entity = self._store.get_full_profile(entity_id)
        if not entity:
            return None

        facts_by_vertical: dict[str, list[dict]] = {}
        for fact in entity.facts:
            facts_by_vertical.setdefault(fact.vertical, []).append({
                "type": fact.fact_type,
                "content": fact.content,
                "occurred_at": fact.occurred_at,
            })

        refs_by_vertical: dict[str, list[dict]] = {}
        for ref in entity.vertical_refs:
            refs_by_vertical.setdefault(ref.vertical, []).append({
                "record_type": ref.record_type,
                "record_id": ref.record_id,
                "confidence": ref.confidence,
            })

        relations = []
        for r in entity.relations:
            outbound = r.source_entity_id == entity_id
            other_id = r.target_entity_id if outbound else r.source_entity_id
            other = self._store.get_entity(other_id)
            relations.append({
                "relation": r.relation,
                "direction": "outbound" if outbound else "inbound",
                "other_entity_id": other_id,
                "other_entity_name": other.canonical_name if other else None,
                "weight": r.weight,
            })

        return {
            "entity": {
                "id": entity.id,
                "type": entity.entity_type,
                "name": entity.canonical_name,
                "aliases": entity.aliases,
                "metadata": entity.metadata,
                "created_at": entity.created_at,
            },
            "verticals": refs_by_vertical,
            "facts": facts_by_vertical,
            "relations": relations,
            "summary": self._summarize(entity, refs_by_vertical, facts_by_vertical),
        }

    # ── Connection finding ────────────────────────────────────────────────────

    def find_connection(
        self, source_id: str, target_id: str, max_depth: int = 4
    ) -> list[EntityPath]:
        """BFS — all paths between two entities up to max_depth hops."""
        if source_id == target_id:
            return []

        found: list[EntityPath] = []
        # Each queue item: (path_of_ids, accumulated_edges, total_weight)
        queue: list[tuple[list[str], list[EntityRelation], float]] = [
            ([source_id], [], 0.0)
        ]
        visited_sets: set[tuple[str, ...]] = set()

        while queue:
            path_ids, path_edges, weight = queue.pop(0)
            if len(path_ids) > max_depth + 1:
                continue
            current_id = path_ids[-1]
            key = tuple(sorted(path_ids))
            if key in visited_sets:
                continue
            visited_sets.add(key)

            for rel in self._store.get_relations(current_id):
                neighbor_id = (
                    rel.target_entity_id
                    if rel.source_entity_id == current_id
                    else rel.source_entity_id
                )
                if neighbor_id in path_ids:
                    continue
                new_ids = path_ids + [neighbor_id]
                new_edges = path_edges + [rel]
                new_weight = weight + rel.weight
                if neighbor_id == target_id:
                    nodes = [self._store.get_entity(eid) for eid in new_ids]
                    found.append(EntityPath(
                        nodes=[n for n in nodes if n is not None],
                        edges=new_edges,
                        total_weight=new_weight,
                    ))
                else:
                    queue.append((new_ids, new_edges, new_weight))

        return sorted(found, key=lambda p: -p.total_weight)

    # ── Network ───────────────────────────────────────────────────────────────

    def get_network(self, entity_id: str, depth: int = 2) -> dict:
        """Return the neighborhood sub-graph up to `depth` hops."""
        visited: set[str] = set()
        nodes: list[dict] = []
        edges: list[dict] = []

        def _traverse(eid: str, remaining: int) -> None:
            if eid in visited or remaining < 0:
                return
            visited.add(eid)
            entity = self._store.get_entity(eid)
            if not entity:
                return
            nodes.append({
                "id": entity.id,
                "name": entity.canonical_name,
                "type": entity.entity_type,
            })
            for rel in self._store.get_relations(eid):
                edge_key = f"{rel.source_entity_id}:{rel.target_entity_id}:{rel.relation}"
                if not any(
                    e["source"] == rel.source_entity_id
                    and e["target"] == rel.target_entity_id
                    and e["relation"] == rel.relation
                    for e in edges
                ):
                    edges.append({
                        "source": rel.source_entity_id,
                        "target": rel.target_entity_id,
                        "relation": rel.relation,
                        "weight": rel.weight,
                    })
                neighbor = (
                    rel.target_entity_id
                    if rel.source_entity_id == eid
                    else rel.source_entity_id
                )
                _traverse(neighbor, remaining - 1)

        _traverse(entity_id, depth)
        return {"nodes": nodes, "edges": edges}

    # ── Summary ───────────────────────────────────────────────────────────────

    def _summarize(
        self,
        entity: CanonicalEntity,
        refs_by_vertical: dict[str, list[dict]],
        facts_by_vertical: dict[str, list[dict]],
    ) -> str:
        parts = [f"{entity.canonical_name} ({entity.entity_type})"]
        for vertical, refs in refs_by_vertical.items():
            types = {r["record_type"] for r in refs}
            parts.append(f"  {vertical}: {', '.join(sorted(types))} ({len(refs)} record(s))")
        for vertical, facts in facts_by_vertical.items():
            if vertical not in refs_by_vertical:
                types = {f["type"] for f in facts}
                parts.append(f"  {vertical}: {', '.join(sorted(types))} ({len(facts)} fact(s))")
        return "\n".join(parts)
