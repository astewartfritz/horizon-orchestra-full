from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from code_agent.memory.store import MemoryEntity, MemoryStore


@dataclass
class GraphNode:
    entity: MemoryEntity
    memory_count: int = 0
    related: list[tuple[str, str, float]] = field(default_factory=list)


@dataclass
class GraphPath:
    nodes: list[MemoryEntity]
    edges: list[tuple[str, str]]
    total_weight: float = 0.0


class MemoryGraph:
    def __init__(self, store: MemoryStore):
        self.store = store

    def get_node(self, entity_id: int) -> GraphNode | None:
        entities = self.store.get_entities()
        entity = next((e for e in entities if e.id == entity_id), None)
        if not entity:
            return None
        memories = self.store.get_memories_by_entity(entity.name)
        related = self.store.get_related_entities(entity_id)
        return GraphNode(
            entity=entity,
            memory_count=len(memories),
            related=[(r.name, rel, w) for r, rel, w in related],
        )

    def find_path(self, source_name: str, target_name: str, max_depth: int = 4) -> list[GraphPath]:
        all_entities = self.store.get_entities()
        source = next((e for e in all_entities if e.name.lower() == source_name.lower()), None)
        target = next((e for e in all_entities if e.name.lower() == target_name.lower()), None)
        if not source or not target:
            return []

        paths = []
        visited = {source.id}
        self._dfs(source.id, target.id, [source], [], 1.0, visited, paths, max_depth)
        return sorted(paths, key=lambda p: p.total_weight, reverse=True)

    def _dfs(
        self,
        current_id: int,
        target_id: int,
        node_path: list[MemoryEntity],
        edge_path: list[tuple[str, str]],
        weight: float,
        visited: set[int],
        paths: list[GraphPath],
        max_depth: int,
    ) -> None:
        if current_id == target_id:
            paths.append(GraphPath(nodes=list(node_path), edges=list(edge_path), total_weight=weight))
            return
        if len(node_path) >= max_depth:
            return

        related = self.store.get_related_entities(current_id)
        for rel_entity, relation, rel_weight in related:
            if rel_entity.id not in visited:
                visited.add(rel_entity.id)
                node_path.append(rel_entity)
                edge_path.append((relation, rel_entity.name))
                self._dfs(rel_entity.id, target_id, node_path, edge_path, weight * rel_weight, visited, paths, max_depth)
                node_path.pop()
                edge_path.pop()
                visited.discard(rel_entity.id)

    def get_entity_network(self, center_name: str, depth: int = 2) -> dict[str, Any]:
        all_entities = self.store.get_entities()
        center = next((e for e in all_entities if e.name.lower() == center_name.lower()), None)
        if not center:
            return {"center": center_name, "nodes": [], "edges": []}

        nodes: dict[int, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        queue = [(center, 0)]
        visited = {center.id}

        while queue:
            entity, d = queue.pop(0)
            nodes[entity.id] = {
                "name": entity.name,
                "type": entity.entity_type,
                "depth": d,
            }
            if d < depth:
                related = self.store.get_related_entities(entity.id)
                for rel_entity, relation, weight in related:
                    edges.append({
                        "source": entity.name,
                        "target": rel_entity.name,
                        "relation": relation,
                        "weight": weight,
                    })
                    if rel_entity.id not in visited:
                        visited.add(rel_entity.id)
                        queue.append((rel_entity, d + 1))

        return {
            "center": center_name,
            "nodes": list(nodes.values()),
            "edges": edges,
        }

    def auto_link_entities(self) -> int:
        entities = self.store.get_entities()
        linked = 0
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                e1 = entities[i]
                e2 = entities[j]
                if e1.entity_type == e2.entity_type:
                    # Check if they appear together in any memory
                    m1 = set(m.id for m in self.store.get_memories_by_entity(e1.name))
                    m2 = set(m.id for m in self.store.get_memories_by_entity(e2.name))
                    overlap = m1 & m2
                    if overlap:
                        weight = len(overlap) / max(len(m1 | m2), 1)
                        self.store.create_edge(e1.id, e2.id, "co_occurs", weight)
                        linked += 1
        return linked

    def stats(self) -> dict[str, Any]:
        entities = self.store.get_entities()
        by_type: dict[str, int] = {}
        for e in entities:
            by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        return {
            "total_entities": len(entities),
            "by_type": by_type,
        }
