from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ChartType(Enum):
    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    AREA = "area"
    BOX = "box"
    HEATMAP = "heatmap"


@dataclass
class ChartConfig:
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    width: int = 800
    height: int = 500
    color: str = "#4f8cf7"
    colors: list[str] = field(default_factory=lambda: ["#4f8cf7", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#3498db"])
    show_legend: bool = True
    show_grid: bool = True
    border: bool = True
    stacked: bool = False


_TEMPLATES: dict[ChartType, str] = {
    ChartType.LINE: """<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: bold 16px sans-serif; fill: #333; }}
    .axis {{ stroke: #ccc; stroke-width: 1; }}
    .line {{ fill: none; stroke: {color}; stroke-width: 2; }}
    .dot {{ fill: {color}; r: 3; }}
    .label {{ font: 11px sans-serif; fill: #666; }}
    .grid {{ stroke: #eee; stroke-width: 1; }}
  </style>
  <text x="{hw}" y="25" text-anchor="middle" class="title">{title}</text>
  {grid_lines}
  {axes}
  {lines}
  {labels}
  {legend}
</svg>""",
    ChartType.BAR: """<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: bold 16px sans-serif; fill: #333; }}
    .axis {{ stroke: #ccc; stroke-width: 1; }}
    .bar {{ fill: {color}; }}
    .label {{ font: 11px sans-serif; fill: #666; text-anchor: middle; }}
    .grid {{ stroke: #eee; stroke-width: 1; }}
  </style>
  <text x="{hw}" y="25" text-anchor="middle" class="title">{title}</text>
  {grid_lines}
  {axes}
  {bars}
  {labels}
  {legend}
</svg>""",
    ChartType.PIE: """<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: bold 16px sans-serif; fill: #333; }}
    .label {{ font: 11px sans-serif; fill: #666; }}
    .legend-text {{ font: 12px sans-serif; fill: #333; }}
  </style>
  <text x="{hw}" y="25" text-anchor="middle" class="title">{title}</text>
  {slices}
  {legend}
</svg>""",
    ChartType.SCATTER: """<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: bold 16px sans-serif; fill: #333; }}
    .axis {{ stroke: #ccc; stroke-width: 1; }}
    .dot {{ fill: {color}; opacity: 0.7; }}
    .label {{ font: 11px sans-serif; fill: #666; }}
    .grid {{ stroke: #eee; stroke-width: 1; }}
  </style>
  <text x="{hw}" y="25" text-anchor="middle" class="title">{title}</text>
  {grid_lines}
  {axes}
  {dots}
  {labels}
</svg>""",
    ChartType.HISTOGRAM: """<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: bold 16px sans-serif; fill: #333; }}
    .axis {{ stroke: #ccc; stroke-width: 1; }}
    .bar {{ fill: {color}; }}
    .label {{ font: 11px sans-serif; fill: #666; text-anchor: middle; }}
    .grid {{ stroke: #eee; stroke-width: 1; }}
  </style>
  <text x="{hw}" y="25" text-anchor="middle" class="title">{title}</text>
  {grid_lines}
  {axes}
  {bars}
  {labels}
</svg>""",
    ChartType.AREA: """<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: bold 16px sans-serif; fill: #333; }}
    .axis {{ stroke: #ccc; stroke-width: 1; }}
    .area {{ fill: {color}; opacity: 0.3; }}
    .line {{ fill: none; stroke: {color}; stroke-width: 2; }}
    .dot {{ fill: {color}; r: 3; }}
    .label {{ font: 11px sans-serif; fill: #666; }}
    .grid {{ stroke: #eee; stroke-width: 1; }}
  </style>
  <text x="{hw}" y="25" text-anchor="middle" class="title">{title}</text>
  {grid_lines}
  {axes}
  {area_path}
  {line_path}
  {dots}
  {labels}
</svg>""",
    ChartType.BOX: """<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: bold 16px sans-serif; fill: #333; }}
    .axis {{ stroke: #ccc; stroke-width: 1; }}
    .box {{ fill: {color}; opacity: 0.6; stroke: #333; }}
    .median {{ stroke: #333; stroke-width: 2; }}
    .whisker {{ stroke: #333; stroke-width: 1; }}
    .label {{ font: 11px sans-serif; fill: #666; text-anchor: middle; }}
    .grid {{ stroke: #eee; stroke-width: 1; }}
  </style>
  <text x="{hw}" y="25" text-anchor="middle" class="title">{title}</text>
  {grid_lines} {axes} {box_plot} {labels}
</svg>""",
}


class DataVizEngine:
    def __init__(self):
        self.config = ChartConfig()

    def line_chart(self, data: list[dict], x_key: str, y_key: str, config: Optional[ChartConfig] = None) -> str:
        cfg = config or self.config
        return self._render_svg(ChartType.LINE, data, x_key, y_key, cfg)

    def bar_chart(self, data: list[dict], x_key: str, y_key: str, config: Optional[ChartConfig] = None) -> str:
        cfg = config or self.config
        return self._render_svg(ChartType.BAR, data, x_key, y_key, cfg)

    def pie_chart(self, data: list[dict], label_key: str, value_key: str, config: Optional[ChartConfig] = None) -> str:
        cfg = config or self.config
        return self._render_svg(ChartType.PIE, data, label_key, value_key, cfg)

    def scatter_plot(self, data: list[dict], x_key: str, y_key: str, config: Optional[ChartConfig] = None) -> str:
        cfg = config or self.config
        return self._render_svg(ChartType.SCATTER, data, x_key, y_key, cfg)

    def histogram(self, data: list[float], bins: int = 10, config: Optional[ChartConfig] = None) -> str:
        cfg = config or self.config
        min_v, max_v = min(data), max(data)
        bin_w = (max_v - min_v) / bins if bins > 0 else 1
        counts = [0] * bins
        for v in data:
            idx = min(int((v - min_v) / bin_w), bins - 1) if bin_w > 0 else 0
            counts[idx] += 1
        labels = [f"{min_v + i * bin_w:.1f}" for i in range(bins)]
        chart_data = [{"label": labels[i], "count": counts[i]} for i in range(bins)]
        return self._render_svg(ChartType.HISTOGRAM, chart_data, "label", "count", cfg)

    def area_chart(self, data: list[dict], x_key: str, y_key: str, config: Optional[ChartConfig] = None) -> str:
        cfg = config or self.config
        return self._render_svg(ChartType.AREA, data, x_key, y_key, cfg)

    def box_plot(self, data: list[float], config: Optional[ChartConfig] = None) -> str:
        cfg = config or self.config
        sorted_d = sorted(data)
        n = len(sorted_d)
        q1 = sorted_d[n // 4]
        q2 = sorted_d[n // 2]
        q3 = sorted_d[3 * n // 4]
        iqr = q3 - q1
        lower = max(sorted_d[0], q1 - 1.5 * iqr)
        upper = min(sorted_d[-1], q3 + 1.5 * iqr)

        padding = 60
        pw, ph = cfg.width, cfg.height
        plot_w = pw - 2 * padding
        plot_h = ph - 2 * padding
        cx = pw // 2
        half_w = 40

        def scale_y(v: float) -> float:
            r = upper - lower if upper != lower else 1
            return padding + plot_h - ((v - lower) / r) * plot_h

        y_lower = scale_y(lower)
        y_q1 = scale_y(q1)
        y_q2 = scale_y(q2)
        y_q3 = scale_y(q3)
        y_upper = scale_y(upper)

        box = f'<rect x="{cx - half_w}" y="{y_q3}" width="{2 * half_w}" height="{y_q1 - y_q3}" class="box"/>'
        median = f'<line x1="{cx - half_w}" y1="{y_q2}" x2="{cx + half_w}" y2="{y_q2}" class="median"/>'
        whiskers = (
            f'<line x1="{cx}" y1="{y_upper}" x2="{cx}" y2="{y_lower}" class="whisker"/>'
            f'<line x1="{cx - 15}" y1="{y_lower}" x2="{cx + 15}" y2="{y_lower}" class="whisker"/>'
            f'<line x1="{cx - 15}" y1="{y_upper}" x2="{cx + 15}" y2="{y_upper}" class="whisker"/>'
        )

        grid_lines = "".join(f'<line x1="{padding}" y1="{y}" x2="{pw - padding}" y2="{y}" class="grid"/>' for y in range(padding + plot_h // 5, padding + plot_h, plot_h // 5))

        t = _TEMPLATES[ChartType.BOX].format(
            width=cfg.width, height=cfg.height, hw=cfg.width // 2,
            title=cfg.title, color=cfg.color,
            grid_lines=grid_lines, axes="", box_plot=box + median + whiskers, labels=""
        )
        return t

    def from_csv(self, csv_path: str, chart_type: ChartType = ChartType.BAR, x_col: Optional[str] = None, y_col: Optional[str] = None) -> str:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            data = list(reader)
        if not data:
            return ""
        keys = list(data[0].keys())
        xk = x_col or keys[0]
        yk = y_col or keys[1]
        numeric_data = []
        for row in data:
            try:
                numeric_data.append({"label": row[xk], "value": float(row[yk])})
            except (ValueError, KeyError):
                continue
        render_map = {
            ChartType.BAR: self.bar_chart,
            ChartType.LINE: self.line_chart,
            ChartType.PIE: self.pie_chart,
            ChartType.SCATTER: self.scatter_plot,
        }
        render_fn = render_map.get(chart_type, self.bar_chart)
        return render_fn(numeric_data, "label", "value")

    def from_json(self, json_data: str, chart_type: ChartType = ChartType.BAR, x_key: Optional[str] = None, y_key: Optional[str] = None) -> str:
        data = json.loads(json_data) if isinstance(json_data, str) else json_data
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not data:
            return ""
        keys = list(data[0].keys())
        xk = x_key or keys[0]
        yk = y_key or keys[1]
        render_map = {
            ChartType.BAR: self.bar_chart,
            ChartType.LINE: self.line_chart,
            ChartType.PIE: self.pie_chart,
            ChartType.SCATTER: self.scatter_plot,
        }
        render_fn = render_map.get(chart_type, self.bar_chart)
        return render_fn(data, xk, yk)

    def save(self, svg: str, output_path: str) -> str:
        Path(output_path).write_text(svg, encoding="utf-8")
        return output_path

    def _render_svg(self, chart_type: ChartType, data: list[dict], x_key: str, y_key: str, cfg: ChartConfig) -> str:
        padding = 60
        pw, ph = cfg.width, cfg.height
        plot_w = pw - 2 * padding
        plot_h = ph - 2 * padding
        hw = pw // 2

        values = []
        labels = []
        for row in data:
            try:
                v = float(row.get(y_key, row.get("value", 0)))
                l = str(row.get(x_key, row.get("label", "")))
                values.append(v)
                labels.append(l)
            except (TypeError, ValueError):
                continue

        if not values:
            return f"<svg width=\"{pw}\" height=\"{ph}\"><text x=\"{hw}\" y=\"{ph//2}\" text-anchor=\"middle\">No data</text></svg>"

        min_v = min(values)
        max_v = max(values)
        v_range = max_v - min_v if max_v != min_v else 1

        def scale_y(v: float) -> float:
            return padding + plot_h - ((v - min_v) / v_range) * plot_h

        def scale_x(i: int, n: int) -> float:
            if n <= 1:
                return hw
            return padding + (i / (n - 1)) * plot_w

        n = len(values)

        if chart_type == ChartType.LINE:
            pts = [f"{scale_x(i, n):.1f},{scale_y(values[i]):.1f}" for i in range(n)]
            line_path = f'<polyline points="{" ".join(pts)}" class="line"/>'
            dots = "".join(f'<circle cx="{scale_x(i, n):.1f}" cy="{scale_y(values[i]):.1f}" class="dot"/>' for i in range(n))
            grid_lines = "".join(
                f'<line x1="{padding}" y1="{y}" x2="{pw - padding}" y2="{y}" class="grid"/>'
                for y in range(padding + plot_h // 5, padding + plot_h, plot_h // 5)
            )
            axes = f'<line x1="{padding}" y1="{padding}" x2="{padding}" y2="{padding + plot_h}" class="axis"/><line x1="{padding}" y1="{padding + plot_h}" x2="{pw - padding}" y2="{padding + plot_h}" class="axis"/>'
            y_labels = "".join(
                f'<text x="{padding - 8}" y="{y + 4}" text-anchor="end" class="label">{min_v + (i / 5) * v_range:.1f}</text>'
                for i in range(6) if (y := scale_y(min_v + (i / 5) * v_range)) is not None
            )
            labels_text = "".join(f'<text x="{scale_x(i, n):.1f}" y="{padding + plot_h + 16}" text-anchor="middle" class="label">{labels[i][:12]}</text>' for i in range(0, n, max(1, n // 10)))
            t = _TEMPLATES[ChartType.LINE].format(width=pw, height=ph, hw=hw, title=cfg.title, color=cfg.color, lines=line_path, dots=dots, grid_lines=grid_lines, axes=axes, labels=y_labels + labels_text, legend="")
            return t

        elif chart_type in (ChartType.BAR, ChartType.HISTOGRAM):
            bar_w = min(plot_w / n * 0.7, 60)
            gap = (plot_w - bar_w * n) / (n + 1)
            bars = []
            for i in range(n):
                x = padding + gap + i * (bar_w + gap)
                h = ((values[i] - min_v) / v_range) * plot_h
                y = padding + plot_h - h
                color = cfg.colors[i % len(cfg.colors)]
                bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{color}" rx="2"/>')
            grid_lines = "".join(
                f'<line x1="{padding}" y1="{y}" x2="{pw - padding}" y2="{y}" class="grid"/>'
                for y in range(padding + plot_h // 5, padding + plot_h, plot_h // 5)
            )
            axes = f'<line x1="{padding}" y1="{padding}" x2="{padding}" y2="{padding + plot_h}" class="axis"/><line x1="{padding}" y1="{padding + plot_h}" x2="{pw - padding}" y2="{padding + plot_h}" class="axis"/>'
            y_labels = "".join(
                f'<text x="{padding - 8}" y="{y + 4}" text-anchor="end" class="label">{min_v + (i / 5) * v_range:.1f}</text>'
                for i in range(6)
            )
            labels_text = "".join(
                f'<text x="{padding + gap + i * (bar_w + gap) + bar_w / 2:.1f}" y="{padding + plot_h + 16}" text-anchor="middle" class="label" transform="rotate(-45,{padding + gap + i * (bar_w + gap) + bar_w / 2:.1f},{padding + plot_h + 16})">{labels[i][:12]}</text>'
                for i in range(0, n, max(1, n // 8))
            )
            t = _TEMPLATES[ChartType.BAR].format(width=pw, height=ph, hw=hw, title=cfg.title, color=cfg.color, bars="".join(bars), grid_lines=grid_lines, axes=axes, labels=y_labels + labels_text, legend="")
            return t

        elif chart_type == ChartType.PIE:
            total = sum(values)
            cx, cy = pw // 2, ph // 2 + 20
            r = min(pw, ph) // 2 - 60
            slices = []
            legend_items = []
            angle = 0
            for i, (v, label) in enumerate(zip(values, labels)):
                if total == 0:
                    continue
                sweep = (v / total) * 360
                color = cfg.colors[i % len(cfg.colors)]
                end_angle = angle + sweep
                rad_a = angle * 3.14159 / 180
                rad_e = end_angle * 3.14159 / 180
                x1 = cx + r * math.cos(rad_a)
                y1 = cy + r * math.sin(rad_a)
                x2 = cx + r * math.cos(rad_e)
                y2 = cy + r * math.sin(rad_e)
                large = 1 if sweep > 180 else 0
                slices.append(f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} A{r},{r} 0 {large},1 {x2:.1f},{y2:.1f} Z" fill="{color}" stroke="#fff" stroke-width="1"/>')
                mid_angle = angle + sweep / 2
                lx = cx + (r + 20) * math.cos(mid_angle * 3.14159 / 180)
                ly = cy + (r + 20) * math.sin(mid_angle * 3.14159 / 180)
                pct = v / total * 100
                slices.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" class="label">{pct:.0f}%</text>')
                legend_items.append(f'<rect x="{pw - 140}" y="{40 + i * 22}" width="14" height="14" fill="{color}" rx="2"/><text x="{pw - 120}" y="{52 + i * 22}" class="legend-text">{label[:20]}</text>')
                angle = end_angle
            t = _TEMPLATES[ChartType.PIE].format(width=pw, height=ph, hw=hw, title=cfg.title, slices="".join(slices), legend="".join(legend_items))
            return t

        elif chart_type == ChartType.SCATTER:
            dots = []
            for i in range(n):
                x = padding + ((values[i] - min_v) / v_range) * plot_w
                y = padding + plot_h - ((values[i] - min_v) / v_range) * plot_h
                dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" class="dot" r="4"/>')
            grid_lines = "".join(
                f'<line x1="{padding}" y1="{y}" x2="{pw - padding}" y2="{y}" class="grid"/>'
                for y in range(padding + plot_h // 5, padding + plot_h, plot_h // 5)
            )
            axes = f'<line x1="{padding}" y1="{padding}" x2="{padding}" y2="{padding + plot_h}" class="axis"/><line x1="{padding}" y1="{padding + plot_h}" x2="{pw - padding}" y2="{padding + plot_h}" class="axis"/>'
            y_labels = "".join(
                f'<text x="{padding - 8}" y="{y + 4}" text-anchor="end" class="label">{min_v + (i / 5) * v_range:.1f}</text>'
                for i in range(6)
            )
            t = _TEMPLATES[ChartType.SCATTER].format(width=pw, height=ph, hw=hw, title=cfg.title, color=cfg.color, dots="".join(dots), grid_lines=grid_lines, axes=axes, labels=y_labels, legend="")
            return t

        return ""
