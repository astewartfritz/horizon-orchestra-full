"""
orchestra/cloud/websocket_relay.py
-----------------------------------
WebSocket relay for real-time streaming through API Gateway + Lambda.

Manages persistent WebSocket connections via DynamoDB and forwards
AgentEvent frames to connected clients through the API Gateway
Management API.
"""
from __future__ import annotations

__all__ = [
    "WebSocketRelay",
    "WebSocketFrame",
]

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import boto3
    from botocore.exceptions import ClientError
    _HAS_BOTO3 = True
except ImportError:  # pragma: no cover — optional cloud dependency
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc,assignment]
    _HAS_BOTO3 = False

logger = logging.getLogger("orchestra.cloud.websocket_relay")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WebSocketFrame:
    """A single frame sent over a WebSocket connection."""

    type: str  # "tool_call" | "tool_result" | "thinking" | "token" | "final" | "error" | "heartbeat"
    data: dict
    sequence: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": self.type,
                "data": self.data,
                "sequence": self.sequence,
                "timestamp": self.timestamp,
            }
        )


# ---------------------------------------------------------------------------
# WebSocketRelay
# ---------------------------------------------------------------------------

class WebSocketRelay:
    """
    Relay for real-time streaming through AWS API Gateway WebSocket + Lambda.

    DynamoDB table schema
    ----------------------
    PK  : connection_id  (String, hash key)
    GSI : user_id-index  (user_id as hash key, connection_id as range key)
    ttl : epoch seconds  (DynamoDB TTL attribute)
    """

    _CONNECTION_TTL_SECONDS: int = 7200  # 2 hours

    def __init__(
        self,
        connection_table: str = "horizon-ws-connections",
        region: str = "us-east-1",
    ) -> None:
        if not _HAS_BOTO3:
            raise RuntimeError(
                "boto3 is required for WebSocketRelay. "
                "Install it with: pip install boto3"
            )
        self._table_name = connection_table
        self._region = region
        self._dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = self._dynamodb.Table(connection_table)
        logger.info(
            "WebSocketRelay initialised (table=%s, region=%s)",
            connection_table,
            region,
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def on_connect(self, connection_id: str, user_id: str) -> dict:
        """Store a new WebSocket connection in DynamoDB.

        Returns the stored item as a dict.
        """
        ttl = int(time.time()) + self._CONNECTION_TTL_SECONDS
        item = {
            "connection_id": connection_id,
            "user_id": user_id,
            "connected_at": time.time(),
            "ttl": ttl,
        }
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._table.put_item(Item=item),
            )
            logger.info("on_connect: stored connection_id=%s user_id=%s", connection_id, user_id)
            return {"statusCode": 200, "item": item}
        except ClientError as exc:
            logger.exception("on_connect: DynamoDB error for connection_id=%s", connection_id)
            return {"statusCode": 500, "error": str(exc)}

    async def on_disconnect(self, connection_id: str) -> dict:
        """Remove a WebSocket connection from DynamoDB."""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._table.delete_item(
                    Key={"connection_id": connection_id}
                ),
            )
            logger.info("on_disconnect: removed connection_id=%s", connection_id)
            return {"statusCode": 200, "connection_id": connection_id}
        except ClientError as exc:
            logger.exception("on_disconnect: DynamoDB error for connection_id=%s", connection_id)
            return {"statusCode": 500, "error": str(exc)}

    # ------------------------------------------------------------------
    # Sending data
    # ------------------------------------------------------------------

    async def send_to_connection(
        self,
        connection_id: str,
        data: dict,
        api_gateway_endpoint: str,
    ) -> bool:
        """POST a message to a single WebSocket connection.

        ``api_gateway_endpoint`` format:
            ``https://{api_id}.execute-api.{region}.amazonaws.com/{stage}``

        Returns True on success, False if the connection is stale / gone.
        """
        # The Management API endpoint includes @connections
        endpoint_url = api_gateway_endpoint.rstrip("/")
        client = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=endpoint_url,
            region_name=self._region,
        )
        payload = json.dumps(data).encode("utf-8")
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.post_to_connection(
                    ConnectionId=connection_id,
                    Data=payload,
                ),
            )
            return True
        except client.exceptions.GoneException:
            logger.warning("send_to_connection: connection %s is gone, cleaning up", connection_id)
            await self.on_disconnect(connection_id)
            return False
        except ClientError as exc:
            logger.exception(
                "send_to_connection: error sending to connection_id=%s", connection_id
            )
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "410":
                await self.on_disconnect(connection_id)
            return False

    async def broadcast_to_user(
        self,
        user_id: str,
        data: dict,
        api_gateway_endpoint: str,
    ) -> int:
        """Send ``data`` to every active connection for ``user_id``.

        Queries the ``user_id-index`` GSI and fans-out concurrently.
        Returns the number of successful sends.
        """
        connections = await self._get_connections_for_user(user_id)
        if not connections:
            logger.debug("broadcast_to_user: no connections for user_id=%s", user_id)
            return 0

        tasks = [
            self.send_to_connection(conn["connection_id"], data, api_gateway_endpoint)
            for conn in connections
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success_count = sum(1 for r in results if r == True)
        logger.debug(
            "broadcast_to_user: user_id=%s connections=%d sent=%d",
            user_id,
            len(connections),
            success_count,
        )
        return success_count

    # ------------------------------------------------------------------
    # Agent streaming
    # ------------------------------------------------------------------

    async def stream_agent_events(
        self,
        user_id: str,
        agent: Any,
        task: str,
        api_gateway_endpoint: str,
    ) -> dict:
        """Run ``agent.stream(task)`` and relay each AgentEvent to all user
        connections as a WebSocket frame.

        The agent must expose an async generator ``stream(task: str)`` that
        yields objects with at minimum a ``type`` attribute and a ``to_dict()``
        method (or a plain dict).

        Returns a summary dict with total events relayed and any error.
        """
        sequence = 0
        events_sent = 0
        start_time = time.time()

        try:
            async for event in agent.stream(task):
                # Normalise event to dict
                if hasattr(event, "to_dict"):
                    event_data = event.to_dict()
                elif isinstance(event, dict):
                    event_data = event
                else:
                    event_data = {"raw": str(event)}

                event_type = event_data.get("type", "token")

                frame = WebSocketFrame(
                    type=event_type,
                    data=event_data,
                    sequence=sequence,
                )
                sequence += 1

                sent = await self.broadcast_to_user(
                    user_id, json.loads(frame.to_json()), api_gateway_endpoint
                )
                if sent > 0:
                    events_sent += 1

            # Send final completion frame
            final_frame = WebSocketFrame(
                type="final",
                data={"status": "completed", "duration": time.time() - start_time},
                sequence=sequence,
            )
            await self.broadcast_to_user(
                user_id, json.loads(final_frame.to_json()), api_gateway_endpoint
            )

            return {
                "status": "completed",
                "events_sent": events_sent,
                "duration": time.time() - start_time,
            }

        except Exception as exc:
            logger.exception("stream_agent_events: error for user_id=%s", user_id)
            error_frame = WebSocketFrame(
                type="error",
                data={"error": str(exc), "duration": time.time() - start_time},
                sequence=sequence,
            )
            await self.broadcast_to_user(
                user_id, json.loads(error_frame.to_json()), api_gateway_endpoint
            )
            return {
                "status": "error",
                "error": str(exc),
                "events_sent": events_sent,
                "duration": time.time() - start_time,
            }

    # ------------------------------------------------------------------
    # Lambda handler
    # ------------------------------------------------------------------

    def lambda_handler(self, event: dict, context: Any) -> dict:
        """API Gateway WebSocket Lambda handler.

        Routes ``$connect``, ``$disconnect``, and ``$default`` routes.
        Runs the async coroutines via a new event loop since Lambda may
        not have a running loop.
        """
        route_key = event.get("requestContext", {}).get("routeKey", "$default")
        connection_id: str = event.get("requestContext", {}).get("connectionId", "")
        domain = event.get("requestContext", {}).get("domainName", "")
        stage = event.get("requestContext", {}).get("stage", "")
        api_gateway_endpoint = f"https://{domain}/{stage}"

        logger.info(
            "lambda_handler: route=%s connection_id=%s", route_key, connection_id
        )

        loop = asyncio.new_event_loop()
        try:
            if route_key == "$connect":
                # Expect user_id in query string parameters
                qs = event.get("queryStringParameters") or {}
                user_id = qs.get("user_id", "anonymous")
                result = loop.run_until_complete(
                    self.on_connect(connection_id, user_id)
                )
                return {"statusCode": result.get("statusCode", 200)}

            elif route_key == "$disconnect":
                result = loop.run_until_complete(self.on_disconnect(connection_id))
                return {"statusCode": result.get("statusCode", 200)}

            else:
                # $default — handle incoming messages (echo / heartbeat)
                body: dict = {}
                raw_body = event.get("body", "")
                if raw_body:
                    try:
                        body = json.loads(raw_body)
                    except json.JSONDecodeError:
                        body = {"raw": raw_body}

                msg_type = body.get("type", "message")
                if msg_type == "heartbeat":
                    # Echo heartbeat back
                    loop.run_until_complete(
                        self.send_to_connection(
                            connection_id,
                            {"type": "heartbeat", "ts": time.time()},
                            api_gateway_endpoint,
                        )
                    )
                else:
                    logger.debug(
                        "lambda_handler: unhandled $default message type=%s", msg_type
                    )

                return {"statusCode": 200}
        finally:
            loop.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_connections_for_user(self, user_id: str) -> list[dict]:
        """Query the user_id GSI for all active connections."""
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._table.query(
                    IndexName="user_id-index",
                    KeyConditionExpression=boto3.dynamodb.conditions.Key("user_id").eq(
                        user_id
                    ),
                ),
            )
            return response.get("Items", [])
        except ClientError:
            logger.exception("_get_connections_for_user: error for user_id=%s", user_id)
            return []
