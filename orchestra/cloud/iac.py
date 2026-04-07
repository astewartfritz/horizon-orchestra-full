"""Infrastructure-as-Code — SAM template + CDK stack generation.

Generates deployment-ready AWS infrastructure definitions.
Run sam deploy or cdk deploy to go live.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

__all__ = ["generate_sam_template", "generate_cdk_stack"]
log = logging.getLogger("orchestra.cloud.iac")


def generate_sam_template(output_dir: str = ".", config: dict[str, Any] | None = None) -> str:
    """Generate an AWS SAM template for Horizon Orchestra."""
    cfg = config or {}
    memory = cfg.get("memory_mb", 1024)
    timeout = cfg.get("timeout", 300)
    region = cfg.get("region", "us-east-1")

    template = f"""AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Horizon Orchestra — Agentic AI Platform on Lambda

Globals:
  Function:
    Runtime: python3.12
    MemorySize: {memory}
    Timeout: {timeout}
    Environment:
      Variables:
        HORIZON_BACKEND: lambda
        PYTHONPATH: /var/task

Resources:
  # ── Lambda Function ─────────────────────────────────────────────
  OrchestraFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: horizon-orchestra
      Handler: handler.lambda_handler
      CodeUri: .
      Description: Horizon Orchestra main handler
      Architectures:
        - x86_64
      Layers:
        - !Ref DependenciesLayer
      Tracing: Active
      Events:
        RunApi:
          Type: HttpApi
          Properties:
            Path: /v1/run
            Method: POST
            ApiId: !Ref HttpApi
        HealthApi:
          Type: HttpApi
          Properties:
            Path: /health
            Method: GET
            ApiId: !Ref HttpApi
        QueryApi:
          Type: HttpApi
          Properties:
            Path: /v1/query
            Method: POST
            ApiId: !Ref HttpApi
        ModelsApi:
          Type: HttpApi
          Properties:
            Path: /v1/models
            Method: GET
            ApiId: !Ref HttpApi
        MemoryApi:
          Type: HttpApi
          Properties:
            Path: /v1/memory/{{proxy+}}
            Method: ANY
            ApiId: !Ref HttpApi
        TaskQueue:
          Type: SQS
          Properties:
            Queue: !GetAtt TaskQueue.Arn
            BatchSize: 1
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref StateTable
        - S3CrudPolicy:
            BucketName: !Ref WorkspaceBucket
        - SQSPollerPolicy:
            QueueName: !GetAtt TaskQueue.QueueName

  # ── Warmup Function (keeps Lambda hot) ──────────────────────────
  WarmupFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: horizon-orchestra-warmup
      Handler: handler.lambda_handler
      CodeUri: .
      MemorySize: 256
      Timeout: 10
      Layers:
        - !Ref DependenciesLayer
      Events:
        WarmupSchedule:
          Type: Schedule
          Properties:
            Schedule: rate(5 minutes)
            Input: '{{"payload": {{"action": "warmup"}}}}'

  # ── Dependencies Lambda Layer ───────────────────────────────────
  DependenciesLayer:
    Type: AWS::Serverless::LayerVersion
    Properties:
      LayerName: horizon-orchestra-deps
      Description: Python dependencies for Horizon Orchestra
      ContentUri: layers/dependencies/
      CompatibleRuntimes:
        - python3.12
      RetentionPolicy: Retain
    Metadata:
      BuildMethod: python3.12

  # ── HTTP API Gateway ────────────────────────────────────────────
  HttpApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      StageName: prod
      CorsConfiguration:
        AllowOrigins:
          - '*'
        AllowMethods:
          - '*'
        AllowHeaders:
          - '*'

  # ── WebSocket API Gateway ───────────────────────────────────────
  WebSocketApi:
    Type: AWS::ApiGatewayV2::Api
    Properties:
      Name: horizon-orchestra-ws
      ProtocolType: WEBSOCKET
      RouteSelectionExpression: $request.body.action

  # ── DynamoDB State Table ────────────────────────────────────────
  StateTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: horizon-orchestra-state
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: pk
          AttributeType: S
        - AttributeName: sk
          AttributeType: S
      KeySchema:
        - AttributeName: pk
          KeyType: HASH
        - AttributeName: sk
          KeyType: RANGE
      TimeToLiveSpecification:
        AttributeName: ttl
        Enabled: true

  # ── S3 Workspace Bucket ─────────────────────────────────────────
  WorkspaceBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub horizon-orchestra-workspaces-${{AWS::AccountId}}
      LifecycleConfiguration:
        Rules:
          - Id: CleanupOldFiles
            Status: Enabled
            ExpirationInDays: 30
      CorsConfiguration:
        CorsRules:
          - AllowedMethods: [GET, PUT]
            AllowedOrigins: ['*']
            AllowedHeaders: ['*']

  # ── SQS Task Queue ─────────────────────────────────────────────
  TaskQueue:
    Type: AWS::SQS::Queue
    Properties:
      QueueName: horizon-orchestra-tasks
      VisibilityTimeout: 600
      MessageRetentionPeriod: 86400
      RedrivePolicy:
        deadLetterTargetArn: !GetAtt DeadLetterQueue.Arn
        maxReceiveCount: 3

  DeadLetterQueue:
    Type: AWS::SQS::Queue
    Properties:
      QueueName: horizon-orchestra-tasks-dlq
      MessageRetentionPeriod: 604800

Outputs:
  ApiUrl:
    Description: HTTP API endpoint
    Value: !Sub "https://${{HttpApi}}.execute-api.${{AWS::Region}}.amazonaws.com/prod"
  WebSocketUrl:
    Description: WebSocket API endpoint
    Value: !Sub "wss://${{WebSocketApi}}.execute-api.${{AWS::Region}}.amazonaws.com/prod"
  FunctionArn:
    Description: Lambda function ARN
    Value: !GetAtt OrchestraFunction.Arn
  StateDynamoTable:
    Description: DynamoDB table name
    Value: !Ref StateTable
  WorkspaceBucket:
    Description: S3 workspace bucket
    Value: !Ref WorkspaceBucket
"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "template.yaml").write_text(template)
    log.info("Generated SAM template: %s/template.yaml", output_dir)
    return str(out / "template.yaml")


def generate_cdk_stack(output_dir: str = ".", config: dict[str, Any] | None = None) -> str:
    """Generate an AWS CDK stack (Python) for Horizon Orchestra."""
    cfg = config or {}

    stack = '''"""Horizon Orchestra — AWS CDK Stack."""
from aws_cdk import (
    Stack, Duration, RemovalPolicy,
    aws_lambda as lambda_,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct


class HorizonOrchestraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Lambda Layer for dependencies
        deps_layer = lambda_.LayerVersion(
            self, "DepsLayer",
            code=lambda_.Code.from_asset("layers/dependencies"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Horizon Orchestra Python dependencies",
        )

        # Main Lambda function
        fn = lambda_.Function(
            self, "OrchestraFn",
            function_name="horizon-orchestra",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("."),
            memory_size=1024,
            timeout=Duration.seconds(300),
            layers=[deps_layer],
            tracing=lambda_.Tracing.ACTIVE,
            environment={"HORIZON_BACKEND": "lambda"},
        )

        # HTTP API
        http_api = apigw.HttpApi(
            self, "HttpApi",
            api_name="horizon-orchestra-api",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[apigw.CorsHttpMethod.ANY],
            ),
        )
        integration = integrations.HttpLambdaIntegration("LambdaIntegration", fn)
        http_api.add_routes(path="/v1/run", methods=[apigw.HttpMethod.POST], integration=integration)
        http_api.add_routes(path="/health", methods=[apigw.HttpMethod.GET], integration=integration)
        http_api.add_routes(path="/v1/query", methods=[apigw.HttpMethod.POST], integration=integration)

        # DynamoDB
        table = dynamodb.Table(
            self, "StateTable",
            table_name="horizon-orchestra-state",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.RETAIN,
        )
        table.grant_read_write_data(fn)

        # S3
        bucket = s3.Bucket(
            self, "WorkspaceBucket",
            bucket_name=f"horizon-orchestra-workspaces-{self.account}",
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
        )
        bucket.grant_read_write(fn)

        # SQS
        dlq = sqs.Queue(self, "DLQ", queue_name="horizon-orchestra-tasks-dlq")
        queue = sqs.Queue(
            self, "TaskQueue",
            queue_name="horizon-orchestra-tasks",
            visibility_timeout=Duration.seconds(600),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=3),
        )
        queue.grant_consume_messages(fn)

        # Warmup scheduled event
        warmup_rule = events.Rule(
            self, "WarmupRule",
            schedule=events.Schedule.rate(Duration.minutes(5)),
        )
        warmup_rule.add_target(targets.LambdaFunction(fn, event=events.RuleTargetInput.from_object({"payload": {"action": "warmup"}})))
'''
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "cdk_stack.py").write_text(stack)
    log.info("Generated CDK stack: %s/cdk_stack.py", output_dir)
    return str(out / "cdk_stack.py")
