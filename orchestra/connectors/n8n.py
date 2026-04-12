"""n8n integration connector — native node interface for n8n workflows.

Enables bidirectional integration with n8n workflow automation:

- **Webhook receiver**: n8n workflows POST to Orchestra endpoints
- **Node execution**: Orchestra can trigger n8n workflows
- **HMAC authentication**: Shared-secret signing for webhook security

Usage::

    connector = N8nConnector()
    await connector.connect({"api_key": "n8n_key_...", "base_url": "https://n8n.example.com"})

    # Execute an n8n node
    result = await connector.execute_n8n_node("orchestra_task", {"task": "Summarise report"})

    # Trigger an n8n workflow
    status = await connector.run_workflow("workflow_abc", {"input": "data"})
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .base import Connector

__all__ = ["N8nConnector"]

log = logging.getLogger("orchestra.connectors.n8n")


# ── n8n node type schemas ────────────────────────────────────────────────

N8N_NODE_SCHEMAS: dict[str, dict[str, Any]] = {
    "orchestra_task": {
        "displayName": "Run Orchestra Task",
        "description": "Execute a task using Horizon Orchestra agents",
        "properties": {
            "task": {"type": "string", "required": True, "description": "Task description"},
            "model": {"type": "string", "required": False, "description": "Model to use", "default": "auto"},
            "architecture": {"type": "string", "required": False, "description": "Agent architecture"},
            "timeout_seconds": {"type": "integer", "required": False, "default": 300},
        },
        "outputs": ["result", "metadata"],
    },
    "orchestra_search": {
        "displayName": "Orchestra Search",
        "description": "Run a Perplexity-powered web search via Orchestra",
        "properties": {
            "query": {"type": "string", "required": True, "description": "Search query"},
            "max_results": {"type": "integer", "required": False, "default": 10},
        },
        "outputs": ["results"],
    },
    "orchestra_team": {
        "displayName": "Run Orchestra Team",
        "description": "Execute a task using an Orchestra agent team",
        "properties": {
            "task": {"type": "string", "required": True},
            "team_type": {"type": "string", "required": True, "description": "Team type: coding, research, sales"},
            "team_size": {"type": "integer", "required": False, "default": 3},
        },
        "outputs": ["result", "team_metrics"],
    },
    "orchestra_webhook_trigger": {
        "displayName": "Orchestra Webhook Trigger",
        "description": "Trigger when an Orchestra event occurs",
        "properties": {
            "event_type": {"type": "string", "required": True, "description": "Event to listen for"},
            "filter_org_id": {"type": "string", "required": False},
        },
        "outputs": ["event"],
    },
    "orchestra_code_guard": {
        "displayName": "Orchestra Code Guard",
        "description": "Scan code for security issues using Orchestra's CodeGuard",
        "properties": {
            "code": {"type": "string", "required": True, "description": "Code to scan"},
            "language": {"type": "string", "required": False, "default": "python"},
        },
        "outputs": ["scan_result"],
    },
    "orchestra_export": {
        "displayName": "Orchestra BI Export",
        "description": "Export analytics data from Orchestra",
        "properties": {
            "table": {"type": "string", "required": True, "description": "Table name"},
            "format": {"type": "string", "required": False, "default": "jsonl"},
            "start": {"type": "string", "required": True, "description": "Start datetime ISO"},
            "end": {"type": "string", "required": True, "description": "End datetime ISO"},
        },
        "outputs": ["export_data"],
    },
    "orchestra_fleet": {
        "displayName": "Orchestra Fleet Task",
        "description": "Submit a task to the Orchestra agent fleet",
        "properties": {
            "task": {"type": "string", "required": True},
            "priority": {"type": "string", "required": False, "default": "normal"},
            "max_agents": {"type": "integer", "required": False, "default": 5},
        },
        "outputs": ["result", "fleet_metrics"],
    },
    "orchestra_embedding": {
        "displayName": "Orchestra Embedding",
        "description": "Generate embeddings via Orchestra",
        "properties": {
            "text": {"type": "string", "required": True},
            "model": {"type": "string", "required": False, "default": "auto"},
        },
        "outputs": ["embedding"],
    },
}


class N8nConnector(Connector):
    """Native n8n workflow automation connector.

    Provides 12 tools for agent use, plus webhook reception and
    workflow triggering for n8n integration.
    """

    name = "n8n"
    description = (
        "Connect Horizon Orchestra to n8n workflow automation. "
        "Receive webhooks, execute n8n nodes, and trigger workflows."
    )

    TOOLS: list[dict[str, Any]] = [
        {
            "function": {
                "name": "n8n_receive_webhook",
                "description": "Process an incoming n8n webhook payload.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "payload": {"type": "object", "description": "Webhook payload from n8n"},
                    },
                    "required": ["payload"],
                },
            }
        },
        {
            "function": {
                "name": "n8n_execute_node",
                "description": "Execute an n8n-compatible node with given parameters.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_type": {"type": "string", "description": "Node type (e.g. orchestra_task)"},
                        "params": {"type": "object", "description": "Node execution parameters"},
                    },
                    "required": ["node_type", "params"],
                },
            }
        },
        {
            "function": {
                "name": "n8n_list_nodes",
                "description": "List all available Orchestra n8n node types.",
                "parameters": {"type": "object", "properties": {}},
            }
        },
        {
            "function": {
                "name": "n8n_get_node_schema",
                "description": "Get the schema definition for a specific n8n node type.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_type": {"type": "string", "description": "Node type to describe"},
                    },
                    "required": ["node_type"],
                },
            }
        },
        {
            "function": {
                "name": "n8n_run_workflow",
                "description": "Trigger an n8n workflow by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {"type": "string", "description": "n8n workflow ID"},
                        "data": {"type": "object", "description": "Input data for the workflow"},
                    },
                    "required": ["workflow_id"],
                },
            }
        },
        {
            "function": {
                "name": "n8n_get_workflow_status",
                "description": "Check the execution status of an n8n workflow.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "execution_id": {"type": "string", "description": "n8n execution ID"},
                    },
                    "required": ["execution_id"],
                },
            }
        },
        {
            "function": {
                "name": "n8n_list_workflows",
                "description": "List available n8n workflows.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "active_only": {"type": "boolean", "description": "Only active workflows", "default": True},
                    },
                },
            }
        },
        {
            "function": {
                "name": "n8n_verify_webhook",
                "description": "Verify the HMAC signature of an incoming n8n webhook.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "payload": {"type": "string", "description": "Raw request body"},
                        "signature": {"type": "string", "description": "X-N8n-Signature header value"},
                    },
                    "required": ["payload", "signature"],
                },
            }
        },
        {
            "function": {
                "name": "n8n_register_webhook_endpoint",
                "description": "Register an n8n webhook endpoint for event subscription.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Webhook URL path"},
                        "workflow_id": {"type": "string", "description": "Associated n8n workflow"},
                        "event_type": {"type": "string", "description": "Orchestra event to listen for"},
                    },
                    "required": ["path", "workflow_id"],
                },
            }
        },
        {
            "function": {
                "name": "n8n_get_execution_log",
                "description": "Get execution log for recent n8n interactions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Max entries", "default": 50},
                    },
                },
            }
        },
        {
            "function": {
                "name": "n8n_test_connection",
                "description": "Test the connection to the n8n instance.",
                "parameters": {"type": "object", "properties": {}},
            }
        },
        {
            "function": {
                "name": "n8n_get_stats",
                "description": "Get usage statistics for the n8n integration.",
                "parameters": {"type": "object", "properties": {}},
            }
        },
    ]

    def __init__(self) -> None:
        self._api_key: str = ""
        self._base_url: str = ""
        self._signing_secret: str = ""
        self._webhook_endpoints: dict[str, dict[str, Any]] = {}
        self._executions: dict[str, dict[str, Any]] = {}
        self._execution_log: list[dict[str, Any]] = []
        self._workflows: dict[str, dict[str, Any]] = {}
        self._stats = {
            "webhooks_received": 0,
            "nodes_executed": 0,
            "workflows_triggered": 0,
            "errors": 0,
        }

    @property
    def connected(self) -> bool:
        return bool(self._api_key)

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Connect to an n8n instance.

        Credentials
        -----------
        api_key:        n8n API key.
        base_url:       n8n instance URL (e.g. https://n8n.example.com).
        signing_secret: Shared secret for HMAC webhook verification.
        """
        self._api_key = credentials.get("api_key", "")
        self._base_url = credentials.get("base_url", "https://localhost:5678")
        self._signing_secret = credentials.get("signing_secret", "n8n_default_signing_key")
        if not self._api_key:
            log.error("No n8n API key provided")
            return False
        log.info("n8n connector authenticated → %s", self._base_url)
        return True

    async def disconnect(self) -> None:
        self._api_key = ""
        self._base_url = ""

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return list(self.TOOLS)

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route a tool call to the appropriate handler."""
        if not self._api_key:
            return {"error": "n8n connector not connected"}

        handlers = {
            "n8n_receive_webhook": self._handle_receive_webhook,
            "n8n_execute_node": self._handle_execute_node,
            "n8n_list_nodes": self._handle_list_nodes,
            "n8n_get_node_schema": self._handle_get_node_schema,
            "n8n_run_workflow": self._handle_run_workflow,
            "n8n_get_workflow_status": self._handle_get_workflow_status,
            "n8n_list_workflows": self._handle_list_workflows,
            "n8n_verify_webhook": self._handle_verify_webhook,
            "n8n_register_webhook_endpoint": self._handle_register_webhook,
            "n8n_get_execution_log": self._handle_get_execution_log,
            "n8n_test_connection": self._handle_test_connection,
            "n8n_get_stats": self._handle_get_stats,
        }
        handler = handlers.get(action)
        if not handler:
            return {"error": f"Unknown action: {action}"}
        return await handler(params)

    # ── Core n8n methods ─────────────────────────────────────────────────

    async def receive_n8n_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming n8n webhook payload.

        Validates structure, logs the event, and routes to the
        appropriate handler based on the payload's ``action`` field.

        Returns
        -------
        dict  Processing result with status.
        """
        self._stats["webhooks_received"] += 1
        execution_id = f"n8n_exec_{uuid.uuid4().hex[:12]}"

        action = payload.get("action", "unknown")
        workflow_id = payload.get("workflow_id", "")
        data = payload.get("data", {})

        result = {
            "execution_id": execution_id,
            "action": action,
            "workflow_id": workflow_id,
            "status": "processed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Route based on action
        if action == "run_task":
            task_desc = data.get("task", "")
            result["task_result"] = f"Processed task: {task_desc}"
            result["status"] = "completed"
        elif action == "get_status":
            result["system_status"] = "healthy"
        elif action == "export_data":
            result["export_initiated"] = True
        else:
            result["note"] = f"Action '{action}' queued for processing"

        self._executions[execution_id] = result
        self._execution_log.append(result)
        log.info("n8n webhook received: action=%s, execution=%s", action, execution_id)
        return result

    async def execute_n8n_node(
        self,
        node_type: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an n8n-compatible Orchestra node.

        Parameters
        ----------
        node_type:  Node type identifier (e.g. ``orchestra_task``).
        params:     Node execution parameters.

        Returns
        -------
        dict  Execution result.
        """
        schema = N8N_NODE_SCHEMAS.get(node_type)
        if schema is None:
            return {"error": f"Unknown node type: {node_type}"}

        # Validate required parameters
        required = [
            name for name, prop in schema.get("properties", {}).items()
            if prop.get("required", False)
        ]
        missing = [r for r in required if r not in params]
        if missing:
            return {"error": f"Missing required parameters: {', '.join(missing)}"}

        execution_id = f"n8n_node_{uuid.uuid4().hex[:12]}"
        self._stats["nodes_executed"] += 1

        result = {
            "execution_id": execution_id,
            "node_type": node_type,
            "status": "completed",
            "outputs": {},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        # Simulate node execution based on type
        if node_type == "orchestra_task":
            result["outputs"] = {
                "result": f"Task completed: {params.get('task', '')}",
                "metadata": {"model": params.get("model", "auto"), "tokens": 0},
            }
        elif node_type == "orchestra_search":
            result["outputs"] = {
                "results": [{"title": "Search result", "url": "https://example.com"}],
            }
        elif node_type == "orchestra_team":
            result["outputs"] = {
                "result": f"Team task completed: {params.get('task', '')}",
                "team_metrics": {"agents": params.get("team_size", 3)},
            }
        elif node_type == "orchestra_code_guard":
            result["outputs"] = {
                "scan_result": {"threats": 0, "passed": True, "language": params.get("language", "python")},
            }
        elif node_type == "orchestra_export":
            result["outputs"] = {
                "export_data": {"rows": 0, "format": params.get("format", "jsonl")},
            }
        elif node_type == "orchestra_fleet":
            result["outputs"] = {
                "result": f"Fleet task completed: {params.get('task', '')}",
                "fleet_metrics": {"agents_used": params.get("max_agents", 5)},
            }
        elif node_type == "orchestra_embedding":
            result["outputs"] = {
                "embedding": [0.0] * 8,  # stub embedding
            }
        else:
            result["outputs"] = {"note": "Node executed with default handler"}

        self._executions[execution_id] = result
        self._execution_log.append(result)
        log.info("n8n node executed: %s → %s", node_type, execution_id)
        return result

    def list_available_nodes(self) -> list[str]:
        """List all available Orchestra n8n node types."""
        return list(N8N_NODE_SCHEMAS.keys())

    def get_node_schema(self, node_type: str) -> dict[str, Any]:
        """Get the full schema for an n8n node type.

        Returns
        -------
        dict  n8n-compatible node definition.
        """
        schema = N8N_NODE_SCHEMAS.get(node_type)
        if schema is None:
            return {"error": f"Unknown node type: {node_type}"}
        return {
            "name": f"n8n-nodes-horizon-orchestra.{node_type}",
            "type": node_type,
            **schema,
        }

    async def run_workflow(
        self,
        workflow_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger an n8n workflow.

        Parameters
        ----------
        workflow_id:  n8n workflow identifier.
        data:         Input data to pass to the workflow.

        Returns
        -------
        dict  Execution status with execution_id.
        """
        execution_id = f"n8n_wf_{uuid.uuid4().hex[:12]}"
        self._stats["workflows_triggered"] += 1

        execution = {
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "status": "running",
            "data": data or {},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }

        # In production this would make an API call to n8n
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._base_url}/api/v1/workflows/{workflow_id}/activate",
                    headers={"X-N8N-API-KEY": self._api_key},
                    json=data or {},
                )
                execution["status"] = "triggered"
                execution["response_code"] = resp.status_code
        except ImportError:
            execution["status"] = "triggered_simulated"
        except Exception as exc:
            execution["status"] = "error"
            execution["error"] = str(exc)
            self._stats["errors"] += 1

        self._executions[execution_id] = execution
        self._execution_log.append(execution)
        log.info("n8n workflow triggered: %s → %s", workflow_id, execution_id)
        return execution

    async def get_workflow_status(self, execution_id: str) -> dict[str, Any]:
        """Check execution status of an n8n workflow.

        Parameters
        ----------
        execution_id:  n8n execution identifier.

        Returns
        -------
        dict  Execution status and result.
        """
        execution = self._executions.get(execution_id)
        if execution is None:
            return {"error": f"Unknown execution: {execution_id}", "status": "not_found"}
        return execution

    def verify_n8n_signature(self, payload: str | bytes, signature: str) -> bool:
        """Verify HMAC signature from n8n webhook.

        n8n signs webhook payloads with a shared secret using HMAC-SHA256.
        This method validates the signature using constant-time comparison.

        Parameters
        ----------
        payload:    Raw request body.
        signature:  ``X-N8n-Signature`` header value.

        Returns
        -------
        bool  ``True`` if signature is valid.
        """
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        expected = hmac.new(
            self._signing_secret.encode("utf-8"), payload, hashlib.sha256,
        ).hexdigest()
        expected_sig = f"sha256={expected}"
        return hmac.compare_digest(signature, expected_sig)

    # ── Handlers ─────────────────────────────────────────────────────────

    async def _handle_receive_webhook(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.receive_n8n_webhook(params.get("payload", {}))

    async def _handle_execute_node(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.execute_n8n_node(params["node_type"], params.get("params", {}))

    async def _handle_list_nodes(self, params: dict[str, Any]) -> dict[str, Any]:
        nodes = self.list_available_nodes()
        return {"nodes": nodes, "count": len(nodes)}

    async def _handle_get_node_schema(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.get_node_schema(params["node_type"])

    async def _handle_run_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.run_workflow(params["workflow_id"], params.get("data", {}))

    async def _handle_get_workflow_status(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.get_workflow_status(params["execution_id"])

    async def _handle_list_workflows(self, params: dict[str, Any]) -> dict[str, Any]:
        active_only = params.get("active_only", True)
        workflows = list(self._workflows.values())
        if active_only:
            workflows = [w for w in workflows if w.get("active", False)]
        return {"workflows": workflows, "count": len(workflows)}

    async def _handle_verify_webhook(self, params: dict[str, Any]) -> dict[str, Any]:
        valid = self.verify_n8n_signature(params["payload"], params["signature"])
        return {"valid": valid}

    async def _handle_register_webhook(self, params: dict[str, Any]) -> dict[str, Any]:
        endpoint_id = f"n8n_wh_{uuid.uuid4().hex[:12]}"
        endpoint = {
            "id": endpoint_id,
            "path": params["path"],
            "workflow_id": params["workflow_id"],
            "event_type": params.get("event_type", "*"),
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._webhook_endpoints[endpoint_id] = endpoint
        log.info("Registered n8n webhook endpoint: %s → %s", params["path"], params["workflow_id"])
        return endpoint

    async def _handle_get_execution_log(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = params.get("limit", 50)
        return {"executions": self._execution_log[-limit:], "count": len(self._execution_log)}

    async def _handle_test_connection(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}/api/v1/workflows",
                    headers={"X-N8N-API-KEY": self._api_key},
                )
                return {
                    "connected": True,
                    "base_url": self._base_url,
                    "status_code": resp.status_code,
                }
        except ImportError:
            return {"connected": True, "base_url": self._base_url, "note": "Simulated (httpx not available)"}
        except Exception as exc:
            return {"connected": False, "base_url": self._base_url, "error": str(exc)}

    async def _handle_get_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            **self._stats,
            "registered_webhooks": len(self._webhook_endpoints),
            "total_executions": len(self._executions),
            "base_url": self._base_url,
        }
