"""CUDA kernel compilation, launch, profiling, and auto-tuning infrastructure."""
from __future__ import annotations

import hashlib
import logging
import math
import random
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("orchestra.cuda.kernel_manager")

__all__ = [
    "CUDAKernelManager",
    "GPUDevice",
    "CompiledKernel",
    "KernelResult",
    "KernelProfile",
    "OccupancyReport",
    "AutoTuneResult",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GPUDevice:
    """Represents a single GPU device and its hardware capabilities."""

    index: int
    name: str
    total_memory_mb: float
    free_memory_mb: float
    compute_capability: str
    sm_clock_mhz: float
    mem_clock_mhz: float
    temperature_c: float
    power_draw_w: float
    utilization_pct: float
    memory_bus_width: int
    n_sms: int = 108
    max_threads_per_sm: int = 2048
    max_registers_per_sm: int = 65536
    max_shared_mem_per_sm_bytes: int = 167936  # 164 KB for A100
    max_threads_per_block: int = 1024
    warp_size: int = 32


@dataclass
class CompiledKernel:
    """A compiled CUDA kernel ready for launch."""

    name: str
    source_hash: str
    ptx: str
    register_usage: int
    shared_mem_static_bytes: int
    shared_mem_dynamic_bytes: int
    max_threads_per_block: int
    compile_time_ms: float
    target_arch: str


@dataclass
class KernelResult:
    """Result of a single kernel launch."""

    name: str
    grid: Tuple[int, ...]
    block: Tuple[int, ...]
    elapsed_us: float
    stream: int
    success: bool
    error: Optional[str] = None


@dataclass
class KernelProfile:
    """Detailed profiling statistics gathered over multiple kernel runs."""

    kernel_name: str
    n_runs: int
    latency_min_us: float
    latency_mean_us: float
    latency_p50_us: float
    latency_p99_us: float
    latency_max_us: float
    throughput_gflops: float
    memory_bandwidth_gb_s: float
    achieved_occupancy: float
    theoretical_occupancy: float
    l1_hit_rate: float
    l2_hit_rate: float
    registers_per_thread: int
    shared_mem_bytes: int
    grid: Tuple[int, ...]
    block: Tuple[int, ...]


@dataclass
class OccupancyReport:
    """GPU occupancy analysis for a kernel configuration."""

    achieved_occupancy: float
    theoretical_occupancy: float
    active_warps_per_sm: int
    max_warps_per_sm: int
    limiting_factor: str
    suggested_block_size: int
    register_limit_warps: int
    shared_mem_limit_warps: int
    block_size_limit_warps: int
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AutoTuneResult:
    """Result of auto-tuning a kernel across multiple configurations."""

    kernel_name: str
    optimal_block_size: int
    optimal_grid_size: Tuple[int, ...]
    optimal_elapsed_us: float
    optimal_occupancy: float
    configs_tested: int
    all_results: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class CUDAKernelManager:
    """Manages CUDA kernel compilation, launch, profiling, and auto-tuning.

    All operations are simulated with realistic calculations so the manager
    works without an actual CUDA runtime or GPU present.
    """

    def __init__(self, device_id: int = 0) -> None:
        """Initialise the kernel manager for a specific GPU device.

        Args:
            device_id: Ordinal index of the target GPU.
        """
        self._device_id = device_id
        self._device: Optional[GPUDevice] = None
        self._compiled_cache: Dict[str, CompiledKernel] = {}
        self._stream_counter: int = 0
        log.info("CUDAKernelManager initialised for device %d", device_id)

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    def get_device_info(self) -> GPUDevice:
        """Query the GPU for hardware information.

        Uses ``nvidia-smi`` when available; falls back to a simulated
        NVIDIA A100-SXM4-80GB specification otherwise.

        Returns:
            A populated :class:`GPUDevice` instance.
        """
        if self._device is not None:
            return self._device

        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,memory.free,"
                    "compute_cap,clocks.sm,clocks.mem,temperature.gpu,"
                    "power.draw,utilization.gpu,memory.bus_width",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr)

            lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            if self._device_id >= len(lines):
                raise IndexError(
                    f"Device {self._device_id} not found ({len(lines)} GPUs detected)"
                )

            parts = [p.strip() for p in lines[self._device_id].split(",")]
            self._device = GPUDevice(
                index=int(parts[0]),
                name=parts[1],
                total_memory_mb=float(parts[2]),
                free_memory_mb=float(parts[3]),
                compute_capability=parts[4],
                sm_clock_mhz=float(parts[5]),
                mem_clock_mhz=float(parts[6]),
                temperature_c=float(parts[7]),
                power_draw_w=float(parts[8]),
                utilization_pct=float(parts[9]),
                memory_bus_width=int(parts[10]),
            )
            log.info("Detected GPU: %s", self._device.name)

        except Exception as exc:
            log.warning(
                "nvidia-smi unavailable (%s); using simulated A100-SXM4-80GB", exc
            )
            self._device = GPUDevice(
                index=self._device_id,
                name="NVIDIA A100-SXM4-80GB (simulated)",
                total_memory_mb=81920.0,
                free_memory_mb=79000.0,
                compute_capability="8.0",
                sm_clock_mhz=1410.0,
                mem_clock_mhz=1215.0,
                temperature_c=34.0,
                power_draw_w=52.0,
                utilization_pct=0.0,
                memory_bus_width=5120,
                n_sms=108,
                max_threads_per_sm=2048,
                max_registers_per_sm=65536,
                max_shared_mem_per_sm_bytes=167936,
            )

        return self._device

    # ------------------------------------------------------------------
    # Compilation
    # ------------------------------------------------------------------

    def compile_kernel(
        self,
        name: str,
        source: str,
        *,
        target_arch: str = "sm_80",
        extra_flags: Optional[List[str]] = None,
    ) -> CompiledKernel:
        """Compile a CUDA kernel from source into PTX.

        The compilation is simulated: a deterministic PTX string is generated
        from the source hash, and register/shared-memory usage is estimated
        from simple source heuristics.

        Args:
            name: Human-readable kernel name.
            source: CUDA C/C++ source code.
            target_arch: Target GPU architecture (e.g. ``sm_80``).
            extra_flags: Additional compiler flags (informational only).

        Returns:
            A :class:`CompiledKernel` with realistic PTX and resource estimates.
        """
        src_hash = hashlib.sha256(source.encode()).hexdigest()[:16]

        if src_hash in self._compiled_cache:
            log.debug("Cache hit for kernel '%s' (hash=%s)", name, src_hash)
            return self._compiled_cache[src_hash]

        t0 = time.monotonic()

        # Heuristic register estimation: count unique variable-like tokens
        tokens = set(source.replace("\n", " ").split())
        float_ops = sum(1 for t in tokens if t in {"float", "double", "half", "__half", "float4"})
        int_ops = sum(1 for t in tokens if t in {"int", "unsigned", "long", "size_t"})
        base_regs = 16
        register_usage = min(255, base_regs + float_ops * 4 + int_ops * 2)

        # Shared memory estimation from __shared__ declarations
        shared_decls = source.count("__shared__")
        shared_mem_static = shared_decls * 4096  # assume 4 KB per declaration
        shared_mem_dynamic = 0
        if "extern __shared__" in source:
            shared_mem_dynamic = 16384  # 16 KB default dynamic

        # Calculate max threads per block based on register pressure
        device = self.get_device_info()
        regs_per_warp = register_usage * device.warp_size
        if regs_per_warp > 0:
            warps_per_sm = min(
                device.max_registers_per_sm // regs_per_warp,
                device.max_threads_per_sm // device.warp_size,
            )
        else:
            warps_per_sm = device.max_threads_per_sm // device.warp_size
        max_tpb = min(device.max_threads_per_block, warps_per_sm * device.warp_size)

        # Generate realistic-looking PTX
        ptx_lines = [
            f"// Generated PTX for '{name}' targeting {target_arch}",
            f"// Source hash: {src_hash}",
            f".version 7.8",
            f".target {target_arch}",
            f".address_size 64",
            f"",
            f".visible .entry {name}(",
            f"    .param .u64 {name}_param_0,",
            f"    .param .u64 {name}_param_1,",
            f"    .param .u32 {name}_param_2",
            f")",
            f"{{",
            f"    .reg .pred   %p<4>;",
            f"    .reg .f32    %f<{register_usage}>;",
            f"    .reg .b32    %r<{register_usage}>;",
            f"    .reg .b64    %rd<16>;",
            f"",
            f"    ld.param.u64    %rd0, [{name}_param_0];",
            f"    ld.param.u64    %rd1, [{name}_param_1];",
            f"    ld.param.u32    %r0, [{name}_param_2];",
            f"",
            f"    mov.u32         %r1, %ctaid.x;",
            f"    mov.u32         %r2, %ntid.x;",
            f"    mov.u32         %r3, %tid.x;",
            f"    mad.lo.s32      %r4, %r1, %r2, %r3;",
            f"",
            f"    setp.ge.s32     %p1, %r4, %r0;",
            f"    @%p1 bra        $L__exit;",
            f"",
            f"    // Kernel body ({len(source)} chars source)",
            f"    cvt.u64.u32     %rd2, %r4;",
            f"    shl.b64         %rd3, %rd2, 2;",
            f"    add.u64         %rd4, %rd0, %rd3;",
            f"    ld.global.f32   %f1, [%rd4];",
            f"    add.f32         %f2, %f1, %f1;",
            f"    add.u64         %rd5, %rd1, %rd3;",
            f"    st.global.f32   [%rd5], %f2;",
            f"",
            f"$L__exit:",
            f"    ret;",
            f"}}",
        ]
        ptx = "\n".join(ptx_lines)

        compile_time_ms = (time.monotonic() - t0) * 1000 + random.uniform(0.5, 5.0)

        kernel = CompiledKernel(
            name=name,
            source_hash=src_hash,
            ptx=ptx,
            register_usage=register_usage,
            shared_mem_static_bytes=shared_mem_static,
            shared_mem_dynamic_bytes=shared_mem_dynamic,
            max_threads_per_block=max_tpb,
            compile_time_ms=round(compile_time_ms, 3),
            target_arch=target_arch,
        )

        self._compiled_cache[src_hash] = kernel
        log.info(
            "Compiled kernel '%s': %d regs, %d B smem, max %d tpb in %.2f ms",
            name,
            register_usage,
            shared_mem_static + shared_mem_dynamic,
            max_tpb,
            compile_time_ms,
        )
        return kernel

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    def launch_kernel(
        self,
        compiled: CompiledKernel,
        grid: Tuple[int, ...],
        block: Tuple[int, ...],
        *,
        shared_mem_bytes: int = 0,
        stream: Optional[int] = None,
    ) -> KernelResult:
        """Launch a compiled kernel on the GPU.

        Validates grid/block dimensions against device limits and returns
        a simulated :class:`KernelResult` with realistic timing.

        Args:
            compiled: The compiled kernel to launch.
            grid: Grid dimensions ``(gx,)`` or ``(gx, gy)`` or ``(gx, gy, gz)``.
            block: Block dimensions ``(bx,)`` or ``(bx, by)`` or ``(bx, by, bz)``.
            shared_mem_bytes: Dynamic shared memory to allocate per block.
            stream: CUDA stream ordinal; auto-assigned if *None*.

        Returns:
            A :class:`KernelResult` describing the launch outcome.
        """
        device = self.get_device_info()

        # Pad to 3-D
        grid3 = (grid + (1, 1))[:3]
        block3 = (block + (1, 1))[:3]

        threads_per_block = block3[0] * block3[1] * block3[2]
        total_blocks = grid3[0] * grid3[1] * grid3[2]

        # Validate dimensions
        if threads_per_block > device.max_threads_per_block:
            msg = (
                f"Block size {threads_per_block} exceeds device maximum "
                f"{device.max_threads_per_block}"
            )
            log.error(msg)
            return KernelResult(
                name=compiled.name,
                grid=grid,
                block=block,
                elapsed_us=0.0,
                stream=stream or 0,
                success=False,
                error=msg,
            )

        if any(d <= 0 for d in grid3) or any(d <= 0 for d in block3):
            msg = "Grid and block dimensions must be positive"
            log.error(msg)
            return KernelResult(
                name=compiled.name,
                grid=grid,
                block=block,
                elapsed_us=0.0,
                stream=stream or 0,
                success=False,
                error=msg,
            )

        total_smem = (
            compiled.shared_mem_static_bytes
            + compiled.shared_mem_dynamic_bytes
            + shared_mem_bytes
        )
        if total_smem > device.max_shared_mem_per_sm_bytes:
            msg = (
                f"Shared memory request {total_smem} B exceeds SM limit "
                f"{device.max_shared_mem_per_sm_bytes} B"
            )
            log.error(msg)
            return KernelResult(
                name=compiled.name,
                grid=grid,
                block=block,
                elapsed_us=0.0,
                stream=stream or 0,
                success=False,
                error=msg,
            )

        # Assign stream
        if stream is None:
            self._stream_counter += 1
            stream = self._stream_counter

        # Simulate execution time
        # Estimate: each block takes ~1 us on average, blocks run across SMs
        waves = math.ceil(total_blocks / device.n_sms)
        base_time_us = waves * 1.0  # 1 us per wave
        # Add register-pressure overhead
        reg_overhead = compiled.register_usage / 255.0
        elapsed_us = base_time_us * (1.0 + reg_overhead) + random.uniform(0.1, 0.5)
        elapsed_us = round(elapsed_us, 3)

        log.info(
            "Launched '%s' grid=%s block=%s => %.1f us (stream %d)",
            compiled.name,
            grid,
            block,
            elapsed_us,
            stream,
        )

        return KernelResult(
            name=compiled.name,
            grid=grid,
            block=block,
            elapsed_us=elapsed_us,
            stream=stream,
            success=True,
        )

    # ------------------------------------------------------------------
    # Profiling
    # ------------------------------------------------------------------

    def profile_kernel(
        self,
        compiled: CompiledKernel,
        grid: Tuple[int, ...],
        block: Tuple[int, ...],
        *,
        n_runs: int = 100,
        data_bytes: int = 0,
        flops: float = 0.0,
    ) -> KernelProfile:
        """Profile a kernel over multiple simulated runs.

        Gathers latency statistics, estimates throughput, memory bandwidth,
        and occupancy metrics.

        Args:
            compiled: The compiled kernel to profile.
            grid: Grid dimensions.
            block: Block dimensions.
            n_runs: Number of profiling iterations.
            data_bytes: Total bytes moved (for bandwidth calculation).
            flops: Total floating-point operations (for throughput).

        Returns:
            A :class:`KernelProfile` with detailed statistics.
        """
        device = self.get_device_info()

        # Run multiple simulated launches
        latencies: List[float] = []
        for _ in range(n_runs):
            result = self.launch_kernel(compiled, grid, block)
            latencies.append(result.elapsed_us)

        latencies.sort()
        mean_us = sum(latencies) / len(latencies)
        p50_idx = int(len(latencies) * 0.50)
        p99_idx = min(int(len(latencies) * 0.99), len(latencies) - 1)

        # Throughput
        mean_s = mean_us * 1e-6
        throughput_gflops = (flops / mean_s / 1e9) if (flops > 0 and mean_s > 0) else 0.0

        # Memory bandwidth
        bandwidth_gb_s = (data_bytes / mean_s / 1e9) if (data_bytes > 0 and mean_s > 0) else 0.0

        # Occupancy
        occ = self.optimize_occupancy(
            compiled.register_usage,
            compiled.shared_mem_static_bytes + compiled.shared_mem_dynamic_bytes,
            block[0] if len(block) >= 1 else 256,
        )

        # Cache hit rate simulation
        l1_hit = min(0.98, 0.70 + random.uniform(0.0, 0.15))
        l2_hit = min(0.99, 0.80 + random.uniform(0.0, 0.10))

        profile = KernelProfile(
            kernel_name=compiled.name,
            n_runs=n_runs,
            latency_min_us=round(latencies[0], 3),
            latency_mean_us=round(mean_us, 3),
            latency_p50_us=round(latencies[p50_idx], 3),
            latency_p99_us=round(latencies[p99_idx], 3),
            latency_max_us=round(latencies[-1], 3),
            throughput_gflops=round(throughput_gflops, 2),
            memory_bandwidth_gb_s=round(bandwidth_gb_s, 2),
            achieved_occupancy=occ.achieved_occupancy,
            theoretical_occupancy=occ.theoretical_occupancy,
            l1_hit_rate=round(l1_hit, 4),
            l2_hit_rate=round(l2_hit, 4),
            registers_per_thread=compiled.register_usage,
            shared_mem_bytes=compiled.shared_mem_static_bytes + compiled.shared_mem_dynamic_bytes,
            grid=grid,
            block=block,
        )
        log.info(
            "Profiled '%s' (%d runs): mean=%.1f us, throughput=%.1f GFLOPS, occ=%.1f%%",
            compiled.name,
            n_runs,
            mean_us,
            throughput_gflops,
            occ.achieved_occupancy * 100,
        )
        return profile

    # ------------------------------------------------------------------
    # Occupancy
    # ------------------------------------------------------------------

    def optimize_occupancy(
        self,
        registers_per_thread: int,
        shared_mem_per_block: int,
        block_size: int,
    ) -> OccupancyReport:
        """Analyse GPU occupancy for a given kernel configuration.

        Uses A100 hardware specifications to determine occupancy limits
        and the primary bottleneck.

        Args:
            registers_per_thread: Number of registers each thread consumes.
            shared_mem_per_block: Total shared memory per block (bytes).
            block_size: Number of threads per block.

        Returns:
            An :class:`OccupancyReport` with occupancy breakdown and
            an optimal block-size suggestion.
        """
        device = self.get_device_info()

        max_warps_per_sm = device.max_threads_per_sm // device.warp_size  # 64 for A100

        # --- Register limit ---
        regs_per_warp = registers_per_thread * device.warp_size
        if regs_per_warp > 0:
            register_limit_warps = min(
                max_warps_per_sm,
                device.max_registers_per_sm // regs_per_warp,
            )
        else:
            register_limit_warps = max_warps_per_sm

        # --- Shared memory limit ---
        if shared_mem_per_block > 0:
            warps_per_block = math.ceil(block_size / device.warp_size)
            blocks_by_smem = device.max_shared_mem_per_sm_bytes // shared_mem_per_block
            shared_mem_limit_warps = min(
                max_warps_per_sm,
                blocks_by_smem * warps_per_block,
            )
        else:
            shared_mem_limit_warps = max_warps_per_sm

        # --- Block size limit ---
        warps_in_block = math.ceil(block_size / device.warp_size)
        if warps_in_block > 0:
            blocks_per_sm = max_warps_per_sm // warps_in_block
            block_size_limit_warps = blocks_per_sm * warps_in_block
        else:
            block_size_limit_warps = 0

        # Active warps is the minimum of all three limits
        active_warps = min(register_limit_warps, shared_mem_limit_warps, block_size_limit_warps)
        theoretical_occupancy = active_warps / max_warps_per_sm if max_warps_per_sm > 0 else 0.0
        # Achieved is slightly lower due to scheduling overhead
        achieved_occupancy = theoretical_occupancy * random.uniform(0.90, 0.98)

        # Determine limiting factor
        limits = {
            "registers": register_limit_warps,
            "shared_memory": shared_mem_limit_warps,
            "block_size": block_size_limit_warps,
        }
        limiting_factor = min(limits, key=limits.get)

        # Suggest optimal block size (multiple of warp size, maximise warps/SM)
        best_block = block_size
        best_warps = active_warps
        for candidate in range(device.warp_size, device.max_threads_per_block + 1, device.warp_size):
            w_in_b = candidate // device.warp_size
            if w_in_b == 0:
                continue
            b_per_sm = min(
                max_warps_per_sm // w_in_b,
                (device.max_shared_mem_per_sm_bytes // shared_mem_per_block)
                if shared_mem_per_block > 0
                else max_warps_per_sm,
                register_limit_warps // w_in_b if w_in_b > 0 else max_warps_per_sm,
            )
            candidate_warps = b_per_sm * w_in_b
            if candidate_warps > best_warps:
                best_warps = candidate_warps
                best_block = candidate

        report = OccupancyReport(
            achieved_occupancy=round(achieved_occupancy, 4),
            theoretical_occupancy=round(theoretical_occupancy, 4),
            active_warps_per_sm=active_warps,
            max_warps_per_sm=max_warps_per_sm,
            limiting_factor=limiting_factor,
            suggested_block_size=best_block,
            register_limit_warps=register_limit_warps,
            shared_mem_limit_warps=shared_mem_limit_warps,
            block_size_limit_warps=block_size_limit_warps,
            details={
                "registers_per_thread": registers_per_thread,
                "shared_mem_per_block": shared_mem_per_block,
                "block_size": block_size,
                "device": device.name,
            },
        )
        log.debug(
            "Occupancy for block_size=%d: %.1f%% (limited by %s)",
            block_size,
            theoretical_occupancy * 100,
            limiting_factor,
        )
        return report

    # ------------------------------------------------------------------
    # Auto-tune
    # ------------------------------------------------------------------

    def auto_tune(
        self,
        name: str,
        source: str,
        total_threads: int,
        *,
        block_sizes: Optional[List[int]] = None,
        n_profile_runs: int = 20,
        data_bytes: int = 0,
        flops: float = 0.0,
    ) -> AutoTuneResult:
        """Auto-tune a kernel by sweeping block sizes and profiling each.

        Args:
            name: Kernel name.
            source: Kernel source code.
            total_threads: Total number of threads to launch.
            block_sizes: Candidate block sizes to test. Defaults to
                ``[32, 64, 128, 256, 512, 1024]``.
            n_profile_runs: Profiling iterations per configuration.
            data_bytes: Bytes moved per launch (for bandwidth).
            flops: FLOPs per launch (for throughput).

        Returns:
            An :class:`AutoTuneResult` with the optimal configuration.
        """
        if block_sizes is None:
            block_sizes = [32, 64, 128, 256, 512, 1024]

        compiled = self.compile_kernel(name, source)
        all_results: List[Dict[str, Any]] = []
        best_time = float("inf")
        best_block = block_sizes[0]
        best_grid: Tuple[int, ...] = (1,)
        best_occ = 0.0

        for bs in block_sizes:
            if bs > compiled.max_threads_per_block:
                continue

            grid_x = math.ceil(total_threads / bs)
            grid = (grid_x,)
            block = (bs,)

            profile = self.profile_kernel(
                compiled,
                grid,
                block,
                n_runs=n_profile_runs,
                data_bytes=data_bytes,
                flops=flops,
            )

            entry = {
                "block_size": bs,
                "grid": grid,
                "mean_us": profile.latency_mean_us,
                "p99_us": profile.latency_p99_us,
                "occupancy": profile.achieved_occupancy,
                "throughput_gflops": profile.throughput_gflops,
                "bandwidth_gb_s": profile.memory_bandwidth_gb_s,
            }
            all_results.append(entry)

            if profile.latency_mean_us < best_time:
                best_time = profile.latency_mean_us
                best_block = bs
                best_grid = grid
                best_occ = profile.achieved_occupancy

        result = AutoTuneResult(
            kernel_name=name,
            optimal_block_size=best_block,
            optimal_grid_size=best_grid,
            optimal_elapsed_us=round(best_time, 3),
            optimal_occupancy=round(best_occ, 4),
            configs_tested=len(all_results),
            all_results=all_results,
        )
        log.info(
            "Auto-tuned '%s': optimal block=%d, grid=%s, time=%.1f us, occ=%.1f%%",
            name,
            best_block,
            best_grid,
            best_time,
            best_occ * 100,
        )
        return result
