"""Horizon Orchestra — PDF Generation.

Generate PDFs from HTML, Markdown, or raw content.  Supports merging,
watermarking, text extraction, image extraction, and page counting.
Uses WeasyPrint (preferred), falls back to ReportLab, then to basic HTML.

Usage::

    from orchestra.documents.pdf import PDFGenerator

    gen = PDFGenerator()
    pdf_bytes = gen.from_markdown("# Hello\\nThis is a PDF.")
    gen.save(pdf_bytes, "output.pdf")
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence

__all__ = [
    "PDFGenerator",
]

log = logging.getLogger("orchestra.documents.pdf")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_docs"))

# Optional dependencies
try:
    import weasyprint
    _HAS_WEASYPRINT = True
except ImportError:
    weasyprint = None  # type: ignore[assignment]
    _HAS_WEASYPRINT = False

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image as RLImage
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    _HAS_REPORTLAB = True
except ImportError:
    _HAS_REPORTLAB = False

try:
    import markdown as _markdown_mod
    _HAS_MARKDOWN = True
except ImportError:
    _markdown_mod = None  # type: ignore[assignment]
    _HAS_MARKDOWN = False

try:
    import PyPDF2
    _HAS_PYPDF2 = True
except ImportError:
    try:
        import pypdf as PyPDF2  # type: ignore[no-redef]
        _HAS_PYPDF2 = True
    except ImportError:
        PyPDF2 = None  # type: ignore[assignment]
        _HAS_PYPDF2 = False


# ---------------------------------------------------------------------------
# Default CSS
# ---------------------------------------------------------------------------

_DEFAULT_CSS = """
@page {
    size: A4;
    margin: 2cm;
    @top-center {
        content: string(title);
        font-size: 9pt;
        color: #666;
    }
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 9pt;
        color: #666;
    }
}

body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
}

h1 {
    font-size: 24pt;
    font-weight: 700;
    color: #111;
    margin-top: 0;
    margin-bottom: 16pt;
    string-set: title content();
}

h2 {
    font-size: 18pt;
    font-weight: 600;
    color: #222;
    margin-top: 24pt;
    margin-bottom: 12pt;
    border-bottom: 1px solid #e0e0e0;
    padding-bottom: 4pt;
}

h3 {
    font-size: 14pt;
    font-weight: 600;
    color: #333;
    margin-top: 20pt;
    margin-bottom: 8pt;
}

p {
    margin-bottom: 10pt;
}

code {
    font-family: "SF Mono", "Fira Code", "Consolas", monospace;
    font-size: 9pt;
    background: #f5f5f5;
    padding: 2pt 4pt;
    border-radius: 3pt;
}

pre {
    background: #f5f5f5;
    padding: 12pt;
    border-radius: 4pt;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.4;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 16pt 0;
}

th, td {
    padding: 8pt 12pt;
    border: 1px solid #ddd;
    text-align: left;
}

th {
    background: #f0f0f0;
    font-weight: 600;
}

tr:nth-child(even) {
    background: #fafafa;
}

ul, ol {
    padding-left: 24pt;
    margin-bottom: 10pt;
}

li {
    margin-bottom: 4pt;
}

blockquote {
    border-left: 3pt solid #3b82f6;
    padding-left: 16pt;
    color: #555;
    margin: 16pt 0;
    font-style: italic;
}
"""


# ---------------------------------------------------------------------------
# PDFGenerator
# ---------------------------------------------------------------------------

class PDFGenerator:
    """PDF generation from HTML, Markdown, or raw content.

    Parameters
    ----------
    workspace:
        Directory for saving output files.
    default_css:
        Default CSS stylesheet for HTML→PDF conversion.
    page_size:
        Default page size (``"A4"`` or ``"letter"``).
    """

    def __init__(
        self,
        workspace: str | Path | None = None,
        default_css: str | None = None,
        page_size: str = "A4",
    ) -> None:
        self.workspace = Path(workspace) if workspace else _WORKSPACE / "pdf"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._css = default_css or _DEFAULT_CSS
        self._page_size = page_size

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_path(self, ext: str = "pdf") -> Path:
        return self.workspace / f"{uuid.uuid4().hex[:12]}.{ext}"

    def _md_to_html(self, md: str) -> str:
        """Convert Markdown to HTML."""
        if _HAS_MARKDOWN:
            extensions = ["tables", "fenced_code", "codehilite", "toc", "nl2br"]
            return _markdown_mod.markdown(md, extensions=extensions)
        # Basic fallback: minimal Markdown conversion
        html = md
        # Headers
        for level in range(6, 0, -1):
            pattern = r"^" + r"#" * level + r"\s+(.+)$"
            html = re.sub(pattern, rf"<h{level}>\1</h{level}>", html, flags=re.MULTILINE)
        # Bold
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        # Italic
        html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
        # Code blocks
        html = re.sub(r"```(\w*)\n(.*?)```", r"<pre><code>\2</code></pre>", html, flags=re.DOTALL)
        # Inline code
        html = re.sub(r"`(.+?)`", r"<code>\1</code>", html)
        # Paragraphs
        paragraphs = html.split("\n\n")
        processed = []
        for p in paragraphs:
            p = p.strip()
            if p and not p.startswith("<"):
                p = f"<p>{p}</p>"
            processed.append(p)
        html = "\n".join(processed)
        return html

    def _wrap_html(self, body_html: str, css: str = "", title: str = "") -> str:
        """Wrap body HTML with a complete HTML document structure."""
        use_css = css or self._css
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>{use_css}</style>
</head>
<body>
{body_html}
</body>
</html>"""

    # ------------------------------------------------------------------
    # WeasyPrint backend
    # ------------------------------------------------------------------

    def _from_html_weasyprint(self, html: str, css: str = "") -> bytes:
        """Generate PDF from HTML using WeasyPrint."""
        if css:
            full_html = self._wrap_html(html, css=css)
        else:
            # Check if html is already a full document
            if "<html" in html.lower():
                full_html = html
            else:
                full_html = self._wrap_html(html)

        doc = weasyprint.HTML(string=full_html)
        return doc.write_pdf()

    # ------------------------------------------------------------------
    # ReportLab backend
    # ------------------------------------------------------------------

    def _from_text_reportlab(self, text: str, title: str = "") -> bytes:
        """Generate PDF from plain text using ReportLab."""
        buffer = io.BytesIO()
        page_size = A4 if self._page_size == "A4" else letter
        doc = SimpleDocTemplate(
            buffer,
            pagesize=page_size,
            topMargin=72,
            bottomMargin=72,
            leftMargin=72,
            rightMargin=72,
        )

        styles = getSampleStyleSheet()
        story: list[Any] = []

        if title:
            title_style = ParagraphStyle(
                "CustomTitle",
                parent=styles["Title"],
                fontSize=24,
                spaceAfter=24,
            )
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 12))

        # Process text line by line
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                story.append(Spacer(1, 8))
                continue

            if line.startswith("# "):
                style = styles["Heading1"]
                line = line[2:]
            elif line.startswith("## "):
                style = styles["Heading2"]
                line = line[3:]
            elif line.startswith("### "):
                style = styles["Heading3"]
                line = line[4:]
            else:
                style = styles["Normal"]

            # Escape XML special characters
            line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(line, style))

        doc.build(story)
        return buffer.getvalue()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def from_html(self, html: str, css: str = "") -> bytes:
        """Generate a PDF from HTML content.

        Parameters
        ----------
        html:
            HTML content (can be a fragment or full document).
        css:
            Optional CSS stylesheet.  Uses default if not provided.

        Returns
        -------
        bytes
            PDF file content.
        """
        if _HAS_WEASYPRINT:
            log.debug("Generating PDF with WeasyPrint")
            return self._from_html_weasyprint(html, css)
        elif _HAS_REPORTLAB:
            log.debug("WeasyPrint not available, falling back to ReportLab")
            # Strip HTML tags for ReportLab text fallback
            text = re.sub(r"<[^>]+>", "", html)
            return self._from_text_reportlab(text)
        else:
            raise ImportError(
                "No PDF backend available. Install weasyprint or reportlab: "
                "pip install weasyprint  (or)  pip install reportlab"
            )

    def from_markdown(self, md: str, css: str = "", title: str = "") -> bytes:
        """Generate a PDF from Markdown content.

        Parameters
        ----------
        md:
            Markdown text.
        css:
            Optional CSS stylesheet.
        title:
            Optional document title.

        Returns
        -------
        bytes
            PDF file content.
        """
        html_body = self._md_to_html(md)
        full_html = self._wrap_html(html_body, css=css, title=title)

        if _HAS_WEASYPRINT:
            return self._from_html_weasyprint(full_html)
        elif _HAS_REPORTLAB:
            return self._from_text_reportlab(md, title=title)
        else:
            raise ImportError(
                "No PDF backend available. Install weasyprint or reportlab."
            )

    def merge(self, pdf_files: Sequence[str | Path | bytes]) -> bytes:
        """Merge multiple PDFs into one.

        Parameters
        ----------
        pdf_files:
            List of PDF file paths or raw bytes.

        Returns
        -------
        bytes
            Merged PDF content.
        """
        if not _HAS_PYPDF2:
            raise ImportError("PyPDF2 or pypdf is required for PDF merging: pip install pypdf")

        merger = PyPDF2.PdfMerger() if hasattr(PyPDF2, "PdfMerger") else PyPDF2.PdfWriter()

        for pdf in pdf_files:
            if isinstance(pdf, bytes):
                merger.append(io.BytesIO(pdf))
            else:
                merger.append(str(pdf))

        output = io.BytesIO()
        merger.write(output)
        merger.close()
        return output.getvalue()

    def add_watermark(self, pdf: str | Path | bytes, text: str) -> bytes:
        """Add a text watermark to every page of a PDF.

        Parameters
        ----------
        pdf:
            Source PDF (path or bytes).
        text:
            Watermark text.

        Returns
        -------
        bytes
            Watermarked PDF content.
        """
        if not _HAS_PYPDF2:
            raise ImportError("pypdf is required for watermarking: pip install pypdf")

        # Create watermark PDF
        if _HAS_WEASYPRINT:
            watermark_html = f"""
            <html><body style="margin:0;">
            <div style="
                position: fixed;
                top: 40%;
                left: 10%;
                transform: rotate(-45deg);
                font-size: 72pt;
                color: rgba(200, 200, 200, 0.3);
                font-family: Helvetica, Arial, sans-serif;
                font-weight: bold;
                white-space: nowrap;
            ">{text}</div>
            </body></html>"""
            watermark_bytes = weasyprint.HTML(string=watermark_html).write_pdf()
        elif _HAS_REPORTLAB:
            buf = io.BytesIO()
            from reportlab.pdfgen import canvas as rl_canvas
            c = rl_canvas.Canvas(buf, pagesize=A4)
            c.setFont("Helvetica-Bold", 60)
            c.setFillColorRGB(0.8, 0.8, 0.8, alpha=0.3)
            c.saveState()
            c.translate(300, 400)
            c.rotate(45)
            c.drawCentredString(0, 0, text)
            c.restoreState()
            c.save()
            watermark_bytes = buf.getvalue()
        else:
            raise ImportError("weasyprint or reportlab required for watermarking.")

        # Read source PDF
        if isinstance(pdf, bytes):
            reader = PyPDF2.PdfReader(io.BytesIO(pdf))
        else:
            reader = PyPDF2.PdfReader(str(pdf))

        watermark_reader = PyPDF2.PdfReader(io.BytesIO(watermark_bytes))
        watermark_page = watermark_reader.pages[0]

        writer = PyPDF2.PdfWriter()
        for page in reader.pages:
            page.merge_page(watermark_page)
            writer.add_page(page)

        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def extract_text(self, pdf: str | Path | bytes) -> str:
        """Extract text content from a PDF.

        Parameters
        ----------
        pdf:
            PDF file path or bytes.

        Returns
        -------
        str
            Extracted text.
        """
        if not _HAS_PYPDF2:
            raise ImportError("pypdf is required for text extraction: pip install pypdf")

        if isinstance(pdf, bytes):
            reader = PyPDF2.PdfReader(io.BytesIO(pdf))
        else:
            reader = PyPDF2.PdfReader(str(pdf))

        texts: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
        return "\n\n".join(texts)

    def extract_images(self, pdf: str | Path | bytes) -> list[bytes]:
        """Extract images from a PDF.

        Parameters
        ----------
        pdf:
            PDF file path or bytes.

        Returns
        -------
        list[bytes]
            List of extracted image data.
        """
        if not _HAS_PYPDF2:
            raise ImportError("pypdf is required for image extraction: pip install pypdf")

        if isinstance(pdf, bytes):
            reader = PyPDF2.PdfReader(io.BytesIO(pdf))
        else:
            reader = PyPDF2.PdfReader(str(pdf))

        images: list[bytes] = []
        for page in reader.pages:
            if "/XObject" not in (page.get("/Resources") or {}):
                continue
            x_objects = page["/Resources"]["/XObject"].get_object()
            for obj_name in x_objects:
                obj = x_objects[obj_name].get_object()
                if obj.get("/Subtype") == "/Image":
                    try:
                        data = obj.get_data()
                        if data:
                            images.append(data)
                    except Exception:
                        log.debug("Failed to extract image %s", obj_name)
        return images

    def get_page_count(self, pdf: str | Path | bytes) -> int:
        """Get the number of pages in a PDF.

        Parameters
        ----------
        pdf:
            PDF file path or bytes.

        Returns
        -------
        int
            Number of pages.
        """
        if not _HAS_PYPDF2:
            raise ImportError("pypdf is required: pip install pypdf")

        if isinstance(pdf, bytes):
            reader = PyPDF2.PdfReader(io.BytesIO(pdf))
        else:
            reader = PyPDF2.PdfReader(str(pdf))

        return len(reader.pages)

    def save(self, pdf_bytes: bytes, path: str | Path | None = None) -> Path:
        """Save PDF bytes to a file.

        Parameters
        ----------
        pdf_bytes:
            PDF content.
        path:
            Output path.  Auto-generated if *None*.

        Returns
        -------
        Path
            Saved file path.
        """
        save_to = Path(path) if path else self._save_path()
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_bytes(pdf_bytes)
        log.info("Saved PDF → %s (%d bytes)", save_to, len(pdf_bytes))
        return save_to
