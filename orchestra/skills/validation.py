"""Data Validation skill — schema checks, quality scoring, anomaly detection.

Generates code for comprehensive data quality assessment: type checking,
range validation, referential integrity, freshness, and anomaly detection.
"""

from __future__ import annotations

import json, logging, textwrap
from typing import Any
from .base import Skill, run_code_in_sandbox

__all__ = ["DataValidationSkill"]
log = logging.getLogger("orchestra.skills.validation")


class DataValidationSkill(Skill):
    name = "data_validation"
    description = "Validate data quality: schema checks, range validation, anomaly detection, quality scoring."

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "validate_schema": self._schema,
            "validate_quality_score": self._quality_score,
            "validate_anomalies": self._anomalies,
            "validate_duplicates": self._duplicates,
            "validate_referential": self._referential,
            "validate_freshness": self._freshness,
        }
        handler = dispatch.get(action)
        return await handler(params) if handler else {"error": f"Unknown: {action}"}

    async def _schema(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        expected = params.get("expected_schema", {})
        if not fp:
            return {"error": "file_path required"}
        expected_str = json.dumps(expected) if expected else "{}"
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            expected = json.loads('{expected_str}')

            issues = []
            actual_schema = {{c: str(t) for c, t in df.dtypes.items()}}

            if expected:
                for col, exp_type in expected.items():
                    if col not in df.columns:
                        issues.append({{"column": col, "issue": "missing_column", "expected": exp_type}})
                    else:
                        actual = str(df[col].dtype)
                        if exp_type not in actual and not (exp_type == "numeric" and np.issubdtype(df[col].dtype, np.number)):
                            issues.append({{"column": col, "issue": "type_mismatch", "expected": exp_type, "actual": actual}})
                extra = [c for c in df.columns if c not in expected]
                if extra:
                    issues.append({{"issue": "unexpected_columns", "columns": extra}})

            # Auto-detect issues
            for col in df.columns:
                if df[col].dtype == "object":
                    mixed = df[col].dropna().apply(type).nunique()
                    if mixed > 1:
                        issues.append({{"column": col, "issue": "mixed_types", "unique_types": int(mixed)}})
                if df[col].isnull().all():
                    issues.append({{"column": col, "issue": "all_null"}})

            print(json.dumps({{
                "valid": len(issues) == 0,
                "actual_schema": actual_schema,
                "issues": issues, "issue_count": len(issues),
                "shape": list(df.shape),
            }}))
        """)
        return await run_code_in_sandbox(code)

    async def _quality_score(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        if not fp:
            return {"error": "file_path required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")

            scores = {{}}

            # Completeness (% non-null)
            completeness = round((1 - df.isnull().mean().mean()) * 100, 2)
            scores["completeness"] = completeness

            # Uniqueness (% unique rows)
            uniqueness = round((1 - df.duplicated().mean()) * 100, 2)
            scores["uniqueness"] = uniqueness

            # Consistency (% columns with consistent types)
            consistent = 0
            for col in df.select_dtypes(include=["object"]).columns:
                types = df[col].dropna().apply(type).nunique()
                if types <= 1:
                    consistent += 1
            total_obj = len(df.select_dtypes(include=["object"]).columns)
            scores["consistency"] = round(consistent / total_obj * 100, 2) if total_obj > 0 else 100.0

            # Validity (numeric columns within reasonable range — no inf)
            valid_cols = 0
            numeric = df.select_dtypes(include=[np.number])
            for col in numeric.columns:
                if not np.isinf(numeric[col]).any():
                    valid_cols += 1
            scores["validity"] = round(valid_cols / len(numeric.columns) * 100, 2) if len(numeric.columns) > 0 else 100.0

            # Overall score
            weights = {{"completeness": 0.35, "uniqueness": 0.20, "consistency": 0.25, "validity": 0.20}}
            overall = sum(scores[k] * weights[k] for k in weights)
            scores["overall"] = round(overall, 2)

            # Grade
            if overall >= 90: grade = "A"
            elif overall >= 75: grade = "B"
            elif overall >= 60: grade = "C"
            elif overall >= 40: grade = "D"
            else: grade = "F"

            per_column = {{}}
            for col in df.columns:
                pct = round((1 - df[col].isnull().mean()) * 100, 1)
                per_column[col] = {{"completeness": pct, "dtype": str(df[col].dtype), "unique": int(df[col].nunique())}}

            print(json.dumps({{
                "scores": scores, "grade": grade,
                "shape": list(df.shape),
                "per_column": per_column,
            }}))
        """)
        return await run_code_in_sandbox(code)

    async def _anomalies(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        method = params.get("method", "isolation_forest")
        contamination = params.get("contamination", 0.05)
        if not fp:
            return {"error": "file_path required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            from sklearn.ensemble import IsolationForest
            from sklearn.preprocessing import StandardScaler

            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            numeric = df.select_dtypes(include=[np.number]).dropna()
            if len(numeric) == 0 or len(numeric.columns) == 0:
                print(json.dumps({{"error": "No numeric columns"}}))
            else:
                scaler = StandardScaler()
                X = scaler.fit_transform(numeric)
                iso = IsolationForest(contamination={contamination}, random_state=42)
                labels = iso.fit_predict(X)
                scores = iso.decision_function(X)

                anomalies = numeric[labels == -1]
                normal = numeric[labels == 1]

                print(json.dumps({{
                    "method": "{method}",
                    "contamination": {contamination},
                    "total_rows": len(numeric),
                    "anomaly_count": int(len(anomalies)),
                    "anomaly_pct": round(len(anomalies) / len(numeric) * 100, 2),
                    "anomaly_indices": anomalies.index.tolist()[:50],
                    "column_anomaly_means": {{c: round(float(anomalies[c].mean()), 4) for c in anomalies.columns}},
                    "column_normal_means": {{c: round(float(normal[c].mean()), 4) for c in normal.columns}},
                }}))
        """)
        return await run_code_in_sandbox(code, timeout=120)

    async def _duplicates(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        columns = params.get("columns", [])
        if not fp:
            return {"error": "file_path required"}
        col_arg = f"[{', '.join(repr(c) for c in columns)}]" if columns else "None"
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            subset = {col_arg}
            dupes = df[df.duplicated(subset=subset, keep=False)]
            groups = df[df.duplicated(subset=subset, keep="first")]
            print(json.dumps({{
                "total_rows": len(df),
                "duplicate_rows": int(len(dupes)),
                "duplicate_groups": int(len(groups)),
                "duplicate_pct": round(len(groups) / len(df) * 100, 2),
                "checked_columns": subset or list(df.columns),
                "sample_duplicates": json.loads(dupes.head(10).to_json(orient="records", date_format="iso")),
            }}))
        """)
        return await run_code_in_sandbox(code)

    async def _referential(self, params: dict[str, Any]) -> dict[str, Any]:
        primary_file = params.get("primary_file", "")
        primary_key = params.get("primary_key", "")
        foreign_file = params.get("foreign_file", "")
        foreign_key = params.get("foreign_key", "")
        if not all([primary_file, primary_key, foreign_file, foreign_key]):
            return {"error": "primary_file, primary_key, foreign_file, foreign_key required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            pk = pd.read_csv("{primary_file}") if "{primary_file}".endswith(".csv") else pd.read_parquet("{primary_file}")
            fk = pd.read_csv("{foreign_file}") if "{foreign_file}".endswith(".csv") else pd.read_parquet("{foreign_file}")
            pk_vals = set(pk["{primary_key}"].dropna().unique())
            fk_vals = set(fk["{foreign_key}"].dropna().unique())
            orphans = fk_vals - pk_vals
            unused = pk_vals - fk_vals
            print(json.dumps({{
                "valid": len(orphans) == 0,
                "primary_unique": len(pk_vals), "foreign_unique": len(fk_vals),
                "orphan_count": len(orphans), "unused_primary_count": len(unused),
                "orphan_values": list(orphans)[:20],
                "integrity_pct": round((1 - len(orphans) / max(len(fk_vals), 1)) * 100, 2),
            }}))
        """)
        return await run_code_in_sandbox(code)

    async def _freshness(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        date_column = params.get("date_column", "")
        if not all([fp, date_column]):
            return {"error": "file_path and date_column required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            from datetime import datetime, timezone
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            df["{date_column}"] = pd.to_datetime(df["{date_column}"], errors="coerce")
            latest = df["{date_column}"].max()
            earliest = df["{date_column}"].min()
            now = pd.Timestamp.now(tz="UTC").tz_localize(None)
            if pd.isna(latest):
                print(json.dumps({{"error": "Could not parse dates"}}))
            else:
                age = (now - latest).total_seconds() / 3600
                span = (latest - earliest).total_seconds() / 86400
                print(json.dumps({{
                    "date_column": "{date_column}",
                    "earliest": str(earliest), "latest": str(latest),
                    "age_hours": round(age, 1),
                    "span_days": round(span, 1),
                    "fresh": age < 24,
                    "row_count": len(df),
                    "null_dates": int(df["{date_column}"].isnull().sum()),
                }}))
        """)
        return await run_code_in_sandbox(code)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "validate_schema", "description": "Validate dataset schema against expected column types.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "expected_schema": {"type": "object", "description": "Map of column name to expected type"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "validate_quality_score", "description": "Compute data quality score (completeness, uniqueness, consistency, validity) with A-F grade.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "validate_anomalies", "description": "Detect anomalies using Isolation Forest.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "method": {"type": "string", "enum": ["isolation_forest"]}, "contamination": {"type": "number", "description": "Expected anomaly fraction (default 0.05)"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "validate_duplicates", "description": "Find duplicate rows, optionally scoped to specific columns.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "columns": {"type": "array", "items": {"type": "string"}}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "validate_referential", "description": "Check referential integrity between two datasets (foreign key validation).", "parameters": {"type": "object", "properties": {"primary_file": {"type": "string"}, "primary_key": {"type": "string"}, "foreign_file": {"type": "string"}, "foreign_key": {"type": "string"}}, "required": ["primary_file", "primary_key", "foreign_file", "foreign_key"]}}},
            {"type": "function", "function": {"name": "validate_freshness", "description": "Check data freshness: how old is the latest record?", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "date_column": {"type": "string"}}, "required": ["file_path", "date_column"]}}},
        ]
