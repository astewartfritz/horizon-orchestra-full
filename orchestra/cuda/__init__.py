"""CUDA kernel management infrastructure for Orchestra."""
from __future__ import annotations

from .kernel_manager import (
    CUDAKernelManager,
    GPUDevice,
    CompiledKernel,
    KernelResult,
    KernelProfile,
    OccupancyReport,
    AutoTuneResult,
)
from .memory_manager import (
    GPUMemoryManager,
    GPUAllocation,
    MemoryStats,
    UnifiedAllocation,
)
from .multi_gpu import MultiGPUOrchestrator
from .kernels import (
    FlashAttentionKernel,
    FusedEmbeddingKernel,
    SecurityScanKernel,
)

__all__ = [
    "CUDAKernelManager", "GPUDevice", "CompiledKernel", "KernelResult",
    "KernelProfile", "OccupancyReport", "AutoTuneResult",
    "GPUMemoryManager", "GPUAllocation", "MemoryStats", "UnifiedAllocation",
    "MultiGPUOrchestrator",
    "FlashAttentionKernel", "FusedEmbeddingKernel", "SecurityScanKernel",
]
