"""
openjarvis/briefing/briefing_tools.py
───────────────────────────────────────
Agent-callable tools for managing daily briefings from inside OpenJarvis's
agent loop. These are wired into the tool registry and are gated to
Enterprise-tier customers.

Tools exposed:
  - briefing_create        Create a new daily briefing
  - briefing_add_topic     Add a topic to an existing briefing
  - briefing_remove_topic  Remove a topic from a briefing
  - briefing_list          List all configured briefings for a customer
  - briefing_trigger_now   Manually trigger a briefing delivery right now
  - briefing_delete        Delete a briefing configuration entirely
  - briefing_status        Get delivery history and last-run summary
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from openjarvis.briefing.briefing_config import (
    BriefingConfig,
    BriefingTopic,
    BriefingSection,
    DeliveryConfig,
    create_default_config,
)


BRIEFING_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "briefing_create",
            "description": (
                "Create a new daily intelligence briefing for an Enterprise customer. "
                "The briefing will be emailed every day at the configured time. "
                "Enterprise plan ($499/mo) required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The customer's unique ID.",
                    },
                    "briefing_name": {
                        "type": "string",
                        "description": "Display name for this briefing, e.g. 'Iran Conflict Briefing'.",
                    },
                    "recipients": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of email addresses to deliver the briefing to.",
                    },
                    "send_hour_utc": {
                        "type": "integer",
                        "description": "Hour in UTC (0-23) to send the daily email. Default 13 = 8am CDT.",
                        "default": 13,
                    },
                    "topics": {
                        "type": "array",
                        "description": "List of topics to monitor.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Topic display name."},
                                "queries": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Search queries to run for this topic.",
                                },
                                "breaking_keywords": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Keywords that trigger a breaking-news notification.",
                                },
                            },
                            "required": ["name", "queries"],
                        },
                    },
                },
                "required": ["customer_id", "briefing_name", "recipients"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "briefing_add_topic",
            "description": "Add a new monitored topic to an existing daily briefing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "topic_name": {"type": "string", "description": "Display name for the topic."},
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Search queries to run for this topic.",
                    },
                    "breaking_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional keywords that trigger a breaking-news push notification.",
                    },
                },
                "required": ["customer_id", "topic_name", "queries"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "briefing_remove_topic",
            "description": "Remove a topic from an existing daily briefing by topic ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "topic_id": {"type": "string", "description": "The topic's unique ID (from briefing_list)."},
                },
                "required": ["customer_id", "topic_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "briefing_list",
            "description": "List all briefing configs and topics for a customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "briefing_trigger_now",
            "description": (
                "Manually trigger an immediate briefing delivery for a customer. "
                "Runs the full pipeline now: search → compose → email."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "briefing_delete",
            "description": "Permanently delete a daily briefing configuration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "briefing_status",
            "description": "Get delivery history and status for a customer's briefing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "last_n": {
                        "type": "integer",
                        "description": "Number of recent delivery logs to return. Default 5.",
                        "default": 5,
                    },
                },
                "required": ["customer_id"],
            },
        },
    },
]


class BriefingToolExecutor:
    TOOL_NAMES = {d["function"]["name"] for d in BRIEFING_TOOL_DEFINITIONS}

    def __init__(self, scheduler, customer_tier_fn=None):
        self.scheduler = scheduler
        self._get_tier = customer_tier_fn or (lambda cid: "enterprise")

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self.TOOL_NAMES

    async def execute(self, tool_name: str, arguments: dict) -> str:
        handlers = {
            "briefing_create": self._create,
            "briefing_add_topic": self._add_topic,
            "briefing_remove_topic": self._remove_topic,
            "briefing_list": self._list,
            "briefing_trigger_now": self._trigger_now,
            "briefing_delete": self._delete,
            "briefing_status": self._status,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            result = await handler(arguments)
            return json.dumps(result)
        except PermissionError as exc:
            return json.dumps({"error": str(exc), "upgrade_url": "openjarvis.com/billing"})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    async def _create(self, args: dict) -> dict:
        customer_id = args["customer_id"]
        tier = self._get_tier(customer_id)

        config = create_default_config(
            customer_id=customer_id,
            recipients=args["recipients"],
            briefing_name=args.get("briefing_name", "Daily Intelligence Briefing"),
            send_hour_utc=args.get("send_hour_utc", 13),
        )

        for t in args.get("topics", []):
            topic = BriefingTopic.create(
                name=t["name"],
                queries=t["queries"],
                breaking_keywords=t.get("breaking_keywords", []),
            )
            config.add_topic(topic)

        self.scheduler.add_config(config, tier)
        return {
            "success": True,
            "config_id": config.id,
            "customer_id": customer_id,
            "briefing_name": config.briefing_name,
            "topics": len(config.topics),
            "schedule": config.delivery.cron_expression,
            "recipients": config.delivery.recipients,
            "message": (
                f"Daily briefing '{config.briefing_name}' created. "
                f"First delivery at {args.get('send_hour_utc', 13)}:00 UTC tomorrow."
            ),
        }

    async def _add_topic(self, args: dict) -> dict:
        customer_id = args["customer_id"]
        config = self.scheduler.get_config(customer_id)
        if not config:
            return {"error": f"No briefing found for customer {customer_id}"}

        topic = BriefingTopic.create(
            name=args["topic_name"],
            queries=args["queries"],
            breaking_keywords=args.get("breaking_keywords", []),
        )
        config.add_topic(topic)
        config.save(self.scheduler.config_dir)
        return {
            "success": True,
            "topic_id": topic.id,
            "topic_name": topic.name,
            "total_topics": len(config.topics),
        }

    async def _remove_topic(self, args: dict) -> dict:
        customer_id = args["customer_id"]
        config = self.scheduler.get_config(customer_id)
        if not config:
            return {"error": f"No briefing found for customer {customer_id}"}

        removed = config.remove_topic(args["topic_id"])
        if removed:
            config.save(self.scheduler.config_dir)
            return {"success": True, "removed_topic_id": args["topic_id"]}
        return {"success": False, "error": "Topic ID not found"}

    async def _list(self, args: dict) -> dict:
        customer_id = args["customer_id"]
        config = self.scheduler.get_config(customer_id)
        if not config:
            return {"briefings": [], "message": "No briefing configured"}
        return {
            "config_id": config.id,
            "briefing_name": config.briefing_name,
            "enabled": config.enabled,
            "recipients": config.delivery.recipients,
            "schedule": config.delivery.cron_expression,
            "topics": [
                {
                    "id": t.id,
                    "name": t.name,
                    "queries": t.queries,
                    "breaking_keywords": t.breaking_keywords,
                }
                for t in config.topics
            ],
        }

    async def _trigger_now(self, args: dict) -> dict:
        customer_id = args["customer_id"]
        result = await self.scheduler.trigger_now(customer_id)
        return {
            "success": True,
            "subject": result.subject,
            "recipients": self.scheduler.get_config(customer_id).delivery.recipients,
            "has_breaking_news": result.has_breaking_news,
            "breaking_summary": result.breaking_summary,
            "generated_at": result.generated_at,
        }

    async def _delete(self, args: dict) -> dict:
        removed = self.scheduler.remove_config(args["customer_id"])
        return {"success": removed}

    async def _status(self, args: dict) -> dict:
        customer_id = args["customer_id"]
        log_dir = Path("openjarvis/data/briefing_logs") / customer_id
        if not log_dir.exists():
            return {"customer_id": customer_id, "deliveries": [], "total_deliveries": 0}

        logs = sorted(log_dir.glob("*.json"), reverse=True)
        n = args.get("last_n", 5)
        deliveries = []
        for fp in logs[:n]:
            try:
                deliveries.append(json.loads(fp.read_text()))
            except Exception:
                pass

        return {
            "customer_id": customer_id,
            "total_deliveries": len(logs),
            "deliveries": deliveries,
        }


def get_briefing_tools(scheduler, customer_tier_fn=None) -> tuple[list[dict], "BriefingToolExecutor"]:
    executor = BriefingToolExecutor(scheduler, customer_tier_fn)
    return BRIEFING_TOOL_DEFINITIONS, executor
