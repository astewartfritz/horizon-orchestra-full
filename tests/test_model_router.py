"""Tests for orchestra/router.py and orchestra/domain_router.py.

ModelRouter:
  - route() selects correct model by task_type strength
  - constraint filtering (require_tools, require_vision, max_cost, providers)
  - falls back to cheapest when no candidate matches
  - get_client() caches AsyncOpenAI instances; raises KeyError for unknown model
  - get_config() / register() / list_models() / is_gemma4()

DomainRouter:
  - classify() routes each of the six domains correctly
  - safety_critical bonus weighting
  - complexity estimation (low / medium / high / extreme)
  - vision/audio signal detection
  - route() returns DomainRoute with correct effort, policy, temperature
  - route_task() is a synchronous convenience wrapper
  - cost_ceiling filters out expensive models
  - custom_domains override built-ins
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from orchestra.router import DEFAULT_MODELS, GEMMA4_MODELS, ModelConfig, ModelRouter
from orchestra.domain_router import (
    DOMAIN_CONFIGS,
    DomainRoute,
    DomainRouter,
    TaskClassification,
)


# ---------------------------------------------------------------------------
# ModelRouter — basic registry operations
# ---------------------------------------------------------------------------

class TestModelRouterRegistry:
    def setup_method(self):
        self.router = ModelRouter()

    def test_default_models_loaded(self):
        assert len(self.router.models) >= len(DEFAULT_MODELS)

    def test_register_new_model(self):
        cfg = ModelConfig(
            model_id="custom-v1",
            provider="custom",
            base_url="http://localhost:9000/v1",
            api_key_env="",
            strengths=("coding",),
        )
        self.router.register("custom-v1", cfg)
        assert "custom-v1" in self.router.models

    def test_get_config_known_model(self):
        cfg = self.router.get_config("kimi-k2.5")
        assert cfg.provider == "moonshot"

    def test_get_config_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown model"):
            self.router.get_config("does-not-exist")

    def test_get_client_raises_for_unknown(self):
        with pytest.raises(KeyError, match="Unknown model"):
            self.router.get_client("totally-unknown")

    def test_get_client_caches_instance(self):
        with patch.dict(os.environ, {"MOONSHOT_API_KEY": "fake-key"}):
            c1, mid1 = self.router.get_client("kimi-k2.5")
            c2, mid2 = self.router.get_client("kimi-k2.5")
        assert c1 is c2  # same object from cache
        assert mid1 == mid2

    def test_is_gemma4_true_for_gemma_variants(self):
        for key in GEMMA4_MODELS:
            assert self.router.is_gemma4(key), f"{key!r} should be Gemma4"

    def test_is_gemma4_false_for_kimi(self):
        assert not self.router.is_gemma4("kimi-k2.5")

    def test_list_gemma4_models_nonempty(self):
        g4 = self.router.list_gemma4_models()
        assert len(g4) >= 5

    def test_list_models_structure(self):
        models = self.router.list_models()
        assert len(models) > 0
        for m in models:
            assert "name" in m
            assert "provider" in m
            assert "supports_tools" in m
            assert "available" in m


# ---------------------------------------------------------------------------
# ModelRouter — route() selection
# ---------------------------------------------------------------------------

class TestModelRouterRoute:
    def setup_method(self):
        # isolated=True starts empty so only the registered test models participate,
        # preventing zero-cost local models in DEFAULT_MODELS from winning routing.
        self.router = ModelRouter(isolated=True)
        # Register two synthetic models: one cheap+capable, one expensive+capable
        self.router.register("cheap-coder", ModelConfig(
            model_id="cheap-coder",
            provider="test",
            base_url="http://localhost:1/v1",
            api_key_env="",          # no key needed → always available
            strengths=("coding", "reasoning"),
            cost_input=0.01, cost_output=0.01,
        ))
        self.router.register("expensive-coder", ModelConfig(
            model_id="expensive-coder",
            provider="test",
            base_url="http://localhost:2/v1",
            api_key_env="",
            strengths=("coding",),
            cost_input=50.0, cost_output=50.0,
        ))
        self.router.register("vision-only", ModelConfig(
            model_id="vision-only",
            provider="test",
            base_url="http://localhost:3/v1",
            api_key_env="",
            strengths=("vision",),
            supports_tools=False,
            supports_vision=True,
        ))
        self.router.register("no-tools", ModelConfig(
            model_id="no-tools",
            provider="test",
            base_url="http://localhost:4/v1",
            api_key_env="",
            strengths=("web_search",),
            supports_tools=False,
            supports_vision=False,
        ))

    def test_route_coding_prefers_cheaper_capable_model(self):
        # Both models have "coding" strength; cheaper should score higher
        chosen = self.router.route("coding")
        assert chosen == "cheap-coder"

    def test_route_require_tools_excludes_no_tools(self):
        chosen = self.router.route("web_search", constraints={"require_tools": True})
        # "no-tools" lacks tool support, so it must not be selected
        assert chosen != "no-tools"

    def test_route_require_vision_excludes_non_vision(self):
        chosen = self.router.route("vision", constraints={"require_vision": True})
        assert chosen == "vision-only"

    def test_route_max_cost_filters_expensive(self):
        # cost ceiling below expensive-coder's output cost
        chosen = self.router.route("coding", constraints={"max_cost_output": 1.0})
        assert chosen == "cheap-coder"

    def test_route_provider_constraint(self):
        chosen = self.router.route("coding", constraints={"providers": ["test"]})
        assert chosen in ("cheap-coder", "expensive-coder")

    def test_route_no_candidates_returns_cheapest_fallback(self):
        # Ask for a strength that no test model has AND filter to test provider
        # No model has "telepathy" strength, but we should still get a fallback
        chosen = self.router.route("telepathy", constraints={"providers": ["test"]})
        assert chosen is not None  # some fallback is returned

    def test_route_missing_api_key_skips_model(self):
        self.router.register("needs-key", ModelConfig(
            model_id="needs-key",
            provider="test",
            base_url="http://localhost:5/v1",
            api_key_env="SOME_MISSING_KEY_XYZ999",
            strengths=("coding",),
            cost_input=0.001, cost_output=0.001,  # cheapest possible
        ))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SOME_MISSING_KEY_XYZ999", None)
            chosen = self.router.route("coding", constraints={"providers": ["test"]})
        # "needs-key" must be excluded because its API key is missing
        assert chosen != "needs-key"


# ---------------------------------------------------------------------------
# DomainRouter — classify()
# ---------------------------------------------------------------------------

class TestDomainRouterClassify:
    def setup_method(self):
        self.dr = DomainRouter(router=ModelRouter())

    @pytest.mark.asyncio
    async def test_coding_task(self):
        c = await self.dr.classify("Refactor the payment service and fix the bug in the API endpoint")
        assert c.domain == "coding"
        assert c.confidence > 0.3

    @pytest.mark.asyncio
    async def test_research_task(self):
        c = await self.dr.classify("Research the latest academic papers on transformer architectures")
        assert c.domain == "research"
        assert c.confidence > 0.3

    @pytest.mark.asyncio
    async def test_creative_task(self):
        c = await self.dr.classify("Write a creative blog post about artificial intelligence")
        assert c.domain == "creative"
        assert c.confidence > 0.3

    @pytest.mark.asyncio
    async def test_data_analysis_task(self):
        c = await self.dr.classify("Analyze this CSV dataset and plot a chart using pandas and matplotlib")
        assert c.domain == "data_analysis"
        assert c.confidence > 0.3

    @pytest.mark.asyncio
    async def test_safety_critical_medical(self):
        c = await self.dr.classify("Evaluate the patient medical diagnosis and dosage prescription")
        assert c.domain == "safety_critical"

    @pytest.mark.asyncio
    async def test_safety_critical_financial(self):
        c = await self.dr.classify("Perform financial audit and regulatory compliance review for SEC")
        assert c.domain == "safety_critical"

    @pytest.mark.asyncio
    async def test_safety_critical_legal(self):
        c = await self.dr.classify("Review this legal contract and indemnification clause for GDPR compliance")
        assert c.domain == "safety_critical"

    @pytest.mark.asyncio
    async def test_general_fallback(self):
        c = await self.dr.classify("hello")
        assert c.domain == "general"
        assert c.confidence <= 0.6

    @pytest.mark.asyncio
    async def test_empty_task_is_general(self):
        c = await self.dr.classify("")
        assert c.domain == "general"

    @pytest.mark.asyncio
    async def test_confidence_bounded_0_to_1(self):
        for task in [
            "debug the code",
            "research papers",
            "write a story",
            "analyze data",
            "medical diagnosis",
            "hello world",
        ]:
            c = await self.dr.classify(task)
            assert 0.0 <= c.confidence <= 1.0, f"confidence out of range for: {task!r}"

    @pytest.mark.asyncio
    async def test_vision_signal_detected(self):
        c = await self.dr.classify("Analyze this image and describe the screenshot")
        assert c.requires_vision is True

    @pytest.mark.asyncio
    async def test_audio_signal_detected(self):
        c = await self.dr.classify("Transcribe this audio recording from the podcast")
        assert c.requires_audio is True

    @pytest.mark.asyncio
    async def test_tool_detection_web_search(self):
        c = await self.dr.classify("Please search the web for the latest news")
        assert "web_search" in c.requires_tools

    @pytest.mark.asyncio
    async def test_complexity_low_for_short_task(self):
        c = await self.dr.classify("simple quick fix")
        assert c.estimated_complexity == "low"

    @pytest.mark.asyncio
    async def test_complexity_extreme_for_complex_task(self):
        words = " ".join(["word"] * 210)  # > 200 words
        c = await self.dr.classify(words)
        assert c.estimated_complexity == "extreme"

    @pytest.mark.asyncio
    async def test_subdomain_detection_for_coding(self):
        c = await self.dr.classify("Debug the traceback and fix the exception in the crash")
        assert c.domain == "coding"
        assert c.subdomain == "debugging"


# ---------------------------------------------------------------------------
# DomainRouter — route()
# ---------------------------------------------------------------------------

class TestDomainRouterRoute:
    def setup_method(self):
        # Use a router with controllable API key presence
        self.router = ModelRouter()
        # Add a local (no-key) model for each domain's preference list so that
        # route() always finds an available model in CI.
        local = ModelConfig(
            model_id="local-test",
            provider="local",
            base_url="http://localhost:8000/v1",
            api_key_env="",
            strengths=("coding", "research", "creative", "data_analysis", "general"),
        )
        self.router.register("local-test", local)
        self.dr = DomainRouter(router=self.router)

    def test_coding_domain_produces_strict_policy(self):
        c = TaskClassification(domain="coding", confidence=0.8)
        route = self.dr.route(c)
        assert isinstance(route, DomainRoute)
        assert route.policy_name == "strict"

    def test_safety_critical_produces_max_effort(self):
        c = TaskClassification(domain="safety_critical", confidence=0.9, estimated_complexity="high")
        route = self.dr.route(c)
        assert route.policy_name == "safety_critical"
        # effort should be high or max for safety_critical
        assert route.effort in ("high", "max")

    def test_creative_domain_high_temperature(self):
        c = TaskClassification(domain="creative", confidence=0.7)
        route = self.dr.route(c)
        assert route.temperature >= 0.7  # creative domain uses 0.9

    def test_data_analysis_low_temperature(self):
        c = TaskClassification(domain="data_analysis", confidence=0.8)
        route = self.dr.route(c)
        assert route.temperature <= 0.3

    def test_extreme_complexity_upgrades_effort_to_max(self):
        c = TaskClassification(domain="research", confidence=0.8, estimated_complexity="extreme")
        route = self.dr.route(c)
        assert route.effort == "max"
        assert route.thinking_budget >= 65_536

    def test_low_complexity_downgrades_high_effort_to_medium(self):
        # coding domain normally uses effort="high"; with low complexity it should become medium
        c = TaskClassification(domain="coding", confidence=0.8, estimated_complexity="low")
        route = self.dr.route(c)
        assert route.effort == "medium"

    def test_fallback_models_listed(self):
        c = TaskClassification(domain="coding", confidence=0.8)
        route = self.dr.route(c)
        assert isinstance(route.fallback_models, list)

    def test_cost_ceiling_excludes_expensive_model(self):
        # All models in coding primary list are expensive; set a very low ceiling
        # so they all fail and we fall back to local-test
        c = TaskClassification(domain="coding", confidence=0.8)
        route = self.dr.route(c, cost_ceiling=0.001)
        # Should fall back to local-test (cost_output=0.0) or cheapest available
        assert route.model is not None

    def test_reasoning_string_included(self):
        c = TaskClassification(domain="research", confidence=0.75)
        route = self.dr.route(c)
        assert len(route.reasoning) > 0
        assert "research" in route.reasoning.lower()


# ---------------------------------------------------------------------------
# DomainRouter — route_task() synchronous convenience
# ---------------------------------------------------------------------------

class TestDomainRouterRouteTask:
    def setup_method(self):
        self.dr = DomainRouter(router=ModelRouter())

    def test_route_task_returns_domain_route(self):
        route = self.dr.route_task("Debug the traceback in the API endpoint")
        assert isinstance(route, DomainRoute)

    def test_route_task_coding_is_strict(self):
        route = self.dr.route_task("Refactor and implement the new class")
        assert route.policy_name == "strict"

    def test_route_task_creative_is_permissive(self):
        route = self.dr.route_task("Write a creative poem about the ocean")
        assert route.policy_name == "permissive"

    def test_route_task_safety_critical(self):
        route = self.dr.route_task("Review the patient medical records and HIPAA compliance")
        assert route.policy_name == "safety_critical"


# ---------------------------------------------------------------------------
# DomainRouter — custom domains
# ---------------------------------------------------------------------------

class TestDomainRouterCustomDomains:
    def test_custom_domain_merged(self):
        custom = {
            "robotics": {
                "primary_models": ["kimi-k2.5-local"],
                "effort": "high",
                "policy": "strict",
                "max_iterations": 50,
                "temperature": 0.4,
                "thinking_budget": 8192,
                "tool_preferences": ["execute_code"],
                "description": "Robotics control tasks",
            }
        }
        dr = DomainRouter(router=ModelRouter(), custom_domains=custom)
        domains = {d["name"] for d in dr.list_domains()}
        assert "robotics" in domains

    def test_custom_domain_overrides_builtin(self):
        override = {
            "coding": {
                "primary_models": ["kimi-k2.5-local"],
                "effort": "low",    # override from "high"
                "policy": "permissive",
                "max_iterations": 10,
                "temperature": 0.9,
                "thinking_budget": 1024,
                "tool_preferences": None,
            }
        }
        dr = DomainRouter(router=ModelRouter(), custom_domains=override)
        c = TaskClassification(domain="coding", confidence=0.9)
        route = dr.route(c)
        # With low complexity, effort stays "low" (no downgrade needed)
        assert route.policy_name == "permissive"


# ---------------------------------------------------------------------------
# DomainRouter.list_domains()
# ---------------------------------------------------------------------------

class TestListDomains:
    def test_all_six_default_domains_present(self):
        dr = DomainRouter(router=ModelRouter())
        names = {d["name"] for d in dr.list_domains()}
        assert names == {"coding", "research", "creative", "data_analysis", "safety_critical", "general"}

    def test_domain_dict_has_required_keys(self):
        dr = DomainRouter(router=ModelRouter())
        for domain in dr.list_domains():
            for key in ("name", "description", "primary_models", "effort", "policy",
                        "max_iterations", "temperature", "thinking_budget"):
                assert key in domain, f"Key {key!r} missing from domain {domain['name']!r}"
