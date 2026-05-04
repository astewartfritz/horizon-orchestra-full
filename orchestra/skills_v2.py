"""Horizon Orchestra — Skills 2.0 with Self-Improving Evaluation Loops.

Mirrors Claude's AutoDream concept: skills are prompt templates with
evaluation criteria. An :class:`SkillEvaluator` scores outputs, identifies
weaknesses, and uses an LLM to rewrite the skill's prompt. Skills
accumulate version history and success rates over time.

Usage::

    from orchestra.skills_v2 import SkillV2, SkillStore, SkillEvaluator, SkillComposer
    from orchestra.router import ModelRouter

    router = ModelRouter()
    store = SkillStore()
    evaluator = SkillEvaluator(router=router)

    skill = SkillV2(
        name="summarise",
        description="Summarise a document in 3 bullet points",
        prompt_template="Summarise the following in exactly 3 bullet points:\\n\\n{input}",
        evaluation_criteria="Output has exactly 3 bullet points. Each is concise.",
    )
    store.register(skill)

    # Run a scenario
    output = "• Point 1\\n• Point 2\\n• Point 3"
    score = await evaluator.evaluate(skill, input="Long document...", output=output)
    print(score.score, score.passed)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "SkillV2",
    "EvalScore",
    "SkillStore",
    "SkillEvaluator",
    "SkillComposer",
]

log = logging.getLogger("orchestra.skills_v2")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SkillV2:
    """A versioned, self-improving skill with evaluation criteria.

    Attributes:
        name: Unique skill identifier.
        description: Human-readable description of what the skill does.
        prompt_template: Jinja2-style template with ``{input}`` and other
            placeholders. Used to build prompts for LLM calls.
        evaluation_criteria: Plain-text criteria the LLM evaluator uses
            to judge outputs (e.g. "Output must be ≤ 5 sentences.").
        version: Monotonically increasing integer; incremented on each
            improvement cycle.
        success_rate: Rolling average of passed/total evaluations (0.0–1.0).
        total_runs: Total number of times this skill has been evaluated.
        created_at: Unix timestamp of initial creation.
        updated_at: Unix timestamp of last improvement.
        tags: Optional tags for filtering and discovery.
        model: Preferred LLM model for this skill. Empty = use router default.
    """

    name: str
    description: str
    prompt_template: str
    evaluation_criteria: str = ""
    version: int = 1
    success_rate: float = 1.0
    total_runs: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    model: str = ""

    def render(self, **kwargs: Any) -> str:
        """Render the prompt template with provided keyword arguments.

        Args:
            **kwargs: Template variable values (e.g. ``input="text"``).

        Returns:
            Rendered prompt string.
        """
        try:
            return self.prompt_template.format(**kwargs)
        except KeyError as exc:
            log.warning("Missing template variable %s for skill %r", exc, self.name)
            return self.prompt_template

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict."""
        return {
            "name": self.name,
            "description": self.description,
            "prompt_template": self.prompt_template,
            "evaluation_criteria": self.evaluation_criteria,
            "version": self.version,
            "success_rate": self.success_rate,
            "total_runs": self.total_runs,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillV2":
        """Deserialise from a dict (e.g. loaded from JSON).

        Args:
            data: Dict with skill fields.

        Returns:
            Reconstructed :class:`SkillV2` instance.
        """
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            prompt_template=data.get("prompt_template", ""),
            evaluation_criteria=data.get("evaluation_criteria", ""),
            version=data.get("version", 1),
            success_rate=data.get("success_rate", 1.0),
            total_runs=data.get("total_runs", 0),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            tags=data.get("tags", []),
            model=data.get("model", ""),
        )


@dataclass
class EvalScore:
    """Result of evaluating a skill's output.

    Attributes:
        score: Float in [0, 1]. 1.0 = perfect.
        passed: Boolean pass/fail based on a threshold (typically 0.7).
        reasoning: LLM's explanation of the score.
        suggestions: Concrete suggestions for improvement.
    """

    score: float
    passed: bool
    reasoning: str = ""
    suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SkillStore
# ---------------------------------------------------------------------------

class SkillStore:
    """Registry for :class:`SkillV2` instances with JSON persistence.

    Skills are stored in memory and optionally persisted to disk.

    Args:
        storage_path: Path to the JSON file for persistence.
            If None, the store is in-memory only.
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        self._skills: dict[str, SkillV2] = {}
        self._storage_path = Path(storage_path) if storage_path else None

        if self._storage_path and self._storage_path.exists():
            try:
                self.load_from_disk(str(self._storage_path))
            except Exception as exc:
                log.warning("Failed to load skills from %s: %s", storage_path, exc)

    def register(self, skill: SkillV2) -> None:
        """Register a skill (or replace an existing one with the same name).

        Args:
            skill: :class:`SkillV2` instance to store.
        """
        self._skills[skill.name] = skill
        log.debug("Registered skill %r (v%d)", skill.name, skill.version)

    def get(self, name: str) -> SkillV2:
        """Return a skill by name.

        Args:
            name: Skill name.

        Returns:
            :class:`SkillV2` instance.

        Raises:
            KeyError: If the skill is not registered.
        """
        if name not in self._skills:
            raise KeyError(f"Skill {name!r} not registered")
        return self._skills[name]

    def list(self) -> list[SkillV2]:
        """Return all registered skills, sorted by name.

        Returns:
            Alphabetically sorted list of :class:`SkillV2` instances.
        """
        return sorted(self._skills.values(), key=lambda s: s.name)

    def save_to_disk(self, path: str) -> None:
        """Persist all registered skills to a JSON file.

        Args:
            path: Filesystem path for the JSON file. Directories are
                created automatically.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {name: skill.to_dict() for name, skill in self._skills.items()}
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Saved %d skills to %s", len(data), path)

    def load_from_disk(self, path: str) -> None:
        """Load skills from a JSON file, merging with the current store.

        Skills that already exist in the store are overwritten.

        Args:
            path: Path to the JSON file created by :meth:`save_to_disk`.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Skills file not found: {path}")
        data = json.loads(p.read_text(encoding="utf-8"))
        for name, skill_dict in data.items():
            skill = SkillV2.from_dict(skill_dict)
            self._skills[skill.name] = skill
        log.info("Loaded %d skills from %s", len(data), path)


# ---------------------------------------------------------------------------
# SkillEvaluator
# ---------------------------------------------------------------------------

_EVAL_PROMPT = """\
You are a skill evaluator. Given the skill's evaluation criteria, the input,
and the output, score the output from 0.0 to 1.0.

Skill: {skill_name}
Evaluation criteria: {criteria}

Input:
{input}

Output:
{output}

Return a JSON object:
{{
  "score": 0.85,
  "passed": true,
  "reasoning": "The output meets X criteria but misses Y.",
  "suggestions": ["Improve X by doing Y", "Add Z"]
}}

Only return valid JSON. No markdown fences.
"""

_IMPROVE_PROMPT = """\
You are a prompt engineer. A skill's prompt template is underperforming.
Rewrite it to address the observed failures.

Skill: {skill_name}
Current prompt template:
{current_template}

Evaluation criteria: {criteria}

Observed failures (input → output → reason):
{failures}

Return a JSON object:
{{
  "prompt_template": "...new template with {{input}} placeholder...",
  "reasoning": "What you changed and why"
}}

Only return valid JSON. No markdown fences.
"""

_DREAM_PROMPT = """\
You are a test scenario generator. Generate {n} diverse test scenarios for
the following skill to stress-test it and reveal weaknesses.

Skill: {skill_name}
Description: {description}
Prompt template: {template}
Evaluation criteria: {criteria}

Return a JSON array of objects:
[
  {{
    "input": "...",
    "expected_outcome": "...",
    "difficulty": "easy|medium|hard|edge_case"
  }}
]

Only return valid JSON. No markdown fences.
"""


class SkillEvaluator:
    """Evaluate and improve :class:`SkillV2` instances using LLM feedback.

    Args:
        router: ModelRouter for LLM calls.
        model: Default model for evaluation. Falls back to router default.
        pass_threshold: Score threshold above which a result counts as
            "passed" (default: 0.7).
    """

    def __init__(
        self,
        router: Any | None = None,
        model: str = "kimi-k2.5",
        pass_threshold: float = 0.7,
    ) -> None:
        self.router = router
        self.model = model
        self.pass_threshold = pass_threshold

    async def evaluate(
        self,
        skill: SkillV2,
        input: str,
        output: str,
    ) -> EvalScore:
        """Score an output produced by *skill* against the evaluation criteria.

        Updates ``skill.success_rate`` and ``skill.total_runs`` in-place.

        Args:
            skill: The skill that produced *output*.
            input: The original input text.
            output: The skill's output to evaluate.

        Returns:
            :class:`EvalScore` with score, pass/fail, reasoning, and suggestions.
        """
        if not skill.evaluation_criteria:
            # No criteria defined — assume pass
            score = EvalScore(score=1.0, passed=True, reasoning="No criteria defined.")
        elif self.router is None:
            # No LLM — use length heuristic
            score = self._heuristic_eval(output)
        else:
            score = await self._llm_eval(skill, input, output)

        # Update skill stats
        prev_total = skill.total_runs
        skill.total_runs += 1
        skill.success_rate = (
            (skill.success_rate * prev_total + (1.0 if score.passed else 0.0))
            / skill.total_runs
        )
        log.debug(
            "Evaluated skill %r: score=%.2f passed=%s success_rate=%.2f",
            skill.name, score.score, score.passed, skill.success_rate,
        )
        return score

    async def improve(
        self,
        skill: SkillV2,
        failures: list[dict[str, Any]],
    ) -> SkillV2:
        """Rewrite the skill's prompt template based on observed failures.

        Args:
            skill: Skill to improve. Its ``prompt_template`` will be updated
                in-place, and ``version`` is incremented.
            failures: List of dicts with keys ``input``, ``output``,
                ``reasoning`` describing what went wrong.

        Returns:
            The same :class:`SkillV2` object with updated template and version.
        """
        if self.router is None:
            log.warning("Cannot improve skill %r without a router", skill.name)
            return skill

        if not failures:
            log.debug("No failures provided for skill %r; skipping improvement", skill.name)
            return skill

        failures_text = "\n".join(
            f"Input: {f.get('input', '')[:300]}\n"
            f"Output: {f.get('output', '')[:300]}\n"
            f"Reason: {f.get('reasoning', '')[:200]}"
            for f in failures[:5]
        )

        prompt = _IMPROVE_PROMPT.format(
            skill_name=skill.name,
            current_template=skill.prompt_template,
            criteria=skill.evaluation_criteria,
            failures=failures_text,
        )

        try:
            client, model_id = self.router.get_client(self.model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are an expert prompt engineer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=4096,
            )
            raw = response.choices[0].message.content or "{}"
            data = self._parse_json(raw)
            new_template = data.get("prompt_template", "")
            if new_template and "{input}" in new_template:
                skill.prompt_template = new_template
                skill.version += 1
                skill.updated_at = time.time()
                skill.success_rate = 1.0  # reset stats for new version
                skill.total_runs = 0
                log.info("Improved skill %r to v%d", skill.name, skill.version)
            else:
                log.warning("LLM improvement did not return a valid template for %r", skill.name)
        except Exception as exc:
            log.warning("Skill improvement failed for %r: %s", skill.name, exc)

        return skill

    async def auto_dream(
        self,
        skill: SkillV2,
        n_scenarios: int = 5,
    ) -> list[dict[str, Any]]:
        """Generate test scenarios to stress-test a skill.

        Implements Claude's AutoDream pattern: generate diverse scenarios,
        run them through the skill (if router available), evaluate each,
        and identify weaknesses.

        Args:
            skill: Skill to test.
            n_scenarios: Number of test scenarios to generate.

        Returns:
            List of scenario dicts with keys: ``input``, ``expected_outcome``,
            ``difficulty``, and optionally ``output``, ``score``, ``passed``.
        """
        if self.router is None:
            log.warning("auto_dream requires a router")
            return []

        # Step 1: Generate scenarios
        prompt = _DREAM_PROMPT.format(
            n=n_scenarios,
            skill_name=skill.name,
            description=skill.description,
            template=skill.prompt_template[:500],
            criteria=skill.evaluation_criteria,
        )

        try:
            client, model_id = self.router.get_client(self.model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "Generate test scenarios as JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=4096,
            )
            raw = response.choices[0].message.content or "[]"
            scenarios: list[dict[str, Any]] = self._parse_json_list(raw)
        except Exception as exc:
            log.warning("Scenario generation failed for %r: %s", skill.name, exc)
            return []

        # Step 2: Run each scenario through the skill and evaluate
        results: list[dict[str, Any]] = []
        for scenario in scenarios[:n_scenarios]:
            input_text = scenario.get("input", "")
            if not input_text:
                continue

            # Run the skill
            rendered_prompt = skill.render(input=input_text)
            output_text = await self._run_skill_prompt(rendered_prompt, skill.model or self.model)

            # Evaluate
            eval_score = await self.evaluate(skill, input_text, output_text)

            results.append({
                **scenario,
                "output": output_text,
                "score": eval_score.score,
                "passed": eval_score.passed,
                "reasoning": eval_score.reasoning,
            })

        passed = sum(1 for r in results if r.get("passed"))
        log.info(
            "AutoDream for %r: %d/%d scenarios passed", skill.name, passed, len(results)
        )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _llm_eval(
        self, skill: SkillV2, input_text: str, output: str
    ) -> EvalScore:
        """Use the LLM to evaluate *output* against *skill.evaluation_criteria*.

        Args:
            skill: The skill being evaluated.
            input_text: Input to the skill.
            output: Skill's output.

        Returns:
            :class:`EvalScore`.
        """
        prompt = _EVAL_PROMPT.format(
            skill_name=skill.name,
            criteria=skill.evaluation_criteria,
            input=input_text[:2000],
            output=output[:2000],
        )

        try:
            client, model_id = self.router.get_client(self.model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": "You are a strict evaluator."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            raw = response.choices[0].message.content or "{}"
            data = self._parse_json(raw)
            score_val = float(data.get("score", 0.5))
            score_val = max(0.0, min(1.0, score_val))
            return EvalScore(
                score=score_val,
                passed=bool(data.get("passed", score_val >= self.pass_threshold)),
                reasoning=data.get("reasoning", ""),
                suggestions=data.get("suggestions", []),
            )
        except Exception as exc:
            log.warning("LLM evaluation failed: %s", exc)
            return EvalScore(score=0.5, passed=False, reasoning=f"Evaluation error: {exc}")

    def _heuristic_eval(self, output: str) -> EvalScore:
        """Simple length-based heuristic when no LLM is available.

        Args:
            output: Skill output to evaluate.

        Returns:
            :class:`EvalScore` based on output length.
        """
        if not output or len(output.strip()) < 10:
            return EvalScore(score=0.1, passed=False, reasoning="Output is too short or empty.")
        score = min(1.0, len(output) / 500)
        return EvalScore(
            score=round(score, 2),
            passed=score >= self.pass_threshold,
            reasoning="Heuristic: score based on output length (no LLM available).",
        )

    async def _run_skill_prompt(self, prompt: str, model: str) -> str:
        """Run a rendered skill prompt through the LLM.

        Args:
            prompt: Rendered prompt string.
            model: Model name to use.

        Returns:
            LLM output text.
        """
        if self.router is None:
            return ""
        try:
            client, model_id = self.router.get_client(model or self.model)
            response = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=2048,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            log.warning("Skill prompt execution failed: %s", exc)
            return ""

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Parse JSON from an LLM response, stripping fences if present."""
        import re
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\s*\n", "", raw)
            raw = re.sub(r"\n```\s*$", "", raw)
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            import re as _re
            m = _re.search(r"\{[\s\S]*\}", raw)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            return {}

    @staticmethod
    def _parse_json_list(raw: str) -> list[Any]:
        """Parse a JSON array from an LLM response."""
        import re
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\s*\n", "", raw)
            raw = re.sub(r"\n```\s*$", "", raw)
        try:
            result = json.loads(raw.strip())
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            import re as _re
            m = _re.search(r"\[[\s\S]*\]", raw)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            return []


# ---------------------------------------------------------------------------
# SkillComposer
# ---------------------------------------------------------------------------

class SkillComposer:
    """Chain multiple skills into a pipeline prompt.

    Takes a list of skill names, looks them up in the store, and builds a
    single composite prompt that instructs the LLM to execute them in
    sequence, passing output from one skill as input to the next.

    Args:
        store: :class:`SkillStore` containing the skills to compose.
    """

    def __init__(self, store: SkillStore) -> None:
        self.store = store

    def compose(self, skills: list[str], goal: str) -> str:
        """Build a pipeline prompt chaining *skills* toward *goal*.

        Args:
            skills: Ordered list of skill names to chain.
            goal: High-level goal or user request.

        Returns:
            Composite prompt string describing the full pipeline.

        Raises:
            KeyError: If any skill name is not in the store.
        """
        skill_objects = [self.store.get(name) for name in skills]

        header = (
            f"You are executing a multi-step skill pipeline to achieve the following goal:\n\n"
            f"Goal: {goal}\n\n"
            f"Execute the following {len(skills)} step(s) in order, using each step's "
            f"output as the input for the next:\n"
        )

        steps: list[str] = []
        for i, skill in enumerate(skill_objects, start=1):
            step = (
                f"Step {i}: {skill.name} — {skill.description}\n"
                f"Instructions:\n{skill.prompt_template}\n"
                f"Evaluation criteria: {skill.evaluation_criteria or '(none)'}"
            )
            steps.append(step)

        footer = (
            "\n\nBegin with Step 1. After completing all steps, provide the final "
            "output that satisfies the goal."
        )

        full_prompt = header + "\n\n" + "\n\n---\n\n".join(steps) + footer
        log.debug(
            "Composed pipeline of %d skills: %s",
            len(skills),
            " → ".join(skills),
        )
        return full_prompt
