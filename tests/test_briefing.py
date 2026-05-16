"""
tests/test_briefing.py
───────────────────────
Full test suite for Orchestra Enterprise Daily Briefings.

Coverage:
  - BriefingConfig: creation, serialization, tier enforcement, validation
  - BriefingTopic: creation, deduplication fingerprinting
  - BriefingScheduler: add/remove/list/update, tier gating
  - BriefingToolExecutor: all 7 tool handlers
  - BriefingMonitor: breaking news detection, email composition (mocked)
  - DeliveryLog: persistence
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from orchestra.briefing_config import (
    BriefingConfig,
    BriefingTopic,
    BriefingSection,
    DeliveryConfig,
    create_default_config,
)
from orchestra.briefing_monitor import (
    BriefingMonitor,
    NewsItem,
    TopicResult,
    SonarSearchProvider,
)
from orchestra.briefing_scheduler import (
    BriefingScheduler,
    DeliveryLog,
    EmailSender,
    NotificationPusher,
)
from orchestra.briefing_tools import (
    BriefingToolExecutor,
    BRIEFING_TOOL_DEFINITIONS,
    get_briefing_tools,
)


# ──────────────────────────────────────────────
# Helper factories
# ──────────────────────────────────────────────

def make_topic(name="Test Topic", queries=None, breaking=None):
    return BriefingTopic.create(
        name=name,
        queries=queries or ["test query one", "test query two"],
        breaking_keywords=breaking or ["breaking", "urgent"],
    )

def make_config(customer_id="cust_001", recipients=None):
    return create_default_config(
        customer_id=customer_id,
        recipients=recipients or ["test@example.com"],
        briefing_name="Test Daily Briefing",
        send_hour_utc=13,
    )

def make_news_item(title="Test headline", topic="Test Topic", url="https://example.com/1"):
    return NewsItem(
        title=title, snippet=title, url=url, source="TestSource", topic_name=topic
    )


# ──────────────────────────────────────────────
# BriefingConfig tests
# ──────────────────────────────────────────────

class TestBriefingConfig(unittest.TestCase):

    def test_create_default_config(self):
        config = make_config()
        self.assertEqual(config.customer_id, "cust_001")
        self.assertEqual(config.delivery.recipients, ["test@example.com"])
        self.assertEqual(config.delivery.send_hour_utc, 13)
        self.assertEqual(config.delivery.cron_expression, "0 13 * * *")
        self.assertTrue(config.enabled)

    def test_add_topic(self):
        config = make_config()
        topic = make_topic()
        config.add_topic(topic)
        self.assertEqual(len(config.topics), 1)
        self.assertEqual(config.topics[0].name, "Test Topic")

    def test_remove_topic(self):
        config = make_config()
        topic = make_topic()
        config.add_topic(topic)
        result = config.remove_topic(topic.id)
        self.assertTrue(result)
        self.assertEqual(len(config.topics), 0)

    def test_remove_nonexistent_topic(self):
        config = make_config()
        result = config.remove_topic("nonexistent-id")
        self.assertFalse(result)

    def test_get_topic(self):
        config = make_config()
        topic = make_topic()
        config.add_topic(topic)
        found = config.get_topic(topic.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Test Topic")

    def test_get_all_queries(self):
        config = make_config()
        config.add_topic(make_topic(queries=["q1", "q2"]))
        config.add_topic(make_topic(name="Topic2", queries=["q3"]))
        queries = config.get_all_queries()
        self.assertEqual(len(queries), 3)

    def test_max_topics_enforcement(self):
        config = make_config()
        for i in range(BriefingConfig.MAX_TOPICS):
            config.add_topic(make_topic(name=f"Topic {i}"))
        with self.assertRaises(ValueError):
            config.add_topic(make_topic(name="One too many"))

    def test_tier_enforcement_blocks_non_enterprise(self):
        config = make_config()
        with self.assertRaises(PermissionError):
            config.validate_tier("pro")
        with self.assertRaises(PermissionError):
            config.validate_tier("builder")

    def test_tier_enforcement_allows_enterprise(self):
        config = make_config()
        config.validate_tier("enterprise")  # Should not raise

    def test_validate_bad_email(self):
        config = make_config(recipients=["not-an-email"])
        errors = config.validate()
        self.assertTrue(any("email" in e.lower() for e in errors))

    def test_validate_bad_cron(self):
        config = make_config()
        config.delivery.cron_expression = "bad cron"
        errors = config.validate()
        self.assertTrue(any("cron" in e.lower() for e in errors))

    def test_serialization_roundtrip(self):
        config = make_config()
        config.add_topic(make_topic())
        raw = config.to_json()
        restored = BriefingConfig.from_json(raw)
        self.assertEqual(restored.customer_id, config.customer_id)
        self.assertEqual(len(restored.topics), len(config.topics))
        self.assertEqual(restored.topics[0].name, config.topics[0].name)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config()
            config.add_topic(make_topic())
            config.save(data_dir=tmp)
            loaded = BriefingConfig.load("cust_001", data_dir=tmp)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.customer_id, "cust_001")
            self.assertEqual(len(loaded.topics), 1)

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = BriefingConfig.load("nonexistent", data_dir=tmp)
            self.assertIsNone(result)


# ──────────────────────────────────────────────
# BriefingTopic tests
# ──────────────────────────────────────────────

class TestBriefingTopic(unittest.TestCase):

    def test_topic_has_unique_id(self):
        t1 = make_topic()
        t2 = make_topic()
        self.assertNotEqual(t1.id, t2.id)

    def test_topic_queries(self):
        t = make_topic(queries=["q1", "q2", "q3"])
        self.assertEqual(len(t.queries), 3)

    def test_breaking_keywords(self):
        t = make_topic(breaking=["missile strike", "ceasefire"])
        self.assertIn("missile strike", t.breaking_keywords)


# ──────────────────────────────────────────────
# NewsItem tests
# ──────────────────────────────────────────────

class TestNewsItem(unittest.TestCase):

    def test_fingerprint_uniqueness(self):
        i1 = make_news_item(url="https://example.com/1")
        i2 = make_news_item(url="https://example.com/2")
        self.assertNotEqual(i1.fingerprint, i2.fingerprint)

    def test_fingerprint_consistency(self):
        item = make_news_item(url="https://example.com/3")
        self.assertEqual(item.fingerprint, item.fingerprint)

    def test_duplicate_detection_by_fingerprint(self):
        items = [
            make_news_item(url="https://example.com/1"),
            make_news_item(url="https://example.com/1"),  # duplicate
            make_news_item(url="https://example.com/2"),
        ]
        seen = set()
        unique = []
        for item in items:
            if item.fingerprint not in seen:
                seen.add(item.fingerprint)
                unique.append(item)
        self.assertEqual(len(unique), 2)


# ──────────────────────────────────────────────
# BriefingMonitor tests
# ──────────────────────────────────────────────

class TestBriefingMonitor(unittest.TestCase):

    def setUp(self):
        self.monitor = BriefingMonitor(
            moonshot_key="test-key",
            sonar_key="test-sonar-key",
        )

    def test_detect_breaking_match(self):
        topic = make_topic(breaking=["rescued", "ceasefire"])
        items = [make_news_item(title="Second F-15 crew member rescued alive")]
        tr = TopicResult(topic=topic, items=items)
        is_breaking, headline = self.monitor._detect_breaking(tr)
        self.assertTrue(is_breaking)
        self.assertIn("rescued", headline.lower())

    def test_detect_breaking_no_match(self):
        topic = make_topic(breaking=["nuclear", "invasion"])
        items = [make_news_item(title="Diplomatic talks continue in Geneva")]
        tr = TopicResult(topic=topic, items=items)
        is_breaking, headline = self.monitor._detect_breaking(tr)
        self.assertFalse(is_breaking)
        self.assertIsNone(headline)

    def test_detect_breaking_no_keywords(self):
        topic = BriefingTopic.create("No Keywords", ["query"], breaking_keywords=[])
        tr = TopicResult(topic=topic, items=[make_news_item(title="anything")])
        is_breaking, _ = self.monitor._detect_breaking(tr)
        self.assertFalse(is_breaking)

    def test_compose_email_returns_string(self):
        """Mock Kimi K2.5 response and verify compose returns text."""
        config = make_config()
        config.add_topic(make_topic())
        topic_results = [
            TopicResult(
                topic=config.topics[0],
                items=[make_news_item()],
            )
        ]

        mock_response = MagicMock()
        mock_response.choices[0].message.content = (
            "TEST DAILY BRIEFING -- April 8, 2026\n"
            "----\n\nTEST TOPIC\n- Test headline (TestSource: https://example.com/1)\n\n"
            "KEY TAKEAWAYS\nEverything is fine.\n----"
        )

        with patch.object(self.monitor.kimi.chat.completions, "create",
                          new_callable=AsyncMock, return_value=mock_response):
            result = asyncio.run(
                self.monitor._compose_email(config, topic_results, "April 8, 2026")
            )
        self.assertIsInstance(result, str)
        self.assertIn("TEST TOPIC", result)

    def test_fetch_topic_deduplicates(self):
        """Mock search provider to return duplicate items."""
        config = make_config()
        topic = make_topic(queries=["q1", "q2"])

        # Both queries return the same URL
        item = make_news_item(url="https://example.com/same")
        self.monitor.search.search = AsyncMock(return_value=[item, item])

        result = asyncio.run(self.monitor._fetch_topic(topic))
        # Should deduplicate to 1 item
        self.assertEqual(len(result.items), 1)


# ──────────────────────────────────────────────
# DeliveryLog tests
# ──────────────────────────────────────────────

class TestDeliveryLog(unittest.TestCase):

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = DeliveryLog(
                customer_id="cust_test",
                briefing_name="Test",
                subject="Test Subject",
                recipients=["a@b.com"],
                delivered_at="2026-04-08T13:00:00Z",
                has_breaking=False,
                breaking_summary=None,
                success=True,
            )
            fp = dl.save(log_dir=tmp)
            self.assertTrue(fp.exists())
            data = json.loads(fp.read_text())
            self.assertEqual(data["customer_id"], "cust_test")
            self.assertTrue(data["success"])


# ──────────────────────────────────────────────
# EmailSender tests
# ──────────────────────────────────────────────

class TestEmailSender(unittest.TestCase):

    def test_send_no_transport_returns_error(self):
        sender = EmailSender()  # No connector, no SMTP
        success, error = asyncio.run(
            sender.send(["a@b.com"], "Subject", "Body")
        )
        self.assertFalse(success)
        self.assertIsNotNone(error)

    def test_send_via_connector_success(self):
        mock_connector = MagicMock()
        mock_connector.send_email = AsyncMock(return_value=None)
        sender = EmailSender(gmail_connector=mock_connector)
        success, error = asyncio.run(
            sender.send(["a@b.com"], "Subject", "Body")
        )
        self.assertTrue(success)
        self.assertIsNone(error)

    def test_send_via_connector_failure_returns_error(self):
        mock_connector = MagicMock()
        mock_connector.send_email = AsyncMock(side_effect=Exception("SMTP error"))
        sender = EmailSender(gmail_connector=mock_connector)
        success, error = asyncio.run(
            sender.send(["a@b.com"], "Subject", "Body")
        )
        self.assertFalse(success)
        self.assertIsNotNone(error)


# ──────────────────────────────────────────────
# BriefingScheduler tests
# ──────────────────────────────────────────────

class TestBriefingScheduler(unittest.TestCase):

    def _make_scheduler(self, tmp_dir):
        return BriefingScheduler(
            moonshot_key="test",
            sonar_key="test",
            config_dir=tmp_dir,
        )

    def test_add_config_enterprise(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(tmp)
            config = make_config()
            scheduler.add_config(config, "enterprise")
            self.assertIn("cust_001", scheduler._configs)

    def test_add_config_non_enterprise_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(tmp)
            config = make_config()
            with self.assertRaises(PermissionError):
                scheduler.add_config(config, "pro")

    def test_remove_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(tmp)
            config = make_config()
            scheduler.add_config(config, "enterprise")
            result = scheduler.remove_config("cust_001")
            self.assertTrue(result)
            self.assertNotIn("cust_001", scheduler._configs)

    def test_remove_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(tmp)
            result = scheduler.remove_config("nonexistent")
            self.assertFalse(result)

    def test_list_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(tmp)
            scheduler.add_config(make_config("c1"), "enterprise")
            scheduler.add_config(make_config("c2"), "enterprise")
            listing = scheduler.list_configs()
            self.assertEqual(len(listing), 2)

    def test_load_all_configs_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Save a config manually
            config = make_config()
            config.add_topic(make_topic())
            config.save(data_dir=tmp)

            # New scheduler should load it
            scheduler = self._make_scheduler(tmp)
            scheduler._load_all_configs()
            self.assertIn("cust_001", scheduler._configs)

    def test_trigger_now_no_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(tmp)
            with self.assertRaises(KeyError):
                asyncio.run(scheduler.trigger_now("nonexistent"))


# ──────────────────────────────────────────────
# BriefingToolExecutor tests
# ──────────────────────────────────────────────

class TestBriefingToolExecutor(unittest.TestCase):

    def _make_executor(self, tmp_dir):
        scheduler = BriefingScheduler(
            moonshot_key="test",
            sonar_key="test",
            config_dir=tmp_dir,
        )
        return BriefingToolExecutor(scheduler, customer_tier_fn=lambda cid: "enterprise")

    def test_tool_definitions_valid(self):
        self.assertGreater(len(BRIEFING_TOOL_DEFINITIONS), 0)
        for tool in BRIEFING_TOOL_DEFINITIONS:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])

    def test_can_handle_all_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = self._make_executor(tmp)
            for tool in BRIEFING_TOOL_DEFINITIONS:
                self.assertTrue(executor.can_handle(tool["function"]["name"]))

    def test_can_handle_unknown_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = self._make_executor(tmp)
            self.assertFalse(executor.can_handle("unknown_tool"))

    def test_create_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = self._make_executor(tmp)
            result = asyncio.run(executor.execute("briefing_create", {
                "customer_id": "cust_001",
                "briefing_name": "Test Briefing",
                "recipients": ["test@example.com"],
                "topics": [{"name": "Topic 1", "queries": ["query 1"]}],
            }))
            data = json.loads(result)
            self.assertTrue(data["success"])
            self.assertEqual(data["topics"], 1)

    def test_list_tool_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = self._make_executor(tmp)
            result = asyncio.run(executor.execute("briefing_list", {
                "customer_id": "nonexistent"
            }))
            data = json.loads(result)
            self.assertIn("message", data)

    def test_add_and_remove_topic_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = self._make_executor(tmp)
            # Create
            asyncio.run(executor.execute("briefing_create", {
                "customer_id": "cust_001",
                "briefing_name": "Test",
                "recipients": ["a@b.com"],
            }))
            # Add topic
            result = asyncio.run(executor.execute("briefing_add_topic", {
                "customer_id": "cust_001",
                "topic_name": "New Topic",
                "queries": ["new query"],
            }))
            data = json.loads(result)
            self.assertTrue(data["success"])
            topic_id = data["topic_id"]

            # Remove topic
            result = asyncio.run(executor.execute("briefing_remove_topic", {
                "customer_id": "cust_001",
                "topic_id": topic_id,
            }))
            data = json.loads(result)
            self.assertTrue(data["success"])

    def test_delete_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = self._make_executor(tmp)
            asyncio.run(executor.execute("briefing_create", {
                "customer_id": "cust_001",
                "briefing_name": "Test",
                "recipients": ["a@b.com"],
            }))
            result = asyncio.run(executor.execute("briefing_delete", {
                "customer_id": "cust_001"
            }))
            data = json.loads(result)
            self.assertTrue(data["success"])

    def test_status_tool_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = self._make_executor(tmp)
            result = asyncio.run(executor.execute("briefing_status", {
                "customer_id": "cust_001"
            }))
            data = json.loads(result)
            self.assertEqual(data["total_deliveries"], 0)

    def test_get_briefing_tools_factory(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = BriefingScheduler("test", "test", config_dir=tmp)
            tools, executor = get_briefing_tools(scheduler)
            self.assertIsInstance(tools, list)
            self.assertIsInstance(executor, BriefingToolExecutor)

    def test_tier_gating_via_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Executor that returns "pro" tier
            scheduler = BriefingScheduler("test", "test", config_dir=tmp)
            executor = BriefingToolExecutor(
                scheduler, customer_tier_fn=lambda cid: "pro"
            )
            result = asyncio.run(executor.execute("briefing_create", {
                "customer_id": "cust_001",
                "briefing_name": "Test",
                "recipients": ["a@b.com"],
            }))
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("upgrade_url", data)

    def test_unknown_tool_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = self._make_executor(tmp)
            result = asyncio.run(executor.execute("completely_unknown", {}))
            data = json.loads(result)
            self.assertIn("error", data)


# ──────────────────────────────────────────────
# Integration: full config → tool pipeline
# ──────────────────────────────────────────────

class TestIntegration(unittest.TestCase):

    def test_full_create_list_delete_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = BriefingScheduler("test", "test", config_dir=tmp)
            executor = BriefingToolExecutor(
                scheduler, customer_tier_fn=lambda cid: "enterprise"
            )

            # Create with 2 topics
            asyncio.run(executor.execute("briefing_create", {
                "customer_id": "cust_int",
                "briefing_name": "Integration Briefing",
                "recipients": ["user@test.com"],
                "topics": [
                    {"name": "Topic A", "queries": ["query a1", "query a2"]},
                    {"name": "Topic B", "queries": ["query b1"], "breaking_keywords": ["urgent"]},
                ],
            }))

            # List
            result = json.loads(asyncio.run(executor.execute("briefing_list", {
                "customer_id": "cust_int"
            })))
            self.assertEqual(result["briefing_name"], "Integration Briefing")
            self.assertEqual(len(result["topics"]), 2)

            # Add another topic
            asyncio.run(executor.execute("briefing_add_topic", {
                "customer_id": "cust_int",
                "topic_name": "Topic C",
                "queries": ["query c1"],
            }))
            result = json.loads(asyncio.run(executor.execute("briefing_list", {
                "customer_id": "cust_int"
            })))
            self.assertEqual(len(result["topics"]), 3)

            # Persistence check — reload from disk
            scheduler2 = BriefingScheduler("test", "test", config_dir=tmp)
            scheduler2._load_all_configs()
            self.assertIn("cust_int", scheduler2._configs)
            self.assertEqual(len(scheduler2._configs["cust_int"].topics), 3)

            # Delete
            result = json.loads(asyncio.run(executor.execute("briefing_delete", {
                "customer_id": "cust_int"
            })))
            self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
