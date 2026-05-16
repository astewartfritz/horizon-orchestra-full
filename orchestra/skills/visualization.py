"""Visualization skill — charts, dashboards, interactive plots.

Generates matplotlib/seaborn/plotly code, saves to workspace, returns paths.
"""

from __future__ import annotations

import json, logging, textwrap
from typing import Any
from .base import Skill, run_code_in_sandbox

__all__ = ["VisualizationSkill"]
log = logging.getLogger("orchestra.skills.visualization")


class VisualizationSkill(Skill):
    name = "visualization"
    description = "Generate charts: histogram, scatter, bar, line, heatmap, box, pair plot."

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "viz_histogram": self._histogram, "viz_scatter": self._scatter,
            "viz_bar": self._bar, "viz_line": self._line,
            "viz_heatmap": self._heatmap, "viz_box": self._box,
            "viz_pairplot": self._pairplot,
        }
        handler = dispatch.get(action)
        return await handler(params) if handler else {"error": f"Unknown: {action}"}

    def _preamble(self, fp: str, out: str) -> str:
        return textwrap.dedent(f"""\
            import pandas as pd, matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt, seaborn as sns, json
            plt.style.use("seaborn-v0_8-whitegrid")
            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            out = "{out}"
        """)

    def _epilogue(self, title: str) -> str:
        return textwrap.dedent(f"""\
            plt.title("{title}", fontsize=14, fontweight="bold")
            plt.tight_layout()
            plt.savefig(out, dpi=150, bbox_inches="tight")
            plt.close()
            print(json.dumps({{"chart": "{title}", "path": out}}))
        """)

    async def _histogram(self, p: dict) -> dict[str, Any]:
        fp, col = p.get("file_path", ""), p.get("column", "")
        bins = p.get("bins", 30)
        out = p.get("output", "/tmp/horizon_workspace/histogram.png")
        if not fp or not col: return {"error": "file_path, column required"}
        code = self._preamble(fp, out) + textwrap.dedent(f"""\
            fig, ax = plt.subplots(figsize=(10, 6))
            sns.histplot(df["{col}"].dropna(), bins={bins}, kde=True, ax=ax)
            ax.set_xlabel("{col}")
            ax.set_ylabel("Count")
        """) + self._epilogue(f"Distribution: {col}")
        return await run_code_in_sandbox(code)

    async def _scatter(self, p: dict) -> dict[str, Any]:
        fp, x, y = p.get("file_path", ""), p.get("x", ""), p.get("y", "")
        hue = p.get("hue", "")
        out = p.get("output", "/tmp/horizon_workspace/scatter.png")
        if not all([fp, x, y]): return {"error": "file_path, x, y required"}
        hue_arg = f', hue="{hue}"' if hue else ""
        code = self._preamble(fp, out) + textwrap.dedent(f"""\
            fig, ax = plt.subplots(figsize=(10, 6))
            sns.scatterplot(data=df, x="{x}", y="{y}"{hue_arg}, alpha=0.6, ax=ax)
        """) + self._epilogue(f"{y} vs {x}")
        return await run_code_in_sandbox(code)

    async def _bar(self, p: dict) -> dict[str, Any]:
        fp, x, y = p.get("file_path", ""), p.get("x", ""), p.get("y", "")
        agg = p.get("aggregation", "mean")
        out = p.get("output", "/tmp/horizon_workspace/bar.png")
        if not all([fp, x, y]): return {"error": "file_path, x, y required"}
        code = self._preamble(fp, out) + textwrap.dedent(f"""\
            agg_df = df.groupby("{x}")["{y}"].{agg}().sort_values(ascending=False).head(20).reset_index()
            fig, ax = plt.subplots(figsize=(12, 6))
            sns.barplot(data=agg_df, x="{x}", y="{y}", ax=ax)
            plt.xticks(rotation=45, ha="right")
        """) + self._epilogue(f"{agg.title()} {y} by {x}")
        return await run_code_in_sandbox(code)

    async def _line(self, p: dict) -> dict[str, Any]:
        fp, x, y = p.get("file_path", ""), p.get("x", ""), p.get("y", "")
        out = p.get("output", "/tmp/horizon_workspace/line.png")
        if not all([fp, x, y]): return {"error": "file_path, x, y required"}
        code = self._preamble(fp, out) + textwrap.dedent(f"""\
            fig, ax = plt.subplots(figsize=(12, 6))
            df_sorted = df.sort_values("{x}")
            ax.plot(df_sorted["{x}"], df_sorted["{y}"], marker="o", markersize=3, linewidth=1.5)
            ax.set_xlabel("{x}")
            ax.set_ylabel("{y}")
            plt.xticks(rotation=45, ha="right")
        """) + self._epilogue(f"{y} over {x}")
        return await run_code_in_sandbox(code)

    async def _heatmap(self, p: dict) -> dict[str, Any]:
        fp = p.get("file_path", "")
        out = p.get("output", "/tmp/horizon_workspace/heatmap.png")
        if not fp: return {"error": "file_path required"}
        code = self._preamble(fp, out) + textwrap.dedent("""\
            import numpy as np
            corr = df.select_dtypes(include=[np.number]).corr()
            fig, ax = plt.subplots(figsize=(12, 10))
            sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, square=True, ax=ax, linewidths=0.5)
        """) + self._epilogue("Correlation Heatmap")
        return await run_code_in_sandbox(code)

    async def _box(self, p: dict) -> dict[str, Any]:
        fp, col = p.get("file_path", ""), p.get("column", "")
        group = p.get("group_by", "")
        out = p.get("output", "/tmp/horizon_workspace/box.png")
        if not fp or not col: return {"error": "file_path, column required"}
        group_arg = f', x="{group}"' if group else ""
        code = self._preamble(fp, out) + textwrap.dedent(f"""\
            fig, ax = plt.subplots(figsize=(10, 6))
            sns.boxplot(data=df, y="{col}"{group_arg}, ax=ax)
            if "{group}": plt.xticks(rotation=45, ha="right")
        """) + self._epilogue(f"Box Plot: {col}")
        return await run_code_in_sandbox(code)

    async def _pairplot(self, p: dict) -> dict[str, Any]:
        fp = p.get("file_path", "")
        columns = p.get("columns", [])
        hue = p.get("hue", "")
        out = p.get("output", "/tmp/horizon_workspace/pairplot.png")
        if not fp: return {"error": "file_path required"}
        col_str = f"[{', '.join(repr(c) for c in columns)}]" if columns else ""
        hue_arg = f', hue="{hue}"' if hue else ""
        code = self._preamble(fp, out) + textwrap.dedent(f"""\
            subset = df{f'[{col_str}]' if col_str else '.select_dtypes(include="number").iloc[:, :6]'}
            g = sns.pairplot(subset{hue_arg}, diag_kind="kde", plot_kws={{"alpha": 0.5}})
            g.fig.suptitle("Pair Plot", y=1.02, fontsize=14, fontweight="bold")
            g.savefig(out, dpi=120, bbox_inches="tight")
            plt.close()
            print(json.dumps({{"chart": "pair_plot", "path": out}}))
        """)
        return await run_code_in_sandbox(code)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "viz_histogram", "description": "Histogram with KDE for a numeric column.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}, "bins": {"type": "integer"}, "output": {"type": "string"}}, "required": ["file_path", "column"]}}},
            {"type": "function", "function": {"name": "viz_scatter", "description": "Scatter plot of two columns, optional hue.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "x": {"type": "string"}, "y": {"type": "string"}, "hue": {"type": "string"}, "output": {"type": "string"}}, "required": ["file_path", "x", "y"]}}},
            {"type": "function", "function": {"name": "viz_bar", "description": "Bar chart with aggregation (mean, sum, count, etc).", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "x": {"type": "string"}, "y": {"type": "string"}, "aggregation": {"type": "string", "enum": ["mean", "sum", "count", "median", "max", "min"]}, "output": {"type": "string"}}, "required": ["file_path", "x", "y"]}}},
            {"type": "function", "function": {"name": "viz_line", "description": "Line chart for time series or ordered data.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "x": {"type": "string"}, "y": {"type": "string"}, "output": {"type": "string"}}, "required": ["file_path", "x", "y"]}}},
            {"type": "function", "function": {"name": "viz_heatmap", "description": "Correlation heatmap of all numeric columns.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "output": {"type": "string"}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "viz_box", "description": "Box plot for a column, optionally grouped.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "column": {"type": "string"}, "group_by": {"type": "string"}, "output": {"type": "string"}}, "required": ["file_path", "column"]}}},
            {"type": "function", "function": {"name": "viz_pairplot", "description": "Pair plot matrix for numeric columns.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "columns": {"type": "array", "items": {"type": "string"}}, "hue": {"type": "string"}, "output": {"type": "string"}}, "required": ["file_path"]}}},
        ]
