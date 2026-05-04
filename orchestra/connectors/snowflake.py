"""Snowflake connector — account/user/password or key-pair auth.

Execute SQL queries, discover schemas, analyze data.
Requires: pip install snowflake-connector-python

Credentials via connect() or env vars:
  SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
  SNOWFLAKE_DATABASE, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_SCHEMA
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .base import Connector

__all__ = ["SnowflakeConnector"]

log = logging.getLogger("orchestra.connectors.snowflake")


class SnowflakeConnector(Connector):
    """Snowflake data warehouse integration."""

    name = "snowflake"
    description = "Execute SQL queries, discover schemas, and analyze data in Snowflake."

    def __init__(self) -> None:
        self._conn: Any = None
        self._account: str = ""
        self._database: str = ""
        self._warehouse: str = ""
        self._schema: str = ""

    @property
    def connected(self) -> bool:
        return self._conn is not None

    async def connect(self, credentials: dict[str, str]) -> bool:
        try:
            import snowflake.connector
        except ImportError:
            log.error("Snowflake connector requires: pip install snowflake-connector-python")
            return False

        self._account = credentials.get("account", "") or os.environ.get("SNOWFLAKE_ACCOUNT", "")
        user = credentials.get("user", "") or os.environ.get("SNOWFLAKE_USER", "")
        password = credentials.get("password", "") or os.environ.get("SNOWFLAKE_PASSWORD", "")
        self._database = credentials.get("database", "") or os.environ.get("SNOWFLAKE_DATABASE", "")
        self._warehouse = credentials.get("warehouse", "") or os.environ.get("SNOWFLAKE_WAREHOUSE", "")
        self._schema = credentials.get("schema", "") or os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC")

        if not all([self._account, user, password]):
            log.error("Missing Snowflake credentials (account, user, password)")
            return False

        try:
            self._conn = snowflake.connector.connect(
                account=self._account,
                user=user,
                password=password,
                database=self._database,
                warehouse=self._warehouse,
                schema=self._schema,
            )
            log.info("Snowflake connected: %s.%s", self._database, self._schema)
            return True
        except Exception as exc:
            log.error("Snowflake connection failed: %s", exc)
            self._conn = None
            return False

    async def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
        self._conn = None

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._conn:
            return {"error": "Snowflake not connected."}
        dispatch = {
            "snowflake_query": self._query,
            "snowflake_list_databases": self._list_databases,
            "snowflake_list_schemas": self._list_schemas,
            "snowflake_list_tables": self._list_tables,
            "snowflake_describe_table": self._describe_table,
            "snowflake_sample_data": self._sample_data,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _query(self, params: dict[str, Any]) -> dict[str, Any]:
        sql = params.get("sql", "").strip()
        limit = params.get("limit", 100)
        if not sql:
            return {"error": "sql is required"}

        # Safety: prevent destructive queries unless explicitly allowed
        sql_upper = sql.upper().strip()
        destructive = ("DROP", "DELETE", "TRUNCATE", "ALTER", "INSERT", "UPDATE", "MERGE", "CREATE")
        if any(sql_upper.startswith(kw) for kw in destructive):
            if not params.get("allow_write", False):
                return {"error": f"Destructive query blocked. Pass allow_write=true to override."}

        # Append LIMIT if it's a SELECT without one
        if sql_upper.startswith("SELECT") and "LIMIT" not in sql_upper:
            sql = f"{sql.rstrip(';')} LIMIT {limit}"

        try:
            cursor = self._conn.cursor()
            cursor.execute(sql)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(limit)
            cursor.close()

            # Convert to list of dicts
            results = [dict(zip(columns, row)) for row in rows]

            return {
                "columns": columns,
                "row_count": len(results),
                "rows": results[:limit],
                "sql": sql,
            }
        except Exception as exc:
            return {"error": str(exc), "sql": sql}

    async def _list_databases(self, params: dict[str, Any]) -> dict[str, Any]:
        result = await self._query({"sql": "SHOW DATABASES", "limit": 100})
        if "error" in result:
            return result
        return {
            "databases": [
                {"name": r.get("name"), "created": str(r.get("created_on", ""))}
                for r in result.get("rows", [])
            ]
        }

    async def _list_schemas(self, params: dict[str, Any]) -> dict[str, Any]:
        database = params.get("database", self._database)
        result = await self._query({"sql": f"SHOW SCHEMAS IN DATABASE {database}", "limit": 100})
        if "error" in result:
            return result
        return {
            "schemas": [
                {"name": r.get("name"), "database": database}
                for r in result.get("rows", [])
            ]
        }

    async def _list_tables(self, params: dict[str, Any]) -> dict[str, Any]:
        database = params.get("database", self._database)
        schema = params.get("schema", self._schema)
        result = await self._query({
            "sql": f"SHOW TABLES IN {database}.{schema}",
            "limit": 200,
        })
        if "error" in result:
            return result
        return {
            "tables": [
                {
                    "name": r.get("name"),
                    "rows": r.get("rows"),
                    "bytes": r.get("bytes"),
                    "created": str(r.get("created_on", "")),
                }
                for r in result.get("rows", [])
            ]
        }

    async def _describe_table(self, params: dict[str, Any]) -> dict[str, Any]:
        table = params.get("table", "")
        if not table:
            return {"error": "table is required (e.g. 'database.schema.table')"}
        result = await self._query({"sql": f"DESCRIBE TABLE {table}", "limit": 200})
        if "error" in result:
            return result
        return {
            "table": table,
            "columns": [
                {
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "nullable": r.get("null?"),
                    "default": r.get("default"),
                }
                for r in result.get("rows", [])
            ],
        }

    async def _sample_data(self, params: dict[str, Any]) -> dict[str, Any]:
        table = params.get("table", "")
        limit = params.get("limit", 10)
        if not table:
            return {"error": "table is required"}
        return await self._query({"sql": f"SELECT * FROM {table} LIMIT {limit}", "limit": limit})

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {
                "name": "snowflake_query",
                "description": "Execute a SQL query against Snowflake. SELECT queries are auto-limited. Destructive queries are blocked by default.",
                "parameters": {"type": "object", "properties": {
                    "sql": {"type": "string", "description": "SQL query to execute"},
                    "limit": {"type": "integer", "description": "Max rows to return (default 100)"},
                    "allow_write": {"type": "boolean", "description": "Allow destructive queries (default false)"},
                }, "required": ["sql"]},
            }},
            {"type": "function", "function": {
                "name": "snowflake_list_databases",
                "description": "List all databases in Snowflake.",
                "parameters": {"type": "object", "properties": {}},
            }},
            {"type": "function", "function": {
                "name": "snowflake_list_schemas",
                "description": "List schemas in a Snowflake database.",
                "parameters": {"type": "object", "properties": {
                    "database": {"type": "string", "description": "Database name (default: connected database)"},
                }},
            }},
            {"type": "function", "function": {
                "name": "snowflake_list_tables",
                "description": "List tables in a Snowflake schema.",
                "parameters": {"type": "object", "properties": {
                    "database": {"type": "string"},
                    "schema": {"type": "string"},
                }},
            }},
            {"type": "function", "function": {
                "name": "snowflake_describe_table",
                "description": "Describe the columns of a Snowflake table.",
                "parameters": {"type": "object", "properties": {
                    "table": {"type": "string", "description": "Fully qualified table name (e.g. DB.SCHEMA.TABLE)"},
                }, "required": ["table"]},
            }},
            {"type": "function", "function": {
                "name": "snowflake_sample_data",
                "description": "Preview sample rows from a Snowflake table.",
                "parameters": {"type": "object", "properties": {
                    "table": {"type": "string", "description": "Table name"},
                    "limit": {"type": "integer", "description": "Number of rows (default 10)"},
                }, "required": ["table"]},
            }},
        ]
