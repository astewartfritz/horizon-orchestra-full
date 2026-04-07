"""Lambda Deployer — automated packaging and deployment to AWS Lambda.

Handles: zip packaging, layer creation, API Gateway setup, environment
variables, and IAM role configuration.
"""

from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["LambdaDeployer", "DeployConfig"]
log = logging.getLogger("orchestra.cloud.deployer")


@dataclass
class DeployConfig:
    region: str = "us-east-1"
    function_name: str = "horizon-orchestra"
    runtime: str = "python3.12"
    memory_mb: int = 1024
    timeout: int = 300
    role_arn: str = ""
    s3_bucket: str = ""
    layers: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    api_gateway_name: str = "horizon-orchestra-api"
    enable_websocket: bool = True
    enable_cors: bool = True
    stage: str = "prod"


class LambdaDeployer:
    """Deploy Horizon Orchestra to AWS Lambda."""

    def __init__(self, config: DeployConfig | None = None) -> None:
        self.config = config or DeployConfig()

    async def package(self, source_dir: str = ".", output: str = "deployment.zip") -> str:
        """Package Orchestra into a Lambda deployment zip."""
        source = Path(source_dir)
        buf = io.BytesIO()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add orchestra package
            for py_file in sorted(source.rglob("orchestra/**/*.py")):
                arcname = str(py_file.relative_to(source))
                zf.write(py_file, arcname)

            # Add Lambda handler wrapper
            zf.writestr("handler.py", self._handler_code())

            # Add requirements marker
            zf.writestr("requirements.txt", "openai>=1.60.0\nhttpx>=0.27.0\n")

        out_path = Path(output)
        out_path.write_bytes(buf.getvalue())
        log.info("Packaged deployment: %s (%.1f KB)", output, len(buf.getvalue()) / 1024)
        return str(out_path)

    async def deploy(self, package_path: str = "deployment.zip") -> dict[str, Any]:
        """Deploy the package to Lambda."""
        try:
            import boto3
        except ImportError:
            return {"error": "pip install boto3"}

        client = boto3.client("lambda", region_name=self.config.region)
        pkg = Path(package_path)
        if not pkg.exists():
            return {"error": f"Package not found: {package_path}"}

        zip_bytes = pkg.read_bytes()
        env_vars = {
            "HORIZON_BACKEND": "lambda",
            **self.config.environment,
        }
        # Pass through API keys from local env
        for key in ["MOONSHOT_API_KEY", "PERPLEXITY_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"]:
            if os.environ.get(key):
                env_vars[key] = os.environ[key]

        try:
            # Update existing
            client.update_function_code(FunctionName=self.config.function_name, ZipFile=zip_bytes)
            client.update_function_configuration(
                FunctionName=self.config.function_name,
                Runtime=self.config.runtime,
                Handler="handler.lambda_handler",
                MemorySize=self.config.memory_mb,
                Timeout=self.config.timeout,
                Environment={"Variables": env_vars},
                Layers=self.config.layers,
            )
            return {"deployed": True, "function": self.config.function_name, "action": "updated"}
        except client.exceptions.ResourceNotFoundException:
            # Create new
            if not self.config.role_arn:
                return {"error": "role_arn required for new function creation"}
            client.create_function(
                FunctionName=self.config.function_name,
                Runtime=self.config.runtime,
                Handler="handler.lambda_handler",
                Code={"ZipFile": zip_bytes},
                Role=self.config.role_arn,
                MemorySize=self.config.memory_mb,
                Timeout=self.config.timeout,
                Environment={"Variables": env_vars},
                Layers=self.config.layers,
            )
            return {"deployed": True, "function": self.config.function_name, "action": "created"}
        except Exception as exc:
            return {"error": str(exc)}

    async def setup_api_gateway(self) -> dict[str, Any]:
        """Create API Gateway (REST + WebSocket) pointing to the Lambda."""
        try:
            import boto3
        except ImportError:
            return {"error": "pip install boto3"}

        apigw = boto3.client("apigatewayv2", region_name=self.config.region)
        lam = boto3.client("lambda", region_name=self.config.region)

        results: dict[str, Any] = {}

        # Get Lambda ARN
        try:
            fn = lam.get_function(FunctionName=self.config.function_name)
            lambda_arn = fn["Configuration"]["FunctionArn"]
        except Exception as exc:
            return {"error": f"Lambda not found: {exc}"}

        # REST API (HTTP API v2)
        try:
            api = apigw.create_api(
                Name=f"{self.config.api_gateway_name}-http",
                ProtocolType="HTTP",
                CorsConfiguration={"AllowOrigins": ["*"], "AllowMethods": ["*"], "AllowHeaders": ["*"]} if self.config.enable_cors else {},
            )
            api_id = api["ApiId"]

            # Integration
            integration = apigw.create_integration(
                ApiId=api_id, IntegrationType="AWS_PROXY",
                IntegrationUri=lambda_arn, PayloadFormatVersion="2.0",
            )

            # Route
            apigw.create_route(ApiId=api_id, RouteKey="POST /v1/run", Target=f"integrations/{integration['IntegrationId']}")
            apigw.create_route(ApiId=api_id, RouteKey="GET /health", Target=f"integrations/{integration['IntegrationId']}")

            # Deploy
            apigw.create_stage(ApiId=api_id, StageName=self.config.stage, AutoDeploy=True)

            results["http_api"] = {
                "api_id": api_id,
                "url": f"https://{api_id}.execute-api.{self.config.region}.amazonaws.com/{self.config.stage}",
            }
        except Exception as exc:
            results["http_api"] = {"error": str(exc)}

        # WebSocket API
        if self.config.enable_websocket:
            try:
                ws_api = apigw.create_api(
                    Name=f"{self.config.api_gateway_name}-ws",
                    ProtocolType="WEBSOCKET",
                    RouteSelectionExpression="$request.body.action",
                )
                ws_id = ws_api["ApiId"]

                ws_integration = apigw.create_integration(
                    ApiId=ws_id, IntegrationType="AWS_PROXY",
                    IntegrationUri=lambda_arn,
                )

                for route in ["$connect", "$disconnect", "$default"]:
                    apigw.create_route(ApiId=ws_id, RouteKey=route, Target=f"integrations/{ws_integration['IntegrationId']}")

                apigw.create_stage(ApiId=ws_id, StageName=self.config.stage, AutoDeploy=True)

                results["websocket_api"] = {
                    "api_id": ws_id,
                    "url": f"wss://{ws_id}.execute-api.{self.config.region}.amazonaws.com/{self.config.stage}",
                }
            except Exception as exc:
                results["websocket_api"] = {"error": str(exc)}

        return results

    def _handler_code(self) -> str:
        return '''"""Auto-generated Lambda handler for Horizon Orchestra."""
from orchestra.cloud.lambda_runtime import lambda_handler
'''
