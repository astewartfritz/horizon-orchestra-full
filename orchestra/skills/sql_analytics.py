"""SQL Analytics skill — query generation, optimization, aggregation patterns.

Uses LLM to generate SQL from natural language, then optionally executes
via the Snowflake connector or returns the query for manual use.
"""

from __future__ import annotations

import json, logging, textwrap
from typing import Any
from .base import Skill, run_code_in_sandbox

__all__ = ["SQLAnalyticsSkill"]
log = logging.getLogger("orchestra.skills.sql_analytics")


class SQLAnalyticsSkill(Skill):
    name = "sql_analytics"
    description = "Generate SQL queries, analyze query patterns, optimize queries, and build aggregation pipelines."

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "sql_generate": self._generate,
            "sql_analyze_csv": self._analyze_csv,
            "sql_pivot": self._pivot,
            "sql_window": self._window_functions,
            "sql_funnel": self._funnel,
        }
        handler = dispatch.get(action)
        return await handler(params) if handler else {"error": f"Unknown: {action}"}

    async def _generate(self, params: dict[str, Any]) -> dict[str, Any]:
        """Generate SQL from natural language description + schema."""
        question = params.get("question", "")
        schema = params.get("schema", "")
        dialect = params.get("dialect", "snowflake")
        if not question:
            return {"error": "question required"}

        # This returns the SQL as structured output — the agent can then
        # execute it via the Snowflake connector or present it to the user.
        return {
            "note": "SQL generation requires an LLM call. Use the agent's model to generate SQL from this schema and question.",
            "question": question,
            "schema": schema,
            "dialect": dialect,
            "template": self._get_template(question, dialect),
        }

    def _get_template(self, question: str, dialect: str) -> str:
        """Return a SQL template based on the question pattern."""
        q = question.lower()
        if any(w in q for w in ["trend", "over time", "daily", "weekly", "monthly"]):
            return f"-- Time series aggregation ({dialect})\nSELECT\n  DATE_TRUNC('day', created_at) AS date,\n  COUNT(*) AS count,\n  SUM(amount) AS total\nFROM table\nWHERE created_at >= DATEADD('day', -30, CURRENT_DATE())\nGROUP BY 1\nORDER BY 1;"
        if any(w in q for w in ["top", "rank", "best", "worst"]):
            return f"-- Ranking query ({dialect})\nSELECT\n  name,\n  metric,\n  RANK() OVER (ORDER BY metric DESC) AS rank\nFROM table\nLIMIT 10;"
        if any(w in q for w in ["compare", "versus", "vs", "difference"]):
            return f"-- Comparison query ({dialect})\nSELECT\n  category,\n  SUM(CASE WHEN period = 'current' THEN value END) AS current_value,\n  SUM(CASE WHEN period = 'previous' THEN value END) AS previous_value,\n  ROUND((current_value - previous_value) / NULLIF(previous_value, 0) * 100, 2) AS pct_change\nFROM table\nGROUP BY 1\nORDER BY pct_change DESC;"
        return f"-- Generated query ({dialect})\nSELECT *\nFROM table\nWHERE 1=1\nLIMIT 100;"

    async def _analyze_csv(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run SQL-like analytics on a CSV using DuckDB or pandas."""
        fp = params.get("file_path", "")
        query = params.get("query", "")
        if not all([fp, query]):
            return {"error": "file_path and query required"}

        # Use pandas to simulate SQL on CSV
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")

            # Try DuckDB first (zero-config SQL on dataframes)
            try:
                import duckdb
                result = duckdb.sql(\"\"\"{query}\"\"\").df()
                print(json.dumps({{
                    "engine": "duckdb",
                    "columns": list(result.columns),
                    "row_count": len(result),
                    "rows": json.loads(result.head(100).to_json(orient="records", date_format="iso")),
                }}))
            except ImportError:
                # Fallback: pandas eval (limited SQL-like operations)
                print(json.dumps({{
                    "engine": "pandas_fallback",
                    "note": "Install duckdb for full SQL support: pip install duckdb",
                    "columns": list(df.columns),
                    "shape": list(df.shape),
                    "sample": json.loads(df.head(10).to_json(orient="records", date_format="iso")),
                }}))
        """)
        return await run_code_in_sandbox(code)

    async def _pivot(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a pivot table from a dataset."""
        fp = params.get("file_path", "")
        index = params.get("index", "")
        columns = params.get("columns", "")
        values = params.get("values", "")
        aggfunc = params.get("aggfunc", "sum")
        if not all([fp, index, values]):
            return {"error": "file_path, index, values required"}
        col_arg = f', columns="{columns}"' if columns else ""
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            pivot = pd.pivot_table(df, index="{index}"{col_arg}, values="{values}", aggfunc="{aggfunc}", fill_value=0)
            result = json.loads(pivot.reset_index().head(50).to_json(orient="records", date_format="iso"))
            print(json.dumps({{"pivot_shape": list(pivot.shape), "rows": result}}))
        """)
        return await run_code_in_sandbox(code)

    async def _window_functions(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply window functions: running totals, moving averages, rankings."""
        fp = params.get("file_path", "")
        column = params.get("column", "")
        window = params.get("window_type", "rolling_mean")
        window_size = params.get("window_size", 7)
        partition = params.get("partition_by", "")
        if not all([fp, column]):
            return {"error": "file_path and column required"}
        part_code = f'.groupby("{partition}")' if partition else ""
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            df = df.sort_index()
            if "{window}" == "rolling_mean":
                df["result"] = df{part_code}["{column}"].transform(lambda x: x.rolling({window_size}).mean())
            elif "{window}" == "cumsum":
                df["result"] = df{part_code}["{column}"].cumsum()
            elif "{window}" == "rank":
                df["result"] = df{part_code}["{column}"].rank(ascending=False)
            elif "{window}" == "pct_change":
                df["result"] = df{part_code}["{column}"].pct_change() * 100
            else:
                df["result"] = df{part_code}["{column}"].transform(lambda x: x.rolling({window_size}).mean())
            sample = json.loads(df.head(30).to_json(orient="records", date_format="iso"))
            print(json.dumps({{"window_type": "{window}", "column": "{column}", "window_size": {window_size}, "sample_rows": sample}}))
        """)
        return await run_code_in_sandbox(code)

    async def _funnel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Funnel analysis: conversion rates between stages."""
        fp = params.get("file_path", "")
        stage_column = params.get("stage_column", "")
        stages = params.get("stages", [])
        if not all([fp, stage_column, stages]):
            return {"error": "file_path, stage_column, stages required"}
        stages_str = repr(stages)
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            stages = {stages_str}
            counts = []
            for s in stages:
                count = int(df[df["{stage_column}"] == s].shape[0])
                counts.append(count)
            funnel = []
            for i, (s, c) in enumerate(zip(stages, counts)):
                conv = round(c / counts[0] * 100, 2) if counts[0] > 0 else 0
                drop = round((1 - c / counts[i-1]) * 100, 2) if i > 0 and counts[i-1] > 0 else 0
                funnel.append({{"stage": s, "count": c, "conversion_from_top": conv, "drop_from_previous": drop if i > 0 else None}})
            print(json.dumps({{"funnel": funnel, "overall_conversion": round(counts[-1] / counts[0] * 100, 2) if counts[0] > 0 else 0}}))
        """)
        return await run_code_in_sandbox(code)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "sql_generate", "description": "Generate SQL from natural language + schema.", "parameters": {"type": "object", "properties": {"question": {"type": "string"}, "schema": {"type": "string", "description": "Table/column definitions"}, "dialect": {"type": "string", "enum": ["snowflake", "postgres", "mysql", "bigquery"]}}, "required": ["question"]}}},
            {"type": "function", "function": {"name": "sql_analyze_csv", "description": "Run SQL queries on a CSV file (uses DuckDB or pandas).", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "query": {"type": "string", "description": "SQL query (use 'df' as table name)"}}, "required": ["file_path", "query"]}}},
            {"type": "function", "function": {"name": "sql_pivot", "description": "Create a pivot table from a dataset.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "index": {"type": "string"}, "columns": {"type": "string"}, "values": {"type": "string"}, "aggfunc": {"type": "string", "enum": ["sum", "mean", "count", "max", "min"]}}, "required": ["file_path", "index", "values"]}}},
            {"type": "function", "function": {"name": "sql_window", "description": "Apply window functions: rolling mean, cumsum, rank, pct change.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}, "window_type": {"type": "string", "enum": ["rolling_mean", "cumsum", "rank", "pct_change"]}, "window_size": {"type": "integer"}, "partition_by": {"type": "string"}}, "required": ["file_path", "column"]}}},
            {"type": "function", "function": {"name": "sql_funnel", "description": "Funnel analysis: conversion rates between ordered stages.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "stage_column": {"type": "string"}, "stages": {"type": "array", "items": {"type": "string"}, "description": "Ordered list of stage values"}}, "required": ["file_path", "stage_column", "stages"]}}},
        ]
