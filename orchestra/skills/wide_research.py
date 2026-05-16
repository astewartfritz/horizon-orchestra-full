"""Horizon Orchestra — Wide Research Skill.

Batch entity research — Horizon Prince wide research pattern.
Researches a list of entities concurrently using a configurable prompt
template, extracts structured data per-entity via an LLM, and saves
results to CSV.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import Skill

if TYPE_CHECKING:
    from ..router import ModelRouter
    from ..perplexity import PerplexitySearch

__all__ = ["WideResearch"]

log = logging.getLogger("orchestra.skills.wide_research")

_WORKSPACE = Path(os.environ.get("ORCHESTRA_WORKSPACE", "/tmp/orchestra_wide"))


# ---------------------------------------------------------------------------
# Wide Research
# ---------------------------------------------------------------------------

class WideResearch(Skill):
    """Batch entity research with structured extraction.

    For each entity in a list, substitutes the entity into a
    ``{entity}`` prompt template, performs a web search (via Perplexity
    Sonar or LLM knowledge), extracts structured data per *output_schema*,
    and saves results to CSV.
    """

    name: str = "wide_research"
    description: str = (
        "Research a list of entities in parallel. For each entity, search the web "
        "and extract structured data fields. Returns a CSV file of results."
    )

    def __init__(
        self,
        router: ModelRouter,
        perplexity: PerplexitySearch | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        self.router = router
        self.perplexity = perplexity
        self.workspace = Path(workspace) if workspace else _WORKSPACE
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def research_entities(
        self,
        entities: list[str],
        prompt_template: str,
        output_schema: dict[str, Any],
        max_parallel: int = 10,
    ) -> list[dict[str, Any]]:
        """Research a list of entities in parallel.

        Args:
            entities: List of entity names / identifiers.
            prompt_template: Research prompt with ``{entity}`` placeholder.
            output_schema: JSON Schema dict describing the output fields
                           (keys are field names; values are descriptions).
            max_parallel: Maximum concurrent research tasks (semaphore size).

        Returns:
            List of result dicts — one per entity — matching *output_schema*.
        """
        log.info(
            "research_entities() n=%d max_parallel=%d schema_fields=%s",
            len(entities), max_parallel, list(output_schema.keys()),
        )
        semaphore = asyncio.Semaphore(max_parallel)
        t_start = time.monotonic()

        async def _one(entity: str) -> dict[str, Any]:
            async with semaphore:
                return await self._research_single_entity(
                    entity, prompt_template, output_schema
                )

        tasks = [_one(e) for e in entities]
        results: list[dict[str, Any] | BaseException] = await asyncio.gather(
            *tasks, return_exceptions=True
        )

        output: list[dict[str, Any]] = []
        for entity, result in zip(entities, results):
            if isinstance(result, BaseException):
                log.warning("Entity %r failed: %s", entity, result)
                # Include error row so the CSV is complete
                row: dict[str, Any] = {"entity": entity, "_error": str(result)}
                row.update({k: "" for k in output_schema if k != "entity"})
                output.append(row)
            else:
                output.append(result)

        # Save to CSV
        if output:
            ts = int(time.monotonic())
            csv_path = self.workspace / f"wide_research_{ts}.csv"
            _save_csv(output, str(csv_path))
            log.info(
                "wide_research done in %.2fs — %d rows saved to %s",
                time.monotonic() - t_start, len(output), csv_path,
            )
            # Attach path to every result so callers know where the file is
            for row in output:
                row["_csv_path"] = str(csv_path)

        return output

    async def research_from_file(
        self,
        entities_file: str,
        prompt_template: str,
        output_schema: dict[str, Any],
        output_csv: str = "",
        max_parallel: int = 10,
    ) -> str:
        """Read entity names from a file (one per line), research them, save CSV.

        Args:
            entities_file: Path to a plain-text file with one entity per line.
            prompt_template: Research prompt with ``{entity}`` placeholder.
            output_schema: Dict of field_name → description.
            output_csv: Optional explicit output CSV path.
            max_parallel: Maximum concurrency.

        Returns:
            Path to the saved CSV file.
        """
        path = Path(entities_file)
        if not path.exists():
            raise FileNotFoundError(f"Entities file not found: {entities_file}")

        entities = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        log.info("research_from_file() loaded %d entities from %s", len(entities), entities_file)

        results = await self.research_entities(
            entities, prompt_template, output_schema, max_parallel=max_parallel
        )

        # Determine CSV path
        if output_csv:
            csv_path = output_csv
            _save_csv(results, csv_path)
        else:
            csv_path = results[0].get("_csv_path", str(self.workspace / "wide_output.csv")) if results else ""
            if csv_path:
                _save_csv(results, csv_path)

        return csv_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _research_single_entity(
        self,
        entity: str,
        prompt_template: str,
        output_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Run research for a single entity and extract structured output."""
        # Build the research query
        query = prompt_template.replace("{entity}", entity)

        # Web search
        raw_text = await self._search(query, entity)

        # Extract structured data
        extracted = await self._extract_structured(raw_text, output_schema)

        # Always include the entity name
        extracted["entity"] = entity
        return extracted

    async def _search(self, query: str, entity: str) -> str:
        """Search for an entity — Sonar if available, else LLM knowledge."""
        if self.perplexity:
            try:
                result = await self.perplexity.search(query, model="sonar")
                text = result.content
                if result.citations:
                    text += "\n\nSources:\n" + "\n".join(result.citations[:5])
                return text
            except Exception as exc:
                log.warning("Sonar search for %r failed: %s", entity, exc)

        # LLM fallback
        model_name = self.router.route("reasoning")
        client, model_id = self.router.get_client(model_name)
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": query}],
                max_tokens=1500,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            log.error("LLM fallback search failed for %r: %s", entity, exc)
            return f"[Search failed: {exc}]"

    async def _extract_structured(
        self,
        text: str,
        schema: dict[str, Any],
        router: ModelRouter | None = None,
    ) -> dict[str, Any]:
        """Use LLM to extract structured data from *text* per *schema*.

        Args:
            text: Raw research text to extract data from.
            schema: Dict mapping field names to their descriptions/types.
            router: Optional override router (uses ``self.router`` if None).

        Returns:
            Dict matching the schema keys.
        """
        rtr = router or self.router

        # Build schema description
        schema_lines = []
        for field_name, field_desc in schema.items():
            if isinstance(field_desc, dict):
                desc = field_desc.get("description", str(field_desc))
                type_str = field_desc.get("type", "string")
                schema_lines.append(f"  {field_name} ({type_str}): {desc}")
            else:
                schema_lines.append(f"  {field_name}: {field_desc}")
        schema_str = "\n".join(schema_lines)

        field_names = list(schema.keys())
        prompt = (
            f"Extract the following structured information from the text below. "
            f"Respond with ONLY a valid JSON object. Use null for missing values.\n\n"
            f"Required fields:\n{schema_str}\n\n"
            f"=== TEXT ===\n{text[:4000]}\n\n"
            f"JSON output (keys: {field_names}):"
        )

        model_name = rtr.route("reasoning")
        client, model_id = rtr.get_client(model_name)

        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            raw = resp.choices[0].message.content or "{}"
            # Extract JSON block
            extracted = _parse_json_response(raw)
            # Ensure all schema keys are present
            for k in field_names:
                if k not in extracted:
                    extracted[k] = None
            return extracted
        except Exception as exc:
            log.error("Structured extraction failed: %s", exc)
            return {k: None for k in field_names}

    # ------------------------------------------------------------------
    # Skill ABC interface
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "wide_research",
                    "description": (
                        "Research a list of entities in parallel. For each entity, "
                        "substitutes {entity} into the prompt template, searches the web, "
                        "and extracts structured output fields. Returns a list of result dicts."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entities": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of entity names to research.",
                            },
                            "prompt_template": {
                                "type": "string",
                                "description": (
                                    "Research prompt. Use {entity} as a placeholder. "
                                    "Example: 'Find the CEO and founding year of {entity}'"
                                ),
                            },
                            "output_schema": {
                                "type": "object",
                                "description": (
                                    "Dict mapping field names to descriptions. "
                                    "Example: {\"ceo\": \"Full name of the CEO\", "
                                    "\"founded\": \"Year the company was founded\"}"
                                ),
                            },
                            "max_parallel": {
                                "type": "integer",
                                "description": "Max concurrent tasks (default 10).",
                                "default": 10,
                            },
                        },
                        "required": ["entities", "prompt_template", "output_schema"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "wide_research_from_file",
                    "description": (
                        "Read entity names from a file (one per line), research each, "
                        "and save results to a CSV. Returns the CSV file path."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entities_file": {
                                "type": "string",
                                "description": "Path to a plain-text file with one entity per line.",
                            },
                            "prompt_template": {
                                "type": "string",
                                "description": "Research prompt with {entity} placeholder.",
                            },
                            "output_schema": {
                                "type": "object",
                                "description": "Dict mapping field names to descriptions.",
                            },
                            "output_csv": {
                                "type": "string",
                                "description": "Optional output CSV path.",
                                "default": "",
                            },
                            "max_parallel": {
                                "type": "integer",
                                "description": "Max concurrent tasks (default 10).",
                                "default": 10,
                            },
                        },
                        "required": ["entities_file", "prompt_template", "output_schema"],
                    },
                },
            },
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "wide_research":
            results = await self.research_entities(
                entities=params["entities"],
                prompt_template=params["prompt_template"],
                output_schema=params["output_schema"],
                max_parallel=int(params.get("max_parallel", 10)),
            )
            return {"results": results, "count": len(results)}

        if action == "wide_research_from_file":
            csv_path = await self.research_from_file(
                entities_file=params["entities_file"],
                prompt_template=params["prompt_template"],
                output_schema=params["output_schema"],
                output_csv=params.get("output_csv", ""),
                max_parallel=int(params.get("max_parallel", 10)),
            )
            return {"csv_path": csv_path}

        return {"error": f"Unknown action: {action!r}"}


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _save_csv(rows: list[dict[str, Any]], path: str) -> None:
    """Save a list of dicts as a CSV file."""
    if not rows:
        return
    # Collect all unique keys, put 'entity' first
    all_keys: list[str] = []
    seen_keys: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen_keys:
                all_keys.append(k)
                seen_keys.add(k)

    # Reorder: entity first, _csv_path / _error last
    priority = ["entity"]
    meta = [k for k in all_keys if k.startswith("_")]
    middle = [k for k in all_keys if k not in priority and k not in meta]
    fieldnames = priority + middle + meta

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _parse_json_response(text: str) -> dict[str, Any]:
    """Extract and parse a JSON object from a (possibly noisy) LLM response."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract from code fence
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Find first {...} block
    m2 = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group(0))
        except json.JSONDecodeError:
            pass

    log.warning("Could not parse JSON from LLM response: %s", text[:200])
    return {}
