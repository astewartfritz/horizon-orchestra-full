"""Data Exploration skill — profiling, distributions, missing data, outliers.

Generates and executes pandas-based profiling code, returning
structured summaries the agent can reason over.
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

from .base import Skill, run_code_in_sandbox

__all__ = ["DataExplorationSkill"]

log = logging.getLogger("orchestra.skills.exploration")


class DataExplorationSkill(Skill):
    name = "data_exploration"
    description = "Profile datasets: shape, dtypes, distributions, missing data, outliers, correlations."

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "ds_profile": self._profile,
            "ds_describe": self._describe,
            "ds_missing": self._missing,
            "ds_outliers": self._outliers,
            "ds_correlations": self._correlations,
            "ds_value_counts": self._value_counts,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    async def _profile(self, params: dict[str, Any]) -> dict[str, Any]:
        file_path = params.get("file_path", "")
        if not file_path:
            return {"error": "file_path required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json, sys
            df = pd.read_csv("{file_path}") if "{file_path}".endswith(".csv") else pd.read_parquet("{file_path}")
            profile = {{
                "shape": list(df.shape),
                "columns": list(df.columns),
                "dtypes": {{c: str(t) for c, t in df.dtypes.items()}},
                "memory_mb": round(df.memory_usage(deep=True).sum() / 1e6, 2),
                "missing_pct": {{c: round(v * 100, 1) for c, v in (df.isnull().mean()).items() if v > 0}},
                "numeric_stats": json.loads(df.describe().to_json()),
                "sample_rows": json.loads(df.head(5).to_json(orient="records", date_format="iso")),
                "duplicates": int(df.duplicated().sum()),
            }}
            print(json.dumps(profile))
        """)
        return await run_code_in_sandbox(code)

    async def _describe(self, params: dict[str, Any]) -> dict[str, Any]:
        file_path = params.get("file_path", "")
        columns = params.get("columns", [])
        if not file_path:
            return {"error": "file_path required"}
        col_filter = f"[{', '.join(repr(c) for c in columns)}]" if columns else ""
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            df = pd.read_csv("{file_path}") if "{file_path}".endswith(".csv") else pd.read_parquet("{file_path}")
            subset = df{f'[{col_filter}]' if col_filter else ''}
            desc = subset.describe(include="all").round(4)
            print(json.dumps(json.loads(desc.to_json())))
        """)
        return await run_code_in_sandbox(code)

    async def _missing(self, params: dict[str, Any]) -> dict[str, Any]:
        file_path = params.get("file_path", "")
        if not file_path:
            return {"error": "file_path required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            df = pd.read_csv("{file_path}") if "{file_path}".endswith(".csv") else pd.read_parquet("{file_path}")
            total = len(df)
            missing = df.isnull().sum()
            result = {{
                "total_rows": total,
                "columns": {{
                    c: {{"missing": int(v), "pct": round(v / total * 100, 2), "dtype": str(df[c].dtype)}}
                    for c, v in missing.items() if v > 0
                }},
                "complete_rows": int((~df.isnull().any(axis=1)).sum()),
                "complete_pct": round((~df.isnull().any(axis=1)).mean() * 100, 1),
                "strategy_suggestions": {{
                    c: "drop" if v / total > 0.5 else ("mode" if str(df[c].dtype) == "object" else "median")
                    for c, v in missing.items() if v > 0
                }},
            }}
            print(json.dumps(result))
        """)
        return await run_code_in_sandbox(code)

    async def _outliers(self, params: dict[str, Any]) -> dict[str, Any]:
        file_path = params.get("file_path", "")
        method = params.get("method", "iqr")
        if not file_path:
            return {"error": "file_path required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            df = pd.read_csv("{file_path}") if "{file_path}".endswith(".csv") else pd.read_parquet("{file_path}")
            numeric = df.select_dtypes(include=[np.number])
            result = {{"method": "{method}", "columns": {{}}}}
            for col in numeric.columns:
                vals = numeric[col].dropna()
                if "{method}" == "iqr":
                    q1, q3 = vals.quantile(0.25), vals.quantile(0.75)
                    iqr = q3 - q1
                    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                else:
                    mean, std = vals.mean(), vals.std()
                    lower, upper = mean - 3 * std, mean + 3 * std
                outliers = vals[(vals < lower) | (vals > upper)]
                if len(outliers) > 0:
                    result["columns"][col] = {{
                        "count": int(len(outliers)),
                        "pct": round(len(outliers) / len(vals) * 100, 2),
                        "lower_bound": round(float(lower), 4),
                        "upper_bound": round(float(upper), 4),
                        "min_outlier": round(float(outliers.min()), 4),
                        "max_outlier": round(float(outliers.max()), 4),
                    }}
            print(json.dumps(result))
        """)
        return await run_code_in_sandbox(code)

    async def _correlations(self, params: dict[str, Any]) -> dict[str, Any]:
        file_path = params.get("file_path", "")
        method = params.get("method", "pearson")
        threshold = params.get("threshold", 0.5)
        if not file_path:
            return {"error": "file_path required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            df = pd.read_csv("{file_path}") if "{file_path}".endswith(".csv") else pd.read_parquet("{file_path}")
            corr = df.select_dtypes(include=[np.number]).corr(method="{method}")
            strong = []
            for i in range(len(corr.columns)):
                for j in range(i + 1, len(corr.columns)):
                    val = corr.iloc[i, j]
                    if abs(val) >= {threshold}:
                        strong.append({{
                            "col_a": corr.columns[i], "col_b": corr.columns[j],
                            "correlation": round(float(val), 4),
                        }})
            strong.sort(key=lambda x: abs(x["correlation"]), reverse=True)
            print(json.dumps({{"method": "{method}", "threshold": {threshold}, "strong_correlations": strong, "matrix_shape": list(corr.shape)}}))
        """)
        return await run_code_in_sandbox(code)

    async def _value_counts(self, params: dict[str, Any]) -> dict[str, Any]:
        file_path = params.get("file_path", "")
        column = params.get("column", "")
        top_n = params.get("top_n", 20)
        if not file_path or not column:
            return {"error": "file_path and column required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            df = pd.read_csv("{file_path}") if "{file_path}".endswith(".csv") else pd.read_parquet("{file_path}")
            vc = df["{column}"].value_counts().head({top_n})
            result = {{
                "column": "{column}", "unique": int(df["{column}"].nunique()),
                "total": int(len(df)), "top_values": [
                    {{"value": str(k), "count": int(v), "pct": round(v / len(df) * 100, 2)}}
                    for k, v in vc.items()
                ],
            }}
            print(json.dumps(result))
        """)
        return await run_code_in_sandbox(code)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "ds_profile", "description": "Full dataset profile: shape, dtypes, stats, missing data, sample rows.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string", "description": "Path to CSV or Parquet file"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "ds_describe", "description": "Statistical description of columns.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "columns": {"type": "array", "items": {"type": "string"}}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "ds_missing", "description": "Analyze missing data with imputation strategy suggestions.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "ds_outliers", "description": "Detect outliers using IQR or z-score method.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "method": {"type": "string", "enum": ["iqr", "zscore"]}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "ds_correlations", "description": "Find strong correlations between numeric columns.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "method": {"type": "string", "enum": ["pearson", "spearman", "kendall"]}, "threshold": {"type": "number"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "ds_value_counts", "description": "Value frequency counts for a column.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}, "top_n": {"type": "integer"}}, "required": ["file_path", "column"]}}},
        ]
