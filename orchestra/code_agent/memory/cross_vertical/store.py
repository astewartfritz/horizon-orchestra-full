from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterator

from .entities import CanonicalEntity, EntityFact, EntityRelation, VerticalRef

_DB_PATH = Path.home() / ".orchestra_cv.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _normalize_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit())


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cv_entities (
                id              TEXT PRIMARY KEY,
                entity_type     TEXT NOT NULL,
                canonical_name  TEXT NOT NULL,
                aliases         TEXT NOT NULL DEFAULT '[]',
                metadata        TEXT NOT NULL DEFAULT '{}',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cve_name ON cv_entities(canonical_name);
            CREATE INDEX IF NOT EXISTS idx_cve_type ON cv_entities(entity_type);

            CREATE TABLE IF NOT EXISTS cv_vertical_refs (
                id          TEXT PRIMARY KEY,
                entity_id   TEXT NOT NULL REFERENCES cv_entities(id) ON DELETE CASCADE,
                vertical    TEXT NOT NULL,
                record_type TEXT NOT NULL,
                record_id   TEXT NOT NULL,
                confidence  REAL NOT NULL DEFAULT 1.0,
                evidence    TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                UNIQUE(vertical, record_type, record_id)
            );
            CREATE INDEX IF NOT EXISTS idx_cvvr_entity ON cv_vertical_refs(entity_id);
            CREATE INDEX IF NOT EXISTS idx_cvvr_record ON cv_vertical_refs(vertical, record_type, record_id);

            CREATE TABLE IF NOT EXISTS cv_relations (
                id               TEXT PRIMARY KEY,
                source_entity_id TEXT NOT NULL REFERENCES cv_entities(id) ON DELETE CASCADE,
                target_entity_id TEXT NOT NULL REFERENCES cv_entities(id) ON DELETE CASCADE,
                relation         TEXT NOT NULL,
                weight           REAL NOT NULL DEFAULT 1.0,
                metadata         TEXT NOT NULL DEFAULT '{}',
                created_at       TEXT NOT NULL,
                UNIQUE(source_entity_id, target_entity_id, relation)
            );
            CREATE INDEX IF NOT EXISTS idx_cvrel_src ON cv_relations(source_entity_id);
            CREATE INDEX IF NOT EXISTS idx_cvrel_tgt ON cv_relations(target_entity_id);

            CREATE TABLE IF NOT EXISTS cv_facts (
                id          TEXT PRIMARY KEY,
                entity_id   TEXT NOT NULL REFERENCES cv_entities(id) ON DELETE CASCADE,
                vertical    TEXT NOT NULL,
                fact_type   TEXT NOT NULL,
                content     TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT,
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cvf_entity ON cv_facts(entity_id);
            CREATE INDEX IF NOT EXISTS idx_cvf_vertical ON cv_facts(entity_id, vertical);
        """)


# ── Row helpers ───────────────────────────────────────────────────────────────

def _to_entity(row: sqlite3.Row) -> CanonicalEntity:
    d = dict(row)
    return CanonicalEntity(
        id=d["id"], entity_type=d["entity_type"],
        canonical_name=d["canonical_name"],
        aliases=json.loads(d["aliases"]),
        metadata=json.loads(d["metadata"]),
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


def _to_ref(row: sqlite3.Row) -> VerticalRef:
    d = dict(row)
    return VerticalRef(
        id=d["id"], entity_id=d["entity_id"], vertical=d["vertical"],
        record_type=d["record_type"], record_id=d["record_id"],
        confidence=d["confidence"], evidence=json.loads(d["evidence"]),
        created_at=d["created_at"],
    )


def _to_relation(row: sqlite3.Row) -> EntityRelation:
    d = dict(row)
    return EntityRelation(
        id=d["id"], source_entity_id=d["source_entity_id"],
        target_entity_id=d["target_entity_id"], relation=d["relation"],
        weight=d["weight"], metadata=json.loads(d["metadata"]),
        created_at=d["created_at"],
    )


def _to_fact(row: sqlite3.Row) -> EntityFact:
    d = dict(row)
    return EntityFact(
        id=d["id"], entity_id=d["entity_id"], vertical=d["vertical"],
        fact_type=d["fact_type"], content=json.loads(d["content"]),
        occurred_at=d.get("occurred_at") or "", created_at=d["created_at"],
    )


# ── Store ─────────────────────────────────────────────────────────────────────

class CrossVerticalStore:
    """SQLite-backed store for the cross-vertical knowledge graph."""

    def __init__(self, db_path: Path | None = None) -> None:
        global _DB_PATH
        if db_path is not None:
            _DB_PATH = db_path
        init_db()

    # ── Entities ──────────────────────────────────────────────────────────────

    def upsert_entity(
        self,
        entity_type: str,
        canonical_name: str,
        aliases: list[str] | None = None,
        metadata: dict | None = None,
        entity_id: str | None = None,
    ) -> CanonicalEntity:
        now = _now()
        eid = entity_id or _uuid()
        aliases_json = json.dumps(aliases or [])
        meta_json = json.dumps(metadata or {})
        with _conn() as conn:
            existing = conn.execute(
                "SELECT id FROM cv_entities WHERE id=?", (eid,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE cv_entities
                       SET canonical_name=?, aliases=?, metadata=?, updated_at=?
                       WHERE id=?""",
                    (canonical_name, aliases_json, meta_json, now, eid),
                )
            else:
                conn.execute(
                    """INSERT INTO cv_entities
                       (id, entity_type, canonical_name, aliases, metadata, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (eid, entity_type, canonical_name, aliases_json, meta_json, now, now),
                )
        return self.get_entity(eid)  # type: ignore[return-value]

    def get_entity(self, entity_id: str) -> CanonicalEntity | None:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM cv_entities WHERE id=?", (entity_id,)
            ).fetchone()
        return _to_entity(row) if row else None

    def list_entities(self, entity_type: str | None = None) -> list[CanonicalEntity]:
        with _conn() as conn:
            if entity_type:
                rows = conn.execute(
                    "SELECT * FROM cv_entities WHERE entity_type=? ORDER BY canonical_name",
                    (entity_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cv_entities ORDER BY canonical_name"
                ).fetchall()
        return [_to_entity(r) for r in rows]

    def search_entities(
        self,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        entity_type: str | None = None,
    ) -> list[CanonicalEntity]:
        candidates = self.list_entities(entity_type)
        results: list[CanonicalEntity] = []
        for e in candidates:
            if email and e.metadata.get("email", "").lower() == email.lower():
                results.append(e)
                continue
            if phone and _normalize_phone(e.metadata.get("phone", "")) == _normalize_phone(phone):
                results.append(e)
                continue
            if name:
                all_names = [e.canonical_name] + e.aliases
                if any(_name_similarity(n, name) > 0.82 for n in all_names):
                    results.append(e)
        return results

    # ── Vertical refs ─────────────────────────────────────────────────────────

    def link_vertical_record(
        self,
        entity_id: str,
        vertical: str,
        record_type: str,
        record_id: str,
        confidence: float = 1.0,
        evidence: dict | None = None,
    ) -> VerticalRef:
        now = _now()
        ref_id = _uuid()
        with _conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO cv_vertical_refs
                   (id, entity_id, vertical, record_type, record_id,
                    confidence, evidence, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (ref_id, entity_id, vertical, record_type, record_id,
                 confidence, json.dumps(evidence or {}), now),
            )
        return VerticalRef(
            id=ref_id, entity_id=entity_id, vertical=vertical,
            record_type=record_type, record_id=record_id,
            confidence=confidence, evidence=evidence or {}, created_at=now,
        )

    def get_vertical_refs(self, entity_id: str) -> list[VerticalRef]:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT * FROM cv_vertical_refs WHERE entity_id=?", (entity_id,)
            ).fetchall()
        return [_to_ref(r) for r in rows]

    def find_entity_for_record(
        self, vertical: str, record_type: str, record_id: str
    ) -> CanonicalEntity | None:
        with _conn() as conn:
            row = conn.execute(
                """SELECT entity_id FROM cv_vertical_refs
                   WHERE vertical=? AND record_type=? AND record_id=?""",
                (vertical, record_type, record_id),
            ).fetchone()
        return self.get_entity(row["entity_id"]) if row else None

    # ── Relations ─────────────────────────────────────────────────────────────

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
        metadata: dict | None = None,
    ) -> EntityRelation:
        now = _now()
        rid = _uuid()
        with _conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO cv_relations
                   (id, source_entity_id, target_entity_id, relation,
                    weight, metadata, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (rid, source_id, target_id, relation, weight,
                 json.dumps(metadata or {}), now),
            )
        return EntityRelation(
            id=rid, source_entity_id=source_id, target_entity_id=target_id,
            relation=relation, weight=weight, metadata=metadata or {}, created_at=now,
        )

    def get_relations(self, entity_id: str) -> list[EntityRelation]:
        with _conn() as conn:
            rows = conn.execute(
                """SELECT * FROM cv_relations
                   WHERE source_entity_id=? OR target_entity_id=?""",
                (entity_id, entity_id),
            ).fetchall()
        return [_to_relation(r) for r in rows]

    # ── Facts ─────────────────────────────────────────────────────────────────

    def record_fact(
        self,
        entity_id: str,
        vertical: str,
        fact_type: str,
        content: dict,
        occurred_at: str | None = None,
    ) -> EntityFact:
        now = _now()
        fid = _uuid()
        with _conn() as conn:
            conn.execute(
                """INSERT INTO cv_facts
                   (id, entity_id, vertical, fact_type, content,
                    occurred_at, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (fid, entity_id, vertical, fact_type,
                 json.dumps(content), occurred_at, now),
            )
        return EntityFact(
            id=fid, entity_id=entity_id, vertical=vertical,
            fact_type=fact_type, content=content,
            occurred_at=occurred_at or "", created_at=now,
        )

    def get_facts(
        self,
        entity_id: str,
        vertical: str | None = None,
        fact_type: str | None = None,
    ) -> list[EntityFact]:
        with _conn() as conn:
            if vertical and fact_type:
                rows = conn.execute(
                    """SELECT * FROM cv_facts
                       WHERE entity_id=? AND vertical=? AND fact_type=?
                       ORDER BY occurred_at DESC""",
                    (entity_id, vertical, fact_type),
                ).fetchall()
            elif vertical:
                rows = conn.execute(
                    """SELECT * FROM cv_facts WHERE entity_id=? AND vertical=?
                       ORDER BY occurred_at DESC""",
                    (entity_id, vertical),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cv_facts WHERE entity_id=? ORDER BY occurred_at DESC",
                    (entity_id,),
                ).fetchall()
        return [_to_fact(r) for r in rows]

    # ── Full profile ──────────────────────────────────────────────────────────

    def get_full_profile(self, entity_id: str) -> CanonicalEntity | None:
        entity = self.get_entity(entity_id)
        if not entity:
            return None
        entity.vertical_refs = self.get_vertical_refs(entity_id)
        entity.facts = self.get_facts(entity_id)
        entity.relations = self.get_relations(entity_id)
        return entity

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with _conn() as conn:
            return {
                "entities": conn.execute("SELECT COUNT(*) FROM cv_entities").fetchone()[0],
                "vertical_refs": conn.execute("SELECT COUNT(*) FROM cv_vertical_refs").fetchone()[0],
                "relations": conn.execute("SELECT COUNT(*) FROM cv_relations").fetchone()[0],
                "facts": conn.execute("SELECT COUNT(*) FROM cv_facts").fetchone()[0],
            }
