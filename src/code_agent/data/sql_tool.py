from __future__ import annotations

import sqlite3
from typing import Any

from code_agent.tools.base import Tool, ToolResult, ToolSpec


class SqlTool(Tool):
    spec = ToolSpec(
        name="sql",
        description="Run SQL queries against a SQLite database file. Supports SELECT, INSERT, UPDATE, DELETE, CREATE, and DDL statements.",
        parameters={
            "query": {"type": "string", "description": "SQL query to execute"},
            "db_path": {"type": "string", "description": "Path to SQLite database file", "default": ":memory:"},
            "params": {"type": "string", "description": "JSON array of positional parameters", "default": "[]"},
            "fetch": {"type": "string", "description": "all|one|none", "default": "all"},
        },
    )

    async def __call__(
        self, query: str,
        db_path: str = ":memory:",
        params: str = "[]",
        fetch: str = "all",
    ) -> ToolResult:
        import json
        try:
            parsed_params: list[Any] = json.loads(params) if params else []
        except json.JSONDecodeError:
            return ToolResult(error="Invalid params JSON")

        try:
            conn = sqlite3.connect(db_path if db_path != ":memory:" else ":memory:")
            cur = conn.cursor()
            cur.execute(query, parsed_params)

            q_upper = query.strip().upper()
            if q_upper.startswith("SELECT") or q_upper.startswith("PRAGMA") or q_upper.startswith("EXPLAIN"):
                if fetch == "one":
                    rows = cur.fetchone()
                    if rows:
                        cols = [desc[0] for desc in cur.description]
                        output = f"Columns: {cols}\nRow: {list(rows)}"
                    else:
                        output = "(empty)"
                else:
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description]
                    output = f"Columns: {cols}\nRows: {len(rows)}\n"
                    for r in rows[:50]:
                        output += f"  {list(r)}\n"
                    if len(rows) > 50:
                        output += f"  ... ({len(rows) - 50} more rows)"
            else:
                conn.commit()
                output = f"OK. Rows affected: {cur.rowcount}"

            conn.close()
            return ToolResult(output=output)

        except sqlite3.Error as e:
            return ToolResult(error=f"SQL error: {e}")
        except Exception as e:
            return ToolResult(error=str(e))
