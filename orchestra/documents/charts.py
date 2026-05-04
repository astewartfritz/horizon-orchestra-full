"""Horizon Orchestra — Chart / Visualization Generation.

Generate charts and visualizations using matplotlib (preferred) with
plotly fallback.  Supports bar charts, line charts, pie charts, scatter
plots, heatmaps, and dashboard layouts.

Usage::

    from orchestra.documents.charts import ChartGenerator

    gen = ChartGenerator()
    img = gen.bar_chart({"Q1": 100, "Q2": 150, "Q3": 120}, title="Revenue")
"""

from __future__ import annotations

import io
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence, Union

__all__ = [
    "ChartGenerator",
]

log = logging.getLogger("orchestra.documents.charts")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_docs"))

# Optional dependency: matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    from matplotlib.figure import Figure
    _HAS_MPL = True
except ImportError:
    plt = None  # type: ignore[assignment]
    _HAS_MPL = False

# Optional dependency: plotly
try:
    import plotly.graph_objects as go
    import plotly.io as pio
    _HAS_PLOTLY = True
except ImportError:
    go = None  # type: ignore[assignment]
    pio = None  # type: ignore[assignment]
    _HAS_PLOTLY = False

# Optional dependency: numpy
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore[assignment]
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Horizon Brand Colors
# ---------------------------------------------------------------------------

HORIZON_COLORS = [
    "#3B82F6",  # Blue
    "#10B981",  # Emerald
    "#F59E0B",  # Amber
    "#EF4444",  # Red
    "#8B5CF6",  # Purple
    "#06B6D4",  # Cyan
    "#F97316",  # Orange
    "#EC4899",  # Pink
    "#14B8A6",  # Teal
    "#6366F1",  # Indigo
]

HORIZON_BG = "#FFFFFF"
HORIZON_TEXT = "#1A1A1A"
HORIZON_GRID = "#E5E7EB"
HORIZON_AXIS = "#6B7280"


# ---------------------------------------------------------------------------
# ChartGenerator
# ---------------------------------------------------------------------------

class ChartGenerator:
    """Chart and visualization generator with consistent Horizon styling.

    Parameters
    ----------
    workspace:
        Directory for saving output files.
    figsize:
        Default figure size as (width, height) in inches.
    dpi:
        Default DPI for rendered images.
    style:
        Matplotlib style name (``"seaborn-v0_8-whitegrid"``, etc.).
    """

    def __init__(
        self,
        workspace: str | Path | None = None,
        figsize: tuple[float, float] = (10, 6),
        dpi: int = 150,
        style: str = "",
    ) -> None:
        if not _HAS_MPL and not _HAS_PLOTLY:
            raise ImportError(
                "matplotlib or plotly is required for chart generation: "
                "pip install matplotlib  (or)  pip install plotly"
            )
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "charts"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._figsize = figsize
        self._dpi = dpi
        self._style = style

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_path(self, ext: str = "png") -> Path:
        return self.workspace / f"{uuid.uuid4().hex[:12]}.{ext}"

    def _apply_horizon_style(self, ax: Any) -> None:
        """Apply Horizon brand styling to a matplotlib axes."""
        ax.set_facecolor(HORIZON_BG)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(HORIZON_GRID)
        ax.spines["bottom"].set_color(HORIZON_GRID)
        ax.tick_params(colors=HORIZON_AXIS, labelsize=10)
        ax.yaxis.grid(True, color=HORIZON_GRID, linestyle="-", linewidth=0.5, alpha=0.7)
        ax.xaxis.grid(False)
        ax.title.set_color(HORIZON_TEXT)
        ax.title.set_fontsize(14)
        ax.title.set_fontweight("bold")

    def _fig_to_bytes(self, fig: Any, fmt: str = "png") -> bytes:
        """Convert a matplotlib figure to bytes."""
        buffer = io.BytesIO()
        fig.savefig(buffer, format=fmt, dpi=self._dpi, bbox_inches="tight",
                    facecolor=HORIZON_BG, edgecolor="none")
        plt.close(fig)
        return buffer.getvalue()

    def _normalize_data(
        self,
        data: dict[str, float] | Sequence[float] | Any,
        labels: Sequence[str] | None = None,
    ) -> tuple[list[str], list[float]]:
        """Normalize various data formats to (labels, values)."""
        if isinstance(data, dict):
            return list(data.keys()), list(data.values())
        values = list(data)
        if labels:
            return list(labels), values
        return [str(i) for i in range(len(values))], values

    # ------------------------------------------------------------------
    # Bar chart
    # ------------------------------------------------------------------

    def bar_chart(
        self,
        data: dict[str, float] | Sequence[float],
        title: str = "",
        labels: Sequence[str] | None = None,
        *,
        xlabel: str = "",
        ylabel: str = "",
        horizontal: bool = False,
        colors: Sequence[str] | None = None,
        figsize: tuple[float, float] | None = None,
    ) -> bytes:
        """Generate a bar chart.

        Parameters
        ----------
        data:
            Dict of {label: value} or list of values.
        title:
            Chart title.
        labels:
            X-axis labels (if data is a list).
        xlabel, ylabel:
            Axis labels.
        horizontal:
            If *True*, draw horizontal bars.
        colors:
            Custom bar colors.
        figsize:
            Figure size override.

        Returns
        -------
        bytes
            PNG image data.
        """
        if not _HAS_MPL:
            return self._bar_chart_plotly(data, title, labels)

        cats, vals = self._normalize_data(data, labels)
        bar_colors = list(colors or HORIZON_COLORS)

        fig, ax = plt.subplots(figsize=figsize or self._figsize)
        self._apply_horizon_style(ax)

        color_list = [bar_colors[i % len(bar_colors)] for i in range(len(cats))]

        if horizontal:
            ax.barh(cats, vals, color=color_list, edgecolor="none", height=0.6)
            if xlabel:
                ax.set_xlabel(xlabel, color=HORIZON_AXIS)
            if ylabel:
                ax.set_ylabel(ylabel, color=HORIZON_AXIS)
        else:
            ax.bar(cats, vals, color=color_list, edgecolor="none", width=0.6)
            if xlabel:
                ax.set_xlabel(xlabel, color=HORIZON_AXIS)
            if ylabel:
                ax.set_ylabel(ylabel, color=HORIZON_AXIS)
            plt.xticks(rotation=45, ha="right")

        if title:
            ax.set_title(title, pad=16)

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    def _bar_chart_plotly(
        self,
        data: dict[str, float] | Sequence[float],
        title: str = "",
        labels: Sequence[str] | None = None,
    ) -> bytes:
        """Plotly fallback for bar chart."""
        cats, vals = self._normalize_data(data, labels)
        fig = go.Figure(data=[go.Bar(x=cats, y=vals, marker_color=HORIZON_COLORS[0])])
        fig.update_layout(title=title, template="plotly_white")
        return pio.to_image(fig, format="png", width=1000, height=600)

    # ------------------------------------------------------------------
    # Line chart
    # ------------------------------------------------------------------

    def line_chart(
        self,
        data: dict[str, Sequence[float]] | Sequence[float],
        title: str = "",
        labels: Sequence[str] | None = None,
        *,
        xlabel: str = "",
        ylabel: str = "",
        markers: bool = True,
        figsize: tuple[float, float] | None = None,
    ) -> bytes:
        """Generate a line chart.

        Parameters
        ----------
        data:
            Dict of {series_name: values} for multi-line, or a single
            list of values.
        title:
            Chart title.
        labels:
            X-axis labels.
        xlabel, ylabel:
            Axis labels.
        markers:
            Show data point markers.
        figsize:
            Figure size override.

        Returns
        -------
        bytes
            PNG image data.
        """
        if not _HAS_MPL:
            return self._line_chart_plotly(data, title, labels)

        fig, ax = plt.subplots(figsize=figsize or self._figsize)
        self._apply_horizon_style(ax)

        if isinstance(data, dict):
            for i, (name, values) in enumerate(data.items()):
                color = HORIZON_COLORS[i % len(HORIZON_COLORS)]
                marker = "o" if markers else ""
                x = list(labels) if labels else list(range(len(values)))
                ax.plot(x, values, label=name, color=color, marker=marker,
                        linewidth=2, markersize=6)
            ax.legend(frameon=False, fontsize=10)
        else:
            x = list(labels) if labels else list(range(len(data)))
            marker = "o" if markers else ""
            ax.plot(x, list(data), color=HORIZON_COLORS[0], marker=marker,
                    linewidth=2, markersize=6)

        if xlabel:
            ax.set_xlabel(xlabel, color=HORIZON_AXIS)
        if ylabel:
            ax.set_ylabel(ylabel, color=HORIZON_AXIS)
        if title:
            ax.set_title(title, pad=16)

        if labels:
            plt.xticks(rotation=45, ha="right")

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    def _line_chart_plotly(
        self,
        data: dict[str, Sequence[float]] | Sequence[float],
        title: str = "",
        labels: Sequence[str] | None = None,
    ) -> bytes:
        """Plotly fallback for line chart."""
        fig = go.Figure()
        if isinstance(data, dict):
            for i, (name, values) in enumerate(data.items()):
                x = list(labels) if labels else list(range(len(values)))
                fig.add_trace(go.Scatter(x=x, y=list(values), name=name,
                                         line=dict(color=HORIZON_COLORS[i % len(HORIZON_COLORS)])))
        else:
            x = list(labels) if labels else list(range(len(data)))
            fig.add_trace(go.Scatter(x=x, y=list(data), line=dict(color=HORIZON_COLORS[0])))
        fig.update_layout(title=title, template="plotly_white")
        return pio.to_image(fig, format="png", width=1000, height=600)

    # ------------------------------------------------------------------
    # Pie chart
    # ------------------------------------------------------------------

    def pie_chart(
        self,
        data: dict[str, float] | Sequence[float],
        labels: Sequence[str] | None = None,
        title: str = "",
        *,
        explode: Sequence[float] | None = None,
        show_pct: bool = True,
        figsize: tuple[float, float] | None = None,
    ) -> bytes:
        """Generate a pie chart.

        Parameters
        ----------
        data:
            Dict of {label: value} or list of values.
        labels:
            Slice labels (if data is a list).
        title:
            Chart title.
        explode:
            Explode offset for each slice.
        show_pct:
            Show percentage labels.
        figsize:
            Figure size override.

        Returns
        -------
        bytes
            PNG image data.
        """
        if not _HAS_MPL:
            return self._pie_chart_plotly(data, labels, title)

        cats, vals = self._normalize_data(data, labels)
        n = len(cats)
        colors = [HORIZON_COLORS[i % len(HORIZON_COLORS)] for i in range(n)]

        fig, ax = plt.subplots(figsize=figsize or (8, 8))
        ax.set_facecolor(HORIZON_BG)

        wedge_kwargs = {"edgecolor": "white", "linewidth": 2}
        autopct = "%1.1f%%" if show_pct else ""

        ax.pie(
            vals,
            labels=cats,
            colors=colors,
            autopct=autopct,
            startangle=90,
            explode=explode,
            wedgeprops=wedge_kwargs,
            textprops={"fontsize": 11, "color": HORIZON_TEXT},
        )

        if title:
            ax.set_title(title, fontsize=14, fontweight="bold", color=HORIZON_TEXT, pad=20)

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    def _pie_chart_plotly(
        self,
        data: dict[str, float] | Sequence[float],
        labels: Sequence[str] | None = None,
        title: str = "",
    ) -> bytes:
        """Plotly fallback for pie chart."""
        cats, vals = self._normalize_data(data, labels)
        fig = go.Figure(data=[go.Pie(labels=cats, values=vals,
                                      marker=dict(colors=HORIZON_COLORS[:len(cats)]))])
        fig.update_layout(title=title, template="plotly_white")
        return pio.to_image(fig, format="png", width=800, height=800)

    # ------------------------------------------------------------------
    # Scatter plot
    # ------------------------------------------------------------------

    def scatter_plot(
        self,
        x: Sequence[float],
        y: Sequence[float],
        title: str = "",
        *,
        xlabel: str = "",
        ylabel: str = "",
        size: Sequence[float] | float = 40,
        color: str = "",
        figsize: tuple[float, float] | None = None,
    ) -> bytes:
        """Generate a scatter plot.

        Parameters
        ----------
        x:
            X-axis values.
        y:
            Y-axis values.
        title:
            Chart title.
        xlabel, ylabel:
            Axis labels.
        size:
            Marker size(s).
        color:
            Marker color.
        figsize:
            Figure size override.

        Returns
        -------
        bytes
            PNG image data.
        """
        if not _HAS_MPL:
            return self._scatter_plotly(x, y, title)

        fig, ax = plt.subplots(figsize=figsize or self._figsize)
        self._apply_horizon_style(ax)

        ax.scatter(
            x, y,
            s=size,
            c=color or HORIZON_COLORS[0],
            alpha=0.7,
            edgecolors="white",
            linewidth=0.5,
        )

        if xlabel:
            ax.set_xlabel(xlabel, color=HORIZON_AXIS)
        if ylabel:
            ax.set_ylabel(ylabel, color=HORIZON_AXIS)
        if title:
            ax.set_title(title, pad=16)

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    def _scatter_plotly(
        self,
        x: Sequence[float],
        y: Sequence[float],
        title: str = "",
    ) -> bytes:
        """Plotly fallback for scatter plot."""
        fig = go.Figure(data=[go.Scatter(x=list(x), y=list(y), mode="markers",
                                          marker=dict(color=HORIZON_COLORS[0]))])
        fig.update_layout(title=title, template="plotly_white")
        return pio.to_image(fig, format="png", width=1000, height=600)

    # ------------------------------------------------------------------
    # Heatmap
    # ------------------------------------------------------------------

    def heatmap(
        self,
        data: Sequence[Sequence[float]] | Any,
        labels: Sequence[str] | None = None,
        title: str = "",
        *,
        x_labels: Sequence[str] | None = None,
        y_labels: Sequence[str] | None = None,
        cmap: str = "Blues",
        annotate: bool = True,
        figsize: tuple[float, float] | None = None,
    ) -> bytes:
        """Generate a heatmap.

        Parameters
        ----------
        data:
            2D array of values (or numpy array).
        labels:
            Deprecated — use *x_labels* and *y_labels*.
        title:
            Chart title.
        x_labels:
            Column labels.
        y_labels:
            Row labels.
        cmap:
            Matplotlib colormap name.
        annotate:
            Show values in cells.
        figsize:
            Figure size override.

        Returns
        -------
        bytes
            PNG image data.
        """
        if not _HAS_MPL:
            raise ImportError("matplotlib is required for heatmaps: pip install matplotlib")

        if _HAS_NUMPY:
            arr = np.array(data)
        else:
            arr = data

        nrows = len(arr)
        ncols = len(arr[0]) if nrows else 0

        fig, ax = plt.subplots(figsize=figsize or (max(8, ncols * 1.2), max(6, nrows * 0.8)))
        ax.set_facecolor(HORIZON_BG)

        im = ax.imshow(arr, cmap=cmap, aspect="auto")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        xl = list(x_labels or labels or [str(i) for i in range(ncols)])
        yl = list(y_labels or [str(i) for i in range(nrows)])

        ax.set_xticks(range(ncols))
        ax.set_xticklabels(xl, rotation=45, ha="right", fontsize=10)
        ax.set_yticks(range(nrows))
        ax.set_yticklabels(yl, fontsize=10)

        if annotate:
            for i in range(nrows):
                for j in range(ncols):
                    val = arr[i][j] if _HAS_NUMPY else arr[i][j]
                    ax.text(j, i, f"{val:.1f}", ha="center", va="center",
                            fontsize=9, color="black" if val < (max(max(row) for row in arr) * 0.7) else "white")

        if title:
            ax.set_title(title, fontsize=14, fontweight="bold", color=HORIZON_TEXT, pad=16)

        fig.tight_layout()
        return self._fig_to_bytes(fig)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def dashboard(
        self,
        charts: Sequence[dict[str, Any]],
        layout: str = "auto",
        title: str = "",
    ) -> str:
        """Generate an HTML dashboard from multiple chart specifications.

        Parameters
        ----------
        charts:
            List of chart dicts, each with:
            - ``type``: chart type (``bar``, ``line``, ``pie``, ``scatter``)
            - ``data``: chart data
            - ``title``: chart title
            - additional kwargs for the chart function
        layout:
            Layout mode (``auto``, ``2x2``, ``3x1``, ``1x3``).
        title:
            Dashboard title.

        Returns
        -------
        str
            HTML string containing the dashboard.
        """
        import base64

        chart_images: list[str] = []
        for spec in charts:
            chart_type = spec.get("type", "bar")
            chart_data = spec.get("data", {})
            chart_title = spec.get("title", "")
            kwargs = {k: v for k, v in spec.items() if k not in ("type", "data", "title")}

            method_map = {
                "bar": self.bar_chart,
                "line": self.line_chart,
                "pie": self.pie_chart,
                "scatter": self.scatter_plot,
            }
            method = method_map.get(chart_type, self.bar_chart)

            if chart_type == "scatter":
                img_bytes = method(
                    x=chart_data.get("x", []),
                    y=chart_data.get("y", []),
                    title=chart_title,
                    **kwargs,
                )
            else:
                img_bytes = method(chart_data, title=chart_title, **kwargs)

            b64 = base64.b64encode(img_bytes).decode("utf-8")
            chart_images.append(f'<img src="data:image/png;base64,{b64}" alt="{chart_title}" />')

        # Determine grid layout
        n = len(chart_images)
        if layout == "auto":
            if n <= 2:
                cols = n
            elif n <= 4:
                cols = 2
            else:
                cols = 3
        elif layout == "2x2":
            cols = 2
        elif layout == "3x1":
            cols = 3
        elif layout == "1x3":
            cols = 3
        else:
            cols = 2

        charts_html = "\n".join(
            f'<div class="chart-cell">{img}</div>' for img in chart_images
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title or "Dashboard"}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            background: {HORIZON_BG};
            color: {HORIZON_TEXT};
            padding: 24px;
        }}
        h1 {{
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 24px;
            color: {HORIZON_TEXT};
        }}
        .dashboard-grid {{
            display: grid;
            grid-template-columns: repeat({cols}, 1fr);
            gap: 16px;
        }}
        .chart-cell {{
            background: white;
            border-radius: 8px;
            padding: 16px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .chart-cell img {{
            max-width: 100%;
            height: auto;
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    {"<h1>" + title + "</h1>" if title else ""}
    <div class="dashboard-grid">
        {charts_html}
    </div>
</body>
</html>"""

    def save(self, image_bytes: bytes, path: str | Path | None = None, ext: str = "png") -> Path:
        """Save chart image to a file.

        Parameters
        ----------
        image_bytes:
            Image content.
        path:
            Output path.
        ext:
            Image format extension.

        Returns
        -------
        Path
            Saved file path.
        """
        save_to = Path(path) if path else self._save_path(ext)
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_bytes(image_bytes)
        log.info("Saved chart → %s (%d bytes)", save_to, len(image_bytes))
        return save_to
