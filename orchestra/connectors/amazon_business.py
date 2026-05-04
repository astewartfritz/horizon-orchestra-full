"""Amazon Business connector — AWS Organizations, Bedrock, S3, DynamoDB, Cost Explorer.

Provides unified access to core AWS services plus Amazon Bedrock AI,
using boto3 for all AWS API interactions.

Requires: pip install boto3

Env vars:
    AWS_ACCESS_KEY_ID       — AWS access key
    AWS_SECRET_ACCESS_KEY   — AWS secret key
    AWS_DEFAULT_REGION      — Default region (e.g. us-east-1)
    AWS_BEDROCK_REGION      — Region for Bedrock service (may differ)
    AMAZON_BUSINESS_ACCESS_KEY — Optional: Amazon Business API key
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

from .base import Connector

__all__ = ["AmazonBusinessConnector", "AmazonBusinessError"]

log = logging.getLogger("orchestra.connectors.amazon_business")

# Optional dependency guard
try:
    import boto3 as _boto3
    from botocore.exceptions import ClientError as _ClientError
    from botocore.exceptions import BotoCoreError as _BotoCoreError
except ImportError:
    _boto3 = None  # type: ignore[assignment]
    _ClientError = Exception  # type: ignore[assignment,misc]
    _BotoCoreError = Exception  # type: ignore[assignment,misc]

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class AmazonBusinessError(Exception):
    """Base error for Amazon Business connector."""


class AmazonBusinessAuthError(AmazonBusinessError):
    """AWS credential / authentication failure."""


class AmazonBusinessAPIError(AmazonBusinessError):
    """AWS API call failure."""


class AmazonBusinessRateLimitError(AmazonBusinessError):
    """AWS throttling / rate limit exceeded."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 4
INITIAL_BACKOFF = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _retry_with_backoff(coro_factory, *, max_retries: int = MAX_RETRIES):
    """Retry with exponential backoff on transient errors."""
    delay = INITIAL_BACKOFF
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except AmazonBusinessRateLimitError:
            if attempt < max_retries:
                log.warning("AWS rate limited, retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
        except (AmazonBusinessAPIError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                log.warning(
                    "AWS request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries + 1, delay, exc,
                )
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exc  # type: ignore[misc]


def _require_boto3() -> Any:
    if _boto3 is None:
        raise AmazonBusinessError("Amazon Business connector requires: pip install boto3")
    return _boto3


def _handle_client_error(exc: Exception) -> None:
    """Convert boto3 ClientError to connector errors."""
    err_code = ""
    if hasattr(exc, "response"):
        err_code = exc.response.get("Error", {}).get("Code", "")  # type: ignore[union-attr]
    if err_code in ("Throttling", "TooManyRequestsException", "RequestLimitExceeded"):
        raise AmazonBusinessRateLimitError(str(exc)) from exc
    raise AmazonBusinessAPIError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class AmazonBusinessConnector(Connector):
    """Full AWS / Amazon Business integration — Orgs, Bedrock, S3, DynamoDB, Cost.

    Provides 20 tools covering AWS Organizations, cost management, S3 storage,
    EC2 instances, Bedrock AI, DynamoDB, Lambda, CloudWatch, and IAM.
    """

    name = "amazon_business"
    description = (
        "Manage AWS resources including Organizations, S3, EC2, Bedrock AI, "
        "DynamoDB, Lambda, CloudWatch, IAM, and Cost Explorer."
    )

    TOOLS: list[str] = [
        "aws_list_organizations",
        "aws_list_accounts",
        "aws_get_account_budget",
        "aws_get_cost_breakdown",
        "aws_get_cost_forecast",
        "aws_list_s3_buckets",
        "aws_get_s3_bucket_metrics",
        "aws_create_s3_bucket",
        "aws_list_ec2_instances",
        "aws_get_ec2_metrics",
        "aws_list_bedrock_models",
        "aws_invoke_bedrock",
        "aws_list_bedrock_knowledge_bases",
        "aws_query_bedrock_kb",
        "aws_list_dynamodb_tables",
        "aws_get_dynamodb_metrics",
        "aws_list_lambda_functions",
        "aws_get_cloudwatch_alarms",
        "aws_list_iam_users",
        "aws_get_iam_user_permissions",
    ]

    def __init__(self) -> None:
        self._session: Any = None  # boto3 Session
        self._region: str = ""
        self._bedrock_region: str = ""
        self._clients: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self, credentials: dict[str, str]) -> bool:
        """Authenticate with AWS.

        Credential keys:
            - access_key_id, secret_access_key — explicit keys
            - region — default AWS region
            - bedrock_region — region for Bedrock (may differ)
            - session_token — optional STS session token
            - profile_name — AWS CLI profile to use
        """
        boto3 = _require_boto3()

        access_key = credentials.get("access_key_id", os.getenv("AWS_ACCESS_KEY_ID", ""))
        secret_key = credentials.get("secret_access_key", os.getenv("AWS_SECRET_ACCESS_KEY", ""))
        self._region = credentials.get("region", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        self._bedrock_region = credentials.get(
            "bedrock_region", os.getenv("AWS_BEDROCK_REGION", self._region)
        )
        session_token = credentials.get("session_token", os.getenv("AWS_SESSION_TOKEN", ""))
        profile = credentials.get("profile_name", "")

        try:
            kwargs: dict[str, Any] = {"region_name": self._region}
            if profile:
                kwargs["profile_name"] = profile
            elif access_key and secret_key:
                kwargs["aws_access_key_id"] = access_key
                kwargs["aws_secret_access_key"] = secret_key
                if session_token:
                    kwargs["aws_session_token"] = session_token
            # Else: rely on default credential chain (IAM role, env, etc.)

            self._session = boto3.Session(**kwargs)
            # Quick validation: STS get-caller-identity
            sts = self._session.client("sts")
            identity = sts.get_caller_identity()
            log.info(
                "AWS connected (account=%s, arn=%s, region=%s)",
                identity.get("Account"),
                identity.get("Arn"),
                self._region,
            )
            return True
        except Exception as exc:
            self._session = None
            raise AmazonBusinessAuthError(f"AWS auth failed: {exc}") from exc

    async def disconnect(self) -> None:
        """Clear AWS session and cached clients."""
        self._session = None
        self._clients.clear()
        log.info("AWS disconnected")

    # ------------------------------------------------------------------
    # Client factory
    # ------------------------------------------------------------------

    def _client(self, service: str, region: str | None = None) -> Any:
        """Get or create a boto3 client for a service."""
        region = region or self._region
        key = f"{service}:{region}"
        if key not in self._clients:
            self._clients[key] = self._session.client(service, region_name=region)
        return self._clients[key]

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Route an action to its handler with retry/backoff."""
        if not self.connected:
            return {"error": "AWS not connected. Call connect() first."}

        dispatch: dict[str, Any] = {
            "aws_list_organizations": self._list_organizations,
            "aws_list_accounts": self._list_accounts,
            "aws_get_account_budget": self._get_account_budget,
            "aws_get_cost_breakdown": self._get_cost_breakdown,
            "aws_get_cost_forecast": self._get_cost_forecast,
            "aws_list_s3_buckets": self._list_s3_buckets,
            "aws_get_s3_bucket_metrics": self._get_s3_bucket_metrics,
            "aws_create_s3_bucket": self._create_s3_bucket,
            "aws_list_ec2_instances": self._list_ec2_instances,
            "aws_get_ec2_metrics": self._get_ec2_metrics,
            "aws_list_bedrock_models": self._list_bedrock_models,
            "aws_invoke_bedrock": self._invoke_bedrock,
            "aws_list_bedrock_knowledge_bases": self._list_bedrock_knowledge_bases,
            "aws_query_bedrock_kb": self._query_bedrock_kb,
            "aws_list_dynamodb_tables": self._list_dynamodb_tables,
            "aws_get_dynamodb_metrics": self._get_dynamodb_metrics,
            "aws_list_lambda_functions": self._list_lambda_functions,
            "aws_get_cloudwatch_alarms": self._get_cloudwatch_alarms,
            "aws_list_iam_users": self._list_iam_users,
            "aws_get_iam_user_permissions": self._get_iam_user_permissions,
        }
        handler = dispatch.get(action)
        if not handler:
            return {"error": f"Unknown AWS action: {action}"}
        try:
            return await _retry_with_backoff(lambda: handler(params))
        except AmazonBusinessError as exc:
            return {"error": str(exc)}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {"error": str(exc)}  # unreachable but keeps type checker happy
        except Exception as exc:
            log.exception("Unexpected error in AWS action %s", action)
            return {"error": f"Internal error: {exc}"}

    # ------------------------------------------------------------------
    # Tool implementations (20 tools)
    # ------------------------------------------------------------------

    # ---- AWS Organizations ----

    async def _list_organizations(self, params: dict[str, Any]) -> dict[str, Any]:
        """List AWS Organization details."""
        try:
            orgs = self._client("organizations")
            data = orgs.describe_organization()
            org = data.get("Organization", {})
            return {
                "id": org.get("Id"),
                "arn": org.get("Arn"),
                "master_account_id": org.get("MasterAccountId"),
                "master_account_email": org.get("MasterAccountEmail"),
                "feature_set": org.get("FeatureSet"),
            }
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _list_accounts(self, params: dict[str, Any]) -> dict[str, Any]:
        """List member accounts in the AWS Organization."""
        try:
            orgs = self._client("organizations")
            paginator = orgs.get_paginator("list_accounts")
            accounts: list[dict[str, Any]] = []
            for page in paginator.paginate():
                for a in page.get("Accounts", []):
                    accounts.append({
                        "id": a.get("Id"),
                        "name": a.get("Name"),
                        "email": a.get("Email"),
                        "status": a.get("Status"),
                        "joined": str(a.get("JoinedTimestamp", "")),
                    })
            return {"count": len(accounts), "accounts": accounts}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ---- Cost Explorer ----

    async def _get_account_budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get budget and cost data for an AWS account."""
        account_id = params.get("account_id", "")
        try:
            budgets = self._client("budgets")
            data = budgets.describe_budgets(AccountId=account_id or self._session.client("sts").get_caller_identity()["Account"])
            budget_list = [
                {
                    "name": b.get("BudgetName"),
                    "type": b.get("BudgetType"),
                    "limit": b.get("BudgetLimit", {}).get("Amount"),
                    "actual_spend": b.get("CalculatedSpend", {}).get("ActualSpend", {}).get("Amount"),
                    "forecasted_spend": b.get("CalculatedSpend", {}).get("ForecastedSpend", {}).get("Amount"),
                    "time_unit": b.get("TimeUnit"),
                }
                for b in data.get("Budgets", [])
            ]
            return {"budgets": budget_list}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _get_cost_breakdown(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get cost and usage breakdown from Cost Explorer."""
        start = params.get("start", "")
        end = params.get("end", "")
        granularity = params.get("granularity", "MONTHLY")
        group_by = params.get("group_by", "SERVICE")
        if not start or not end:
            return {"error": "start and end dates (YYYY-MM-DD) are required"}
        try:
            ce = self._client("ce")
            kwargs: dict[str, Any] = {
                "TimePeriod": {"Start": start, "End": end},
                "Granularity": granularity,
                "Metrics": ["BlendedCost", "UnblendedCost", "UsageQuantity"],
                "GroupBy": [{"Type": "DIMENSION", "Key": group_by}],
            }
            data = ce.get_cost_and_usage(**kwargs)
            results = []
            for period in data.get("ResultsByTime", []):
                for group in period.get("Groups", []):
                    results.append({
                        "period_start": period.get("TimePeriod", {}).get("Start"),
                        "period_end": period.get("TimePeriod", {}).get("End"),
                        "key": group.get("Keys", [""])[0],
                        "blended_cost": group.get("Metrics", {}).get("BlendedCost", {}).get("Amount"),
                        "unblended_cost": group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount"),
                        "usage_quantity": group.get("Metrics", {}).get("UsageQuantity", {}).get("Amount"),
                    })
            return {"results": results, "total_results": len(results)}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _get_cost_forecast(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get cost forecast from Cost Explorer."""
        start = params.get("start", "")
        end = params.get("end", "")
        if not start or not end:
            return {"error": "start and end dates (YYYY-MM-DD) are required"}
        try:
            ce = self._client("ce")
            data = ce.get_cost_forecast(
                TimePeriod={"Start": start, "End": end},
                Metric="UNBLENDED_COST",
                Granularity="MONTHLY",
            )
            return {
                "total_forecast": data.get("Total", {}).get("Amount"),
                "unit": data.get("Total", {}).get("Unit"),
                "forecast_by_time": [
                    {
                        "period_start": f.get("TimePeriod", {}).get("Start"),
                        "mean": f.get("MeanValue"),
                    }
                    for f in data.get("ForecastResultsByTime", [])
                ],
            }
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ---- S3 ----

    async def _list_s3_buckets(self, params: dict[str, Any]) -> dict[str, Any]:
        """List S3 buckets in the account."""
        try:
            s3 = self._client("s3")
            data = s3.list_buckets()
            buckets = [
                {
                    "name": b.get("Name"),
                    "created": str(b.get("CreationDate", "")),
                }
                for b in data.get("Buckets", [])
            ]
            return {"count": len(buckets), "buckets": buckets}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _get_s3_bucket_metrics(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get size and object count metrics for an S3 bucket."""
        bucket = params.get("bucket", "")
        if not bucket:
            return {"error": "bucket name is required"}
        try:
            from datetime import datetime, timedelta
            cw = self._client("cloudwatch")
            end = datetime.utcnow()
            start = end - timedelta(days=2)
            # BucketSizeBytes
            size_data = cw.get_metric_statistics(
                Namespace="AWS/S3",
                MetricName="BucketSizeBytes",
                Dimensions=[
                    {"Name": "BucketName", "Value": bucket},
                    {"Name": "StorageType", "Value": "StandardStorage"},
                ],
                StartTime=start,
                EndTime=end,
                Period=86400,
                Statistics=["Average"],
            )
            # NumberOfObjects
            count_data = cw.get_metric_statistics(
                Namespace="AWS/S3",
                MetricName="NumberOfObjects",
                Dimensions=[
                    {"Name": "BucketName", "Value": bucket},
                    {"Name": "StorageType", "Value": "AllStorageTypes"},
                ],
                StartTime=start,
                EndTime=end,
                Period=86400,
                Statistics=["Average"],
            )
            size_bytes = 0
            if size_data.get("Datapoints"):
                size_bytes = size_data["Datapoints"][-1].get("Average", 0)
            obj_count = 0
            if count_data.get("Datapoints"):
                obj_count = int(count_data["Datapoints"][-1].get("Average", 0))
            return {
                "bucket": bucket,
                "size_bytes": size_bytes,
                "size_gb": round(size_bytes / (1024**3), 2),
                "object_count": obj_count,
            }
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _create_s3_bucket(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new S3 bucket with optional encryption."""
        name = params.get("name", "")
        region = params.get("region", self._region)
        encryption = params.get("encryption", "AES256")
        if not name:
            return {"error": "bucket name is required"}
        try:
            s3 = self._client("s3", region=region)
            create_kwargs: dict[str, Any] = {"Bucket": name}
            if region != "us-east-1":
                create_kwargs["CreateBucketConfiguration"] = {
                    "LocationConstraint": region,
                }
            s3.create_bucket(**create_kwargs)
            # Enable encryption
            s3.put_bucket_encryption(
                Bucket=name,
                ServerSideEncryptionConfiguration={
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": encryption,
                            },
                        },
                    ],
                },
            )
            return {"bucket": name, "region": region, "encryption": encryption, "created": True}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ---- EC2 ----

    async def _list_ec2_instances(self, params: dict[str, Any]) -> dict[str, Any]:
        """List EC2 instances with optional filters."""
        region = params.get("region", self._region)
        filters: list[dict[str, Any]] = params.get("filters", [])
        try:
            ec2 = self._client("ec2", region=region)
            kwargs: dict[str, Any] = {}
            if filters:
                kwargs["Filters"] = filters
            data = ec2.describe_instances(**kwargs)
            instances: list[dict[str, Any]] = []
            for reservation in data.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    name_tag = ""
                    for tag in inst.get("Tags", []):
                        if tag.get("Key") == "Name":
                            name_tag = tag.get("Value", "")
                    instances.append({
                        "id": inst.get("InstanceId"),
                        "name": name_tag,
                        "type": inst.get("InstanceType"),
                        "state": inst.get("State", {}).get("Name"),
                        "az": inst.get("Placement", {}).get("AvailabilityZone"),
                        "private_ip": inst.get("PrivateIpAddress"),
                        "public_ip": inst.get("PublicIpAddress"),
                        "launch_time": str(inst.get("LaunchTime", "")),
                    })
            return {"count": len(instances), "instances": instances}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _get_ec2_metrics(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get CloudWatch metrics for an EC2 instance."""
        instance_id = params.get("instance_id", "")
        metric = params.get("metric", "CPUUtilization")
        period = params.get("period", 3600)
        if not instance_id:
            return {"error": "instance_id is required"}
        try:
            from datetime import datetime, timedelta
            cw = self._client("cloudwatch")
            end = datetime.utcnow()
            start = end - timedelta(hours=24)
            data = cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName=metric,
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start,
                EndTime=end,
                Period=period,
                Statistics=["Average", "Maximum"],
            )
            points = sorted(data.get("Datapoints", []), key=lambda d: str(d.get("Timestamp", "")))
            return {
                "instance_id": instance_id,
                "metric": metric,
                "datapoints": [
                    {
                        "timestamp": str(p.get("Timestamp")),
                        "average": p.get("Average"),
                        "maximum": p.get("Maximum"),
                    }
                    for p in points
                ],
            }
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ---- Bedrock ----

    async def _list_bedrock_models(self, params: dict[str, Any]) -> dict[str, Any]:
        """List available Bedrock foundation models."""
        try:
            bedrock = self._client("bedrock", region=self._bedrock_region)
            data = bedrock.list_foundation_models()
            models = [
                {
                    "id": m.get("modelId"),
                    "name": m.get("modelName"),
                    "provider": m.get("providerName"),
                    "input_modalities": m.get("inputModalities", []),
                    "output_modalities": m.get("outputModalities", []),
                    "streaming": m.get("responseStreamingSupported", False),
                }
                for m in data.get("modelSummaries", [])
            ]
            return {"count": len(models), "models": models}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _invoke_bedrock(self, params: dict[str, Any]) -> dict[str, Any]:
        """Invoke a Bedrock foundation model with a prompt."""
        model_id = params.get("model_id", "")
        prompt = params.get("prompt", "")
        invoke_params: dict[str, Any] = params.get("params", {})
        if not model_id or not prompt:
            return {"error": "model_id and prompt are required"}
        try:
            bedrock_rt = self._client("bedrock-runtime", region=self._bedrock_region)
            # Build request body based on model provider
            body: dict[str, Any]
            if "anthropic" in model_id.lower():
                body = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": invoke_params.get("max_tokens", 1024),
                    **{k: v for k, v in invoke_params.items() if k != "max_tokens"},
                }
            elif "amazon" in model_id.lower() or "titan" in model_id.lower():
                body = {
                    "inputText": prompt,
                    "textGenerationConfig": {
                        "maxTokenCount": invoke_params.get("max_tokens", 1024),
                        "temperature": invoke_params.get("temperature", 0.7),
                    },
                }
            elif "meta" in model_id.lower() or "llama" in model_id.lower():
                body = {
                    "prompt": prompt,
                    "max_gen_len": invoke_params.get("max_tokens", 1024),
                    "temperature": invoke_params.get("temperature", 0.7),
                }
            else:
                body = {"inputText": prompt, **invoke_params}

            response = bedrock_rt.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            # Extract text from various response formats
            text = ""
            if "content" in result:  # Anthropic
                text = result["content"][0].get("text", "") if result["content"] else ""
            elif "results" in result:  # Titan
                text = result["results"][0].get("outputText", "") if result["results"] else ""
            elif "generation" in result:  # Llama
                text = result["generation"]
            elif "completions" in result:
                text = result["completions"][0].get("data", {}).get("text", "")
            else:
                text = json.dumps(result)
            return {"model_id": model_id, "response": text}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _list_bedrock_knowledge_bases(self, params: dict[str, Any]) -> dict[str, Any]:
        """List Bedrock Knowledge Bases."""
        try:
            agent = self._client("bedrock-agent", region=self._bedrock_region)
            data = agent.list_knowledge_bases()
            kbs = [
                {
                    "id": kb.get("knowledgeBaseId"),
                    "name": kb.get("name"),
                    "description": kb.get("description"),
                    "status": kb.get("status"),
                    "updated": str(kb.get("updatedAt", "")),
                }
                for kb in data.get("knowledgeBaseSummaries", [])
            ]
            return {"count": len(kbs), "knowledge_bases": kbs}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _query_bedrock_kb(self, params: dict[str, Any]) -> dict[str, Any]:
        """Query a Bedrock Knowledge Base with semantic search."""
        kb_id = params.get("kb_id", "")
        query = params.get("query", "")
        max_results = params.get("max_results", 5)
        if not kb_id or not query:
            return {"error": "kb_id and query are required"}
        try:
            agent_rt = self._client("bedrock-agent-runtime", region=self._bedrock_region)
            data = agent_rt.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {"numberOfResults": max_results},
                },
            )
            results = [
                {
                    "content": r.get("content", {}).get("text", ""),
                    "score": r.get("score"),
                    "source": r.get("location", {}).get("s3Location", {}).get("uri"),
                }
                for r in data.get("retrievalResults", [])
            ]
            return {"kb_id": kb_id, "results": results}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ---- DynamoDB ----

    async def _list_dynamodb_tables(self, params: dict[str, Any]) -> dict[str, Any]:
        """List DynamoDB tables in a region."""
        region = params.get("region", self._region)
        try:
            ddb = self._client("dynamodb", region=region)
            data = ddb.list_tables()
            tables = data.get("TableNames", [])
            return {"count": len(tables), "tables": tables, "region": region}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _get_dynamodb_metrics(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get DynamoDB table metrics (capacity, throttle, item count)."""
        table_name = params.get("table_name", "")
        if not table_name:
            return {"error": "table_name is required"}
        try:
            ddb = self._client("dynamodb")
            desc = ddb.describe_table(TableName=table_name)
            table = desc.get("Table", {})
            return {
                "table_name": table_name,
                "status": table.get("TableStatus"),
                "item_count": table.get("ItemCount"),
                "size_bytes": table.get("TableSizeBytes"),
                "read_capacity": table.get("ProvisionedThroughput", {}).get("ReadCapacityUnits"),
                "write_capacity": table.get("ProvisionedThroughput", {}).get("WriteCapacityUnits"),
                "billing_mode": table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
                "gsi_count": len(table.get("GlobalSecondaryIndexes", [])),
            }
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ---- Lambda ----

    async def _list_lambda_functions(self, params: dict[str, Any]) -> dict[str, Any]:
        """List AWS Lambda functions in a region."""
        region = params.get("region", self._region)
        try:
            lam = self._client("lambda", region=region)
            paginator = lam.get_paginator("list_functions")
            functions: list[dict[str, Any]] = []
            for page in paginator.paginate():
                for f in page.get("Functions", []):
                    functions.append({
                        "name": f.get("FunctionName"),
                        "runtime": f.get("Runtime"),
                        "memory_mb": f.get("MemorySize"),
                        "timeout": f.get("Timeout"),
                        "handler": f.get("Handler"),
                        "last_modified": f.get("LastModified"),
                        "code_size": f.get("CodeSize"),
                    })
            return {"count": len(functions), "functions": functions, "region": region}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ---- CloudWatch ----

    async def _get_cloudwatch_alarms(self, params: dict[str, Any]) -> dict[str, Any]:
        """List CloudWatch alarms, optionally filtered by state."""
        region = params.get("region", self._region)
        state = params.get("state", "")
        try:
            cw = self._client("cloudwatch", region=region)
            kwargs: dict[str, Any] = {}
            if state:
                kwargs["StateValue"] = state
            data = cw.describe_alarms(**kwargs)
            alarms = [
                {
                    "name": a.get("AlarmName"),
                    "state": a.get("StateValue"),
                    "metric": a.get("MetricName"),
                    "namespace": a.get("Namespace"),
                    "threshold": a.get("Threshold"),
                    "comparison": a.get("ComparisonOperator"),
                    "description": a.get("AlarmDescription"),
                    "updated": str(a.get("StateUpdatedTimestamp", "")),
                }
                for a in data.get("MetricAlarms", [])
            ]
            return {"count": len(alarms), "alarms": alarms}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ---- IAM ----

    async def _list_iam_users(self, params: dict[str, Any]) -> dict[str, Any]:
        """List IAM users in the AWS account."""
        try:
            iam = self._client("iam")
            paginator = iam.get_paginator("list_users")
            users: list[dict[str, Any]] = []
            for page in paginator.paginate():
                for u in page.get("Users", []):
                    users.append({
                        "username": u.get("UserName"),
                        "user_id": u.get("UserId"),
                        "arn": u.get("Arn"),
                        "created": str(u.get("CreateDate", "")),
                        "password_last_used": str(u.get("PasswordLastUsed", "")),
                    })
            return {"count": len(users), "users": users}
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    async def _get_iam_user_permissions(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get attached policies and group memberships for an IAM user."""
        username = params.get("username", "")
        if not username:
            return {"error": "username is required"}
        try:
            iam = self._client("iam")
            # Attached policies
            policies_data = iam.list_attached_user_policies(UserName=username)
            policies = [
                {"name": p.get("PolicyName"), "arn": p.get("PolicyArn")}
                for p in policies_data.get("AttachedPolicies", [])
            ]
            # Inline policies
            inline_data = iam.list_user_policies(UserName=username)
            inline_policies = inline_data.get("PolicyNames", [])
            # Groups
            groups_data = iam.list_groups_for_user(UserName=username)
            groups = [g.get("GroupName") for g in groups_data.get("Groups", [])]
            # MFA devices
            mfa_data = iam.list_mfa_devices(UserName=username)
            mfa = [m.get("SerialNumber") for m in mfa_data.get("MFADevices", [])]
            return {
                "username": username,
                "attached_policies": policies,
                "inline_policies": inline_policies,
                "groups": groups,
                "mfa_devices": mfa,
            }
        except _ClientError as exc:
            _handle_client_error(exc)
            return {}

    # ------------------------------------------------------------------
    # Tool definitions (OpenAI function-calling format)
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas for all 20 Amazon Business tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "aws_list_organizations",
                    "description": "Get AWS Organization details (ID, master account, feature set).",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_list_accounts",
                    "description": "List member accounts in the AWS Organization.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "org_id": {"type": "string", "description": "Organization ID (optional)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_get_account_budget",
                    "description": "Get budget and cost data for an AWS account.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account_id": {"type": "string", "description": "AWS account ID"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_get_cost_breakdown",
                    "description": "Get cost and usage breakdown from AWS Cost Explorer.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                            "granularity": {"type": "string", "description": "DAILY, MONTHLY, or HOURLY"},
                            "group_by": {"type": "string", "description": "Dimension to group by (SERVICE, REGION, etc)"},
                        },
                        "required": ["start", "end"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_get_cost_forecast",
                    "description": "Get cost forecast from AWS Cost Explorer.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "description": "Forecast start date"},
                            "end": {"type": "string", "description": "Forecast end date"},
                        },
                        "required": ["start", "end"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_list_s3_buckets",
                    "description": "List all S3 buckets in the AWS account.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_get_s3_bucket_metrics",
                    "description": "Get size and object count metrics for an S3 bucket.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "bucket": {"type": "string", "description": "S3 bucket name"},
                        },
                        "required": ["bucket"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_create_s3_bucket",
                    "description": "Create a new S3 bucket with optional encryption.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Bucket name"},
                            "region": {"type": "string", "description": "AWS region"},
                            "encryption": {"type": "string", "description": "Encryption type (AES256 or aws:kms)"},
                        },
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_list_ec2_instances",
                    "description": "List EC2 instances with optional filters.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "region": {"type": "string", "description": "AWS region"},
                            "filters": {
                                "type": "array", "items": {"type": "object"},
                                "description": "EC2 describe-instances filter list",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_get_ec2_metrics",
                    "description": "Get CloudWatch metrics (CPU, network, etc) for an EC2 instance.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "instance_id": {"type": "string", "description": "EC2 instance ID"},
                            "metric": {"type": "string", "description": "Metric name (default: CPUUtilization)"},
                            "period": {"type": "integer", "description": "Period in seconds (default 3600)"},
                        },
                        "required": ["instance_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_list_bedrock_models",
                    "description": "List available Amazon Bedrock foundation models.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_invoke_bedrock",
                    "description": "Invoke an Amazon Bedrock foundation model with a prompt.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "model_id": {"type": "string", "description": "Bedrock model ID"},
                            "prompt": {"type": "string", "description": "Input prompt text"},
                            "params": {"type": "object", "description": "Model parameters (max_tokens, temperature, etc)"},
                        },
                        "required": ["model_id", "prompt"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_list_bedrock_knowledge_bases",
                    "description": "List Amazon Bedrock Knowledge Bases.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_query_bedrock_kb",
                    "description": "Query a Bedrock Knowledge Base with semantic search.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kb_id": {"type": "string", "description": "Knowledge Base ID"},
                            "query": {"type": "string", "description": "Search query text"},
                            "max_results": {"type": "integer", "description": "Max results (default 5)"},
                        },
                        "required": ["kb_id", "query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_list_dynamodb_tables",
                    "description": "List DynamoDB tables in a region.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "region": {"type": "string", "description": "AWS region"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_get_dynamodb_metrics",
                    "description": "Get DynamoDB table metrics (capacity, size, item count).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "DynamoDB table name"},
                        },
                        "required": ["table_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_list_lambda_functions",
                    "description": "List AWS Lambda functions in a region.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "region": {"type": "string", "description": "AWS region"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_get_cloudwatch_alarms",
                    "description": "List CloudWatch alarms, optionally filtered by state.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "region": {"type": "string", "description": "AWS region"},
                            "state": {"type": "string", "description": "Alarm state filter (OK, ALARM, INSUFFICIENT_DATA)"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_list_iam_users",
                    "description": "List IAM users in the AWS account.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "aws_get_iam_user_permissions",
                    "description": "Get attached policies, inline policies, groups, and MFA for an IAM user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string", "description": "IAM username"},
                        },
                        "required": ["username"],
                    },
                },
            },
        ]
