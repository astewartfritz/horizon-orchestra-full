"""AWS connector — boto3 credential chain.

S3, Lambda, EC2, CloudWatch operations.
Requires: pip install boto3
Auth: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars, or IAM role, or pass to connect().
"""

from __future__ import annotations

import json, logging, os
from typing import Any
from .base import Connector

__all__ = ["AWSConnector"]
log = logging.getLogger("orchestra.connectors.aws")


class AWSConnector(Connector):
    name = "aws"
    description = "Manage S3, Lambda, EC2, and CloudWatch on AWS."

    def __init__(self) -> None:
        self._session: Any = None
        self._region: str = ""

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self, credentials: dict[str, str]) -> bool:
        try:
            import boto3
        except ImportError:
            log.error("pip install boto3")
            return False

        key = credentials.get("access_key", "") or os.environ.get("AWS_ACCESS_KEY_ID", "")
        secret = credentials.get("secret_key", "") or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        self._region = credentials.get("region", "") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

        try:
            if key and secret:
                self._session = boto3.Session(aws_access_key_id=key, aws_secret_access_key=secret, region_name=self._region)
            else:
                self._session = boto3.Session(region_name=self._region)
            # Verify
            sts = self._session.client("sts")
            identity = sts.get_caller_identity()
            log.info("AWS connected: %s (%s)", identity.get("Arn"), self._region)
            return True
        except Exception as exc:
            log.error("AWS connection failed: %s", exc)
            self._session = None
            return False

    async def disconnect(self) -> None:
        self._session = None

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._session: return {"error": "AWS not connected."}
        d = {
            "aws_s3_list": self._s3_list, "aws_s3_read": self._s3_read, "aws_s3_write": self._s3_write,
            "aws_lambda_invoke": self._lambda_invoke, "aws_lambda_list": self._lambda_list,
            "aws_ec2_list": self._ec2_list, "aws_cloudwatch_query": self._cw_query,
        }
        h = d.get(action)
        return await h(params) if h else {"error": f"Unknown: {action}"}

    async def _s3_list(self, p: dict) -> dict[str, Any]:
        bucket = p.get("bucket", "")
        prefix = p.get("prefix", "")
        try:
            s3 = self._session.client("s3")
            if not bucket:
                r = s3.list_buckets()
                return {"buckets": [{"name": b["Name"], "created": str(b["CreationDate"])} for b in r.get("Buckets", [])]}
            kwargs: dict[str, Any] = {"Bucket": bucket, "MaxKeys": p.get("limit", 50)}
            if prefix: kwargs["Prefix"] = prefix
            r = s3.list_objects_v2(**kwargs)
            return {"objects": [{"key": o["Key"], "size": o["Size"], "modified": str(o["LastModified"])} for o in r.get("Contents", [])]}
        except Exception as exc:
            return {"error": str(exc)}

    async def _s3_read(self, p: dict) -> dict[str, Any]:
        bucket, key = p.get("bucket", ""), p.get("key", "")
        if not bucket or not key: return {"error": "bucket and key required"}
        try:
            s3 = self._session.client("s3")
            obj = s3.get_object(Bucket=bucket, Key=key)
            body = obj["Body"].read()
            text = body.decode("utf-8", errors="replace")[:50_000]
            return {"bucket": bucket, "key": key, "size": len(body), "content": text}
        except Exception as exc:
            return {"error": str(exc)}

    async def _s3_write(self, p: dict) -> dict[str, Any]:
        bucket, key, content = p.get("bucket", ""), p.get("key", ""), p.get("content", "")
        if not all([bucket, key, content]): return {"error": "bucket, key, content required"}
        try:
            s3 = self._session.client("s3")
            s3.put_object(Bucket=bucket, Key=key, Body=content.encode())
            return {"written": True, "bucket": bucket, "key": key}
        except Exception as exc:
            return {"error": str(exc)}

    async def _lambda_list(self, p: dict) -> dict[str, Any]:
        try:
            lam = self._session.client("lambda")
            r = lam.list_functions(MaxItems=p.get("limit", 20))
            return {"functions": [
                {"name": f["FunctionName"], "runtime": f.get("Runtime"), "memory": f.get("MemorySize"), "timeout": f.get("Timeout"), "modified": f.get("LastModified")}
                for f in r.get("Functions", [])
            ]}
        except Exception as exc:
            return {"error": str(exc)}

    async def _lambda_invoke(self, p: dict) -> dict[str, Any]:
        name = p.get("function_name", "")
        payload = p.get("payload", {})
        if not name: return {"error": "function_name required"}
        try:
            lam = self._session.client("lambda")
            r = lam.invoke(FunctionName=name, Payload=json.dumps(payload))
            resp_payload = r["Payload"].read().decode()
            return {"status": r["StatusCode"], "response": resp_payload[:10_000]}
        except Exception as exc:
            return {"error": str(exc)}

    async def _ec2_list(self, p: dict) -> dict[str, Any]:
        try:
            ec2 = self._session.client("ec2")
            r = ec2.describe_instances(MaxResults=p.get("limit", 20))
            instances = []
            for res in r.get("Reservations", []):
                for i in res.get("Instances", []):
                    name = ""
                    for t in i.get("Tags", []):
                        if t["Key"] == "Name": name = t["Value"]
                    instances.append({"id": i["InstanceId"], "name": name, "type": i.get("InstanceType"), "state": i.get("State", {}).get("Name"), "public_ip": i.get("PublicIpAddress")})
            return {"instances": instances}
        except Exception as exc:
            return {"error": str(exc)}

    async def _cw_query(self, p: dict) -> dict[str, Any]:
        query = p.get("query", "")
        hours = p.get("hours", 1)
        if not query: return {"error": "query required"}
        try:
            from datetime import datetime, timedelta, timezone
            cw = self._session.client("logs")
            r = cw.start_query(
                logGroupName=p.get("log_group", "/aws/lambda"),
                startTime=int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()),
                endTime=int(datetime.now(timezone.utc).timestamp()),
                queryString=query, limit=p.get("limit", 50),
            )
            qid = r["queryId"]
            import time; time.sleep(2)
            result = cw.get_query_results(queryId=qid)
            return {"status": result["status"], "results": [
                {f["field"]: f["value"] for f in row} for row in result.get("results", [])
            ]}
        except Exception as exc:
            return {"error": str(exc)}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "aws_s3_list", "description": "List S3 buckets or objects.", "parameters": {"type": "object", "properties": {"bucket": {"type": "string"}, "prefix": {"type": "string"}, "limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "aws_s3_read", "description": "Read a file from S3.", "parameters": {"type": "object", "properties": {"bucket": {"type": "string"}, "key": {"type": "string"}}, "required": ["bucket", "key"]}}},
            {"type": "function", "function": {"name": "aws_s3_write", "description": "Write a file to S3.", "parameters": {"type": "object", "properties": {"bucket": {"type": "string"}, "key": {"type": "string"}, "content": {"type": "string"}}, "required": ["bucket", "key", "content"]}}},
            {"type": "function", "function": {"name": "aws_lambda_list", "description": "List Lambda functions.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "aws_lambda_invoke", "description": "Invoke a Lambda function.", "parameters": {"type": "object", "properties": {"function_name": {"type": "string"}, "payload": {"type": "object"}}, "required": ["function_name"]}}},
            {"type": "function", "function": {"name": "aws_ec2_list", "description": "List EC2 instances.", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "aws_cloudwatch_query", "description": "Query CloudWatch Logs Insights.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "log_group": {"type": "string"}, "hours": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
        ]
