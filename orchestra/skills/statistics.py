"""Statistical Analysis skill — hypothesis testing, regression, correlation.

Generates scipy/statsmodels code for rigorous statistical tests.
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

from .base import Skill, run_code_in_sandbox

__all__ = ["StatisticalAnalysisSkill"]
log = logging.getLogger("orchestra.skills.statistics")


class StatisticalAnalysisSkill(Skill):
    name = "statistical_analysis"
    description = "Hypothesis testing, regression, ANOVA, chi-square, normality tests, and confidence intervals."

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "stats_ttest": self._ttest,
            "stats_anova": self._anova,
            "stats_chi_square": self._chi_square,
            "stats_regression": self._regression,
            "stats_normality": self._normality,
            "stats_confidence_interval": self._ci,
        }
        handler = dispatch.get(action)
        return await handler(params) if handler else {"error": f"Unknown: {action}"}

    async def _ttest(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        col_a = params.get("column_a", "")
        col_b = params.get("column_b", "")
        test_type = params.get("test_type", "independent")
        if not all([fp, col_a, col_b]):
            return {"error": "file_path, column_a, column_b required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            from scipy import stats
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            a, b = df["{col_a}"].dropna(), df["{col_b}"].dropna()
            if "{test_type}" == "paired":
                t, p = stats.ttest_rel(a[:min(len(a),len(b))], b[:min(len(a),len(b))])
            else:
                t, p = stats.ttest_ind(a, b)
            d = (a.mean() - b.mean()) / ((a.std()**2 + b.std()**2) / 2)**0.5
            print(json.dumps({{"test": "t-test ({test_type})", "t_statistic": round(float(t), 4), "p_value": round(float(p), 6), "significant_005": p < 0.05, "effect_size_d": round(float(d), 4), "mean_a": round(float(a.mean()), 4), "mean_b": round(float(b.mean()), 4), "n_a": len(a), "n_b": len(b)}}))
        """)
        return await run_code_in_sandbox(code)

    async def _anova(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        value_col = params.get("value_column", "")
        group_col = params.get("group_column", "")
        if not all([fp, value_col, group_col]):
            return {"error": "file_path, value_column, group_column required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            from scipy import stats
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            groups = [g["{value_col}"].dropna().values for _, g in df.groupby("{group_col}")]
            f, p = stats.f_oneway(*groups)
            group_stats = df.groupby("{group_col}")["{value_col}"].agg(["mean","std","count"]).round(4).to_dict("index")
            print(json.dumps({{"test": "one-way ANOVA", "f_statistic": round(float(f), 4), "p_value": round(float(p), 6), "significant_005": p < 0.05, "n_groups": len(groups), "group_stats": group_stats}}))
        """)
        return await run_code_in_sandbox(code)

    async def _chi_square(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        col_a = params.get("column_a", "")
        col_b = params.get("column_b", "")
        if not all([fp, col_a, col_b]):
            return {"error": "file_path, column_a, column_b required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            from scipy import stats
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            ct = pd.crosstab(df["{col_a}"], df["{col_b}"])
            chi2, p, dof, expected = stats.chi2_contingency(ct)
            n = ct.sum().sum()
            v = (chi2 / (n * (min(ct.shape) - 1)))**0.5
            print(json.dumps({{"test": "chi-square", "chi2": round(float(chi2), 4), "p_value": round(float(p), 6), "dof": int(dof), "significant_005": p < 0.05, "cramers_v": round(float(v), 4), "contingency_shape": list(ct.shape)}}))
        """)
        return await run_code_in_sandbox(code)

    async def _regression(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        target = params.get("target", "")
        features = params.get("features", [])
        if not all([fp, target, features]):
            return {"error": "file_path, target, features required"}
        feat_str = ", ".join(f'"{f}"' for f in features)
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            from sklearn.linear_model import LinearRegression
            from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
            from sklearn.model_selection import train_test_split
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            feat_cols = [{feat_str}]
            df_clean = df[feat_cols + ["{target}"]].dropna()
            X, y = df_clean[feat_cols], df_clean["{target}"]
            X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
            model = LinearRegression().fit(X_tr, y_tr)
            pred = model.predict(X_te)
            coefs = dict(zip(feat_cols, [round(float(c), 6) for c in model.coef_]))
            print(json.dumps({{
                "type": "linear_regression", "target": "{target}", "features": feat_cols,
                "r2_train": round(float(model.score(X_tr, y_tr)), 4),
                "r2_test": round(float(r2_score(y_te, pred)), 4),
                "rmse": round(float(mean_squared_error(y_te, pred)**0.5), 4),
                "mae": round(float(mean_absolute_error(y_te, pred)), 4),
                "intercept": round(float(model.intercept_), 6),
                "coefficients": coefs, "n_train": len(X_tr), "n_test": len(X_te),
            }}))
        """)
        return await run_code_in_sandbox(code)

    async def _normality(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        column = params.get("column", "")
        if not all([fp, column]):
            return {"error": "file_path and column required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            from scipy import stats
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            vals = df["{column}"].dropna()
            sw_stat, sw_p = stats.shapiro(vals[:5000])
            ks_stat, ks_p = stats.kstest(vals, "norm", args=(vals.mean(), vals.std()))
            skew, kurt = float(vals.skew()), float(vals.kurtosis())
            print(json.dumps({{
                "column": "{column}", "n": len(vals),
                "shapiro_wilk": {{"statistic": round(float(sw_stat), 4), "p_value": round(float(sw_p), 6), "normal": sw_p > 0.05}},
                "kolmogorov_smirnov": {{"statistic": round(float(ks_stat), 4), "p_value": round(float(ks_p), 6), "normal": ks_p > 0.05}},
                "skewness": round(skew, 4), "kurtosis": round(kurt, 4),
                "verdict": "likely normal" if sw_p > 0.05 and abs(skew) < 1 else "not normal",
            }}))
        """)
        return await run_code_in_sandbox(code)

    async def _ci(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        column = params.get("column", "")
        confidence = params.get("confidence", 0.95)
        if not all([fp, column]):
            return {"error": "file_path and column required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json
            from scipy import stats
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            vals = df["{column}"].dropna()
            mean = float(vals.mean())
            se = float(vals.std() / len(vals)**0.5)
            ci = stats.t.interval({confidence}, len(vals)-1, loc=mean, scale=se)
            print(json.dumps({{
                "column": "{column}", "confidence": {confidence}, "mean": round(mean, 4),
                "std_error": round(se, 4), "ci_lower": round(float(ci[0]), 4), "ci_upper": round(float(ci[1]), 4),
                "n": len(vals), "margin_of_error": round(float(ci[1] - mean), 4),
            }}))
        """)
        return await run_code_in_sandbox(code)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "stats_ttest", "description": "T-test between two columns (independent or paired).", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "column_a": {"type": "string"}, "column_b": {"type": "string"}, "test_type": {"type": "string", "enum": ["independent", "paired"]}}, "required": ["file_path", "column_a", "column_b"]}}},
            {"type": "function", "function": {"name": "stats_anova", "description": "One-way ANOVA: compare means across groups.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "value_column": {"type": "string"}, "group_column": {"type": "string"}}, "required": ["file_path", "value_column", "group_column"]}}},
            {"type": "function", "function": {"name": "stats_chi_square", "description": "Chi-square test of independence between two categorical columns.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "column_a": {"type": "string"}, "column_b": {"type": "string"}}, "required": ["file_path", "column_a", "column_b"]}}},
            {"type": "function", "function": {"name": "stats_regression", "description": "Linear regression with train/test split, coefficients, R2, RMSE.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "target": {"type": "string"}, "features": {"type": "array", "items": {"type": "string"}}}, "required": ["file_path", "target", "features"]}}},
            {"type": "function", "function": {"name": "stats_normality", "description": "Normality test (Shapiro-Wilk + KS) for a column.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}}, "required": ["file_path", "column"]}}},
            {"type": "function", "function": {"name": "stats_confidence_interval", "description": "Confidence interval for a column's mean.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}, "confidence": {"type": "number"}}, "required": ["file_path", "column"]}}},
        ]
