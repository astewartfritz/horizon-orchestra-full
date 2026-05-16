"""Multi-GPU orchestration with data, tensor, and pipeline parallelism."""
from __future__ import annotations

import logging
import math
import random
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("orchestra.cuda.multi_gpu")

__all__ = ["MultiGPUOrchestrator"]


@dataclass
class _DeviceSlot:
    """Internal bookkeeping for a single GPU in the orchestrator."""

    device_id: int
    name: str
    total_memory_mb: float
    nvlink_peers: List[int] = field(default_factory=list)


class MultiGPUOrchestrator:
    """Orchestrates workloads across multiple GPUs with NVLink awareness.

    Supports three parallelism strategies:

    * **Data parallelism** -- replicate the kernel and split input batches.
    * **Tensor parallelism** -- shard weight matrices across GPUs.
    * **Pipeline parallelism** -- stage-wise execution with micro-batch
      interleaving to hide pipeline bubbles.

    All operations are simulated with realistic timing derived from A100
    hardware specifications.
    """

    # NVLink 3.0 bidirectional bandwidth (A100 SXM)
    NVLINK_BW_GB_S: float = 600.0
    # PCIe Gen4 x16 bandwidth (fallback)
    PCIE_BW_GB_S: float = 31.5

    def __init__(self, device_ids: Optional[List[int]] = None) -> None:
        """Initialise the multi-GPU orchestrator.

        Auto-detects GPUs via ``nvidia-smi`` if *device_ids* is not provided.
        Probes NVLink topology for peer bandwidth estimation.

        Args:
            device_ids: Explicit list of GPU ordinals.  When *None*,
                auto-detection is attempted (falls back to ``[0, 1]``).
        """
        if device_ids is None:
            n_gpus = self._detect_gpu_count()
            device_ids = list(range(n_gpus))

        self._device_ids = device_ids
        self._devices: Dict[int, _DeviceSlot] = {}
        self._nvlink_topology: Dict[Tuple[int, int], bool] = {}

        for did in device_ids:
            self._devices[did] = _DeviceSlot(
                device_id=did,
                name=f"NVIDIA A100-SXM4-80GB (simulated, GPU {did})",
                total_memory_mb=81920.0,
            )

        self._detect_nvlink()
        log.info(
            "MultiGPUOrchestrator: %d GPUs %s", len(device_ids), device_ids
        )

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_gpu_count() -> int:
        """Detect the number of GPUs via ``nvidia-smi``.

        Returns:
            Number of detected GPUs, or 2 as a fallback.
        """
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
                count = len(lines)
                if count > 0:
                    log.info("Detected %d GPUs via nvidia-smi", count)
                    return count
        except Exception as exc:
            log.warning("GPU detection failed (%s); defaulting to 2", exc)
        return 2

    def _detect_nvlink(self) -> None:
        """Probe NVLink topology between managed GPUs.

        Attempts to parse ``nvidia-smi topo -m`` output.  Falls back to
        assuming full NVLink mesh for all device pairs.
        """
        try:
            result = subprocess.run(
                ["nvidia-smi", "topo", "-m"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and "NV" in result.stdout:
                lines = result.stdout.strip().splitlines()
                # Parse the matrix: rows starting with "GPU" contain topology
                gpu_lines = [
                    l for l in lines if l.strip().startswith("GPU")
                ]
                for line in gpu_lines:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    src_str = parts[0].replace("GPU", "")
                    src_id = int(src_str)
                    for col_idx, token in enumerate(parts[1:], start=0):
                        if "NV" in token and col_idx < len(self._device_ids):
                            dst_id = col_idx
                            if src_id != dst_id:
                                self._nvlink_topology[(src_id, dst_id)] = True
                                if src_id in self._devices:
                                    if dst_id not in self._devices[src_id].nvlink_peers:
                                        self._devices[src_id].nvlink_peers.append(dst_id)
                log.info("NVLink topology detected from nvidia-smi")
                return
        except Exception as exc:
            log.debug("nvidia-smi topo failed (%s); simulating NVLink mesh", exc)

        # Fallback: assume full NVLink mesh
        for i in self._device_ids:
            for j in self._device_ids:
                if i != j:
                    self._nvlink_topology[(i, j)] = True
                    self._devices[i].nvlink_peers.append(j)
        log.info("Simulated full NVLink mesh for %d GPUs", len(self._device_ids))

    def _peer_bandwidth_gb_s(self, src: int, dst: int) -> float:
        """Return the estimated bandwidth between two devices in GB/s."""
        if (src, dst) in self._nvlink_topology:
            return self.NVLINK_BW_GB_S
        return self.PCIE_BW_GB_S

    # ------------------------------------------------------------------
    # Data parallelism
    # ------------------------------------------------------------------

    def data_parallel_dispatch(
        self,
        inputs: List[Any],
        kernel: str,
    ) -> Dict[str, Any]:
        """Execute a kernel in data-parallel mode across all GPUs.

        Splits the input list evenly across devices, simulates parallel
        execution, and gathers the results.

        Args:
            inputs: List of input items (or batches) to distribute.
            kernel: Kernel name (for logging and result tagging).

        Returns:
            A dict containing per-device results, timing, and aggregate
            statistics.
        """
        n_gpus = len(self._device_ids)
        if n_gpus == 0:
            return {"error": "No GPUs available"}

        # Split inputs across GPUs
        chunk_size = math.ceil(len(inputs) / n_gpus)
        chunks: List[List[Any]] = []
        for i in range(n_gpus):
            start = i * chunk_size
            end = min(start + chunk_size, len(inputs))
            chunks.append(inputs[start:end])

        # Simulate parallel execution -- each GPU processes its chunk
        # Execution time dominated by the slowest GPU
        per_device_results: List[Dict[str, Any]] = []
        max_time_us = 0.0

        for idx, device_id in enumerate(self._device_ids):
            chunk = chunks[idx] if idx < len(chunks) else []
            n_items = len(chunk)

            # Simulate: ~0.5 us per item + base kernel launch overhead
            exec_time_us = 3.5 + n_items * 0.5 + random.uniform(0.0, 0.3)
            max_time_us = max(max_time_us, exec_time_us)

            per_device_results.append({
                "device_id": device_id,
                "items_processed": n_items,
                "exec_time_us": round(exec_time_us, 3),
                "kernel": kernel,
            })

        # All-reduce gradient synchronisation cost (simulated)
        # Ring all-reduce: 2 * (n-1)/n * data_size / bandwidth
        gradient_bytes = len(inputs) * 4096  # assume 4 KB per gradient element
        allreduce_time_us = self._ring_allreduce_time_us(gradient_bytes)

        total_time_us = max_time_us + allreduce_time_us

        result = {
            "strategy": "data_parallel",
            "kernel": kernel,
            "n_gpus": n_gpus,
            "total_inputs": len(inputs),
            "per_device": per_device_results,
            "compute_time_us": round(max_time_us, 3),
            "allreduce_time_us": round(allreduce_time_us, 3),
            "total_time_us": round(total_time_us, 3),
            "throughput_items_per_sec": round(
                len(inputs) / (total_time_us * 1e-6), 1
            ) if total_time_us > 0 else 0.0,
        }

        log.info(
            "Data-parallel '%s' on %d GPUs: %.1f us compute + %.1f us allreduce",
            kernel,
            n_gpus,
            max_time_us,
            allreduce_time_us,
        )
        return result

    # ------------------------------------------------------------------
    # Tensor parallelism
    # ------------------------------------------------------------------

    def tensor_parallel_dispatch(
        self,
        weight_shards: List[Any],
        input_data: Any,
    ) -> Dict[str, Any]:
        """Execute a tensor-parallel operation across GPUs.

        Each GPU holds a shard of the weight matrix and computes its
        partial result.  An all-reduce follows to combine partial sums.

        Args:
            weight_shards: Pre-sharded weight matrices, one per GPU.
            input_data: The input tensor (broadcast to all GPUs).

        Returns:
            A dict with per-shard timings and the all-reduce cost.
        """
        n_gpus = len(self._device_ids)
        if len(weight_shards) != n_gpus:
            log.warning(
                "weight_shards length (%d) != n_gpus (%d); adjusting",
                len(weight_shards),
                n_gpus,
            )

        shards_to_use = min(len(weight_shards), n_gpus)

        # Simulate per-shard matmul
        shard_results: List[Dict[str, Any]] = []
        max_compute_us = 0.0
        for i in range(shards_to_use):
            device_id = self._device_ids[i]
            # Simulate: compute is proportional to shard size
            shard_size = len(str(weight_shards[i]))  # proxy for size
            compute_us = 2.0 + shard_size * 0.001 + random.uniform(0.0, 0.2)
            max_compute_us = max(max_compute_us, compute_us)
            shard_results.append({
                "device_id": device_id,
                "shard_index": i,
                "compute_us": round(compute_us, 3),
            })

        # All-reduce to combine partial results
        # For tensor parallelism the communicated data is the partial output
        output_bytes = 4096 * 4  # assume output vector * FP32
        allreduce_us = self._ring_allreduce_time_us(output_bytes)

        total_us = max_compute_us + allreduce_us

        result = {
            "strategy": "tensor_parallel",
            "n_gpus": shards_to_use,
            "shard_results": shard_results,
            "compute_time_us": round(max_compute_us, 3),
            "allreduce_time_us": round(allreduce_us, 3),
            "total_time_us": round(total_us, 3),
        }

        log.info(
            "Tensor-parallel on %d GPUs: %.1f us compute + %.1f us allreduce",
            shards_to_use,
            max_compute_us,
            allreduce_us,
        )
        return result

    # ------------------------------------------------------------------
    # Pipeline parallelism
    # ------------------------------------------------------------------

    def pipeline_parallel(
        self,
        stages: List[str],
        input_data: Any,
        micro_batches: int = 4,
    ) -> Dict[str, Any]:
        """Execute pipeline-parallel inference with micro-batch interleaving.

        Assigns one pipeline stage per GPU.  Micro-batches are fed through
        the pipeline with 1F1B (one-forward-one-backward) scheduling to
        minimise the pipeline bubble.

        Args:
            stages: Names of pipeline stages (one per GPU).
            input_data: The full input batch.
            micro_batches: Number of micro-batches to split the input into.

        Returns:
            A dict with the schedule trace, bubble analysis, and timing.
        """
        n_stages = min(len(stages), len(self._device_ids))
        if n_stages == 0:
            return {"error": "No stages or GPUs available"}

        # Time per micro-batch per stage (simulated)
        stage_time_us = 10.0 + random.uniform(0.0, 1.0)

        # Build the 1F1B schedule trace
        # Warmup: stages fill one at a time
        # Steady state: each timestep one micro-batch exits
        schedule: List[Dict[str, Any]] = []
        total_slots = n_stages + micro_batches - 1  # total timesteps

        for t in range(total_slots):
            for s in range(n_stages):
                mb = t - s  # micro-batch index at stage s at timestep t
                if 0 <= mb < micro_batches:
                    schedule.append({
                        "timestep": t,
                        "stage": stages[s] if s < len(stages) else f"stage_{s}",
                        "device_id": self._device_ids[s],
                        "micro_batch": mb,
                        "time_us": round(stage_time_us, 3),
                    })

        total_time_us = total_slots * stage_time_us

        # Pipeline bubble: idle slots / total slots
        active_slots = len(schedule)
        total_possible = total_slots * n_stages
        bubble_fraction = 1.0 - (active_slots / total_possible) if total_possible > 0 else 0.0

        # Inter-stage transfer cost (per micro-batch, per stage boundary)
        activation_bytes = 4096 * 2  # assume small activation tensor in FP16
        per_transfer_us = (activation_bytes / (self.NVLINK_BW_GB_S * 1e9)) * 1e6
        total_transfer_us = per_transfer_us * (n_stages - 1) * micro_batches

        total_time_with_comm = total_time_us + total_transfer_us

        # Ideal time (fully parallelised, no bubble)
        ideal_time_us = micro_batches * stage_time_us

        result = {
            "strategy": "pipeline_parallel",
            "n_stages": n_stages,
            "micro_batches": micro_batches,
            "stage_names": stages[:n_stages],
            "schedule_trace": schedule,
            "stage_time_us": round(stage_time_us, 3),
            "compute_time_us": round(total_time_us, 3),
            "communication_time_us": round(total_transfer_us, 3),
            "total_time_us": round(total_time_with_comm, 3),
            "ideal_time_us": round(ideal_time_us, 3),
            "bubble_fraction": round(bubble_fraction, 4),
            "pipeline_efficiency": round(1.0 - bubble_fraction, 4),
        }

        log.info(
            "Pipeline-parallel %d stages x %d micro-batches: "
            "%.1f us total, %.1f%% bubble",
            n_stages,
            micro_batches,
            total_time_with_comm,
            bubble_fraction * 100,
        )
        return result

    # ------------------------------------------------------------------
    # Collective operations
    # ------------------------------------------------------------------

    def all_reduce(
        self,
        tensors: List[Any],
        op: str = "sum",
    ) -> Dict[str, Any]:
        """Simulate an NVLink ring all-reduce across all GPUs.

        The ring all-reduce algorithm transfers ``2 * (n-1)/n * data_size``
        bytes in total, achieving near-optimal bandwidth utilisation.

        Args:
            tensors: One tensor per GPU to reduce.  The size of the first
                tensor is used to estimate transfer volume.
            op: Reduction operation (``sum``, ``max``, ``min``, ``avg``).

        Returns:
            A dict with timing, bandwidth, and algorithm details.
        """
        n_gpus = len(self._device_ids)

        if not tensors:
            return {"error": "No tensors provided"}

        # Estimate data size from first tensor
        first = tensors[0]
        if hasattr(first, "__len__"):
            n_elements = len(first)
        elif isinstance(first, (int, float)):
            n_elements = 1
        else:
            n_elements = len(str(first)) // 4  # rough proxy

        bytes_per_elem = 4  # assume FP32
        data_bytes = n_elements * bytes_per_elem

        allreduce_us = self._ring_allreduce_time_us(data_bytes)

        # Effective algorithm bandwidth
        total_transferred = 2.0 * (n_gpus - 1) / n_gpus * data_bytes
        algo_bw_gb_s = (
            (total_transferred / (allreduce_us * 1e-6) / 1e9)
            if allreduce_us > 0
            else 0.0
        )

        result = {
            "operation": op,
            "n_gpus": n_gpus,
            "data_bytes": data_bytes,
            "total_transferred_bytes": int(total_transferred),
            "algorithm": "ring_allreduce",
            "time_us": round(allreduce_us, 3),
            "algorithm_bandwidth_gb_s": round(algo_bw_gb_s, 2),
            "bus_bandwidth_gb_s": self.NVLINK_BW_GB_S,
        }

        log.info(
            "All-reduce (%s) %d bytes across %d GPUs: %.1f us, %.1f GB/s algo BW",
            op,
            data_bytes,
            n_gpus,
            allreduce_us,
            algo_bw_gb_s,
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ring_allreduce_time_us(self, data_bytes: int) -> float:
        """Estimate ring all-reduce time in microseconds.

        Uses the standard formula: ``2 * (n-1)/n * size / bandwidth``,
        plus a latency term for ring setup.

        Args:
            data_bytes: Payload size in bytes.

        Returns:
            Estimated time in microseconds.
        """
        n = len(self._device_ids)
        if n <= 1:
            return 0.0

        # Use the slowest link in the ring as the bottleneck
        # (for a homogeneous NVLink mesh, this is just NVLink BW)
        min_bw = self.NVLINK_BW_GB_S
        for i in range(n):
            j = (i + 1) % n
            bw = self._peer_bandwidth_gb_s(self._device_ids[i], self._device_ids[j])
            min_bw = min(min_bw, bw)

        transfer_bytes = 2.0 * (n - 1) / n * data_bytes
        transfer_time_s = transfer_bytes / (min_bw * 1e9)
        transfer_time_us = transfer_time_s * 1e6

        # Ring latency: ~5 us per hop in the ring
        latency_us = n * 5.0

        return transfer_time_us + latency_us
