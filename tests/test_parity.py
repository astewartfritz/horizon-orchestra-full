"""Tests for the four Perplexity Computer parity modules:
skills.py, model_council.py, citation.py, tasks.py.

All tests run offline — no API keys or network access required.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


# ===========================================================================
# Skills tests (15 tests)
# ===========================================================================

class SkillsBuiltinCountTests(unittest.TestCase):

    def test_builtin_skills_count(self):
        """BUILTIN_SKILLS has exactly 8 entries."""
        from orchestra.skills import BUILTIN_SKILLS
        self.assertEqual(len(BUILTIN_SKILLS), 8)


class SkillDataclassTests(unittest.TestCase):

    def test_skill_dataclass_fields(self):
        """Skill has expected fields: name, description, instructions, etc."""
        from orchestra.skills import Skill
        fields = {f.name for f in dataclasses.fields(Skill)}
        for expected in (
            "name", "description", "instructions", "version", "author",
            "models_preferred", "tools_required", "chains_to", "tags",
            "source_path", "is_builtin", "created_at",
        ):
            self.assertIn(expected, fields)

    def test_skill_activation_keywords(self):
        """activation_keywords property extracts meaningful words from description."""
        from orchestra.skills import Skill
        skill = Skill(
            name="test-skill",
            description="Use when asked to research and investigate topics. Activates on: research, analyze",
            instructions="Do the thing",
        )
        keywords = skill.activation_keywords
        # Should contain non-trivial keywords from the description
        self.assertIsInstance(keywords, list)
        self.assertTrue(len(keywords) > 0)
        # Stop words like 'and', 'to', 'when' should not appear
        for kw in keywords:
            self.assertNotIn(kw, {"and", "or", "to", "when", "use", "asked"})

    def test_validate_name_valid(self):
        """'my-skill' is a valid skill name."""
        from orchestra.skills import SkillLoader
        self.assertTrue(SkillLoader.validate_name("my-skill"))

    def test_validate_name_invalid_spaces(self):
        """'my skill' (with a space) is invalid."""
        from orchestra.skills import SkillLoader
        self.assertFalse(SkillLoader.validate_name("my skill"))

    def test_validate_name_invalid_uppercase(self):
        """'MySkill' (uppercase) is invalid."""
        from orchestra.skills import SkillLoader
        self.assertFalse(SkillLoader.validate_name("MySkill"))

    def test_validate_name_too_long(self):
        """A 65-character name is invalid (max is 64)."""
        from orchestra.skills import SkillLoader
        long_name = "a" * 65
        self.assertFalse(SkillLoader.validate_name(long_name))


class SkillLoaderTests(unittest.TestCase):

    def test_skill_loader_parse_frontmatter(self):
        """SkillLoader._parse_frontmatter correctly parses '---\\nname: test\\n---\\nbody'."""
        from orchestra.skills import SkillLoader
        content = "---\nname: test\ndescription: A test skill\n---\nbody text here"
        meta, body = SkillLoader._parse_frontmatter(content)
        self.assertEqual(meta.get("name"), "test")
        self.assertEqual(meta.get("description"), "A test skill")
        self.assertIn("body text here", body)

    def test_skill_loader_load_from_string(self):
        """load_from_string parses a full skill from a markdown string."""
        from orchestra.skills import SkillLoader
        content = (
            "---\n"
            "name: my-custom-skill\n"
            "description: Use when asked to do custom things\n"
            "version: \"2.0\"\n"
            "---\n"
            "# My Custom Skill\n\n"
            "Do this thing when invoked."
        )
        skill = SkillLoader().load_from_string(content)
        self.assertEqual(skill.name, "my-custom-skill")
        self.assertEqual(skill.version, "2.0")
        self.assertIn("Do this thing", skill.instructions)


class SkillRegistryTests(unittest.TestCase):

    def setUp(self):
        from orchestra.skills import SkillRegistry
        self.registry = SkillRegistry.default()

    def test_skill_registry_default_has_builtins(self):
        """Default registry contains at least 8 built-in skills."""
        self.assertGreaterEqual(len(self.registry._skills), 8)

    def test_skill_registry_match_research(self):
        """'research the top CRM platforms' matches the research skill."""
        matches = self.registry.match("research the top CRM platforms")
        skill_names = [m.skill.name for m in matches]
        self.assertIn("research", skill_names)

    def test_skill_registry_match_slides(self):
        """'create a presentation for the board' matches the slides skill."""
        matches = self.registry.match("create a presentation for the board")
        skill_names = [m.skill.name for m in matches]
        self.assertIn("slides", skill_names)

    def test_skill_registry_match_debug(self):
        """'debug this error traceback' matches the debugging skill."""
        matches = self.registry.match("debug this error traceback")
        skill_names = [m.skill.name for m in matches]
        self.assertIn("debugging", skill_names)

    def test_skill_registry_build_system_prompt(self):
        """build_system_prompt returns a string including the skill name and instructions."""
        matches = self.registry.match("research the top CRM platforms")
        prompt = self.registry.build_system_prompt(matches, base_prompt="You are Orchestra")
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 0)
        # Should contain the base prompt
        self.assertIn("You are Orchestra", prompt)
        # Should contain at least one skill name
        self.assertTrue(
            any(m.skill.name in prompt for m in matches),
            f"None of {[m.skill.name for m in matches]} found in prompt",
        )


class SkillActivatorTests(unittest.TestCase):

    def test_skill_activator_activate_for_task(self):
        """activate_for_task returns a tuple of (matches, prompt_addition)."""
        from orchestra.skills import SkillActivator
        activator = SkillActivator()
        result = activator.activate_for_task("research the top 5 CRMs and build slides")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        matches, prompt_addition = result
        self.assertIsInstance(matches, list)
        self.assertIsInstance(prompt_addition, str)
        # Should have matched at least one skill
        self.assertGreater(len(matches), 0)


# ===========================================================================
# Model Council tests (12 tests)
# ===========================================================================

class CouncilConfigTests(unittest.TestCase):

    def test_council_config_defaults(self):
        """CouncilConfig has the expected default values."""
        from orchestra.model_council import CouncilConfig
        cfg = CouncilConfig(models=["model-a", "model-b"])
        self.assertEqual(cfg.temperature, 0.6)
        self.assertEqual(cfg.max_tokens, 4096)
        self.assertEqual(cfg.timeout_seconds, 120)
        self.assertTrue(cfg.include_model_labels)
        self.assertFalse(cfg.voting_mode)
        self.assertFalse(cfg.require_consensus)


class ModelVoteTests(unittest.TestCase):

    def test_model_vote_fields(self):
        """ModelVote has model, response, latency_seconds, tokens_used, error fields."""
        from orchestra.model_council import ModelVote
        vote = ModelVote(
            model="test-model",
            response="This is my answer.",
            latency_seconds=1.23,
            tokens_used=100,
        )
        self.assertEqual(vote.model, "test-model")
        self.assertEqual(vote.response, "This is my answer.")
        self.assertAlmostEqual(vote.latency_seconds, 1.23)
        self.assertEqual(vote.tokens_used, 100)
        self.assertEqual(vote.error, "")


class CouncilResultTests(unittest.TestCase):

    def _make_result(self, votes=None):
        from orchestra.model_council import CouncilResult, ModelVote
        if votes is None:
            votes = [
                ModelVote(model="model-a", response="Good answer.", latency_seconds=1.0, tokens_used=50),
                ModelVote(model="model-b", response="", latency_seconds=0.5, error="Timeout"),
            ]
        return CouncilResult(
            prompt="What is the best approach?",
            votes=votes,
            consensus="The best approach is X.",
            divergence_points=["Model A prefers X", "Model B prefers Y"],
            unique_insights={"model-a": ["Unique insight A"]},
            agreement_score=0.75,
            orchestrator="model-a",
            total_latency_seconds=2.0,
            fastest_model="model-b",
            most_tokens_model="model-a",
        )

    def test_council_result_successful_votes(self):
        """successful_votes property filters out votes with errors."""
        result = self._make_result()
        successful = result.successful_votes
        self.assertEqual(len(successful), 1)
        self.assertEqual(successful[0].model, "model-a")

    def test_council_result_to_markdown(self):
        """to_markdown returns a non-empty markdown string."""
        result = self._make_result()
        md = result.to_markdown()
        self.assertIsInstance(md, str)
        self.assertGreater(len(md), 0)
        self.assertIn("Model Council Report", md)

    def test_council_result_to_dict(self):
        """to_dict returns a JSON-serializable dict with expected keys."""
        result = self._make_result()
        d = result.to_dict()
        self.assertIsInstance(d, dict)
        for key in ("prompt", "votes", "consensus", "divergence_points",
                    "unique_insights", "agreement_score", "orchestrator",
                    "total_latency_seconds", "fastest_model", "most_tokens_model"):
            self.assertIn(key, d)
        # Verify JSON-serializable
        serialized = json.dumps(d)
        self.assertIsInstance(serialized, str)


class ModelCouncilInitTests(unittest.TestCase):

    def test_model_council_init(self):
        """ModelCouncil constructs with a default router without error."""
        from orchestra.model_council import ModelCouncil
        council = ModelCouncil()
        self.assertIsNotNone(council)
        self.assertIsNotNone(council.router)

    def test_model_council_get_default_council(self):
        """get_default_council returns a non-empty list of model name strings."""
        from orchestra.model_council import ModelCouncil
        council = ModelCouncil()
        defaults = council.get_default_council()
        self.assertIsInstance(defaults, list)
        self.assertGreater(len(defaults), 0)
        for name in defaults:
            self.assertIsInstance(name, str)


class ModelCouncilAsyncTests(unittest.IsolatedAsyncioTestCase):

    async def test_model_council_deliberate_mock(self):
        """deliberate queries models in parallel and synthesises; verify result structure."""
        from orchestra.model_council import ModelCouncil, ModelVote

        council = ModelCouncil()

        async def mock_query(model, prompt, system_prompt, config):
            return ModelVote(
                model=model,
                response=f"My answer from {model}.",
                latency_seconds=1.0,
                tokens_used=50,
            )

        async def mock_synthesize(votes, original_prompt, orchestrator, config):
            return ("Both models agree on approach A.", ["Point 1"], {"model-a": ["insight A"]})

        with mock.patch.object(council, "_query_model", side_effect=mock_query), \
             mock.patch.object(council, "_synthesize", side_effect=mock_synthesize):
            result = await council.deliberate(
                prompt="Should we use approach A or B?",
                models=["model-a", "model-b"],
                orchestrator="model-a",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.prompt, "Should we use approach A or B?")
        self.assertIsInstance(result.votes, list)
        self.assertEqual(len(result.votes), 2)
        self.assertEqual(result.consensus, "Both models agree on approach A.")

    async def test_model_council_handles_failed_model(self):
        """Council continues when one model fails; successful votes are preserved."""
        from orchestra.model_council import ModelCouncil, ModelVote

        council = ModelCouncil()

        async def mock_query(model, prompt, system_prompt, config):
            if model == "model-a":
                return ModelVote(
                    model="model-a",
                    response="The correct answer is X.",
                    latency_seconds=1.0,
                    tokens_used=40,
                )
            # model-b fails
            return ModelVote(
                model="model-b",
                response="",
                latency_seconds=0.1,
                error="Connection refused",
            )

        async def mock_synthesize(votes, original_prompt, orchestrator, config):
            return ("Approach X is best.", [], {"model-a": ["key insight"]})

        with mock.patch.object(council, "_query_model", side_effect=mock_query), \
             mock.patch.object(council, "_synthesize", side_effect=mock_synthesize):
            result = await council.deliberate(
                prompt="Test question",
                models=["model-a", "model-b"],
                orchestrator="model-a",
            )

        # The failed model should appear in the votes list
        failed = [v for v in result.votes if v.error]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].model, "model-b")
        # But the council should still produce a result
        self.assertIsNotNone(result.consensus)


class AgreementScoreTests(unittest.TestCase):

    def test_compute_agreement_score_identical(self):
        """Identical responses yield an agreement score close to 1.0."""
        from orchestra.model_council import ModelCouncil, ModelVote
        council = ModelCouncil()
        text = "The quick brown fox jumps over the lazy dog and it is wonderful"
        votes = [
            ModelVote(model="a", response=text, latency_seconds=1.0),
            ModelVote(model="b", response=text, latency_seconds=1.0),
        ]
        score = council._compute_agreement_score(votes)
        self.assertAlmostEqual(score, 1.0, places=3)

    def test_compute_agreement_score_different(self):
        """Very different responses yield a low agreement score."""
        from orchestra.model_council import ModelCouncil, ModelVote
        council = ModelCouncil()
        votes = [
            ModelVote(
                model="a",
                response="Alpha beta gamma delta epsilon zeta eta theta iota kappa",
                latency_seconds=1.0,
            ),
            ModelVote(
                model="b",
                response="One two three four five six seven eight nine ten eleven twelve",
                latency_seconds=1.0,
            ),
        ]
        score = council._compute_agreement_score(votes)
        self.assertLess(score, 0.3)

    def test_council_deliberate_result_fields(self):
        """CouncilResult has consensus, votes, and agreement_score fields."""
        from orchestra.model_council import CouncilResult, ModelVote
        result = CouncilResult(
            prompt="Test",
            votes=[ModelVote(model="x", response="answer", latency_seconds=0.5)],
            consensus="Agreed answer",
            divergence_points=[],
            unique_insights={},
            agreement_score=0.9,
            orchestrator="x",
            total_latency_seconds=0.5,
            fastest_model="x",
            most_tokens_model="x",
        )
        self.assertIsInstance(result.consensus, str)
        self.assertIsInstance(result.votes, list)
        self.assertIsInstance(result.agreement_score, float)


# ===========================================================================
# Citation tests (15 tests)
# ===========================================================================

class CitationDataclassTests(unittest.TestCase):

    def test_source_dataclass_fields(self):
        """Source dataclass has url, title, content, retrieved_at, tool, citation_index, times_cited."""
        from orchestra.citation import Source
        fields = {f.name for f in dataclasses.fields(Source)}
        for expected in ("url", "title", "content", "retrieved_at", "tool",
                         "citation_index", "times_cited"):
            self.assertIn(expected, fields)

    def test_citation_dataclass_fields(self):
        """Citation dataclass has marker, index, claim, source, confidence."""
        from orchestra.citation import Citation
        fields = {f.name for f in dataclasses.fields(Citation)}
        for expected in ("marker", "index", "claim", "source", "confidence"):
            self.assertIn(expected, fields)


class GroundedResponseTests(unittest.TestCase):

    def _make_grounded(self, citation_rate=0.9):
        from orchestra.citation import GroundedResponse
        return GroundedResponse(
            original="Some text",
            grounded="Some text [1]",
            sources=[],
            citations=[],
            uncited_claims=[],
            citation_rate=citation_rate,
            sources_section="## Sources\n[1] https://example.com",
        )

    def test_grounded_response_citation_rate(self):
        """GroundedResponse.citation_rate returns the correct value."""
        gr = self._make_grounded(citation_rate=0.75)
        self.assertAlmostEqual(gr.citation_rate, 0.75)

    def test_grounded_response_fully_grounded(self):
        """fully_grounded returns True when citation_rate > 0.8."""
        gr_high = self._make_grounded(citation_rate=0.9)
        self.assertTrue(gr_high.fully_grounded)
        gr_low = self._make_grounded(citation_rate=0.5)
        self.assertFalse(gr_low.fully_grounded)


class CitationTrackerTests(unittest.TestCase):

    def setUp(self):
        from orchestra.citation import CitationTracker
        self.tracker = CitationTracker()

    def test_citation_tracker_add_source(self):
        """add_source registers a source and returns a Source object."""
        from orchestra.citation import Source
        src = self.tracker.add_source(
            "https://example.com/article",
            content="Some content here",
            title="Example Article",
        )
        self.assertIsInstance(src, Source)
        self.assertEqual(src.url, "https://example.com/article")
        self.assertEqual(self.tracker.source_count, 1)

    def test_citation_tracker_add_duplicate_url(self):
        """Adding the same URL twice does not increase source count."""
        self.tracker.add_source("https://example.com/article", title="First")
        self.tracker.add_source("https://example.com/article", title="Second")
        self.assertEqual(self.tracker.source_count, 1)

    def test_citation_tracker_add_sources_from_search(self):
        """add_sources_from_search parses a JSON with a citations array."""
        payload = json.dumps({
            "content": "AI adoption grew 34% in 2025.",
            "citations": [
                "https://source1.com",
                "https://source2.com",
            ],
        })
        sources = self.tracker.add_sources_from_search(payload)
        self.assertEqual(len(sources), 2)
        urls = [s.url for s in sources]
        self.assertIn("https://source1.com", urls)
        self.assertIn("https://source2.com", urls)

    def test_citation_tracker_find_relevant_sources(self):
        """find_relevant_sources returns sources whose content matches the claim."""
        self.tracker.add_source(
            "https://gartner.com/report",
            content="AI adoption grew 34% in enterprise in 2025",
            title="Gartner AI Report",
        )
        self.tracker.add_source(
            "https://cooking.com",
            content="The best pasta recipe uses fresh tomatoes",
            title="Pasta Recipe",
        )
        results = self.tracker.find_relevant_sources("AI adoption grew 34%")
        self.assertGreater(len(results), 0)
        top_url = results[0][0].url
        self.assertEqual(top_url, "https://gartner.com/report")

    def test_citation_tracker_reset(self):
        """reset clears all tracked sources."""
        self.tracker.add_source("https://example.com")
        self.assertEqual(self.tracker.source_count, 1)
        self.tracker.reset()
        self.assertEqual(self.tracker.source_count, 0)


class CitationMiddlewareTests(unittest.TestCase):

    def _make_middleware(self, enforce=False):
        from orchestra.citation import CitationTracker, CitationMiddleware
        tracker = CitationTracker()
        return tracker, CitationMiddleware(tracker, enforce_citations=enforce)

    def test_citation_middleware_extract_factual_claims(self):
        """extract_factual_claims finds sentences with percentages and numbers."""
        _, mw = self._make_middleware()
        text = (
            "The sky is blue. "
            "AI adoption grew 34% in 2025. "
            "Companies reported $2.5 billion in savings. "
            "Cats are great pets."
        )
        claims = mw.extract_factual_claims(text)
        self.assertGreater(len(claims), 0)
        # The plain opinion sentence should NOT be flagged
        factual_texts = " ".join(claims)
        self.assertIn("34%", factual_texts)

    def test_citation_middleware_ground_response_no_sources(self):
        """ground_response with no tracked sources returns uncited claims."""
        _, mw = self._make_middleware()
        response = "AI grew 34% in 2025 according to research."
        grounded = mw.ground_response(response)
        # With no sources, citation rate should be 0
        self.assertAlmostEqual(grounded.citation_rate, 0.0)
        # uncited_claims should contain the factual sentence
        self.assertGreater(len(grounded.uncited_claims), 0)

    def test_citation_middleware_ground_response_with_sources(self):
        """ground_response injects [N] markers when sources are available."""
        tracker, mw = self._make_middleware()
        tracker.add_source(
            "https://stats.example.com",
            content="AI adoption grew 34% in 2025 according to new research studies",
            title="AI Stats",
        )
        response = "AI adoption grew 34% in 2025 according to research."
        grounded = mw.ground_response(response)
        # The grounded response should contain a citation marker
        self.assertIn("[1]", grounded.grounded)

    def test_citation_middleware_build_sources_section(self):
        """build_sources_section formats '## Sources\\n[1] URL'."""
        from orchestra.citation import CitationTracker, CitationMiddleware, Source
        tracker = CitationTracker()
        mw = CitationMiddleware(tracker)
        src = Source(
            url="https://example.com/report",
            title="Example Report",
            citation_index=1,
        )
        section = mw.build_sources_section([src])
        self.assertIn("## Sources", section)
        self.assertIn("[1]", section)
        self.assertIn("https://example.com/report", section)

    def test_auto_ground_convenience(self):
        """auto_ground end-to-end: grounds a response given tool_results."""
        from orchestra.citation import auto_ground
        tool_results = [
            {
                "tool": "web_search",
                "result": json.dumps({
                    "content": "China population reached 1.4 billion in 2023",
                    "citations": ["https://worldpop.org/china"],
                }),
                "args": {"query": "China population 2023"},
            }
        ]
        response = "The population grew to 1.4 billion in 2023."
        grounded = auto_ground(response, tool_results)
        # Should have processed the response and returned a GroundedResponse
        self.assertIsNotNone(grounded)
        self.assertEqual(grounded.original, response)

    def test_parse_sonar_citations(self):
        """parse_sonar_citations parses Sonar API response format."""
        from orchestra.citation import parse_sonar_citations
        sonar_json = json.dumps({
            "content": "AI is transforming industries.",
            "citations": [
                "https://techcrunch.com/ai-report",
                "https://wired.com/ai-trends",
            ],
        })
        sources = parse_sonar_citations(sonar_json)
        self.assertEqual(len(sources), 2)
        urls = [s.url for s in sources]
        self.assertIn("https://techcrunch.com/ai-report", urls)
        self.assertIn("https://wired.com/ai-trends", urls)
        # Citation indexes should be assigned
        for i, src in enumerate(sources, start=1):
            self.assertEqual(src.citation_index, i)


# ===========================================================================
# Tasks tests (13 tests)
# ===========================================================================

class TaskEnumTests(unittest.TestCase):

    def test_task_status_enum_values(self):
        """TaskStatus has all 7 expected status values."""
        from orchestra.tasks import TaskStatus
        expected = {
            "pending", "running", "paused", "waiting_for_input",
            "completed", "failed", "cancelled", "scheduled",
        }
        actual = {s.value for s in TaskStatus}
        # Must have at least these 7 core values; module has 8 including SCHEDULED
        for val in expected:
            self.assertIn(val, actual)

    def test_task_priority_enum_values(self):
        """TaskPriority has all 4 priority levels."""
        from orchestra.tasks import TaskPriority
        expected = {"low", "normal", "high", "critical"}
        actual = {p.value for p in TaskPriority}
        self.assertEqual(expected, actual)


class ScheduleTests(unittest.TestCase):

    def test_schedule_matches_now_no_cron(self):
        """Schedule with no cron/run_once_at/interval returns False for matches_now."""
        from orchestra.tasks import Schedule
        s = Schedule()  # all defaults = disabled
        self.assertFalse(s.matches_now())

    def test_schedule_run_once_at_future(self):
        """next_run returns a future Unix timestamp when run_once_at is set."""
        from orchestra.tasks import Schedule
        future = time.time() + 3600
        s = Schedule(run_once_at=future)
        nxt = s.next_run()
        self.assertIsNotNone(nxt)
        self.assertGreater(nxt, time.time())


class CheckInDataclassTests(unittest.TestCase):

    def test_check_in_dataclass_fields(self):
        """CheckIn dataclass has the expected fields."""
        from orchestra.tasks import CheckIn
        fields = {f.name for f in dataclasses.fields(CheckIn)}
        for expected in ("task_id", "question", "context", "options",
                         "required", "timeout_seconds", "response", "responded_at", "id"):
            self.assertIn(expected, fields)


class TaskSpecTests(unittest.TestCase):

    def test_task_spec_dataclass_defaults(self):
        """TaskSpec defaults: model, architecture, priority, max_iterations."""
        from orchestra.tasks import TaskSpec, TaskPriority
        spec = TaskSpec(name="Test Task", prompt="Do something")
        self.assertEqual(spec.model, "claude-opus-4.6-openrouter")
        self.assertEqual(spec.architecture, "A")
        self.assertEqual(spec.priority, TaskPriority.NORMAL)
        self.assertEqual(spec.max_iterations, 300)
        self.assertIsNone(spec.schedule)


class TaskDataclassTests(unittest.TestCase):

    def _make_task(self, status=None):
        from orchestra.tasks import Task, TaskStatus, TaskPriority
        import uuid
        if status is None:
            status = TaskStatus.PENDING
        return Task(
            id=str(uuid.uuid4()),
            name="Test Task",
            prompt="Do something",
            model="claude-opus-4.6-openrouter",
            status=status,
            priority=TaskPriority.NORMAL,
        )

    def test_task_dataclass_is_active_running(self):
        """Task with status RUNNING has is_active = True."""
        from orchestra.tasks import TaskStatus
        task = self._make_task(status=TaskStatus.RUNNING)
        self.assertTrue(task.is_active)

    def test_task_dataclass_is_active_completed(self):
        """Task with status COMPLETED has is_active = False."""
        from orchestra.tasks import TaskStatus
        task = self._make_task(status=TaskStatus.COMPLETED)
        self.assertFalse(task.is_active)

    def test_task_duration_seconds(self):
        """duration_seconds equals completed_at - started_at."""
        from orchestra.tasks import TaskStatus
        task = self._make_task(status=TaskStatus.COMPLETED)
        task.started_at = 1_000_000.0
        task.completed_at = 1_000_120.0
        self.assertAlmostEqual(task.duration_seconds, 120.0, delta=0.01)

    def test_task_pending_checkin_none(self):
        """Task with no check-ins returns None for pending_checkin."""
        task = self._make_task()
        self.assertIsNone(task.pending_checkin)


class TaskManagerInitTests(unittest.IsolatedAsyncioTestCase):

    async def test_task_manager_init(self):
        """TaskManager constructs without error using a temp db path."""
        from orchestra.tasks import TaskManager, TaskStore
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TaskStore(db_path=f"{tmpdir}/tasks.db")
            manager = TaskManager(
                store=store,
                workspace_root=tmpdir,
            )
            self.assertIsNotNone(manager)
            self.assertIsNotNone(manager._ipc)
            self.assertIsNotNone(manager._store)


class FileSystemIPCTests(unittest.TestCase):

    def test_filesystem_ipc_create_workspace(self):
        """create_task_workspace creates the expected directory structure."""
        from orchestra.tasks import FileSystemIPC
        with tempfile.TemporaryDirectory() as tmpdir:
            ipc = FileSystemIPC(workspace_root=tmpdir)
            task_id = "test-task-123"
            task_dir = ipc.create_task_workspace(task_id)

            self.assertTrue(task_dir.exists())
            self.assertTrue((task_dir / "agents").exists())
            self.assertTrue((task_dir / "results").exists())
            self.assertTrue((task_dir / "logs").exists())

    def test_filesystem_ipc_write_read_context(self):
        """write_context followed by read_context returns the original string."""
        from orchestra.tasks import FileSystemIPC
        with tempfile.TemporaryDirectory() as tmpdir:
            ipc = FileSystemIPC(workspace_root=tmpdir)
            task_id = "round-trip-test"
            ipc.create_task_workspace(task_id)

            context = "# Goal\nBuild a Q1 revenue report and presentation."
            ipc.write_context(task_id, context)
            result = ipc.read_context(task_id)

            self.assertEqual(result, context)


if __name__ == "__main__":
    unittest.main()
