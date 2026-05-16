from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from code_agent.skills.models import Skill, Embedder


class SkillStore:
    def __init__(self, db_path: str | Path = ".agent-skills.db", embedder: Embedder | None = None):
        self.db_path = Path(db_path)
        self.embedder = embedder or Embedder()
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    body TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    embedding TEXT,
                    creation_step INTEGER NOT NULL DEFAULT 0,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    total_reward REAL NOT NULL DEFAULT 0.0,
                    environments TEXT NOT NULL DEFAULT '[]',
                    parent_id INTEGER,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_usage ON skills(usage_count DESC)")
            conn.commit()
        finally:
            conn.close()

    def add(self, skill: Skill) -> int:
        if not skill.embedding:
            skill.embedding = self.embedder.embed(skill.body)
        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.execute(
                """INSERT INTO skills (body, tags, embedding, creation_step, usage_count, success_count, total_reward, environments, parent_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (skill.body, json.dumps(skill.tags), json.dumps(skill.embedding) if skill.embedding else None, skill.creation_step, skill.usage_count, skill.success_count, skill.total_reward, json.dumps(skill.environments), skill.parent_id, skill.created_at, skill.updated_at),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def get(self, skill_id: int) -> Skill | None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
            return self._row_to_skill(row) if row else None
        finally:
            conn.close()

    def update(self, skill: Skill) -> bool:
        skill.updated_at = time.time()
        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.execute(
                """UPDATE skills SET body=?, tags=?, embedding=?, creation_step=?, usage_count=?, success_count=?, total_reward=?, environments=?, parent_id=?, updated_at=? WHERE id=?""",
                (skill.body, json.dumps(skill.tags), json.dumps(skill.embedding) if skill.embedding else None, skill.creation_step, skill.usage_count, skill.success_count, skill.total_reward, json.dumps(skill.environments), skill.parent_id, skill.updated_at, skill.id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def remove(self, skill_id: int) -> bool:
        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_all(self, limit: int = 100) -> list[Skill]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute("SELECT * FROM skills ORDER BY usage_count DESC LIMIT ?", (limit,)).fetchall()
            return [self._row_to_skill(r) for r in rows]
        finally:
            conn.close()

    def count(self) -> int:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute("SELECT COUNT(*) FROM skills").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def record_usage(self, skill_id: int, reward: float, success: bool, env: str = "") -> None:
        s = self.get(skill_id)
        if not s:
            return
        s.usage_count += 1
        s.total_reward += reward
        if success:
            s.success_count += 1
        if env and env not in s.environments:
            s.environments.append(env)
        self.update(s)

    def stats(self) -> dict[str, Any]:
        all_skills = self.list_all(limit=1000)
        if not all_skills:
            return {"count": 0}
        rewards = [s.avg_reward for s in all_skills]
        rates = [s.success_rate for s in all_skills if s.usage_count > 0]
        return {"count": len(all_skills), "avg_reward": sum(rewards) / len(rewards), "avg_success_rate": sum(rates) / len(rates) if rates else 0.0, "total_usage": sum(s.usage_count for s in all_skills), "total_successes": sum(s.success_count for s in all_skills)}

    def _row_to_skill(self, row: sqlite3.Row) -> Skill:
        return Skill(id=row[0], body=row[1], tags=json.loads(row[2]) if row[2] else [], embedding=json.loads(row[3]) if row[3] else None, creation_step=row[4], usage_count=row[5], success_count=row[6], total_reward=row[7], environments=json.loads(row[8]) if row[8] else [], parent_id=row[9], created_at=row[10], updated_at=row[11])
