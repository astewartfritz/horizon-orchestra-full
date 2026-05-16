from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_agent.skills.v2.library import SkillLibraryV2
from code_agent.skills.v2.environment import WebShopEnv


@dataclass
class EvalResult:
    task_instruction: str
    skill_id: int
    skill_body: str
    reward: float
    success: bool
    steps: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_instruction": self.task_instruction,
            "skill_id": self.skill_id,
            "skill_body": self.skill_body[:100],
            "reward": self.reward,
            "success": self.success,
            "steps": self.steps,
            "timestamp": self.timestamp,
        }


class EvalStore:
    def __init__(self, db_path: str | Path = ".agent-skills-eval.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS eval_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_instruction TEXT NOT NULL,
                    skill_id INTEGER NOT NULL,
                    skill_body TEXT NOT NULL DEFAULT '',
                    reward REAL NOT NULL DEFAULT 0.0,
                    success INTEGER NOT NULL DEFAULT 0,
                    steps INTEGER NOT NULL DEFAULT 0,
                    timestamp REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_skill ON eval_results(skill_id)")
            conn.commit()
        finally:
            conn.close()

    def add(self, r: EvalResult) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """INSERT INTO eval_results (task_instruction, skill_id, skill_body, reward, success, steps, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (r.task_instruction, r.skill_id, r.skill_body, r.reward, int(r.success), r.steps, r.timestamp),
            )
            conn.commit()
        finally:
            conn.close()

    def get_results(self, skill_id: int | None = None, limit: int = 100) -> list[EvalResult]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            if skill_id is not None:
                rows = conn.execute(
                    "SELECT * FROM eval_results WHERE skill_id=? ORDER BY timestamp DESC LIMIT ?", (skill_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM eval_results ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._row_to_result(r) for r in rows]
        finally:
            conn.close()

    def skill_stats(self, skill_id: int) -> dict[str, Any]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*), AVG(reward), SUM(success), AVG(CAST(success AS REAL)) FROM eval_results WHERE skill_id=?",
                (skill_id,),
            ).fetchone()
            if row and row[0]:
                return {"count": row[0], "avg_reward": row[1] or 0.0, "successes": row[2] or 0, "success_rate": row[3] or 0.0}
            return {"count": 0, "avg_reward": 0.0, "successes": 0, "success_rate": 0.0}
        finally:
            conn.close()

    def comparison(self) -> list[dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            rows = conn.execute(
                """SELECT skill_id, skill_body, COUNT(*) as n, AVG(reward) as avg_r,
                          SUM(success) as succ, AVG(CAST(success AS REAL)) as avg_s
                   FROM eval_results GROUP BY skill_id ORDER BY avg_r DESC"""
            ).fetchall()
            return [
                {"skill_id": r[0], "skill_body": r[1][:80], "count": r[2], "avg_reward": r[3], "successes": r[4], "success_rate": r[5]}
                for r in rows
            ]
        finally:
            conn.close()

    def _row_to_result(self, row: sqlite3.Row) -> EvalResult:
        return EvalResult(
            task_instruction=row[1], skill_id=row[2], skill_body=row[3],
            reward=row[4], success=bool(row[5]), steps=row[6], timestamp=row[7],
        )


class SkillEvaluator:
    def __init__(self, library: SkillLibraryV2, env: WebShopEnv, eval_store: EvalStore | None = None):
        self.library = library
        self.env = env
        self.store = eval_store or EvalStore()

    async def evaluate_skill(self, skill_id: int, tasks: list[str], seed_base: int = 0) -> list[EvalResult]:
        skill = self.library.get(skill_id)
        if not skill:
            return []
        from code_agent.llm.base import LLM
        from code_agent.skills.v2.policy import MetaPolicy
        llm = LLM(provider="ollama", model="nemotron-mini", timeout=60)
        policy = MetaPolicy(llm)

        results = []
        for i, instruction in enumerate(tasks):
            self.env.reset(instruction)
            obs = self.env._get_obs()
            history: list[str] = []
            steps = 0
            while not self.env.done and steps < 30:
                available = self.env.get_available_actions()
                act_out = await policy.act(
                    task_instruction=instruction,
                    skill_body=skill.body,
                    observation=obs,
                    actions=available,
                    history=history,
                )
                action = act_out.content.strip()
                match = [a for a in available if action.lower() == a.lower() or (a.startswith("search[") and action.startswith("search")) or (a.startswith("click[") and action.startswith("click"))]
                cleaned = match[0] if match else available[0]
                obs, reward, done, info = self.env.step(cleaned)
                history.append(f"{cleaned}")
                steps += 1
            result = EvalResult(
                task_instruction=instruction, skill_id=skill_id,
                skill_body=skill.body, reward=reward,
                success=reward > 0, steps=steps,
            )
            self.store.add(result)
            results.append(result)
        return results

    async def benchmark(self, task_pool: list[str] | None = None) -> dict[str, Any]:
        if task_pool is None:
            task_pool = [
                "Buy a monitor under $300",
                "Find a red dress size M",
                "Buy a premium electronics product",
                "Find a sports item under $100",
                "Buy a book with best rating",
                "Find a basic home product in blue",
                "Buy a laptop under $800",
                "Find a white clothing item size L",
            ]
        all_skills = self.library.list_all(limit=50)
        if not all_skills:
            return {"error": "No skills to evaluate"}
        results_by_skill: dict[int, list[EvalResult]] = {}
        for skill in all_skills[:10]:
            results_by_skill[skill.id] = await self.evaluate_skill(skill.id, task_pool[:4])
        return {
            "skills_evaluated": len(results_by_skill),
            "comparison": self.store.comparison(),
            "total_tasks": len(task_pool),
        }
