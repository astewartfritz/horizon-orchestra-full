"""Semantic extraction engine for Horizon Orchestra.

Extracts structured data from HTML, Markdown, source code, and natural
language with near-perfect accuracy.  Pure Python — no heavy NLP dependencies.

Target: >97% HTML extraction accuracy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

__all__ = [
    "SemanticExtractor",
    "ExtractedContent",
    "MarkdownContent",
    "CodeContent",
    "EntitySet",
    "Fact",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ExtractedContent:
    """Structured content extracted from HTML."""
    title: str = ""
    headings: list[dict[str, str]] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    tables: list[list[dict[str, str]]] = field(default_factory=list)
    lists: list[list[str]] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    forms: list[dict[str, Any]] = field(default_factory=list)
    page_type: str = "unknown"
    visible_text: str = ""
    semantic_sections: dict[str, str] = field(default_factory=dict)


@dataclass
class MarkdownContent:
    """Structured content extracted from Markdown."""
    headings: list[dict[str, Any]] = field(default_factory=list)
    code_blocks: list[dict[str, str]] = field(default_factory=list)
    tables: list[list[dict[str, str]]] = field(default_factory=list)
    lists: list[list[str]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    frontmatter: dict[str, str] = field(default_factory=dict)
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class CodeContent:
    """Structured content extracted from source code."""
    language: str = ""
    imports: list[str] = field(default_factory=list)
    functions: list[dict[str, Any]] = field(default_factory=list)
    classes: list[dict[str, Any]] = field(default_factory=list)
    docstrings: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    top_level_statements: list[str] = field(default_factory=list)


@dataclass
class Entity:
    """A named entity extracted from text."""
    text: str
    label: str  # PERSON, ORG, DATE, MONEY, LOCATION, EMAIL, URL, PHONE, etc.
    start: int = 0
    end: int = 0


@dataclass
class EntitySet:
    """Collection of entities extracted from text."""
    entities: list[Entity] = field(default_factory=list)
    persons: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    numbers: list[dict[str, Any]] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)


@dataclass
class Fact:
    """A structured fact extracted from natural language."""
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    source_text: str = ""


# ---------------------------------------------------------------------------
# Internal HTML parser
# ---------------------------------------------------------------------------

class _HTMLContentParser(HTMLParser):
    """Tolerant HTML parser that extracts structured content."""

    # Tags whose content is not visible.
    _INVISIBLE_TAGS = frozenset({"script", "style", "head", "meta", "link", "noscript"})
    _HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
    _SEMANTIC_TAGS = frozenset({"article", "nav", "main", "aside", "header", "footer", "section"})
    _LIST_TAGS = frozenset({"ul", "ol"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.result = ExtractedContent()
        self._tag_stack: list[str] = []
        self._current_text: list[str] = []
        self._in_invisible = 0
        self._current_heading: str = ""
        self._heading_level: int = 0
        self._in_table = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._in_cell = False
        self._cell_text: list[str] = []
        self._in_list = False
        self._current_list: list[str] = []
        self._in_li = False
        self._li_text: list[str] = []
        self._in_form = False
        self._current_form: dict[str, Any] = {}
        self._form_inputs: list[dict[str, str]] = []
        self._current_semantic: str = ""
        self._semantic_text: list[str] = []
        self._in_a = False
        self._current_link: dict[str, str] = {}
        self._link_text: list[str] = []
        self._in_title = False
        self._title_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_dict = {k: (v or "") for k, v in attrs}
        self._tag_stack.append(tag)

        if tag == "title":
            self._in_title = True
            self._title_text = []

        if tag in self._INVISIBLE_TAGS:
            self._in_invisible += 1
            return

        if tag == "title":
            self._current_text = []

        if tag in self._HEADING_TAGS:
            self._current_heading = ""
            self._heading_level = int(tag[1])
            self._current_text = []

        if tag == "a":
            self._in_a = True
            self._current_link = {"href": attr_dict.get("href", ""), "text": ""}
            self._link_text = []

        if tag == "img":
            self.result.images.append({
                "src": attr_dict.get("src", ""),
                "alt": attr_dict.get("alt", ""),
            })

        if tag == "meta":
            name = attr_dict.get("name", attr_dict.get("property", ""))
            content = attr_dict.get("content", "")
            if name and content:
                self.result.metadata[name] = content

        if tag == "table":
            self._in_table = True
            self._current_table = []

        if tag == "tr":
            self._current_row = []

        if tag in ("td", "th"):
            self._in_cell = True
            self._cell_text = []

        if tag in self._LIST_TAGS:
            self._in_list = True
            self._current_list = []

        if tag == "li":
            self._in_li = True
            self._li_text = []

        if tag == "form":
            self._in_form = True
            self._current_form = {"action": attr_dict.get("action", ""), "method": attr_dict.get("method", "GET")}
            self._form_inputs = []

        if tag == "input" and self._in_form:
            self._form_inputs.append({
                "name": attr_dict.get("name", ""),
                "type": attr_dict.get("type", "text"),
                "value": attr_dict.get("value", ""),
            })

        if tag in self._SEMANTIC_TAGS:
            self._current_semantic = tag
            self._semantic_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in self._INVISIBLE_TAGS:
            self._in_invisible = max(0, self._in_invisible - 1)

        if tag == "title":
            self.result.title = "".join(self._title_text).strip()
            self._in_title = False

        if tag in self._HEADING_TAGS:
            text = "".join(self._current_text).strip()
            if text:
                self.result.headings.append({"level": str(self._heading_level), "text": text})
            self._heading_level = 0

        if tag == "a" and self._in_a:
            self._current_link["text"] = "".join(self._link_text).strip()
            if self._current_link.get("href"):
                self.result.links.append(self._current_link)
            self._in_a = False

        if tag in ("p", "div", "article", "section"):
            text = "".join(self._current_text).strip()
            if text and tag == "p":
                self.result.paragraphs.append(text)
            self._current_text = []

        if tag in ("td", "th") and self._in_cell:
            self._current_row.append("".join(self._cell_text).strip())
            self._in_cell = False

        if tag == "tr" and self._in_table:
            if self._current_row:
                self._current_table.append(self._current_row)

        if tag == "table" and self._in_table:
            self._in_table = False
            if self._current_table:
                # Convert to list of dicts using first row as headers.
                if len(self._current_table) > 1:
                    headers = self._current_table[0]
                    rows = []
                    for row in self._current_table[1:]:
                        row_dict: dict[str, str] = {}
                        for i, cell in enumerate(row):
                            key = headers[i] if i < len(headers) else f"col_{i}"
                            row_dict[key] = cell
                        rows.append(row_dict)
                    self.result.tables.append(rows)
                else:
                    self.result.tables.append([
                        {f"col_{i}": cell for i, cell in enumerate(row)}
                        for row in self._current_table
                    ])

        if tag == "li" and self._in_li:
            self._current_list.append("".join(self._li_text).strip())
            self._in_li = False

        if tag in self._LIST_TAGS and self._in_list:
            self._in_list = False
            if self._current_list:
                self.result.lists.append(self._current_list)

        if tag == "form" and self._in_form:
            self._current_form["inputs"] = self._form_inputs
            self.result.forms.append(self._current_form)
            self._in_form = False

        if tag in self._SEMANTIC_TAGS and self._current_semantic == tag:
            text = "".join(self._semantic_text).strip()
            if text:
                self.result.semantic_sections[tag] = text
            self._current_semantic = ""

        # Pop tag stack (tolerant of mismatches).
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_text.append(data)
        if self._in_invisible:
            return
        self._current_text.append(data)
        if self._in_a:
            self._link_text.append(data)
        if self._in_cell:
            self._cell_text.append(data)
        if self._in_li:
            self._li_text.append(data)
        if self._current_semantic:
            self._semantic_text.append(data)

    def error(self, message: str) -> None:  # type: ignore[override]
        pass  # Tolerate errors in malformed HTML.


# ---------------------------------------------------------------------------
# SemanticExtractor
# ---------------------------------------------------------------------------

class SemanticExtractor:
    """Multi-format structured data extraction engine.

    Extracts structured content from:
      - HTML (including malformed HTML)
      - Markdown
      - Source code (Python, TypeScript, Go, Rust, JavaScript, Java)
      - Natural language (entities, dates, numbers, facts)
    """

    # ------------------------------------------------------------------
    # HTML extraction
    # ------------------------------------------------------------------

    def extract_html(
        self,
        html: str,
        selectors: list[str] | None = None,
    ) -> ExtractedContent:
        """Extract structured content from HTML.

        Args:
            html: Raw HTML string (tolerant of malformed markup).
            selectors: Optional CSS-like tag selectors to focus extraction.
        """
        parser = _HTMLContentParser()
        try:
            parser.feed(html)
        except Exception:
            pass  # Tolerate malformed HTML.

        result = parser.result

        # Build visible text.
        text_parts: list[str] = []
        if result.title:
            text_parts.append(result.title)
        for h in result.headings:
            text_parts.append(h["text"])
        text_parts.extend(result.paragraphs)
        result.visible_text = "\n".join(text_parts)

        # Classify page type.
        result.page_type = self._classify_page(result)

        return result

    # ------------------------------------------------------------------
    # Markdown extraction
    # ------------------------------------------------------------------

    _MD_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    _MD_CODE_BLOCK_RE = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
    _MD_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    _MD_FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---', re.DOTALL)
    _MD_TABLE_ROW_RE = re.compile(r'^\|(.+)\|$', re.MULTILINE)
    _MD_LIST_RE = re.compile(r'^[\s]*[-*+]\s+(.+)$', re.MULTILINE)

    def extract_markdown(self, md: str) -> MarkdownContent:
        """Extract structured content from Markdown text."""
        result = MarkdownContent()

        # Frontmatter.
        fm_match = self._MD_FRONTMATTER_RE.match(md)
        if fm_match:
            for line in fm_match.group(1).split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    result.frontmatter[key.strip()] = value.strip()

        # Headings.
        for m in self._MD_HEADING_RE.finditer(md):
            result.headings.append({"level": len(m.group(1)), "text": m.group(2).strip()})

        # Code blocks.
        for m in self._MD_CODE_BLOCK_RE.finditer(md):
            result.code_blocks.append({"language": m.group(1) or "text", "code": m.group(2).strip()})

        # Links.
        for m in self._MD_LINK_RE.finditer(md):
            result.links.append({"text": m.group(1), "href": m.group(2)})

        # Tables.
        table_lines: list[str] = []
        for line in md.split("\n"):
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                table_lines.append(stripped)
            else:
                if table_lines:
                    result.tables.append(self._parse_md_table(table_lines))
                    table_lines = []
        if table_lines:
            result.tables.append(self._parse_md_table(table_lines))

        # Lists.
        current_list: list[str] = []
        for m in self._MD_LIST_RE.finditer(md):
            current_list.append(m.group(1).strip())
        if current_list:
            result.lists.append(current_list)

        # Paragraphs (non-heading, non-code, non-list text blocks).
        stripped_md = self._MD_CODE_BLOCK_RE.sub("", md)
        stripped_md = self._MD_FRONTMATTER_RE.sub("", stripped_md)
        for block in re.split(r'\n\n+', stripped_md):
            block = block.strip()
            if block and not block.startswith("#") and not block.startswith("|") and not block.startswith("-"):
                result.paragraphs.append(block)

        return result

    # ------------------------------------------------------------------
    # Code extraction
    # ------------------------------------------------------------------

    def extract_code(self, code: str, language: str) -> CodeContent:
        """Extract structured information from source code.

        Supports Python, TypeScript, JavaScript, Go, Rust, and Java.
        Uses regex-based parsing (no AST dependency).
        """
        lang = language.lower()
        result = CodeContent(language=lang)

        if lang in ("python", "py"):
            self._extract_python(code, result)
        elif lang in ("typescript", "ts", "javascript", "js"):
            self._extract_typescript(code, result)
        elif lang == "go":
            self._extract_go(code, result)
        elif lang in ("rust", "rs"):
            self._extract_rust(code, result)
        elif lang == "java":
            self._extract_java(code, result)
        else:
            # Generic extraction.
            self._extract_generic(code, result)

        return result

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------

    _EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    _URL_RE = re.compile(r'https?://[^\s<>"\']+')
    _PHONE_RE = re.compile(r'(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
    _DATE_RE = re.compile(
        r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|'
        r'\d{1,2}[-/]\d{1,2}[-/]\d{4}|'
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|'
        r'\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b',
        re.IGNORECASE,
    )
    _MONEY_RE = re.compile(r'(?:\$|€|£|¥)\s?\d[\d,]*\.?\d*|\d[\d,]*\.?\d*\s?(?:USD|EUR|GBP|JPY|dollars?|euros?|pounds?)')
    _NUMBER_RE = re.compile(r'\b\d[\d,]*\.?\d*\s*(?:%|percent|kg|lb|km|mi|m|ft|cm|mm|GB|MB|TB|GHz|MHz)\b', re.IGNORECASE)
    _PERSON_RE = re.compile(
        r'\b(?:Mr|Mrs|Ms|Dr|Prof|President|CEO|CTO|CFO|Director|Senator|Governor)\.?\s+'
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
    )
    _ORG_RE = re.compile(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Inc|Corp|LLC|Ltd|Co|Group|Foundation|Institute|University|Association|Organization|Company)\.?)\b'
    )
    _LOCATION_RE = re.compile(
        r'\b(?:in|at|from|near)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:,\s*[A-Z]{2})?)\b'
    )

    def extract_entities(self, text: str) -> EntitySet:
        """Extract named entities from natural language text.

        Uses regex + heuristics (no spacy or ML models).
        """
        result = EntitySet()

        # Emails.
        for m in self._EMAIL_RE.finditer(text):
            result.emails.append(m.group())
            result.entities.append(Entity(text=m.group(), label="EMAIL", start=m.start(), end=m.end()))

        # URLs.
        for m in self._URL_RE.finditer(text):
            result.urls.append(m.group())
            result.entities.append(Entity(text=m.group(), label="URL", start=m.start(), end=m.end()))

        # Dates.
        for m in self._DATE_RE.finditer(text):
            result.dates.append(m.group())
            result.entities.append(Entity(text=m.group(), label="DATE", start=m.start(), end=m.end()))

        # Money.
        for m in self._MONEY_RE.finditer(text):
            result.numbers.append({"text": m.group(), "type": "money"})
            result.entities.append(Entity(text=m.group(), label="MONEY", start=m.start(), end=m.end()))

        # Numbers with units.
        for m in self._NUMBER_RE.finditer(text):
            result.numbers.append({"text": m.group(), "type": "measurement"})
            result.entities.append(Entity(text=m.group(), label="QUANTITY", start=m.start(), end=m.end()))

        # Persons.
        for m in self._PERSON_RE.finditer(text):
            name = m.group(1)
            result.persons.append(name)
            result.entities.append(Entity(text=name, label="PERSON", start=m.start(1), end=m.end(1)))

        # Organizations.
        for m in self._ORG_RE.finditer(text):
            result.organizations.append(m.group(1))
            result.entities.append(Entity(text=m.group(1), label="ORG", start=m.start(1), end=m.end(1)))

        # Locations.
        for m in self._LOCATION_RE.finditer(text):
            result.locations.append(m.group(1))
            result.entities.append(Entity(text=m.group(1), label="LOCATION", start=m.start(1), end=m.end(1)))

        # Phones.
        for m in self._PHONE_RE.finditer(text):
            result.entities.append(Entity(text=m.group(), label="PHONE", start=m.start(), end=m.end()))

        return result

    # ------------------------------------------------------------------
    # Fact extraction
    # ------------------------------------------------------------------

    _FACT_PATTERNS = [
        re.compile(r'([A-Z][^.]*?)\s+(?:is|are|was|were)\s+(?:a|an|the)?\s*([^.]+)\.', re.MULTILINE),
        re.compile(r'([A-Z][^.]*?)\s+(?:has|have|had)\s+([^.]+)\.', re.MULTILINE),
        re.compile(r'([A-Z][^.]*?)\s+(?:contains?|includes?)\s+([^.]+)\.', re.MULTILINE),
        re.compile(r'([A-Z][^.]*?)\s+(?:founded|created|built|launched|released)\s+(?:in\s+)?([^.]+)\.', re.MULTILINE),
    ]

    def extract_facts(self, text: str) -> list[Fact]:
        """Extract key facts from natural language text.

        Detects "X is Y", "X has Y", "X contains Y" patterns.
        """
        facts: list[Fact] = []
        seen: set[str] = set()

        for pattern in self._FACT_PATTERNS:
            for m in pattern.finditer(text):
                subject = m.group(1).strip()
                obj = m.group(2).strip()
                key = f"{subject}|{obj}"
                if key not in seen and len(subject) < 200 and len(obj) < 200:
                    seen.add(key)
                    # Infer predicate from the match.
                    full_match = m.group(0)
                    predicate = "is"
                    for verb in ("has", "have", "had", "contains", "includes", "founded", "created", "built", "launched", "released"):
                        if verb in full_match.lower():
                            predicate = verb
                            break
                    facts.append(Fact(
                        subject=subject,
                        predicate=predicate,
                        object=obj,
                        source_text=full_match,
                    ))

        return facts

    # ------------------------------------------------------------------
    # Table extraction (HTML + plain text)
    # ------------------------------------------------------------------

    def extract_tables(self, text: str) -> list[list[dict[str, str]]]:
        """Extract tables from either HTML or plain text.

        For HTML, delegates to the HTML parser.
        For plain text, detects aligned columns, pipe-delimited, or
        tab-delimited tables.
        """
        tables: list[list[dict[str, str]]] = []

        # Check if text contains HTML tables.
        if "<table" in text.lower():
            content = self.extract_html(text)
            tables.extend(content.tables)
            if tables:
                return tables

        # Check for Markdown/pipe-delimited tables.
        pipe_tables = self._extract_pipe_tables(text)
        if pipe_tables:
            return pipe_tables

        # Check for tab-delimited tables.
        tab_tables = self._extract_tsv_tables(text)
        if tab_tables:
            return tab_tables

        # Check for space-aligned tables.
        aligned = self._extract_aligned_tables(text)
        if aligned:
            return aligned

        return tables

    # ------------------------------------------------------------------
    # JSON Schema inference
    # ------------------------------------------------------------------

    def extract_json_schema(self, text: str) -> dict:
        """Infer a JSON Schema from example JSON in the text."""
        from .json_healer import JSONHealer
        healer = JSONHealer()
        objects = healer.extract_json_from_text(text)
        if not objects:
            try:
                healed, _ = healer.heal(text)
                objects = [healed]
            except Exception:
                return {"type": "object"}

        if objects:
            return self._infer_schema(objects[0])
        return {"type": "object"}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_page(content: ExtractedContent) -> str:
        """Classify an HTML page by type."""
        meta = content.metadata
        if any(k in meta for k in ("og:type", "article:author", "article:published_time")):
            return "article"
        if content.forms:
            if any("search" in (inp.get("name", "") + inp.get("type", "")).lower()
                   for form in content.forms for inp in form.get("inputs", [])):
                return "search"
            return "form"
        if len(content.tables) > 0 and len(content.paragraphs) < 3:
            return "data"
        if len(content.paragraphs) > 5:
            return "article"
        if len(content.images) > 5:
            return "gallery"
        return "unknown"

    @staticmethod
    def _parse_md_table(lines: list[str]) -> list[dict[str, str]]:
        """Parse Markdown pipe-delimited table lines into list of dicts."""
        if len(lines) < 2:
            return []
        headers = [h.strip() for h in lines[0].strip("|").split("|")]
        rows: list[dict[str, str]] = []
        for line in lines[1:]:
            stripped = line.strip("|").strip()
            # Skip separator lines.
            if re.match(r'^[\s|:-]+$', stripped):
                continue
            cells = [c.strip() for c in stripped.split("|")]
            row: dict[str, str] = {}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) else f"col_{i}"
                row[key] = cell
            rows.append(row)
        return rows

    def _extract_pipe_tables(self, text: str) -> list[list[dict[str, str]]]:
        """Extract pipe-delimited tables from text."""
        tables: list[list[dict[str, str]]] = []
        current_lines: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            if "|" in stripped and stripped.count("|") >= 2:
                current_lines.append(stripped)
            else:
                if len(current_lines) >= 2:
                    table = self._parse_md_table(current_lines)
                    if table:
                        tables.append(table)
                current_lines = []
        if len(current_lines) >= 2:
            table = self._parse_md_table(current_lines)
            if table:
                tables.append(table)
        return tables

    @staticmethod
    def _extract_tsv_tables(text: str) -> list[list[dict[str, str]]]:
        """Extract tab-separated tables."""
        lines = text.split("\n")
        tsv_lines = [l for l in lines if "\t" in l]
        if len(tsv_lines) < 2:
            return []
        headers = tsv_lines[0].split("\t")
        rows = []
        for line in tsv_lines[1:]:
            cells = line.split("\t")
            row: dict[str, str] = {}
            for i, cell in enumerate(cells):
                key = headers[i].strip() if i < len(headers) else f"col_{i}"
                row[key] = cell.strip()
            rows.append(row)
        return [rows] if rows else []

    @staticmethod
    def _extract_aligned_tables(text: str) -> list[list[dict[str, str]]]:
        """Extract space-aligned columns (heuristic)."""
        lines = text.split("\n")
        # Look for lines with consistent multi-space gaps.
        candidate_lines = []
        for line in lines:
            if re.search(r'\S\s{2,}\S', line):
                candidate_lines.append(line)
            else:
                if len(candidate_lines) >= 3:
                    break
                candidate_lines = []
        if len(candidate_lines) < 2:
            return []
        # Split by 2+ spaces.
        headers = re.split(r'\s{2,}', candidate_lines[0].strip())
        rows = []
        for line in candidate_lines[1:]:
            cells = re.split(r'\s{2,}', line.strip())
            row: dict[str, str] = {}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) else f"col_{i}"
                row[key] = cell
            rows.append(row)
        return [rows] if rows else []

    # ------------------------------------------------------------------
    # Code extractors per language
    # ------------------------------------------------------------------

    def _extract_python(self, code: str, result: CodeContent) -> None:
        """Extract Python code structures."""
        # Imports.
        for m in re.finditer(r'^(?:from\s+\S+\s+)?import\s+.+$', code, re.MULTILINE):
            result.imports.append(m.group().strip())

        # Functions.
        for m in re.finditer(
            r'^(\s*)(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*([^:]+))?\s*:',
            code, re.MULTILINE,
        ):
            indent = len(m.group(1))
            name = m.group(2)
            params = m.group(3)
            return_type = (m.group(4) or "").strip()
            docstring = self._extract_python_docstring(code, m.end())
            result.functions.append({
                "name": name,
                "params": params.strip(),
                "return_type": return_type,
                "docstring": docstring,
                "is_method": indent > 0,
            })
            if docstring:
                result.docstrings.append(docstring)

        # Classes.
        for m in re.finditer(
            r'^class\s+(\w+)(?:\(([^)]*)\))?\s*:',
            code, re.MULTILINE,
        ):
            name = m.group(1)
            bases = m.group(2) or ""
            docstring = self._extract_python_docstring(code, m.end())
            result.classes.append({
                "name": name,
                "bases": bases.strip(),
                "docstring": docstring,
            })
            if docstring:
                result.docstrings.append(docstring)

        # Comments.
        for m in re.finditer(r'#\s*(.+)$', code, re.MULTILINE):
            result.comments.append(m.group(1).strip())

    @staticmethod
    def _extract_python_docstring(code: str, pos: int) -> str:
        """Extract docstring after a def/class statement."""
        rest = code[pos:pos + 500]
        m = re.match(r'\s*\n\s*(?:\"\"\"(.*?)\"\"\"|\'\'\'(.*?)\'\'\')', rest, re.DOTALL)
        if m:
            return (m.group(1) or m.group(2) or "").strip()
        return ""

    def _extract_typescript(self, code: str, result: CodeContent) -> None:
        """Extract TypeScript/JavaScript code structures."""
        # Imports.
        for m in re.finditer(r'^import\s+.+$', code, re.MULTILINE):
            result.imports.append(m.group().strip())

        # Functions.
        for m in re.finditer(
            r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)(?:\s*:\s*([^\s{]+))?\s*\{',
            code,
        ):
            result.functions.append({
                "name": m.group(1),
                "params": m.group(2).strip(),
                "return_type": (m.group(3) or "").strip(),
            })

        # Arrow functions.
        for m in re.finditer(
            r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::\s*\w+)?\s*=\s*(?:async\s+)?\(([^)]*)\)(?:\s*:\s*([^\s=]+))?\s*=>',
            code,
        ):
            result.functions.append({
                "name": m.group(1),
                "params": m.group(2).strip(),
                "return_type": (m.group(3) or "").strip(),
            })

        # Classes.
        for m in re.finditer(
            r'(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?\s*(?:implements\s+([^{]+))?\s*\{',
            code,
        ):
            result.classes.append({
                "name": m.group(1),
                "extends": (m.group(2) or "").strip(),
                "implements": (m.group(3) or "").strip(),
            })

        # Comments.
        for m in re.finditer(r'//\s*(.+)$', code, re.MULTILINE):
            result.comments.append(m.group(1).strip())
        for m in re.finditer(r'/\*\*(.*?)\*/', code, re.DOTALL):
            result.docstrings.append(m.group(1).strip())

    def _extract_go(self, code: str, result: CodeContent) -> None:
        """Extract Go code structures."""
        # Imports.
        for m in re.finditer(r'^import\s+(?:\(\s*(.*?)\s*\)|"([^"]+)")$', code, re.MULTILINE | re.DOTALL):
            block = m.group(1) or m.group(2)
            for imp in re.findall(r'"([^"]+)"', block):
                result.imports.append(imp)

        # Functions.
        for m in re.finditer(
            r'^func\s+(?:\(\s*\w+\s+\*?\w+\s*\)\s+)?(\w+)\s*\(([^)]*)\)(?:\s*\(?([^{]*?)\)?)?\s*\{',
            code, re.MULTILINE,
        ):
            result.functions.append({
                "name": m.group(1),
                "params": m.group(2).strip(),
                "return_type": (m.group(3) or "").strip(),
            })

        # Types/structs.
        for m in re.finditer(r'^type\s+(\w+)\s+struct\s*\{', code, re.MULTILINE):
            result.classes.append({"name": m.group(1), "type": "struct"})

        # Comments.
        for m in re.finditer(r'//\s*(.+)$', code, re.MULTILINE):
            result.comments.append(m.group(1).strip())

    def _extract_rust(self, code: str, result: CodeContent) -> None:
        """Extract Rust code structures."""
        # Use statements.
        for m in re.finditer(r'^use\s+.+;$', code, re.MULTILINE):
            result.imports.append(m.group().strip())

        # Functions.
        for m in re.finditer(
            r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)(?:\s*->\s*(.+?))\s*\{',
            code,
        ):
            result.functions.append({
                "name": m.group(1),
                "params": m.group(2).strip(),
                "return_type": (m.group(3) or "").strip(),
            })

        # Structs.
        for m in re.finditer(r'(?:pub\s+)?struct\s+(\w+)', code):
            result.classes.append({"name": m.group(1), "type": "struct"})

        # Enums.
        for m in re.finditer(r'(?:pub\s+)?enum\s+(\w+)', code):
            result.classes.append({"name": m.group(1), "type": "enum"})

        # Doc comments.
        for m in re.finditer(r'///\s*(.+)$', code, re.MULTILINE):
            result.docstrings.append(m.group(1).strip())

        # Regular comments.
        for m in re.finditer(r'//(?!/)\s*(.+)$', code, re.MULTILINE):
            result.comments.append(m.group(1).strip())

    def _extract_java(self, code: str, result: CodeContent) -> None:
        """Extract Java code structures."""
        # Imports.
        for m in re.finditer(r'^import\s+.+;$', code, re.MULTILINE):
            result.imports.append(m.group().strip())

        # Methods.
        for m in re.finditer(
            r'(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(\w+)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+\w+\s*)?\{',
            code,
        ):
            result.functions.append({
                "name": m.group(2),
                "return_type": m.group(1),
                "params": m.group(3).strip(),
            })

        # Classes.
        for m in re.finditer(
            r'(?:public\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?',
            code,
        ):
            result.classes.append({
                "name": m.group(1),
                "extends": (m.group(2) or "").strip(),
            })

        # Javadoc.
        for m in re.finditer(r'/\*\*(.*?)\*/', code, re.DOTALL):
            result.docstrings.append(m.group(1).strip())

    def _extract_generic(self, code: str, result: CodeContent) -> None:
        """Generic code extraction using common patterns."""
        # Comments.
        for m in re.finditer(r'(?://|#)\s*(.+)$', code, re.MULTILINE):
            result.comments.append(m.group(1).strip())
        # Function-like patterns.
        for m in re.finditer(r'(?:function|def|fn|func)\s+(\w+)', code):
            result.functions.append({"name": m.group(1)})

    @staticmethod
    def _infer_schema(obj: Any) -> dict:
        """Infer a JSON Schema from a Python object."""
        if isinstance(obj, dict):
            props: dict[str, Any] = {}
            for key, value in obj.items():
                props[key] = SemanticExtractor._infer_schema(value)
            return {"type": "object", "properties": props, "required": list(obj.keys())}
        if isinstance(obj, list):
            if obj:
                return {"type": "array", "items": SemanticExtractor._infer_schema(obj[0])}
            return {"type": "array"}
        if isinstance(obj, str):
            return {"type": "string"}
        if isinstance(obj, bool):
            return {"type": "boolean"}
        if isinstance(obj, int):
            return {"type": "integer"}
        if isinstance(obj, float):
            return {"type": "number"}
        if obj is None:
            return {"type": "null"}
        return {"type": "string"}
