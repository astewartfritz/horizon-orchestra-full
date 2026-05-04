"""Business Intelligence data export engine.

Supports CSV, JSONL, Parquet (optional pyarrow), and generates
warehouse-specific load scripts for Snowflake, BigQuery, and Redshift.

Pre-built export tables
-----------------------
- ``usage_events``     — every API call with org/user/model/tokens/cost
- ``agent_runs``       — task ID, arch, duration, tool_calls, tokens, result
- ``team_performance`` — team ID, tasks completed, avg latency, success rate
- ``cost_attribution`` — cost by org / team / model / date
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "ExportJob",
    "BIExporter",
]

log = logging.getLogger("orchestra.analytics")


# ── Schema definitions ───────────────────────────────────────────────────

EXPORT_TABLES: dict[str, dict[str, Any]] = {
    "usage_events": {
        "description": "Every API call with org/user/model/tokens/cost",
        "columns": [
            {"name": "event_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "org_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "user_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "model", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(128)"},
            {"name": "input_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "output_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "total_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "cost_usd", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "latency_ms", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "status", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(32)"},
            {"name": "endpoint", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(256)"},
            {"name": "timestamp", "type": "TIMESTAMP", "bq_type": "TIMESTAMP", "sf_type": "TIMESTAMP_NTZ"},
        ],
    },
    "agent_runs": {
        "description": "Task ID, architecture, duration, tool calls, tokens, result",
        "columns": [
            {"name": "run_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "task_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "org_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "architecture", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(32)"},
            {"name": "model", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(128)"},
            {"name": "duration_ms", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "tool_calls", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "input_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "output_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "total_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "cost_usd", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "result_status", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(32)"},
            {"name": "error_type", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(128)"},
            {"name": "started_at", "type": "TIMESTAMP", "bq_type": "TIMESTAMP", "sf_type": "TIMESTAMP_NTZ"},
            {"name": "completed_at", "type": "TIMESTAMP", "bq_type": "TIMESTAMP", "sf_type": "TIMESTAMP_NTZ"},
        ],
    },
    "team_performance": {
        "description": "Team-level performance metrics",
        "columns": [
            {"name": "team_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "org_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "team_name", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(256)"},
            {"name": "tasks_completed", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "tasks_failed", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "avg_latency_ms", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "p95_latency_ms", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "success_rate", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "total_cost_usd", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "total_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "period_start", "type": "TIMESTAMP", "bq_type": "TIMESTAMP", "sf_type": "TIMESTAMP_NTZ"},
            {"name": "period_end", "type": "TIMESTAMP", "bq_type": "TIMESTAMP", "sf_type": "TIMESTAMP_NTZ"},
        ],
    },
    "cost_attribution": {
        "description": "Cost breakdown by org / team / model / date",
        "columns": [
            {"name": "attribution_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "org_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "team_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "model", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(128)"},
            {"name": "date", "type": "DATE", "bq_type": "DATE", "sf_type": "DATE"},
            {"name": "requests", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "input_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "output_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "total_tokens", "type": "INTEGER", "bq_type": "INT64", "sf_type": "INTEGER"},
            {"name": "cost_usd", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "budget_limit_usd", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
            {"name": "budget_utilisation", "type": "FLOAT", "bq_type": "FLOAT64", "sf_type": "FLOAT"},
        ],
    },
    "audit_log": {
        "description": "Security and compliance audit trail",
        "columns": [
            {"name": "log_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "org_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "user_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "action", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(128)"},
            {"name": "resource_type", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(64)"},
            {"name": "resource_id", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(128)"},
            {"name": "ip_address", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(45)"},
            {"name": "user_agent", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(512)"},
            {"name": "status", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(32)"},
            {"name": "details", "type": "STRING", "bq_type": "STRING", "sf_type": "VARCHAR(4096)"},
            {"name": "timestamp", "type": "TIMESTAMP", "bq_type": "TIMESTAMP", "sf_type": "TIMESTAMP_NTZ"},
        ],
    },
}


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class ExportJob:
    """Tracks the state of a BI export job."""

    id: str
    org_id: str
    table: str
    format: str  # csv | jsonl | parquet | snowflake | bigquery | redshift
    filters: dict[str, Any]
    status: str = "pending"  # pending | running | completed | failed
    row_count: int = 0
    file_path: str = ""
    file_size_bytes: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "table": self.table,
            "format": self.format,
            "filters": self.filters,
            "status": self.status,
            "row_count": self.row_count,
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
        }


# ── BI Exporter ──────────────────────────────────────────────────────────

class BIExporter:
    """Enterprise BI data export engine.

    Exports usage, telemetry, cost, and audit data in multiple formats
    for ingestion into data warehouses and BI tools.

    Supported formats:
    - **CSV**       — simple tabular export
    - **JSONL**     — newline-delimited JSON for streaming ingestion
    - **Parquet**   — columnar format (requires optional ``pyarrow``)
    - **Snowflake** — CSV + ``COPY INTO`` script
    - **BigQuery**  — CSV + JSON schema for BQ load jobs
    - **Redshift**  — CSV + ``COPY`` command for S3 → Redshift
    """

    SUPPORTED_FORMATS = {"csv", "jsonl", "parquet", "snowflake", "bigquery", "redshift"}

    def __init__(self, export_dir: str = "/tmp/orchestra-exports") -> None:
        self._export_dir = export_dir
        self._jobs: dict[str, ExportJob] = {}
        self._data_store: dict[str, list[dict[str, Any]]] = {
            table: [] for table in EXPORT_TABLES
        }
        self._scheduled_exports: dict[str, dict[str, Any]] = {}

    # ── Data ingestion (for internal use) ─────────────────────────────────

    def ingest(self, table: str, record: dict[str, Any]) -> None:
        """Ingest a single record into the in-memory data store."""
        if table not in self._data_store:
            raise ValueError(f"Unknown table: {table}")
        self._data_store[table].append(record)

    def ingest_batch(self, table: str, records: list[dict[str, Any]]) -> int:
        """Ingest multiple records. Returns count ingested."""
        if table not in self._data_store:
            raise ValueError(f"Unknown table: {table}")
        self._data_store[table].extend(records)
        return len(records)

    # ── Query helper ──────────────────────────────────────────────────────

    def _query_data(
        self,
        table: str,
        org_id: str,
        start: datetime,
        end: datetime,
        extra_filters: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Filter data from in-memory store. Returns (rows, column_names)."""
        schema = EXPORT_TABLES.get(table)
        if schema is None:
            raise ValueError(f"Unknown table: {table}")

        columns = [c["name"] for c in schema["columns"]]
        records = self._data_store.get(table, [])

        # Filter by org and time range
        filtered = []
        for rec in records:
            if rec.get("org_id") != org_id:
                continue
            # Check timestamp fields
            ts = rec.get("timestamp") or rec.get("started_at") or rec.get("period_start") or rec.get("date")
            if ts is not None:
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except (ValueError, TypeError):
                        pass
                if isinstance(ts, datetime):
                    if ts < start or ts > end:
                        continue
            if extra_filters:
                skip = False
                for k, v in extra_filters.items():
                    if rec.get(k) != v:
                        skip = True
                        break
                if skip:
                    continue
            filtered.append(rec)

        return filtered, columns

    # ── Export methods ────────────────────────────────────────────────────

    async def export_usage(
        self,
        org_id: str,
        start: datetime,
        end: datetime,
        format: str = "csv",
        **filters: Any,
    ) -> ExportJob:
        """Export usage events for an organisation.

        Parameters
        ----------
        org_id:  Organisation identifier.
        start:   Start of date range (inclusive).
        end:     End of date range (inclusive).
        format:  One of csv, jsonl, parquet, snowflake, bigquery, redshift.
        """
        return await self._run_export("usage_events", org_id, start, end, format, filters)

    async def export_agent_telemetry(
        self,
        org_id: str,
        start: datetime,
        end: datetime,
        format: str = "csv",
        **filters: Any,
    ) -> ExportJob:
        """Export agent run telemetry data."""
        return await self._run_export("agent_runs", org_id, start, end, format, filters)

    async def export_cost_breakdown(
        self,
        org_id: str,
        start: datetime,
        end: datetime,
        format: str = "csv",
        **filters: Any,
    ) -> ExportJob:
        """Export cost attribution data."""
        return await self._run_export("cost_attribution", org_id, start, end, format, filters)

    async def export_audit_log(
        self,
        org_id: str,
        start: datetime,
        end: datetime,
        format: str = "csv",
        **filters: Any,
    ) -> ExportJob:
        """Export security and compliance audit log."""
        return await self._run_export("audit_log", org_id, start, end, format, filters)

    async def export_team_performance(
        self,
        org_id: str,
        start: datetime,
        end: datetime,
        format: str = "csv",
        **filters: Any,
    ) -> ExportJob:
        """Export team-level performance metrics."""
        return await self._run_export("team_performance", org_id, start, end, format, filters)

    async def _run_export(
        self,
        table: str,
        org_id: str,
        start: datetime,
        end: datetime,
        fmt: str,
        filters: dict[str, Any],
    ) -> ExportJob:
        """Execute an export job."""
        if fmt not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {fmt}. Use one of {self.SUPPORTED_FORMATS}")

        job = ExportJob(
            id=f"exp_{uuid.uuid4().hex[:16]}",
            org_id=org_id,
            table=table,
            format=fmt,
            filters={"start": start.isoformat(), "end": end.isoformat(), **filters},
        )
        self._jobs[job.id] = job
        job.started_at = datetime.now(timezone.utc)
        job.status = "running"

        try:
            data, columns = self._query_data(table, org_id, start, end, filters or None)
            job.row_count = len(data)

            if fmt == "csv":
                content = self.to_csv(data, columns)
                job.file_path = f"{self._export_dir}/{job.id}.csv"
            elif fmt == "jsonl":
                content = self.to_jsonl(data)
                job.file_path = f"{self._export_dir}/{job.id}.jsonl"
            elif fmt == "parquet":
                content = self.to_parquet(data, columns)
                job.file_path = f"{self._export_dir}/{job.id}.parquet"
            elif fmt == "snowflake":
                content = self.to_csv(data, columns)
                job.file_path = f"{self._export_dir}/{job.id}.csv"
                script = self.snowflake_copy_script(table, f"s3://orchestra-exports/{job.id}.csv")
                job.filters["snowflake_script"] = script
            elif fmt == "bigquery":
                content = self.to_csv(data, columns)
                job.file_path = f"{self._export_dir}/{job.id}.csv"
                schema = self.bigquery_schema(columns, table)
                job.filters["bigquery_schema"] = schema
            elif fmt == "redshift":
                content = self.to_csv(data, columns)
                job.file_path = f"{self._export_dir}/{job.id}.csv"
                script = self.redshift_copy_script(table, f"s3://orchestra-exports/{job.id}.csv")
                job.filters["redshift_script"] = script
            else:
                raise ValueError(f"Unsupported format: {fmt}")

            if isinstance(content, bytes):
                job.file_size_bytes = len(content)
            else:
                job.file_size_bytes = len(content.encode("utf-8")) if isinstance(content, str) else 0

            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            log.info("Export %s completed: %d rows, %s format, %d bytes",
                     job.id, job.row_count, fmt, job.file_size_bytes)

        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            log.error("Export %s failed: %s", job.id, exc)

        return job

    # ── Format converters ────────────────────────────────────────────────

    @staticmethod
    def to_csv(data: list[dict[str, Any]], columns: list[str]) -> str:
        """Convert rows to CSV string.

        Parameters
        ----------
        data:    List of row dicts.
        columns: Ordered column names for the header.

        Returns
        -------
        str  CSV-formatted string with header row.
        """
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            # Ensure all columns present
            normalised = {col: row.get(col, "") for col in columns}
            writer.writerow(normalised)
        return buf.getvalue()

    @staticmethod
    def to_jsonl(data: list[dict[str, Any]]) -> str:
        """Convert rows to newline-delimited JSON.

        Each row is a single JSON object on one line, suitable for
        streaming ingestion into BigQuery, Kafka, or ElasticSearch.
        """
        lines: list[str] = []
        for row in data:
            # Serialise datetime objects
            cleaned: dict[str, Any] = {}
            for k, v in row.items():
                if isinstance(v, datetime):
                    cleaned[k] = v.isoformat()
                else:
                    cleaned[k] = v
            lines.append(json.dumps(cleaned, separators=(",", ":")))
        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def to_parquet(data: list[dict[str, Any]], columns: list[str]) -> bytes:
        """Convert rows to Apache Parquet format.

        Requires ``pyarrow`` to be installed.  Falls back to a
        descriptive error if the dependency is missing.

        Returns
        -------
        bytes  Parquet binary data.
        """
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            # Build column arrays
            arrays = []
            for col in columns:
                values = [row.get(col) for row in data]
                arrays.append(pa.array(values))

            table = pa.table({col: arr for col, arr in zip(columns, arrays)})
            buf = io.BytesIO()
            pq.write_table(table, buf)
            return buf.getvalue()

        except ImportError:
            # Fallback: return a stub that describes the data
            stub = {
                "format": "parquet_stub",
                "note": "pyarrow not installed — install via: pip install pyarrow",
                "row_count": len(data),
                "columns": columns,
            }
            return json.dumps(stub).encode("utf-8")

    # ── Warehouse-specific scripts ───────────────────────────────────────

    @staticmethod
    def snowflake_copy_script(table: str, s3_path: str, *, role: str = "ORCHESTRA_LOADER") -> str:
        """Generate a Snowflake COPY INTO command.

        Parameters
        ----------
        table:   Target Snowflake table name.
        s3_path: S3 URI where the CSV is staged.
        role:    Snowflake role to use.
        """
        schema = EXPORT_TABLES.get(table, {})
        col_defs = []
        for col in schema.get("columns", []):
            col_defs.append(f"    {col['name']} {col['sf_type']}")
        create_ddl = ",\n".join(col_defs)

        return f"""-- Snowflake COPY INTO script for {table}
-- Generated by Horizon Orchestra BI Exporter

USE ROLE {role};
USE WAREHOUSE ORCHESTRA_WH;

-- Create table if not exists
CREATE TABLE IF NOT EXISTS ORCHESTRA_DB.ANALYTICS.{table.upper()} (
{create_ddl}
);

-- Create stage
CREATE OR REPLACE STAGE ORCHESTRA_DB.ANALYTICS.{table.upper()}_STAGE
  URL = '{s3_path}'
  CREDENTIALS = (AWS_KEY_ID = '{{{{aws_key}}}}' AWS_SECRET_KEY = '{{{{aws_secret}}}}')
  FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"' SKIP_HEADER = 1);

-- Load data
COPY INTO ORCHESTRA_DB.ANALYTICS.{table.upper()}
  FROM @ORCHESTRA_DB.ANALYTICS.{table.upper()}_STAGE
  FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"' SKIP_HEADER = 1)
  ON_ERROR = 'CONTINUE';

-- Verify
SELECT COUNT(*) AS rows_loaded FROM ORCHESTRA_DB.ANALYTICS.{table.upper()};
"""

    @staticmethod
    def bigquery_schema(columns: list[str], table: str | None = None) -> dict[str, Any]:
        """Generate a BigQuery JSON schema for a table.

        Parameters
        ----------
        columns: Column names to include.
        table:   Table name (to look up types).

        Returns
        -------
        dict  BigQuery-compatible table schema.
        """
        schema = EXPORT_TABLES.get(table or "", {})
        col_lookup = {c["name"]: c for c in schema.get("columns", [])}

        fields = []
        for col_name in columns:
            col_info = col_lookup.get(col_name, {})
            bq_type = col_info.get("bq_type", "STRING")
            fields.append({
                "name": col_name,
                "type": bq_type,
                "mode": "NULLABLE",
                "description": "",
            })

        return {
            "schema": {"fields": fields},
            "sourceFormat": "CSV",
            "skipLeadingRows": 1,
            "writeDisposition": "WRITE_APPEND",
            "autodetect": False,
            "tableReference": {
                "projectId": "{{project_id}}",
                "datasetId": "orchestra_analytics",
                "tableId": table or "export",
            },
        }

    @staticmethod
    def redshift_copy_script(table: str, s3_path: str) -> str:
        """Generate an Amazon Redshift COPY command.

        Parameters
        ----------
        table:   Target Redshift table name.
        s3_path: S3 URI where the CSV is staged.
        """
        schema = EXPORT_TABLES.get(table, {})
        col_defs = []
        type_map = {
            "VARCHAR": "VARCHAR",
            "INTEGER": "INTEGER",
            "FLOAT": "FLOAT",
            "TIMESTAMP_NTZ": "TIMESTAMP",
            "DATE": "DATE",
        }
        for col in schema.get("columns", []):
            sf_type = col.get("sf_type", "VARCHAR(256)")
            # Map Snowflake types to Redshift-compatible
            rs_type = sf_type
            for sf_key, rs_val in type_map.items():
                if sf_key in sf_type:
                    rs_type = sf_type.replace(sf_key, rs_val) if "(" in sf_type else rs_val
                    break
            col_defs.append(f"    {col['name']} {rs_type}")
        create_ddl = ",\n".join(col_defs)

        return f"""-- Redshift COPY script for {table}
-- Generated by Horizon Orchestra BI Exporter

-- Create table if not exists
CREATE TABLE IF NOT EXISTS analytics.{table} (
{create_ddl}
);

-- Load from S3
COPY analytics.{table}
FROM '{s3_path}'
IAM_ROLE '{{{{redshift_iam_role}}}}'
FORMAT AS CSV
IGNOREHEADER 1
DATEFORMAT 'auto'
TIMEFORMAT 'auto'
REGION 'us-east-1';

-- Verify
SELECT COUNT(*) AS rows_loaded FROM analytics.{table};
"""

    # ── Scheduled exports ────────────────────────────────────────────────

    async def schedule_export(
        self,
        org_id: str,
        config: dict[str, Any],
        cron: str,
    ) -> str:
        """Schedule a recurring BI export job.

        Parameters
        ----------
        org_id: Organisation identifier.
        config: Export configuration dict containing:
            - table: str — which table to export
            - format: str — output format
            - destination: str — S3 path or webhook URL for delivery
            - lookback_hours: int — hours of data to include (default 24)
        cron: Cron expression (e.g. "0 2 * * *" for daily at 2am UTC).

        Returns
        -------
        str  Schedule ID.
        """
        schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
        self._scheduled_exports[schedule_id] = {
            "id": schedule_id,
            "org_id": org_id,
            "config": config,
            "cron": cron,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_run_at": None,
            "next_run_at": None,
            "run_count": 0,
        }
        log.info("Scheduled export %s for org %s: %s (cron: %s)",
                 schedule_id, org_id, config.get("table", "?"), cron)
        return schedule_id

    async def list_schedules(self, org_id: str) -> list[dict[str, Any]]:
        """List all scheduled exports for an organisation."""
        return [
            s for s in self._scheduled_exports.values()
            if s["org_id"] == org_id
        ]

    async def cancel_schedule(self, schedule_id: str) -> bool:
        """Cancel a scheduled export."""
        sched = self._scheduled_exports.get(schedule_id)
        if sched is None:
            return False
        sched["active"] = False
        return True

    # ── Job management ───────────────────────────────────────────────────

    async def get_job(self, job_id: str) -> ExportJob | None:
        """Retrieve an export job by ID."""
        return self._jobs.get(job_id)

    async def list_jobs(
        self,
        org_id: str,
        limit: int = 50,
        status: str | None = None,
    ) -> list[ExportJob]:
        """List export jobs for an organisation."""
        jobs = [j for j in self._jobs.values() if j.org_id == org_id]
        if status:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: j.started_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return jobs[:limit]

    async def get_available_tables(self) -> dict[str, dict[str, Any]]:
        """Return metadata about all available export tables."""
        result: dict[str, dict[str, Any]] = {}
        for name, schema in EXPORT_TABLES.items():
            result[name] = {
                "description": schema["description"],
                "columns": [c["name"] for c in schema["columns"]],
                "column_count": len(schema["columns"]),
            }
        return result

    # ── API Routes ───────────────────────────────────────────────────────

    def register_routes(self, app: Any) -> None:
        """Mount BI export endpoints onto a FastAPI / Starlette app.

        Endpoints
        ---------
        POST  /v1/analytics/export          — create an export job
        GET   /v1/analytics/export/{id}     — get job status
        GET   /v1/analytics/export          — list jobs for org
        GET   /v1/analytics/tables          — list available tables
        POST  /v1/analytics/schedule        — schedule recurring export
        GET   /v1/analytics/schedule        — list scheduled exports
        DELETE /v1/analytics/schedule/{id}  — cancel scheduled export
        """
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        async def _export(request: Request) -> JSONResponse:
            body = await request.json()
            org_id = body.get("org_id", "")
            table = body.get("table", "")
            fmt = body.get("format", "csv")
            start_str = body.get("start", "")
            end_str = body.get("end", "")
            filters = body.get("filters", {})

            try:
                start = datetime.fromisoformat(start_str)
                end = datetime.fromisoformat(end_str)
            except (ValueError, TypeError):
                return JSONResponse({"error": "Invalid start/end datetime"}, status_code=400)

            dispatch = {
                "usage_events": self.export_usage,
                "agent_runs": self.export_agent_telemetry,
                "cost_attribution": self.export_cost_breakdown,
                "audit_log": self.export_audit_log,
                "team_performance": self.export_team_performance,
            }
            handler = dispatch.get(table)
            if not handler:
                return JSONResponse({"error": f"Unknown table: {table}"}, status_code=400)

            job = await handler(org_id, start, end, fmt, **filters)
            return JSONResponse(job.to_dict(), status_code=201)

        async def _get_job(request: Request) -> JSONResponse:
            job_id = request.path_params["job_id"]
            job = await self.get_job(job_id)
            if not job:
                return JSONResponse({"error": "Not found"}, status_code=404)
            return JSONResponse(job.to_dict())

        async def _list_jobs(request: Request) -> JSONResponse:
            org_id = request.query_params.get("org_id", "")
            limit = int(request.query_params.get("limit", "50"))
            status = request.query_params.get("status")
            jobs = await self.list_jobs(org_id, limit, status)
            return JSONResponse([j.to_dict() for j in jobs])

        async def _tables(request: Request) -> JSONResponse:
            tables = await self.get_available_tables()
            return JSONResponse(tables)

        async def _schedule(request: Request) -> JSONResponse:
            body = await request.json()
            org_id = body.get("org_id", "")
            config = body.get("config", {})
            cron = body.get("cron", "")
            sid = await self.schedule_export(org_id, config, cron)
            return JSONResponse({"schedule_id": sid}, status_code=201)

        async def _list_schedules(request: Request) -> JSONResponse:
            org_id = request.query_params.get("org_id", "")
            schedules = await self.list_schedules(org_id)
            return JSONResponse(schedules)

        async def _cancel_schedule(request: Request) -> JSONResponse:
            sid = request.path_params["schedule_id"]
            ok = await self.cancel_schedule(sid)
            if not ok:
                return JSONResponse({"error": "Not found"}, status_code=404)
            return JSONResponse({"cancelled": True})

        from starlette.routing import Route

        routes = [
            Route("/v1/analytics/export", _export, methods=["POST"]),
            Route("/v1/analytics/export", _list_jobs, methods=["GET"]),
            Route("/v1/analytics/tables", _tables, methods=["GET"]),
            Route("/v1/analytics/schedule", _schedule, methods=["POST"]),
            Route("/v1/analytics/schedule", _list_schedules, methods=["GET"]),
            Route("/v1/analytics/export/{job_id}", _get_job, methods=["GET"]),
            Route("/v1/analytics/schedule/{schedule_id}", _cancel_schedule, methods=["DELETE"]),
        ]

        if hasattr(app, "routes"):
            app.routes.extend(routes)
        elif hasattr(app, "add_route"):
            for route in routes:
                for method in route.methods or ["GET"]:
                    app.add_route(route.path, route.endpoint, methods=[method])
