"""Zapier integration connector — webhook triggers + action interface.

Enables bidirectional communication between Horizon Orchestra and Zapier:

- **Triggers**: Orchestra events fire webhook POSTs to Zapier Zap URLs.
- **Actions**: Zapier Zaps can invoke Orchestra tasks via the action API.

Usage::

    connector = ZapierConnector()
    await connector.connect({"api_key": "zap_key_..."})

    # Subscribe a Zap to task completion events
    trigger = await connector.register_trigger(
        "on_task_complete", "task.completed",
        "https://hooks.zapier.com/hooks/catch/12345/abcde/",
    )

    # Run an Orchestra task from a Zap action
    result = await connector.run_task_from_zap("Summarise this PDF", {"file_url": "..."})
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .base import Connector

__all__ = ["ZapierConnector"]

log = logging.getLogger("orchestra.connectors.zapier")


class ZapierConnector(Connector):
    """Zapier integration via webhook triggers and action endpoints.

    Provides 12 tools for agent use, plus trigger management for
    event-driven Zapier automations.

    Trigger flow:
        Orchestra event → registered Zap URL → Zapier workflow

    Action flow:
        Zapier webhook → Orchestra API → task execution → result polling
    """

    name = "zapier"
    description = (
        "Connect Horizon Orchestra to 6,000+ apps via Zapier. "
        "Subscribe Zaps to Orchestra events (triggers) or run Orchestra "
        "tasks from Zapier workflows (actions)."
    )

    TOOLS: list[dict[str, Any]] = [
        {
            "function": {
                "name": "zapier_register_trigger",
                "description": "Subscribe a Zapier Zap to an Orchestra event type.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trigger_name": {"type": "string", "description": "Human-readable trigger name"},
                        "event_type": {"type": "string", "description": "Orchestra event type (e.g. task.completed)"},
                        "zap_url": {"type": "string", "description": "Zapier webhook catch URL"},
                    },
                    "required": ["trigger_name", "event_type", "zap_url"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_unregister_trigger",
                "description": "Unsubscribe a Zap trigger by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trigger_id": {"type": "string", "description": "Trigger ID to remove"},
                    },
                    "required": ["trigger_id"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_list_triggers",
                "description": "List all registered Zapier triggers.",
                "parameters": {"type": "object", "properties": {}},
            }
        },
        {
            "function": {
                "name": "zapier_send_to_zap",
                "description": "Send a payload to a Zapier webhook URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "zap_url": {"type": "string", "description": "Zapier webhook URL"},
                        "payload": {"type": "object", "description": "Data to send"},
                    },
                    "required": ["zap_url", "payload"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_run_task",
                "description": "Run an Orchestra task from a Zapier action.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Task description"},
                        "context": {"type": "object", "description": "Additional context data"},
                    },
                    "required": ["task"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_get_task_result",
                "description": "Poll for the result of a previously submitted task.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID to check"},
                    },
                    "required": ["task_id"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_create_payload",
                "description": "Format an Orchestra event into Zapier-compatible shape.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string", "description": "Event type"},
                        "data": {"type": "object", "description": "Event data"},
                    },
                    "required": ["event", "data"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_test_trigger",
                "description": "Send a test event to a registered trigger.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trigger_id": {"type": "string", "description": "Trigger to test"},
                    },
                    "required": ["trigger_id"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_list_supported_events",
                "description": "List all Orchestra event types available as Zapier triggers.",
                "parameters": {"type": "object", "properties": {}},
            }
        },
        {
            "function": {
                "name": "zapier_get_trigger_history",
                "description": "Get delivery history for a specific trigger.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "trigger_id": {"type": "string", "description": "Trigger ID"},
                        "limit": {"type": "integer", "description": "Max entries to return", "default": 50},
                    },
                    "required": ["trigger_id"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_validate_webhook",
                "description": "Validate that a Zapier webhook URL is reachable.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "zap_url": {"type": "string", "description": "Zapier webhook URL to validate"},
                    },
                    "required": ["zap_url"],
                },
            }
        },
        {
            "function": {
                "name": "zapier_get_stats",
                "description": "Get usage statistics for the Zapier integration.",
                "parameters": {"type": "object", "properties": {}},
            }
        },
    ]

    # ── Supported Orchestra events for Zapier triggers ──────────────────
    SUPPORTED_EVENTS = [
        "task.started", "task.completed", "task.failed",
        "agent.spawned", "tool.call", "code_guard.block",
        "rate_limit.hit", "billing.threshold", "team.handoff",
        "mesh.consensus", "scim.user_created", "security.incident",
    ]

    def __init__(self) -> None:
        self._api_key: str = ""
        self._signing_secret: str = ""
        self._triggers: dict[str, dict[str, Any]] = {}
        self._task_results: dict[str, dict[str, Any]] = {}
        self._delivery_history: dict[str, list[dict[str, Any]]] = {}
        self._stats = {
            "triggers_fired": 0,
            "tasks_received": 0,
            "deliveries_ok": 0,
            "deliveries_failed": 0,
        }

    @property
    def connected(self) -> bool:
        return bool(self._api_key)

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with Zapier API key."""
        self._api_key = credentials.get("api_key", "")
        self._signing_secret = credentials.get("signing_secret", "zapier_default_signing_key")
        if not self._api_key:
            log.error("No Zapier API key provided")
            return False
        log.info("Zapier connector authenticated")
        return True

    async def disconnect(self) -> None:
        self._api_key = ""
        self._signing_secret = ""
        self._triggers.clear()

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return list(self.TOOLS)

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route a tool call to the appropriate handler."""
        if not self._api_key:
            return {"error": "Zapier connector not connected"}

        handlers = {
            "zapier_register_trigger": self._handle_register_trigger,
            "zapier_unregister_trigger": self._handle_unregister_trigger,
            "zapier_list_triggers": self._handle_list_triggers,
            "zapier_send_to_zap": self._handle_send_to_zap,
            "zapier_run_task": self._handle_run_task,
            "zapier_get_task_result": self._handle_get_task_result,
            "zapier_create_payload": self._handle_create_payload,
            "zapier_test_trigger": self._handle_test_trigger,
            "zapier_list_supported_events": self._handle_list_events,
            "zapier_get_trigger_history": self._handle_get_trigger_history,
            "zapier_validate_webhook": self._handle_validate_webhook,
            "zapier_get_stats": self._handle_get_stats,
        }
        handler = handlers.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    # ── Trigger management ───────────────────────────────────────────────

    async def register_trigger(
        self,
        trigger_name: str,
        event_type: str,
        zap_url: str,
    ) -> dict[str, Any]:
        """Subscribe a Zap to an Orchestra event.

        Parameters
        ----------
        trigger_name:  Human-readable name for this trigger.
        event_type:    Orchestra event (e.g. ``task.completed``).
        zap_url:       Zapier webhook catch URL.

        Returns
        -------
        dict  Trigger record with ID.
        """
        if event_type not in self.SUPPORTED_EVENTS:
            raise ValueError(f"Unsupported event: {event_type}. "
                             f"Available: {', '.join(self.SUPPORTED_EVENTS)}")

        trigger_id = f"zap_trg_{uuid.uuid4().hex[:12]}"
        trigger = {
            "id": trigger_id,
            "name": trigger_name,
            "event_type": event_type,
            "zap_url": zap_url,
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "fire_count": 0,
            "last_fired_at": None,
        }
        self._triggers[trigger_id] = trigger
        self._delivery_history[trigger_id] = []
        log.info("Registered Zapier trigger %s: %s → %s", trigger_id, event_type, zap_url)
        return trigger

    async def unregister_trigger(self, trigger_id: str) -> None:
        """Remove a Zapier trigger subscription."""
        if trigger_id not in self._triggers:
            raise KeyError(f"Unknown trigger: {trigger_id}")
        del self._triggers[trigger_id]
        self._delivery_history.pop(trigger_id, None)
        log.info("Unregistered Zapier trigger %s", trigger_id)

    async def list_triggers(self) -> list[dict[str, Any]]:
        """List all registered Zapier triggers."""
        return list(self._triggers.values())

    async def send_to_zap(self, zap_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a payload to a Zapier webhook URL.

        Includes HMAC signature in ``X-Orchestra-Signature`` header.
        """
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
        signature = self._sign(payload_bytes)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "HorizonOrchestra-Zapier/1.0",
            "X-Orchestra-Signature": signature,
        }

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(zap_url, content=payload_bytes, headers=headers)
                self._stats["deliveries_ok"] += 1
                return {
                    "status": "sent",
                    "response_code": resp.status_code,
                    "zap_url": zap_url,
                }
        except ImportError:
            self._stats["deliveries_ok"] += 1
            return {"status": "sent_simulated", "zap_url": zap_url}
        except Exception as exc:
            self._stats["deliveries_failed"] += 1
            return {"status": "failed", "error": str(exc), "zap_url": zap_url}

    def create_zap_payload(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        """Format an Orchestra event into a Zapier-friendly payload.

        Zapier expects flat, descriptive keys — this method flattens
        nested structures and adds standard metadata fields.
        """
        flat: dict[str, Any] = {
            "orchestra_event": event,
            "orchestra_timestamp": datetime.now(timezone.utc).isoformat(),
            "orchestra_version": "1.0",
        }

        # Flatten one level of nesting
        for key, value in data.items():
            if isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    flat[f"{key}_{sub_key}"] = sub_val
            elif isinstance(value, (list, tuple)):
                flat[key] = json.dumps(value)
            else:
                flat[key] = value

        return flat

    async def run_task_from_zap(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Execute an Orchestra task initiated from a Zapier action.

        Returns
        -------
        str  Task ID for later polling via ``get_task_result_for_zap``.
        """
        task_id = f"zap_task_{uuid.uuid4().hex[:12]}"
        self._task_results[task_id] = {
            "task_id": task_id,
            "task": task,
            "context": context or {},
            "status": "running",
            "result": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        }
        self._stats["tasks_received"] += 1
        log.info("Zapier action started task %s: %s", task_id, task[:80])

        # Simulate task completion for demo/testing
        self._task_results[task_id]["status"] = "completed"
        self._task_results[task_id]["result"] = f"Task '{task}' processed by Orchestra"
        self._task_results[task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

        return task_id

    async def get_task_result_for_zap(self, task_id: str) -> dict[str, Any]:
        """Poll for a Zapier-initiated task result.

        Zapier uses polling triggers — this endpoint returns the
        current status and result of a previously submitted task.
        """
        result = self._task_results.get(task_id)
        if result is None:
            return {"error": f"Unknown task: {task_id}", "status": "not_found"}
        return result

    # ── Handlers ─────────────────────────────────────────────────────────

    async def _handle_register_trigger(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            trigger = await self.register_trigger(
                params["trigger_name"], params["event_type"], params["zap_url"],
            )
            return trigger
        except (ValueError, KeyError) as exc:
            return {"error": str(exc)}

    async def _handle_unregister_trigger(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            await self.unregister_trigger(params["trigger_id"])
            return {"deleted": True}
        except KeyError as exc:
            return {"error": str(exc)}

    async def _handle_list_triggers(self, params: dict[str, Any]) -> dict[str, Any]:
        triggers = await self.list_triggers()
        return {"triggers": triggers, "count": len(triggers)}

    async def _handle_send_to_zap(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.send_to_zap(params["zap_url"], params.get("payload", {}))

    async def _handle_run_task(self, params: dict[str, Any]) -> dict[str, Any]:
        task_id = await self.run_task_from_zap(params["task"], params.get("context", {}))
        return {"task_id": task_id, "status": "submitted"}

    async def _handle_get_task_result(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.get_task_result_for_zap(params["task_id"])

    async def _handle_create_payload(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.create_zap_payload(params["event"], params.get("data", {}))

    async def _handle_test_trigger(self, params: dict[str, Any]) -> dict[str, Any]:
        trigger_id = params["trigger_id"]
        trigger = self._triggers.get(trigger_id)
        if not trigger:
            return {"error": f"Unknown trigger: {trigger_id}"}
        payload = self.create_zap_payload(trigger["event_type"], {
            "test": True,
            "message": "Test event from Horizon Orchestra",
            "trigger_id": trigger_id,
        })
        result = await self.send_to_zap(trigger["zap_url"], payload)
        trigger["fire_count"] += 1
        trigger["last_fired_at"] = datetime.now(timezone.utc).isoformat()
        self._stats["triggers_fired"] += 1
        self._delivery_history.setdefault(trigger_id, []).append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": trigger["event_type"],
            "status": result.get("status", "unknown"),
            "test": True,
        })
        return {"test_sent": True, **result}

    async def _handle_list_events(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "events": self.SUPPORTED_EVENTS,
            "count": len(self.SUPPORTED_EVENTS),
        }

    async def _handle_get_trigger_history(self, params: dict[str, Any]) -> dict[str, Any]:
        trigger_id = params["trigger_id"]
        limit = params.get("limit", 50)
        history = self._delivery_history.get(trigger_id, [])
        return {"trigger_id": trigger_id, "deliveries": history[-limit:]}

    async def _handle_validate_webhook(self, params: dict[str, Any]) -> dict[str, Any]:
        zap_url = params["zap_url"]
        if not zap_url.startswith("https://hooks.zapier.com/"):
            return {"valid": False, "error": "URL must be a Zapier webhook catch URL"}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.head(zap_url)
                return {"valid": True, "status_code": resp.status_code, "url": zap_url}
        except ImportError:
            return {"valid": True, "note": "Simulated (httpx not available)", "url": zap_url}
        except Exception as exc:
            return {"valid": False, "error": str(exc), "url": zap_url}

    async def _handle_get_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            **self._stats,
            "registered_triggers": len(self._triggers),
            "active_triggers": sum(1 for t in self._triggers.values() if t["active"]),
            "pending_tasks": sum(
                1 for t in self._task_results.values() if t["status"] == "running"
            ),
        }

    # ── Internal helpers ─────────────────────────────────────────────────

    def _sign(self, payload: bytes) -> str:
        """Compute HMAC-SHA256 signature."""
        mac = hmac.new(self._signing_secret.encode(), payload, hashlib.sha256)
        return f"sha256={mac.hexdigest()}"

    async def fire_triggers(self, event_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Fire all triggers matching an event type.

        Called internally by the webhook delivery engine when an event
        occurs.  Fans out to all matching Zapier webhook URLs.

        Returns list of delivery results.
        """
        results: list[dict[str, Any]] = []
        for trigger in self._triggers.values():
            if trigger["event_type"] != event_type or not trigger["active"]:
                continue
            payload = self.create_zap_payload(event_type, data)
            result = await self.send_to_zap(trigger["zap_url"], payload)
            trigger["fire_count"] += 1
            trigger["last_fired_at"] = datetime.now(timezone.utc).isoformat()
            self._stats["triggers_fired"] += 1
            self._delivery_history.setdefault(trigger["id"], []).append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "status": result.get("status", "unknown"),
                "test": False,
            })
            results.append(result)
        return results
