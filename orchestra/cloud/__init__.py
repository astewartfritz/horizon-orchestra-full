"""Horizon Orchestra — Cloud Runtime Layer.

Compute abstraction that runs Orchestra on AWS Lambda now and
migrates to Terafab (Horizon's custom infrastructure) later.
The backend is swappable — same interface, different execution.

GPU compute integration connects to the strongest available hardware:
- NVIDIA GB200 NVL72 (CoreWeave, Oracle) — 72 Blackwell GPUs, 1+ exaflop
- NVIDIA B200 (Lambda, CoreWeave) — 180GB VRAM, $4.62-6.99/hr
- NVIDIA H200 (AWS P5e, Lambda) — 141GB HBM3e
- NVIDIA H100 (everywhere) — baseline workhorse, $0.99-4.29/hr
"""

from .compute import ComputeBackend, ComputeRequest, ComputeResponse
from .lambda_runtime import LambdaRuntime, LambdaConfig
from .terafab import TerafabRuntime, TerafabConfig
from .state import CloudState, StateConfig
from .deployer import LambdaDeployer, DeployConfig
from .edge import EdgeRouter, EdgeConfig
from .iac import generate_sam_template, generate_cdk_stack
from .websocket_relay import WebSocketRelay, WebSocketFrame
from .files import CloudFiles
from .sessions import CloudSessionStore
from .gpu_providers import GPUProviderRegistry, GPUSpec, ProviderConfig, GPUPricing
from .gpu_cluster import GPUCluster, ClusterConfig, GPUNode
from .autoscaler import AutoScaler, ScalingPolicy
from .inference_router import InferenceRouter, InferenceEndpoint, RoutingStrategy

__all__ = [
    # Compute abstraction
    "ComputeBackend",
    "ComputeRequest",
    "ComputeResponse",
    # Lambda
    "LambdaRuntime",
    "LambdaConfig",
    # Terafab
    "TerafabRuntime",
    "TerafabConfig",
    # State
    "CloudState",
    "StateConfig",
    # Deployment
    "LambdaDeployer",
    "DeployConfig",
    "EdgeRouter",
    "EdgeConfig",
    "generate_sam_template",
    "generate_cdk_stack",
    # Real-time
    "WebSocketRelay",
    "WebSocketFrame",
    "CloudFiles",
    "CloudSessionStore",
    # GPU compute
    "GPUProviderRegistry",
    "GPUSpec",
    "ProviderConfig",
    "GPUPricing",
    "GPUCluster",
    "ClusterConfig",
    "GPUNode",
    "AutoScaler",
    "ScalingPolicy",
    "InferenceRouter",
    "InferenceEndpoint",
    "RoutingStrategy",
]
