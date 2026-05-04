"""Horizon Orchestra — Skills System.

Skills are reusable instruction sets that teach Orchestra agents how to
handle specific tasks.  Modelled on Perplexity Computer's Skills feature.

A skill is a Markdown file with YAML frontmatter::

    ---
    name: research-report
    description: Use when asked to research a topic and produce a detailed report.
                 Activates on: research, analyze, investigate, deep-dive
    version: "1.0"
    author: ashton
    models_preferred: ["claude-opus-4.6-openrouter", "sonar-reasoning-pro"]
    tools_required: ["web_search", "fetch_url", "file_write", "memory_search"]
    chains_to: ["slides", "executive-summary"]
    ---

    # Research Report Skill

    You are a rigorous research analyst. When this skill activates:

    1. Start with memory_search to check prior research on this topic
    2. Use web_search with at least 5 distinct queries
    3. For each major claim, fetch the source URL and verify
    4. Synthesize findings with inline citations [Source: URL]
    5. Structure: Executive Summary → Key Findings → Evidence → Recommendations
    6. Save to /tmp/horizon_workspace/research_{topic}_{date}.md

Built-in skills ship as Python strings in this module (so they work without
any filesystem access).  Custom skills are stored in ~/.horizon/skills/.

Usage::

    from orchestra.skills import SkillRegistry, SkillLoader

    registry = SkillRegistry.default()

    # Auto-select skills for a task
    active = registry.match("Research the top 5 CRM platforms and make slides")
    # -> [SkillMatch(skill=Skill(name='research'), ...), SkillMatch(skill=Skill(name='slides'), ...)]

    # Build enriched system prompt
    system = registry.build_system_prompt(active, base_prompt="You are Orchestra...")
"""

from __future__ import annotations

import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
    HAS_YAML = True
except ImportError:
    yaml = None  # type: ignore[assignment]
    HAS_YAML = False

__all__ = [
    "Skill",
    "SkillMatch",
    "SkillChain",
    "SkillLoader",
    "SkillRegistry",
    "SkillActivator",
    "BUILTIN_SKILLS",
    "parse_skill_md",
    "match_skills",
]

log = logging.getLogger("orchestra.skills")


# ---------------------------------------------------------------------------
# Built-in skill definitions (shipped as Python strings — no filesystem needed)
# ---------------------------------------------------------------------------

BUILTIN_SKILLS: list[dict[str, Any]] = [
    {
        "name": "research",
        "description": (
            "Use when asked to research a topic, investigate a subject, analyze information, "
            "study an area, do a deep-dive, look into something, or find out about a topic. "
            "Activates on: research, investigate, analyze, study, deep-dive, look into, find out about, "
            "explore, examine, discover, survey, review literature"
        ),
        "instructions": """\
# Research Skill

You are a rigorous research analyst. Apply this methodology for every research task:

## Process
1. **Memory check** — Call `memory_search` with the topic first. Retrieve any prior research,
   user preferences, or relevant context already stored.
2. **Multi-angle search** — Use `web_search` with at least 5 distinct queries covering:
   - Primary topic overview
   - Recent developments (include current year in query)
   - Expert perspectives / criticism
   - Data and statistics
   - Practical implications
3. **Source verification** — For each major claim, call `fetch_url` on the source URL to
   read the primary content. Do not rely on search snippets alone.
4. **Cross-reference** — Identify where sources agree and disagree. Note conflicts explicitly.
5. **Citation discipline** — Every fact must cite its source as `[Source: URL]` inline.
6. **Synthesis** — Produce a structured report:
   - Executive Summary (3–5 sentences)
   - Key Findings (bullet list with citations)
   - Evidence & Analysis (subsections per theme)
   - Limitations & Gaps
   - Recommendations / Next Steps
7. **Save output** — Write the finished report to
   `/tmp/horizon_workspace/research_{topic}_{date}.md` using `file_write`.

## Quality Standards
- Minimum 5 distinct sources per major claim cluster
- Never state something as fact without a citation
- Flag speculative statements with "(unverified)"
- Include publication dates for all sources
""",
        "models_preferred": ["sonar-reasoning-pro", "claude-opus-4.6-openrouter"],
        "tools_required": ["web_search", "fetch_url", "memory_search", "file_write"],
        "chains_to": ["research-report", "slides", "executive-summary"],
        "tags": ["research", "analysis", "information-gathering"],
    },
    {
        "name": "slides",
        "description": (
            "Use when asked to create a presentation, slides, deck, PowerPoint, Keynote, "
            "or any slide-based show. Activates on: presentation, slides, deck, PowerPoint, "
            "keynote, show, slideshow, pitch deck, slide deck"
        ),
        "instructions": """\
# Slides Skill

You are an expert presentation designer. Follow these rules for every deck:

## Structure Rules
- **10–15 slides maximum** — focus ruthlessly; cut rather than pad
- Every slide has: a punchy **title** (≤8 words) + **3–5 bullet points**
- Bullet points are fragments, not sentences — max 10 words each
- Slide 1: Title + subtitle + presenter name
- Slide 2: Agenda / outline
- Last slide: Key takeaways + call to action

## Content Rules
- Data slides: one chart / table per slide with a headline finding caption
- No more than 2 concepts per slide
- Use the "So what?" test — every bullet must answer "why does this matter?"
- Include speaker notes for each slide (2–4 sentences of talking points)

## Output Format
Use Markdown with slide separators:

```
# Slide 1 Title
- Bullet one
- Bullet two
- Bullet three

> **Speaker notes:** Talking points here.

---

# Slide 2 Title
...
```

## Process
1. If research data is available (from the `research` skill), load it first
2. Identify 3–5 key messages the audience should remember
3. Build slide outline, then flesh out each slide
4. Write speaker notes last
5. Save the finished deck to `/tmp/horizon_workspace/deck_{title}_{date}.md` via `file_write`
""",
        "models_preferred": ["claude-opus-4.6-openrouter", "claude-sonnet-4.6"],
        "tools_required": ["file_write", "execute_code"],
        "chains_to": ["research"],
        "tags": ["presentations", "slides", "storytelling"],
    },
    {
        "name": "data-analysis",
        "description": (
            "Use when asked to analyze data, work with CSV files, datasets, statistics, "
            "trends, charts, visualizations, or spreadsheets. Activates on: analyze data, "
            "CSV, dataset, statistics, trends, chart, visualize, spreadsheet, data exploration, "
            "EDA, correlation, regression, distribution"
        ),
        "instructions": """\
# Data Analysis Skill

You are a data scientist. Apply this workflow for every data analysis task:

## Workflow
1. **Load & inspect** — Use `file_read` to load the data. Print shape, dtypes, first 5 rows,
   and `describe()` statistics.
2. **Clean** — Handle missing values (report count and %), remove duplicates, fix dtypes,
   standardise string casing. Document every cleaning decision.
3. **Explore (EDA)** — Compute:
   - Distributions (histograms for numeric, bar charts for categorical)
   - Correlations (heatmap for numeric columns)
   - Outlier detection (IQR method, flag but don't auto-remove)
   - Time trends if a date column exists
4. **Visualise** — Generate Python code using `matplotlib` / `seaborn`. Save charts as PNG
   to `/tmp/horizon_workspace/charts/` via `execute_code` + `file_write`.
5. **Insights** — Write 5–10 bullet-point findings, ranked by business impact.
6. **Save results** — Output a Markdown summary + the chart files.

## Code Standards
- Use pandas for data manipulation
- Use seaborn for statistical charts, matplotlib for custom plots
- Always set figure size explicitly: `fig, ax = plt.subplots(figsize=(10, 6))`
- Use `plt.tight_layout()` before saving
- Handle exceptions around file loading and plotting

## Output
- Summary report: `/tmp/horizon_workspace/analysis_{name}_{date}.md`
- Charts: `/tmp/horizon_workspace/charts/{name}_{chart_type}.png`
""",
        "models_preferred": ["gemma-4-31b", "claude-sonnet-4.6"],
        "tools_required": ["execute_code", "file_read", "file_write"],
        "chains_to": ["research-report"],
        "tags": ["data", "statistics", "visualization", "EDA"],
    },
    {
        "name": "code-review",
        "description": (
            "Use when asked to review code, do a code review, audit code, check code for bugs, "
            "find bugs, review a PR, or review a pull request. Activates on: review code, "
            "code review, PR review, audit, check this code, find bugs, code audit, "
            "security review, quality check"
        ),
        "instructions": """\
# Code Review Skill

You are a senior software engineer. Perform systematic code reviews:

## Review Checklist (in order)

### 1. Correctness
- Does the code do what it claims to do?
- Are edge cases handled (empty inputs, nulls, boundary values)?
- Are error paths tested and handled?

### 2. Security
- SQL injection, XSS, command injection vulnerabilities
- Hardcoded secrets or credentials
- Unsafe deserialization
- Missing authentication / authorisation checks
- Dependency vulnerabilities (flag outdated packages)

### 3. Performance
- Obvious O(n²) or worse algorithms where O(n log n) is available
- N+1 query problems
- Missing indexes on frequently queried fields
- Unnecessary memory allocations in hot paths

### 4. Style & Readability
- Naming clarity (variables, functions, classes)
- Function length (>50 lines is a smell)
- Dead code, commented-out blocks
- Consistency with codebase conventions

### 5. Test Coverage
- Are there tests for the new code?
- Are happy-path AND error-path cases tested?
- Are tests meaningful (not just coverage-padding)?

### 6. Error Handling
- Are exceptions caught at the right level?
- Are error messages user-friendly and loggable?

## Output Format

```
## Summary
[2-3 sentence overall assessment]

## Critical Issues 🔴
[Must fix before merge — numbered list]

## Warnings 🟡
[Should fix — numbered list]

## Suggestions 🟢
[Nice to have — numbered list]

## Positive Notes ✅
[What the code does well]
```

## Process
- Use `file_read` to load all relevant files
- Use `execute_code` to run tests and check for obvious runtime errors
- Use `web_search` to verify security best practices for specific frameworks
""",
        "models_preferred": ["claude-opus-4.6-openrouter", "gemma-4-31b", "kimi-k2.5"],
        "tools_required": ["file_read", "execute_code", "web_search"],
        "chains_to": [],
        "tags": ["code", "review", "security", "quality"],
    },
    {
        "name": "writing",
        "description": (
            "Use when asked to write, draft, or compose text content: blog posts, articles, "
            "essays, emails, copy, documentation, or any written material. Activates on: "
            "write, draft, compose, blog post, article, essay, email, copy, content, "
            "documentation, letter, report, announcement"
        ),
        "instructions": """\
# Writing Skill

You are a professional writer and editor. Produce polished written content:

## Core Principles
- **Hook first** — the opening line must compel the reader to continue
- **Match tone to context** — formal for business, conversational for blogs,
  authoritative for technical docs
- **Vary sentence length** — alternate short punchy sentences with longer ones
- **No corporate jargon** — ban: "leverage", "synergy", "circle back", "bandwidth",
  "move the needle", "low-hanging fruit"
- **Show, don't tell** — use specific examples and numbers, not adjectives

## Structure
1. **Hook** — striking opening (question, surprising stat, bold claim, story)
2. **Context** — why this matters to the reader right now
3. **Body** — well-organized content with clear subheadings
4. **CTA / Conclusion** — what should the reader do or think next?

## Process
1. Clarify the audience, tone, and goal (infer from context if not stated)
2. Use `memory_search` to check any user preferences on voice or style
3. Use `web_search` to verify any facts or statistics included
4. Write a first draft
5. **Revision pass** — read aloud mentally; cut every word that doesn't earn its place
6. Add estimated reading time at the top (avg 238 words/min)
7. Save to `/tmp/horizon_workspace/writing_{title}_{date}.md` via `file_write`

## Format Conventions
- Subheadings: use H2 (##) for sections, H3 (###) for subsections
- Lists: use when 3+ parallel items; avoid lists of 2 (just use "and")
- Bold: only for the single most important phrase per paragraph
- Estimated reading time: add as `*~N min read*` at the very top
""",
        "models_preferred": ["claude-opus-4.6-openrouter", "claude-sonnet-4.6"],
        "tools_required": ["web_search", "file_write", "memory_search"],
        "chains_to": [],
        "tags": ["writing", "content", "drafting", "editing"],
    },
    {
        "name": "executive-summary",
        "description": (
            "Use when asked for an executive summary, TL;DR, summary, key points, brief overview, "
            "or concise version of a document or topic. Activates on: executive summary, "
            "TL;DR, summarize, key points, brief, overview, abstract, synopsis, recap"
        ),
        "instructions": """\
# Executive Summary Skill

You produce crisp, high-signal executive summaries for busy decision-makers.

## Hard Constraints
- **Maximum 500 words** — ruthlessly enforce this
- **No padding** — every sentence must carry new information
- **Numbers over adjectives** — "35% increase" beats "significant increase"
- **Active voice** — "The team shipped X" not "X was shipped by the team"

## Format

```
## Executive Summary

**Situation:** [1–2 sentences: what is the context and why does it matter now?]

**Key Findings:**
- Finding 1 (with supporting number/data)
- Finding 2
- Finding 3
- Finding 4 (max 5 bullets)

**Recommendations:**
1. [Specific action] — [expected outcome]
2. [Specific action] — [expected outcome]
3. [Specific action] — [expected outcome] (max 3)

**Next Steps:**
- Owner: [person/team] | Action: [what] | By: [when]
- Owner: [person/team] | Action: [what] | By: [when]
```

## Process
1. Use `file_read` to load any source documents
2. Identify the 3–5 highest-impact points
3. Quantify every claim that can be quantified
4. Write to the template above
5. Check: if a busy CEO read only the Findings + Recommendations, would they have enough to decide?
""",
        "models_preferred": ["claude-sonnet-4.6", "grok-3"],
        "tools_required": ["file_read"],
        "chains_to": [],
        "tags": ["summary", "executive", "brief", "tldr"],
    },
    {
        "name": "debugging",
        "description": (
            "Use when asked to debug code, fix an error, investigate a traceback or exception, "
            "or resolve something that is not working or is broken. Activates on: debug, fix, "
            "error, traceback, exception, not working, broken, crash, bug, issue, problem, "
            "TypeError, ValueError, ImportError, AttributeError"
        ),
        "instructions": """\
# Debugging Skill

You are a systematic debugger. Never guess — trace through the actual execution path.

## Debugging Methodology

### Step 1: Reproduce
- Confirm you can trigger the exact error described
- Note: exact error message, line number, Python/language version, OS if relevant
- Use `execute_code` to reproduce the error in isolation

### Step 2: Isolate
- Reduce to the minimal code that reproduces the issue
- Remove irrelevant code, dependencies, data
- Identify the precise line where the failure occurs

### Step 3: Hypothesize
- List 2–3 plausible root causes, ordered by likelihood
- For each hypothesis, state what evidence would confirm or rule it out

### Step 4: Test Hypotheses
- Test each hypothesis with targeted `execute_code` calls
- Add debug prints / logging at the suspected failure point
- Use `web_search` to check if this is a known issue with the library/version

### Step 5: Fix
- Apply the minimal fix that addresses the root cause
- Do NOT refactor unrelated code in the same commit
- Explain what caused the bug and why the fix works

### Step 6: Verify
- Re-run the original failing code — confirm it passes
- Run the broader test suite if available

### Step 7: Regression Test
- Write a test that would have caught this bug
- Add it to the test suite via `file_write`

## Anti-patterns to Avoid
- Do not catch and suppress exceptions without logging them
- Do not change multiple things at once ("shotgun debugging")
- Do not assume the error message is always the root cause (it may be a symptom)
""",
        "models_preferred": ["claude-opus-4.6-openrouter", "kimi-k2.5"],
        "tools_required": ["execute_code", "file_read", "file_write", "web_search"],
        "chains_to": [],
        "tags": ["debugging", "bugs", "errors", "troubleshooting"],
    },
    {
        "name": "competitor-analysis",
        "description": (
            "Use when asked for competitive analysis, to compare competitors, benchmark products, "
            "do market research, or analyse the competitive landscape. Activates on: competitor, "
            "competitive analysis, vs, compare, benchmark, market research, landscape, "
            "competition, rivals, alternative, comparison"
        ),
        "instructions": """\
# Competitor Analysis Skill

You produce rigorous, evidence-based competitive intelligence.

## Framework: PPMFWG
For each competitor, cover all six dimensions:

1. **Positioning** — target customer, key value proposition, brand voice
2. **Pricing** — tiers, price points, free tier?, enterprise pricing model
3. **Features** — capability matrix vs. the subject product
4. **Weaknesses** — documented complaints, gaps, known limitations
5. **Go-to-market** — acquisition channels, key partnerships, geographic focus
6. **Growth signals** — funding, headcount trend, product velocity, reviews trend

## Evidence Standards
- Every claim requires a source citation `[Source: URL]`
- Use `web_search` + `fetch_url` for each competitor
- Check: company website, G2/Capterra reviews, LinkedIn headcount, Crunchbase funding,
  recent press releases, job postings (reveals roadmap direction)
- Date all data — competitive landscapes shift fast

## Output Format

### Comparison Table
| Dimension | Our Product | Competitor A | Competitor B | Competitor C |
|-----------|-------------|--------------|--------------|--------------|
| Pricing   | ...         | ...          | ...          | ...          |
| Feature X | ✅          | ❌           | ✅           | ⚠️ partial  |

### Per-Competitor Deep Dive
[One section per competitor, following PPMFWG]

### Strategic Implications
- Top 3 threats
- Top 3 opportunities to differentiate
- Recommended positioning response

## Process
1. Use `web_search` with "[competitor name] pricing", "[competitor name] reviews",
   "[competitor name] vs [our product]", "[competitor name] funding"
2. `fetch_url` the competitor's homepage and pricing page
3. Compile comparison table
4. Write strategic implications
5. Save to `/tmp/horizon_workspace/competitive_{topic}_{date}.md` via `file_write`
""",
        "models_preferred": ["sonar-reasoning-pro", "claude-opus-4.6-openrouter"],
        "tools_required": ["web_search", "fetch_url", "file_write"],
        "chains_to": ["slides", "research-report"],
        "tags": ["competitive", "market-research", "strategy", "analysis"],
    },
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    """A reusable instruction set for a specific type of task.

    Skills are identified by a lowercase-hyphen name and matched against
    incoming tasks by keyword overlap on their description field.
    """
    name: str                              # lowercase-hyphen, e.g. "research-report"
    description: str                       # used for matching — include trigger phrases
    instructions: str                      # full markdown body
    version: str = "1.0"
    author: str = "system"
    models_preferred: list[str] = field(default_factory=list)
    tools_required: list[str] = field(default_factory=list)
    chains_to: list[str] = field(default_factory=list)  # skill names this hands off to
    tags: list[str] = field(default_factory=list)
    source_path: str = ""                  # file path if loaded from disk
    is_builtin: bool = False
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (suitable for JSON)."""
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "version": self.version,
            "author": self.author,
            "models_preferred": self.models_preferred,
            "tools_required": self.tools_required,
            "chains_to": self.chains_to,
            "tags": self.tags,
            "source_path": self.source_path,
            "is_builtin": self.is_builtin,
            "created_at": self.created_at,
        }

    @property
    def activation_keywords(self) -> list[str]:
        """Extract meaningful keywords from the description for fast matching.

        Strips stop-words and short tokens; returns lowercase unique words.
        """
        _STOP = {
            "a", "an", "the", "and", "or", "for", "of", "in", "on", "to",
            "is", "are", "be", "by", "as", "at", "do", "use", "when", "asked",
            "with", "any", "this", "that", "it", "from", "about", "into",
            "also", "can", "you", "your", "their", "its", "was", "were",
        }
        raw = re.sub(r"[^\w\s-]", " ", self.description.lower())
        tokens = raw.split()
        seen: dict[str, None] = {}
        result: list[str] = []
        for tok in tokens:
            tok = tok.strip("-_")
            if len(tok) >= 3 and tok not in _STOP and tok not in seen:
                seen[tok] = None
                result.append(tok)
        return result

    def __repr__(self) -> str:  # pragma: no cover
        return f"Skill(name={self.name!r}, version={self.version!r})"


@dataclass
class SkillMatch:
    """A skill paired with its relevance score for a given task."""
    skill: Skill
    score: float                          # 0.0–1.0 relevance score
    matched_keywords: list[str]
    trigger_reason: str                   # human-readable explanation

    def __repr__(self) -> str:  # pragma: no cover
        return f"SkillMatch(skill={self.skill.name!r}, score={self.score:.2f})"


@dataclass
class SkillChain:
    """An ordered sequence of skills that will execute together."""
    skills: list[Skill]
    total_instructions: str              # combined prompt injection
    required_tools: set[str]
    preferred_models: list[str]

    def __repr__(self) -> str:  # pragma: no cover
        names = [s.name for s in self.skills]
        return f"SkillChain(skills={names!r})"


# ---------------------------------------------------------------------------
# SkillLoader
# ---------------------------------------------------------------------------

class SkillLoader:
    """Loads skills from .md files and .zip archives.

    Searches :attr:`SKILL_DIRS` by default; individual paths can also be
    passed directly to :meth:`load_from_file`.
    """

    SKILL_DIRS: list[Path] = [
        Path(__file__).parent / "skills",        # built-in skills dir
        Path.home() / ".horizon" / "skills",     # user skills
        Path("/tmp/horizon_workspace/skills"),    # workspace skills
    ]

    # -- public API ----------------------------------------------------------

    def load_from_file(self, path: Path) -> Skill:
        """Load a single .md skill file.  Parses YAML frontmatter."""
        path = Path(path)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"Cannot read skill file {path}: {exc}") from exc

        skill = self.load_from_string(content, name=path.stem)
        skill.source_path = str(path)
        log.debug("Loaded skill %r from %s", skill.name, path)
        return skill

    def load_from_zip(self, path: Path) -> list[Skill]:
        """Load all skills from a .zip archive.

        The archive may contain one or more ``.md`` files anywhere in its
        tree.  Each ``.md`` is parsed as a skill.
        """
        path = Path(path)
        skills: list[Skill] = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                md_names = [n for n in zf.namelist() if n.endswith(".md")]
                if not md_names:
                    log.warning("No .md files found in zip archive %s", path)
                    return skills
                for name in md_names:
                    try:
                        content = zf.read(name).decode("utf-8")
                        stem = Path(name).stem
                        skill = self.load_from_string(content, name=stem)
                        skill.source_path = f"{path}!{name}"
                        skills.append(skill)
                        log.debug("Loaded skill %r from %s!%s", skill.name, path, name)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Failed to parse skill from %s!%s: %s", path, name, exc)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"Not a valid zip archive: {path}") from exc
        return skills

    def load_from_string(self, content: str, name: str = "") -> Skill:
        """Parse a skill from a markdown string.

        Frontmatter fields take precedence over the ``name`` argument.
        """
        meta, body = self._parse_frontmatter(content)

        skill_name = meta.get("name", name) or name
        if not skill_name:
            skill_name = "unnamed-skill"

        # Normalise to lowercase-hyphen
        skill_name = re.sub(r"[^a-z0-9-]", "-", skill_name.lower()).strip("-")
        if not self.validate_name(skill_name):
            log.warning("Skill name %r is invalid; using 'unnamed-skill'", skill_name)
            skill_name = "unnamed-skill"

        # Parse list fields — accept either YAML lists or comma-separated strings
        def _to_list(val: Any) -> list[str]:
            if isinstance(val, list):
                return [str(v) for v in val]
            if isinstance(val, str):
                return [v.strip() for v in val.split(",") if v.strip()]
            return []

        return Skill(
            name=skill_name,
            description=str(meta.get("description", body[:200])),
            instructions=body.strip(),
            version=str(meta.get("version", "1.0")),
            author=str(meta.get("author", "user")),
            models_preferred=_to_list(meta.get("models_preferred", [])),
            tools_required=_to_list(meta.get("tools_required", [])),
            chains_to=_to_list(meta.get("chains_to", [])),
            tags=_to_list(meta.get("tags", [])),
            is_builtin=bool(meta.get("is_builtin", False)),
            created_at=float(meta.get("created_at", time.time())),
        )

    def load_directory(self, directory: Path) -> list[Skill]:
        """Load all .md files from a directory (non-recursive)."""
        directory = Path(directory)
        if not directory.exists():
            log.debug("Skill directory does not exist: %s", directory)
            return []

        skills: list[Skill] = []
        for md_path in sorted(directory.glob("*.md")):
            try:
                skills.append(self.load_from_file(md_path))
            except Exception as exc:  # noqa: BLE001
                log.warning("Skipping skill file %s: %s", md_path, exc)
        return skills

    def load_all(self) -> list[Skill]:
        """Load skills from all :attr:`SKILL_DIRS`."""
        skills: list[Skill] = []
        for directory in self.SKILL_DIRS:
            skills.extend(self.load_directory(directory))
        log.info("Loaded %d skills from filesystem (all SKILL_DIRS)", len(skills))
        return skills

    # -- private helpers -----------------------------------------------------

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
        """Split YAML frontmatter from the markdown body.

        Returns ``(meta_dict, body_string)``.  If no frontmatter is found,
        returns ``({}, full_content)``.
        """
        content = content.lstrip()
        if not content.startswith("---"):
            return {}, content

        # Find the closing ---
        end_marker = content.find("\n---", 3)
        if end_marker == -1:
            return {}, content

        yaml_block = content[3:end_marker].strip()
        body = content[end_marker + 4:].lstrip("\n")

        meta: dict[str, Any] = {}
        if HAS_YAML:
            try:
                parsed = yaml.safe_load(yaml_block)
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception as exc:  # noqa: BLE001
                log.warning("YAML parse error in frontmatter: %s; falling back to simple parser", exc)
                meta = SkillLoader._simple_frontmatter_parse(yaml_block)
        else:
            meta = SkillLoader._simple_frontmatter_parse(yaml_block)

        return meta, body

    @staticmethod
    def _simple_frontmatter_parse(block: str) -> dict[str, Any]:
        """Minimal key: value frontmatter parser (no PyYAML required).

        Handles simple string values and bracketed list syntax.
        """
        meta: dict[str, Any] = {}
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, raw_val = line.partition(":")
            key = key.strip()
            raw_val = raw_val.strip()

            # Bracketed list: ["a", "b", "c"]
            if raw_val.startswith("[") and raw_val.endswith("]"):
                inner = raw_val[1:-1]
                items = [
                    v.strip().strip('"').strip("'")
                    for v in inner.split(",")
                    if v.strip().strip('"').strip("'")
                ]
                meta[key] = items
            else:
                # Strip surrounding quotes
                raw_val = raw_val.strip('"').strip("'")
                meta[key] = raw_val

        return meta

    @staticmethod
    def validate_name(name: str) -> bool:
        """Validate skill name: lowercase, hyphens only, 1–64 chars."""
        return bool(re.match(r"^[a-z][a-z0-9-]{0,62}[a-z0-9]?$", name))


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------

class SkillRegistry:
    """Registry of available skills with keyword matching for auto-activation.

    Holds both built-in skills (from :data:`BUILTIN_SKILLS`) and custom
    skills loaded from disk or created programmatically.
    """

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        if skills:
            for skill in skills:
                self.register(skill)

    # -- registration --------------------------------------------------------

    def register(self, skill: Skill) -> None:
        """Add or replace a skill in the registry."""
        if skill.name in self._skills:
            log.debug("Replacing existing skill %r", skill.name)
        self._skills[skill.name] = skill
        log.debug("Registered skill %r (builtin=%s)", skill.name, skill.is_builtin)

    def unregister(self, name: str) -> None:
        """Remove a skill by name.  Silent if not found."""
        removed = self._skills.pop(name, None)
        if removed:
            log.debug("Unregistered skill %r", name)

    def get(self, name: str) -> Skill | None:
        """Retrieve a skill by exact name."""
        return self._skills.get(name)

    # -- matching ------------------------------------------------------------

    def match(
        self,
        task: str,
        max_skills: int = 3,
        min_score: float = 0.15,
    ) -> list[SkillMatch]:
        """Find skills that match a task description.

        Scoring algorithm:

        1. Tokenise the task into lowercase words (≥3 chars, no stop-words).
        2. For each skill, count how many of its :attr:`~Skill.activation_keywords`
           appear in the task tokens.
        3. Base score = ``matched_keywords / total_skill_keywords``.
        4. **Phrase boost** (+0.25): at least one bigram from the skill description
           appears verbatim in the lowercased task.
        5. **Tag boost** (+0.10 each): any skill tag found in the task tokens.
        6. Return up to ``max_skills`` matches with score ≥ ``min_score``,
           sorted descending by score.
        """
        task_lower = task.lower()
        task_tokens = set(re.sub(r"[^\w\s-]", " ", task_lower).split())

        _STOP = {
            "a", "an", "the", "and", "or", "for", "of", "in", "on", "to",
            "is", "are", "be", "by", "as", "at", "do", "use", "when",
            "with", "any", "this", "that", "it", "from", "about", "into",
        }
        task_tokens = {t for t in task_tokens if len(t) >= 3 and t not in _STOP}

        matches: list[SkillMatch] = []

        for skill in self._skills.values():
            keywords = skill.activation_keywords
            if not keywords:
                continue

            matched = [kw for kw in keywords if kw in task_tokens]
            base_score = len(matched) / len(keywords) if keywords else 0.0

            # Phrase boost: check 2-word phrases from the skill description
            phrase_boost = 0.0
            words = re.sub(r"[^\w\s]", " ", skill.description.lower()).split()
            bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
            for bigram in bigrams:
                if bigram in task_lower:
                    phrase_boost = 0.25
                    break

            # Tag boost
            tag_boost = sum(
                0.10 for tag in skill.tags
                if tag.lower().replace("-", " ") in task_lower
                or tag.lower() in task_tokens
            )
            tag_boost = min(tag_boost, 0.30)  # cap tag contribution

            score = min(1.0, base_score + phrase_boost + tag_boost)

            if score >= min_score:
                top_matches = sorted(matched, key=lambda kw: -len(kw))[:5]
                phrase_info = f"phrase '{bigrams[0]}' matched; " if phrase_boost else ""
                reason = (
                    f"{phrase_info}{len(matched)}/{len(keywords)} keywords matched "
                    f"({', '.join(top_matches[:3]) or 'none'})"
                )
                matches.append(SkillMatch(
                    skill=skill,
                    score=score,
                    matched_keywords=matched,
                    trigger_reason=reason,
                ))

        matches.sort(key=lambda m: m.score, reverse=True)
        result = matches[:max_skills]
        if result:
            log.info(
                "Matched %d skill(s) for task %r: %s",
                len(result),
                task[:60],
                [f"{m.skill.name}({m.score:.2f})" for m in result],
            )
        else:
            log.debug("No skills matched task %r (min_score=%.2f)", task[:60], min_score)
        return result

    # -- chaining ------------------------------------------------------------

    def resolve_chain(self, skill_names: list[str]) -> list[Skill]:
        """Resolve a list of skill names to Skill objects, deduplicating.

        Skills that cannot be found are logged and skipped.
        """
        seen: set[str] = set()
        result: list[Skill] = []
        for name in skill_names:
            if name in seen:
                continue
            seen.add(name)
            skill = self.get(name)
            if skill:
                result.append(skill)
            else:
                log.debug("Chain references unknown skill %r; skipping", name)
        return result

    def build_chain(self, seed_matches: list[SkillMatch]) -> SkillChain:
        """Build a full :class:`SkillChain` from seed matches, following ``chains_to``.

        Performs a breadth-first expansion: for each matched skill, adds its
        ``chains_to`` skills (looked up in the registry).  Each skill appears
        at most once.
        """
        seen: set[str] = set()
        ordered: list[Skill] = []

        queue: list[Skill] = [m.skill for m in seed_matches]
        # Also expand chains_to for each seed
        for m in seed_matches:
            for chained_name in m.skill.chains_to:
                chained = self.get(chained_name)
                if chained and chained.name not in [s.name for s in queue]:
                    queue.append(chained)

        for skill in queue:
            if skill.name not in seen:
                seen.add(skill.name)
                ordered.append(skill)

        instructions = self.build_system_prompt(ordered)
        required_tools: set[str] = set()
        preferred_models: list[str] = []
        seen_models: set[str] = set()
        for skill in ordered:
            required_tools.update(skill.tools_required)
            for m in skill.models_preferred:
                if m not in seen_models:
                    preferred_models.append(m)
                    seen_models.add(m)

        return SkillChain(
            skills=ordered,
            total_instructions=instructions,
            required_tools=required_tools,
            preferred_models=preferred_models,
        )

    # -- prompt building -----------------------------------------------------

    def build_system_prompt(
        self,
        matches: list[SkillMatch] | list[Skill],
        base_prompt: str = "",
    ) -> str:
        """Build an enriched system prompt from matched skills.

        Accepts either a list of :class:`SkillMatch` or raw :class:`Skill`
        objects for convenience.

        Output format::

            {base_prompt}

            ## Active Skills

            ### research
            [instructions]

            ---
            ### slides
            [instructions]

            ---
            ## Required Tools for This Task
            web_search, fetch_url, file_write
        """
        # Normalise to list[Skill]
        skills: list[Skill] = []
        for item in matches:
            if isinstance(item, SkillMatch):
                skills.append(item.skill)
            else:
                skills.append(item)

        if not skills:
            return base_prompt

        parts: list[str] = []
        if base_prompt:
            parts.append(base_prompt.rstrip())
            parts.append("")

        parts.append("## Active Skills")
        parts.append("")

        for skill in skills:
            parts.append(f"### {skill.name}")
            parts.append(skill.instructions.strip())
            parts.append("")
            parts.append("---")
            parts.append("")

        # Union of all required tools
        all_tools: set[str] = set()
        for skill in skills:
            all_tools.update(skill.tools_required)

        if all_tools:
            parts.append("## Required Tools for This Task")
            parts.append(", ".join(sorted(all_tools)))
            parts.append("")

        return "\n".join(parts).strip()

    def get_preferred_models(self, matches: list[SkillMatch]) -> list[str]:
        """Return a deduplicated ordered list of preferred models from matches.

        Models from higher-scored matches appear first.
        """
        seen: set[str] = set()
        result: list[str] = []
        for match in sorted(matches, key=lambda m: m.score, reverse=True):
            for model in match.skill.models_preferred:
                if model not in seen:
                    result.append(model)
                    seen.add(model)
        return result

    # -- persistence ---------------------------------------------------------

    def save_skill(self, skill: Skill, directory: Path | None = None) -> Path:
        """Save a skill to disk as a .md file with YAML frontmatter.

        Defaults to ``~/.horizon/skills/``.
        """
        if directory is None:
            directory = Path.home() / ".horizon" / "skills"
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        out_path = directory / f"{skill.name}.md"

        frontmatter_lines = [
            "---",
            f"name: {skill.name}",
            f'description: "{skill.description}"',
            f"version: \"{skill.version}\"",
            f"author: {skill.author}",
        ]
        if skill.models_preferred:
            models_str = json.dumps(skill.models_preferred)
            frontmatter_lines.append(f"models_preferred: {models_str}")
        if skill.tools_required:
            tools_str = json.dumps(skill.tools_required)
            frontmatter_lines.append(f"tools_required: {tools_str}")
        if skill.chains_to:
            chains_str = json.dumps(skill.chains_to)
            frontmatter_lines.append(f"chains_to: {chains_str}")
        if skill.tags:
            tags_str = json.dumps(skill.tags)
            frontmatter_lines.append(f"tags: {tags_str}")
        frontmatter_lines.append(f"created_at: {skill.created_at}")
        frontmatter_lines.append("---")

        content = "\n".join(frontmatter_lines) + "\n\n" + skill.instructions.strip() + "\n"
        out_path.write_text(content, encoding="utf-8")
        log.info("Saved skill %r to %s", skill.name, out_path)
        return out_path

    def create_skill_from_description(
        self,
        name: str,
        description: str,
        instructions: str,
        models_preferred: list[str] | None = None,
        tools_required: list[str] | None = None,
        chains_to: list[str] | None = None,
        tags: list[str] | None = None,
        author: str = "user",
    ) -> Skill:
        """Create and register a skill programmatically.

        The skill is registered immediately but not saved to disk.
        Call :meth:`save_skill` to persist it.
        """
        loader = SkillLoader()
        clean_name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
        if not SkillLoader.validate_name(clean_name):
            raise ValueError(
                f"Invalid skill name {name!r}. "
                "Must be lowercase letters, digits, and hyphens; 1–64 chars."
            )

        skill = Skill(
            name=clean_name,
            description=description,
            instructions=instructions,
            models_preferred=models_preferred or [],
            tools_required=tools_required or [],
            chains_to=chains_to or [],
            tags=tags or [],
            author=author,
            is_builtin=False,
            created_at=time.time(),
        )
        self.register(skill)
        log.info("Created custom skill %r", clean_name)
        return skill

    # -- convenience properties ----------------------------------------------

    @property
    def all_skills(self) -> list[Skill]:
        """All registered skills, sorted by name."""
        return sorted(self._skills.values(), key=lambda s: s.name)

    @property
    def builtin_skills(self) -> list[Skill]:
        """Only built-in skills."""
        return [s for s in self.all_skills if s.is_builtin]

    @property
    def custom_skills(self) -> list[Skill]:
        """Only user-created / filesystem skills."""
        return [s for s in self.all_skills if not s.is_builtin]

    def list_skills(self) -> list[dict[str, Any]]:
        """Return a list of skill summary dicts (no instructions body)."""
        return [
            {
                "name": s.name,
                "description": s.description[:100] + ("..." if len(s.description) > 100 else ""),
                "version": s.version,
                "author": s.author,
                "is_builtin": s.is_builtin,
                "tags": s.tags,
                "tools_required": s.tools_required,
                "models_preferred": s.models_preferred,
                "chains_to": s.chains_to,
            }
            for s in self.all_skills
        ]

    # -- factory -------------------------------------------------------------

    @classmethod
    def default(cls) -> "SkillRegistry":
        """Create a registry pre-loaded with all built-in skills.

        Also attempts to load custom skills from filesystem SKILL_DIRS.
        Built-in skills can be overridden by user skills with the same name.
        """
        registry = cls()

        # Register built-in skills
        for raw in BUILTIN_SKILLS:
            skill = Skill(
                name=raw["name"],
                description=raw["description"],
                instructions=raw["instructions"],
                models_preferred=raw.get("models_preferred", []),
                tools_required=raw.get("tools_required", []),
                chains_to=raw.get("chains_to", []),
                tags=raw.get("tags", []),
                author="system",
                is_builtin=True,
                created_at=0.0,
            )
            registry.register(skill)

        log.info("Loaded %d built-in skills", len(BUILTIN_SKILLS))

        # Load filesystem skills (user overrides built-ins)
        loader = SkillLoader()
        fs_skills = loader.load_all()
        for skill in fs_skills:
            registry.register(skill)  # overwrites built-in if same name

        return registry


# ---------------------------------------------------------------------------
# SkillActivator
# ---------------------------------------------------------------------------

class SkillActivator:
    """Automatically activates skills during agent execution.

    Plugs into agent classes (``MonolithicAgent``, ``SwarmAgent``) to
    enrich system prompts with relevant skill instructions based on the
    incoming task.
    """

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        auto_activate: bool = True,
        max_skills: int = 3,
        min_score: float = 0.15,
    ) -> None:
        self.registry = registry or SkillRegistry.default()
        self.auto_activate = auto_activate
        self.max_skills = max_skills
        self.min_score = min_score

    def activate_for_task(self, task: str) -> tuple[list[SkillMatch], str]:
        """Match skills and build an enriched system prompt addition.

        Returns ``(matches, prompt_addition)``.  If ``auto_activate`` is
        ``False``, returns an empty list and empty string.
        """
        if not self.auto_activate:
            return [], ""

        matches = self.registry.match(
            task,
            max_skills=self.max_skills,
            min_score=self.min_score,
        )
        if not matches:
            return [], ""

        prompt_addition = self.registry.build_system_prompt(matches)
        log.info(
            "SkillActivator: activated %d skill(s) for task: %s",
            len(matches),
            [m.skill.name for m in matches],
        )
        return matches, prompt_addition

    def get_required_tools(self, matches: list[SkillMatch]) -> list[str]:
        """Return sorted list of all tools required by the matched skills."""
        tools: set[str] = set()
        for match in matches:
            tools.update(match.skill.tools_required)
        return sorted(tools)

    def get_preferred_models(self, matches: list[SkillMatch]) -> list[str]:
        """Return ordered list of preferred models from the matched skills."""
        return self.registry.get_preferred_models(matches)


# ---------------------------------------------------------------------------
# Top-level convenience functions
# ---------------------------------------------------------------------------

def parse_skill_md(content: str) -> Skill:
    """Parse a SKILL.md string into a :class:`Skill` object.

    Convenience wrapper around :meth:`SkillLoader.load_from_string`.
    """
    return SkillLoader().load_from_string(content)


def match_skills(
    task: str,
    registry: SkillRegistry | None = None,
) -> list[SkillMatch]:
    """Match skills for a task against the default (or supplied) registry.

    Convenience function for one-line skill matching::

        matches = match_skills("Debug this Python traceback")
    """
    reg = registry or SkillRegistry.default()
    return reg.match(task)
