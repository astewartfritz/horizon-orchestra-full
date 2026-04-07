"""Cloud State Layer — DynamoDB for sessions, S3 for workspace, SQS for task queue.

Replaces in-memory state with cloud-native persistence so Lambda
functions (stateless) can share state across invocations.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["CloudState", "StateConfig"]

log = logging.getLogger("orchestra.cloud.state")


@dataclass
class StateConfig:
    region: str = "us-east-1"
    dynamodb_table: str = "horizon-orchestra-state"
    s3_bucket: str = "horizon-orchestra-workspaces"
    sqs_queue: str = "horizon-orchestra-tasks"
    sqs_dlq: str = "horizon-orchestra-tasks-dlq"
    ttl_hours: int = 24


class CloudState:
    """Cloud-native state management for serverless deployment."""

    def __init__(self, config: StateConfig | None = None) -> None:
        self.config = config or StateConfig()
        self._dynamo: Any = None
        self._s3: Any = None
        self._sqs: Any = None

    def _get_dynamo(self) -> Any:
        if not self._dynamo:
            import boto3
            self._dynamo = boto3.resource("dynamodb", region_name=self.config.region)
        return self._dynamo

    def _get_s3(self) -> Any:
        if not self._s3:
            import boto3
            self._s3 = boto3.client("s3", region_name=self.config.region)
        return self._s3

    def _get_sqs(self) -> Any:
        if not self._sqs:
            import boto3
            self._sqs = boto3.client("sqs", region_name=self.config.region)
        return self._sqs

    # -- DynamoDB: sessions + memory ----------------------------------------

    async def save_session(self, user_id: str, session_id: str, data: dict[str, Any]) -> None:
        table = self._get_dynamo().Table(self.config.dynamodb_table)
        table.put_item(Item={
            "pk": f"session#{user_id}",
            "sk": session_id,
            "data": json.dumps(data),
            "updated_at": int(time.time()),
            "ttl": int(time.time() + self.config.ttl_hours * 3600),
        })

    async def load_session(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        table = self._get_dynamo().Table(self.config.dynamodb_table)
        resp = table.get_item(Key={"pk": f"session#{user_id}", "sk": session_id})
        item = resp.get("Item")
        if not item:
            return None
        return json.loads(item.get("data", "{}"))

    async def save_memory(self, user_id: str, memory_id: str, content: str, category: str = "fact", embedding_json: str = "") -> None:
        table = self._get_dynamo().Table(self.config.dynamodb_table)
        table.put_item(Item={
            "pk": f"memory#{user_id}",
            "sk": memory_id,
            "content": content,
            "category": category,
            "embedding": embedding_json,
            "updated_at": int(time.time()),
        })

    async def search_memories(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        table = self._get_dynamo().Table(self.config.dynamodb_table)
        resp = table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": f"memory#{user_id}"},
            Limit=limit,
            ScanIndexForward=False,
        )
        return [
            {"id": i["sk"], "content": i.get("content", ""), "category": i.get("category", ""),
             "embedding": i.get("embedding", ""), "updated_at": i.get("updated_at")}
            for i in resp.get("Items", [])
        ]

    async def save_job(self, job_id: str, data: dict[str, Any]) -> None:
        table = self._get_dynamo().Table(self.config.dynamodb_table)
        table.put_item(Item={
            "pk": "job",
            "sk": job_id,
            "data": json.dumps(data),
            "status": data.get("status", "pending"),
            "updated_at": int(time.time()),
            "ttl": int(time.time() + 7 * 86400),
        })

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        table = self._get_dynamo().Table(self.config.dynamodb_table)
        resp = table.get_item(Key={"pk": "job", "sk": job_id})
        item = resp.get("Item")
        if not item:
            return None
        return json.loads(item.get("data", "{}"))

    # -- S3: workspace files ------------------------------------------------

    async def upload_file(self, user_id: str, filename: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        s3 = self._get_s3()
        key = f"workspaces/{user_id}/{filename}"
        s3.put_object(Bucket=self.config.s3_bucket, Key=key, Body=content, ContentType=content_type)
        return f"s3://{self.config.s3_bucket}/{key}"

    async def download_file(self, user_id: str, filename: str) -> bytes:
        s3 = self._get_s3()
        key = f"workspaces/{user_id}/{filename}"
        resp = s3.get_object(Bucket=self.config.s3_bucket, Key=key)
        return resp["Body"].read()

    async def list_files(self, user_id: str, prefix: str = "") -> list[dict[str, Any]]:
        s3 = self._get_s3()
        full_prefix = f"workspaces/{user_id}/{prefix}"
        resp = s3.list_objects_v2(Bucket=self.config.s3_bucket, Prefix=full_prefix, MaxKeys=100)
        return [
            {"key": o["Key"].replace(f"workspaces/{user_id}/", ""), "size": o["Size"], "modified": str(o["LastModified"])}
            for o in resp.get("Contents", [])
        ]

    async def get_presigned_url(self, user_id: str, filename: str, expires: int = 3600) -> str:
        s3 = self._get_s3()
        key = f"workspaces/{user_id}/{filename}"
        return s3.generate_presigned_url("get_object", Params={"Bucket": self.config.s3_bucket, "Key": key}, ExpiresIn=expires)

    # -- SQS: async task queue ----------------------------------------------

    async def enqueue_task(self, task: dict[str, Any], priority: str = "normal") -> str:
        sqs = self._get_sqs()
        queue_url = self._get_queue_url()
        msg_attrs = {}
        if priority == "high":
            msg_attrs["Priority"] = {"DataType": "String", "StringValue": "high"}
        resp = sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(task), MessageAttributes=msg_attrs)
        return resp.get("MessageId", "")

    async def dequeue_task(self, wait_seconds: int = 5) -> dict[str, Any] | None:
        sqs = self._get_sqs()
        queue_url = self._get_queue_url()
        resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=wait_seconds)
        messages = resp.get("Messages", [])
        if not messages:
            return None
        msg = messages[0]
        # Delete from queue (ack)
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
        return json.loads(msg["Body"])

    async def queue_depth(self) -> int:
        sqs = self._get_sqs()
        queue_url = self._get_queue_url()
        attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessages"])
        return int(attrs.get("Attributes", {}).get("ApproximateNumberOfMessages", 0))

    def _get_queue_url(self) -> str:
        sqs = self._get_sqs()
        resp = sqs.get_queue_url(QueueName=self.config.sqs_queue)
        return resp["QueueUrl"]

    # -- Provisioning -------------------------------------------------------

    async def provision(self) -> dict[str, Any]:
        """Create DynamoDB table, S3 bucket, SQS queues if they don't exist."""
        results: dict[str, str] = {}

        # DynamoDB
        try:
            dynamo = self._get_dynamo()
            dynamo.create_table(
                TableName=self.config.dynamodb_table,
                KeySchema=[
                    {"AttributeName": "pk", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            results["dynamodb"] = "created"
        except Exception as exc:
            results["dynamodb"] = f"exists or error: {exc}"

        # S3
        try:
            s3 = self._get_s3()
            if self.config.region == "us-east-1":
                s3.create_bucket(Bucket=self.config.s3_bucket)
            else:
                s3.create_bucket(Bucket=self.config.s3_bucket, CreateBucketConfiguration={"LocationConstraint": self.config.region})
            results["s3"] = "created"
        except Exception as exc:
            results["s3"] = f"exists or error: {exc}"

        # SQS
        try:
            sqs = self._get_sqs()
            sqs.create_queue(QueueName=self.config.sqs_queue)
            sqs.create_queue(QueueName=self.config.sqs_dlq)
            results["sqs"] = "created"
        except Exception as exc:
            results["sqs"] = f"exists or error: {exc}"

        return results
