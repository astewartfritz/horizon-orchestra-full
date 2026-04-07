"""Horizon Orchestra — Document Factory.

Comprehensive document generation toolkit for PDF, PowerPoint, Excel,
charts/visualizations, and format conversion via Pandoc.

Quick start::

    from orchestra.documents import PDFGenerator, PPTXGenerator, XLSXGenerator
    from orchestra.documents import ChartGenerator, DocumentConverter

    pdf = PDFGenerator()
    result = pdf.from_markdown("# Hello\\nWorld")

    charts = ChartGenerator()
    img = charts.bar_chart({"A": 10, "B": 20}, title="Sales")
"""

from __future__ import annotations

from .pdf import PDFGenerator
from .pptx import PPTXGenerator, SlideSpec
from .xlsx import XLSXGenerator
from .charts import ChartGenerator
from .converter import DocumentConverter

__all__ = [
    # PDF
    "PDFGenerator",
    # PowerPoint
    "PPTXGenerator",
    "SlideSpec",
    # Excel
    "XLSXGenerator",
    # Charts
    "ChartGenerator",
    # Converter
    "DocumentConverter",
]
