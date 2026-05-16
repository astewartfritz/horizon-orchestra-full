"""Tests for CUDA kernel infrastructure.

All tests run offline — nvidia-smi calls are mocked.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock


# Bootstrap: load modules directly to avoid circular __init__ import
def _load_module(dotted_name: str, rel_path: str):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(base, rel_path)
    spec = importlib.util.spec_from_file_location(dotted_name, full_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load in dependency order — kernel_manager and memory_manager have no
# internal cross-imports; multi_gpu is also standalone.  The kernel
# sub-modules (attention, embedding, security_scan) are leaf modules.
kernel_manager = _load_module(
    "orchestra.cuda.kernel_manager",
    "orchestra/cuda/kernel_manager.py",
)
memory_manager = _load_module(
    "orchestra.cuda.memory_manager",
    "orchestra/cuda/memory_manager.py",
)
multi_gpu = _load_module(
    "orchestra.cuda.multi_gpu",
    "orchestra/cuda/multi_gpu.py",
)
attention = _load_module(
    "orchestra.cuda.kernels.attention",
    "orchestra/cuda/kernels/attention.py",
)
embedding = _load_module(
    "orchestra.cuda.kernels.embedding",
    "orchestra/cuda/kernels/embedding.py",
)
security_scan = _load_module(
    "orchestra.cuda.kernels.security_scan",
    "orchestra/cuda/kernels/security_scan.py",
)

# Re-export for convenience
CUDAKernelManager = kernel_manager.CUDAKernelManager
GPUDevice = kernel_manager.GPUDevice
CompiledKernel = kernel_manager.CompiledKernel
KernelResult = kernel_manager.KernelResult
KernelProfile = kernel_manager.KernelProfile
OccupancyReport = kernel_manager.OccupancyReport
AutoTuneResult = kernel_manager.AutoTuneResult

GPUMemoryManager = memory_manager.GPUMemoryManager
GPUAllocation = memory_manager.GPUAllocation
MemoryStats = memory_manager.MemoryStats
UnifiedAllocation = memory_manager.UnifiedAllocation

MultiGPUOrchestrator = multi_gpu.MultiGPUOrchestrator

FlashAttentionKernel = attention.FlashAttentionKernel
FusedEmbeddingKernel = embedding.FusedEmbeddingKernel
SecurityScanKernel = security_scan.SecurityScanKernel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NVIDIA_SMI_CSV = (
    "0, NVIDIA A100-SXM4-80GB, 81920, 79000, 8.0, 1410, 1215, "
    "34, 52.0, 3, 5120"
)

NVIDIA_SMI_CSV_2GPU = (
    "0, NVIDIA A100-SXM4-80GB, 81920, 79000, 8.0, 1410, 1215, "
    "34, 52.0, 3, 5120\n"
    "1, NVIDIA A100-SXM4-80GB, 81920, 78500, 8.0, 1410, 1215, "
    "36, 55.0, 5, 5120"
)

SIMPLE_KERNEL_SRC = """\
__global__ void add_kernel(float *a, float *b, int n) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) b[idx] = a[idx] + a[idx];
}
"""

SHARED_MEM_KERNEL_SRC = """\
extern __shared__ float smem[];
__global__ void smem_kernel(float *a, float *b, int n) {
    __shared__ float local[1024];
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) {
        local[threadIdx.x] = a[idx];
        __syncthreads();
        b[idx] = local[threadIdx.x];
    }
}
"""


def _mock_nvidia_smi_success(csv_output=NVIDIA_SMI_CSV):
    """Return a mock subprocess.run that mimics a successful nvidia-smi call."""
    result = mock.MagicMock()
    result.returncode = 0
    result.stdout = csv_output
    result.stderr = ""
    return mock.patch("subprocess.run", return_value=result)


def _mock_nvidia_smi_failure():
    """Return a mock subprocess.run that mimics nvidia-smi not being found."""
    return mock.patch(
        "subprocess.run", side_effect=FileNotFoundError("nvidia-smi not found")
    )


# ===========================================================================
# TestKernelManager
# ===========================================================================


class TestKernelManager(unittest.TestCase):
    """Tests for CUDAKernelManager device detection, compilation, launch,
    profiling, occupancy analysis, and auto-tuning."""

    def test_device_detection(self):
        """Mock nvidia-smi subprocess, verify GPUDevice fields."""
        with _mock_nvidia_smi_success():
            mgr = CUDAKernelManager(device_id=0)
            dev = mgr.get_device_info()

        self.assertIsInstance(dev, GPUDevice)
        self.assertEqual(dev.index, 0)
        self.assertEqual(dev.name, "NVIDIA A100-SXM4-80GB")
        self.assertEqual(dev.total_memory_mb, 81920.0)
        self.assertEqual(dev.free_memory_mb, 79000.0)
        self.assertEqual(dev.compute_capability, "8.0")
        self.assertEqual(dev.sm_clock_mhz, 1410.0)
        self.assertEqual(dev.mem_clock_mhz, 1215.0)
        self.assertEqual(dev.temperature_c, 34.0)
        self.assertAlmostEqual(dev.power_draw_w, 52.0)
        self.assertEqual(dev.utilization_pct, 3.0)
        self.assertEqual(dev.memory_bus_width, 5120)

    def test_device_detection_fallback(self):
        """Mock nvidia-smi failure, verify simulated A100."""
        with _mock_nvidia_smi_failure():
            mgr = CUDAKernelManager(device_id=0)
            dev = mgr.get_device_info()

        self.assertIsInstance(dev, GPUDevice)
        self.assertIn("simulated", dev.name)
        self.assertEqual(dev.total_memory_mb, 81920.0)
        self.assertEqual(dev.compute_capability, "8.0")
        self.assertEqual(dev.n_sms, 108)
        self.assertEqual(dev.max_threads_per_sm, 2048)
        self.assertEqual(dev.max_registers_per_sm, 65536)
        self.assertEqual(dev.max_shared_mem_per_sm_bytes, 167936)

    def test_compile_kernel(self):
        """Compile a simple kernel, verify CompiledKernel fields."""
        with _mock_nvidia_smi_failure():
            mgr = CUDAKernelManager()
            ck = mgr.compile_kernel("add_kernel", SIMPLE_KERNEL_SRC)

        self.assertIsInstance(ck, CompiledKernel)
        self.assertEqual(ck.name, "add_kernel")
        self.assertEqual(ck.target_arch, "sm_80")
        self.assertTrue(len(ck.source_hash) > 0)
        self.assertIn("add_kernel", ck.ptx)
        self.assertIn(".target sm_80", ck.ptx)
        self.assertGreater(ck.register_usage, 0)
        self.assertGreaterEqual(ck.shared_mem_static_bytes, 0)
        self.assertGreater(ck.max_threads_per_block, 0)
        self.assertGreater(ck.compile_time_ms, 0.0)

    def test_compile_kernel_sm90(self):
        """Compile with sm_90 arch."""
        with _mock_nvidia_smi_failure():
            mgr = CUDAKernelManager()
            ck = mgr.compile_kernel(
                "add_kernel_90", SIMPLE_KERNEL_SRC, target_arch="sm_90"
            )

        self.assertEqual(ck.target_arch, "sm_90")
        self.assertIn(".target sm_90", ck.ptx)

    def test_launch_kernel(self):
        """Launch a compiled kernel, verify KernelResult."""
        with _mock_nvidia_smi_failure():
            mgr = CUDAKernelManager()
            ck = mgr.compile_kernel("add_kernel", SIMPLE_KERNEL_SRC)
            result = mgr.launch_kernel(ck, grid=(128,), block=(256,))

        self.assertIsInstance(result, KernelResult)
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(result.name, "add_kernel")
        self.assertEqual(result.grid, (128,))
        self.assertEqual(result.block, (256,))
        self.assertGreater(result.elapsed_us, 0.0)
        self.assertGreater(result.stream, 0)

    def test_launch_kernel_invalid_block(self):
        """Test with block size > 1024."""
        with _mock_nvidia_smi_failure():
            mgr = CUDAKernelManager()
            ck = mgr.compile_kernel("add_kernel", SIMPLE_KERNEL_SRC)
            result = mgr.launch_kernel(ck, grid=(1,), block=(2048,))

        self.assertIsInstance(result, KernelResult)
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        self.assertIn("exceeds", result.error)

    def test_profile_kernel(self):
        """Profile and verify KernelProfile stats."""
        with _mock_nvidia_smi_failure():
            mgr = CUDAKernelManager()
            ck = mgr.compile_kernel("add_kernel", SIMPLE_KERNEL_SRC)
            prof = mgr.profile_kernel(
                ck,
                grid=(128,),
                block=(256,),
                n_runs=50,
                data_bytes=128 * 256 * 4,
                flops=128 * 256 * 2.0,
            )

        self.assertIsInstance(prof, KernelProfile)
        self.assertEqual(prof.kernel_name, "add_kernel")
        self.assertEqual(prof.n_runs, 50)
        self.assertGreater(prof.latency_mean_us, 0.0)
        self.assertLessEqual(prof.latency_min_us, prof.latency_mean_us)
        self.assertLessEqual(prof.latency_p50_us, prof.latency_max_us)
        self.assertLessEqual(prof.latency_p99_us, prof.latency_max_us)
        self.assertGreater(prof.throughput_gflops, 0.0)
        self.assertGreater(prof.memory_bandwidth_gb_s, 0.0)
        self.assertGreater(prof.achieved_occupancy, 0.0)
        self.assertLessEqual(prof.achieved_occupancy, prof.theoretical_occupancy)
        self.assertGreater(prof.l1_hit_rate, 0.0)
        self.assertGreater(prof.l2_hit_rate, 0.0)
        self.assertGreater(prof.registers_per_thread, 0)
        self.assertEqual(prof.grid, (128,))
        self.assertEqual(prof.block, (256,))

    def test_occupancy(self):
        """Verify OccupancyReport with realistic values."""
        with _mock_nvidia_smi_failure():
            mgr = CUDAKernelManager()
            # Force device detection
            mgr.get_device_info()
            report = mgr.optimize_occupancy(
                registers_per_thread=32,
                shared_mem_per_block=16384,
                block_size=256,
            )

        self.assertIsInstance(report, OccupancyReport)
        self.assertGreater(report.achieved_occupancy, 0.0)
        self.assertLessEqual(report.achieved_occupancy, 1.0)
        self.assertGreater(report.theoretical_occupancy, 0.0)
        self.assertLessEqual(report.theoretical_occupancy, 1.0)
        self.assertGreater(report.active_warps_per_sm, 0)
        self.assertEqual(report.max_warps_per_sm, 64)  # A100: 2048 / 32
        self.assertIn(
            report.limiting_factor,
            {"registers", "shared_memory", "block_size"},
        )
        self.assertGreater(report.suggested_block_size, 0)
        self.assertEqual(report.suggested_block_size % 32, 0)  # multiple of warp size
        self.assertGreater(report.register_limit_warps, 0)
        self.assertGreater(report.shared_mem_limit_warps, 0)
        self.assertGreater(report.block_size_limit_warps, 0)
        self.assertIn("device", report.details)

    def test_auto_tune(self):
        """Auto-tune and verify optimal result selected."""
        with _mock_nvidia_smi_failure():
            mgr = CUDAKernelManager()
            result = mgr.auto_tune(
                name="add_kernel",
                source=SIMPLE_KERNEL_SRC,
                total_threads=65536,
                block_sizes=[64, 128, 256, 512],
                n_profile_runs=10,
                data_bytes=65536 * 4,
                flops=65536 * 2.0,
            )

        self.assertIsInstance(result, AutoTuneResult)
        self.assertEqual(result.kernel_name, "add_kernel")
        self.assertIn(result.optimal_block_size, [64, 128, 256, 512])
        self.assertGreater(result.optimal_elapsed_us, 0.0)
        self.assertGreater(result.optimal_occupancy, 0.0)
        self.assertGreater(result.configs_tested, 0)
        self.assertLessEqual(result.configs_tested, 4)
        self.assertEqual(len(result.all_results), result.configs_tested)

        # Verify the optimal result is actually the best (minimum mean time)
        mean_times = [r["mean_us"] for r in result.all_results]
        self.assertAlmostEqual(
            result.optimal_elapsed_us, min(mean_times), places=3
        )


# ===========================================================================
# TestMemoryManager
# ===========================================================================


class TestMemoryManager(unittest.TestCase):
    """Tests for GPUMemoryManager allocation, freeing, P2P copies,
    stats, defragmentation, and unified memory."""

    def test_allocate_default(self):
        """Allocate memory, verify GPUAllocation."""
        mgr = GPUMemoryManager(device_ids=[0])
        alloc = mgr.allocate(1024 * 1024, device_id=0, tag="test_alloc")

        self.assertIsInstance(alloc, GPUAllocation)
        self.assertEqual(alloc.size_bytes, 1024 * 1024)
        self.assertEqual(alloc.pool, "default")
        self.assertEqual(alloc.device_id, 0)
        self.assertGreater(alloc.ptr, 0)
        self.assertGreater(alloc.allocated_at, 0.0)
        self.assertEqual(alloc.tag, "test_alloc")

    def test_allocate_pinned(self):
        """Allocate pinned memory."""
        mgr = GPUMemoryManager(device_ids=[0])
        alloc = mgr.allocate(2048, device_id=0, pool="pinned", tag="pinned")

        self.assertIsInstance(alloc, GPUAllocation)
        self.assertEqual(alloc.pool, "pinned")
        self.assertEqual(alloc.size_bytes, 2048)

    def test_free(self):
        """Allocate then free, verify stats updated."""
        mgr = GPUMemoryManager(device_ids=[0])
        alloc = mgr.allocate(4096, device_id=0)

        stats_before = mgr.get_memory_stats(device_id=0)
        self.assertEqual(stats_before.n_allocations, 1)
        self.assertEqual(stats_before.allocated_bytes, 4096)

        mgr.free(alloc)

        stats_after = mgr.get_memory_stats(device_id=0)
        self.assertEqual(stats_after.n_allocations, 0)
        self.assertEqual(stats_after.allocated_bytes, 0)
        # Peak should still reflect the allocation
        self.assertEqual(stats_after.peak_allocated_bytes, 4096)

    def test_peer_to_peer_copy(self):
        """P2P copy, verify time > 0."""
        mgr = GPUMemoryManager(device_ids=[0, 1])
        src = mgr.allocate(1024 * 1024, device_id=0, tag="src")
        dst = mgr.peer_to_peer_copy(src, dst_device_id=1)

        self.assertIsInstance(dst, GPUAllocation)
        self.assertEqual(dst.device_id, 1)
        self.assertEqual(dst.size_bytes, src.size_bytes)
        self.assertEqual(dst.pool, "peer")
        self.assertIn("p2p_from_dev0", dst.tag)

        # Verify the destination device now has an allocation
        stats = mgr.get_memory_stats(device_id=1)
        self.assertEqual(stats.n_allocations, 1)
        self.assertEqual(stats.allocated_bytes, 1024 * 1024)

    def test_memory_stats(self):
        """Get stats, verify fields."""
        mgr = GPUMemoryManager(device_ids=[0])
        mgr.allocate(1000, device_id=0, pool="default", tag="a")
        mgr.allocate(2000, device_id=0, pool="pinned", tag="b")

        stats = mgr.get_memory_stats(device_id=0)

        self.assertIsInstance(stats, MemoryStats)
        self.assertEqual(stats.device_id, 0)
        self.assertEqual(stats.total_bytes, GPUMemoryManager.DEFAULT_TOTAL_BYTES)
        self.assertEqual(stats.allocated_bytes, 3000)
        self.assertEqual(stats.free_bytes, GPUMemoryManager.DEFAULT_TOTAL_BYTES - 3000)
        self.assertEqual(stats.peak_allocated_bytes, 3000)
        self.assertEqual(stats.n_allocations, 2)
        self.assertIn("default", stats.pool_breakdown)
        self.assertIn("pinned", stats.pool_breakdown)
        self.assertEqual(stats.pool_breakdown["default"], 1000)
        self.assertEqual(stats.pool_breakdown["pinned"], 2000)
        self.assertGreaterEqual(stats.fragmentation_estimate, 0.0)
        self.assertLessEqual(stats.fragmentation_estimate, 1.0)

    def test_defragment(self):
        """Allocate/free/defragment, verify fragmentation reduced."""
        mgr = GPUMemoryManager(device_ids=[0])

        # Create allocation churn to build up fragmentation
        allocs = []
        for i in range(10):
            allocs.append(mgr.allocate(1024, device_id=0, tag=f"chunk_{i}"))

        # Free every other allocation to create fragmentation
        for i in range(0, 10, 2):
            mgr.free(allocs[i])

        stats_before = mgr.get_memory_stats(device_id=0)
        frag_before = stats_before.fragmentation_estimate

        result = mgr.defragment(device_id=0)

        stats_after = mgr.get_memory_stats(device_id=0)
        frag_after = stats_after.fragmentation_estimate

        self.assertIsInstance(result, dict)
        self.assertEqual(result["device_id"], 0)
        self.assertEqual(result["allocations_compacted"], 5)
        # After defragmentation, frag ops are reset, so fragmentation should
        # be at zero (frag_ops == n_allocs means (0) / (2*n) = 0).
        self.assertLessEqual(frag_after, frag_before)
        self.assertAlmostEqual(frag_after, 0.0)

    def test_unified_memory(self):
        """Enable unified memory, verify UnifiedAllocation."""
        mgr = GPUMemoryManager(device_ids=[0])
        ua = mgr.enable_unified_memory(
            8192, cpu_resident=True, gpu_resident=True
        )

        self.assertIsInstance(ua, UnifiedAllocation)
        self.assertEqual(ua.size_bytes, 8192)
        self.assertTrue(ua.cpu_resident)
        self.assertTrue(ua.gpu_resident)
        self.assertGreater(ua.ptr, 0)
        self.assertGreater(ua.allocated_at, 0.0)

        # Verify it shows up in stats
        stats = mgr.get_memory_stats(device_id=0)
        self.assertEqual(stats.unified_allocations, 1)
        self.assertEqual(stats.unified_total_bytes, 8192)


# ===========================================================================
# TestFlashAttention
# ===========================================================================


class TestFlashAttention(unittest.TestCase):
    """Tests for FlashAttentionKernel parameter computation and tools."""

    def setUp(self):
        self.kernel = FlashAttentionKernel()

    def test_init_defaults(self):
        """Verify default params."""
        self.assertEqual(self.kernel.head_dim, 128)
        self.assertEqual(self.kernel.block_row, 128)
        self.assertEqual(self.kernel.block_col, 64)
        self.assertIsInstance(self.kernel.source, str)
        self.assertGreater(len(self.kernel.source), 0)

    def test_compute_grid(self):
        """Known batch/heads/seq -> expected grid dims."""
        # batch=2, heads=8, seq_len=512
        # grid_x = ceil(512 / 128) = 4
        # grid_y = 2 * 8 = 16
        grid = self.kernel.compute_grid(batch_size=2, n_heads=8, seq_len=512)
        self.assertEqual(grid, (4, 16))

        # Edge case: seq_len not a multiple of block_row
        # batch=1, heads=1, seq_len=200 -> ceil(200/128) = 2, grid_y=1
        grid2 = self.kernel.compute_grid(batch_size=1, n_heads=1, seq_len=200)
        self.assertEqual(grid2, (2, 1))

    def test_shared_memory_estimate(self):
        """Verify > 0 and reasonable."""
        smem = self.kernel.estimate_shared_memory()
        self.assertGreater(smem, 0)

        # Expected: Q_tile(128*128*2) + K_tile(64*128*2) + V_tile(64*128*2) + S_tile(128*64*4)
        # = 32768 + 16384 + 16384 + 32768 = 98304
        expected = (
            128 * 128 * 2  # Q tile (block_row * head_dim * FP16)
            + 64 * 128 * 2  # K tile (block_col * head_dim * FP16)
            + 64 * 128 * 2  # V tile (block_col * head_dim * FP16)
            + 128 * 64 * 4  # score tile (block_row * block_col * FP32)
        )
        self.assertEqual(smem, expected)

        # Should fit in A100 shared memory (164 KB per SM)
        self.assertLess(smem, 167936)

    def test_flops_estimate(self):
        """Verify scaling with seq_len squared."""
        flops_512 = self.kernel.estimate_flops(
            batch_size=1, n_heads=1, seq_len=512
        )
        flops_1024 = self.kernel.estimate_flops(
            batch_size=1, n_heads=1, seq_len=1024
        )

        self.assertGreater(flops_512, 0.0)
        self.assertGreater(flops_1024, 0.0)

        # Since attention is O(N^2), doubling seq_len should ~4x the FLOPs.
        # The softmax_flops term (5*N^2) is small relative to the 4*N^2*d term
        # so the ratio should be close to 4.
        ratio = flops_1024 / flops_512
        self.assertAlmostEqual(ratio, 4.0, places=1)

    def test_memory_bytes(self):
        """Verify O(N) vs O(N^2) comparison, savings factor."""
        mem = self.kernel.estimate_memory_bytes(
            batch_size=4, n_heads=32, seq_len=2048
        )

        self.assertIn("total", mem)
        self.assertIn("vs_naive_attention", mem)
        self.assertIn("memory_savings_factor", mem)
        self.assertIn("qkv_input", mem)
        self.assertIn("output", mem)
        self.assertIn("log_sum_exp", mem)

        # Flash total should be less than naive total
        self.assertLess(mem["total"], mem["vs_naive_attention"])

        # Savings factor should be > 1 (naive uses more memory)
        self.assertGreater(mem["memory_savings_factor"], 1.0)

        # For large seq_len, the savings should be substantial
        # because naive has O(N^2) score matrix while flash has O(N) LSE
        self.assertGreater(mem["memory_savings_factor"], 1.5)

    def test_get_tools(self):
        """Verify tool list non-empty."""
        tools = self.kernel.get_tools()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

        # Each tool should have the expected structure
        for tool in tools:
            self.assertIn("type", tool)
            self.assertEqual(tool["type"], "function")
            self.assertIn("function", tool)
            self.assertIn("name", tool["function"])
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])


# ===========================================================================
# TestFusedEmbedding
# ===========================================================================


class TestFusedEmbedding(unittest.TestCase):
    """Tests for FusedEmbeddingKernel parameter computation and tools."""

    def setUp(self):
        self.kernel = FusedEmbeddingKernel()

    def test_init_defaults(self):
        """Verify vocab/dim."""
        self.assertEqual(self.kernel.vocab_size, 128256)
        self.assertEqual(self.kernel.embed_dim, 4096)
        self.assertEqual(self.kernel.threads_per_block, 256)
        self.assertIsInstance(self.kernel.source, str)
        self.assertGreater(len(self.kernel.source), 0)

    def test_bandwidth_utilization(self):
        """Verify dict keys and reasonable values."""
        bw = self.kernel.estimate_bandwidth_utilization(
            batch_size=8, seq_len=2048
        )

        self.assertIsInstance(bw, dict)
        self.assertIn("fused_hbm_bytes", bw)
        self.assertIn("naive_hbm_bytes", bw)
        self.assertIn("bandwidth_savings_ratio", bw)
        self.assertIn("fused_estimated_time_us", bw)
        self.assertIn("naive_estimated_time_us", bw)
        self.assertIn("a100_peak_bw_gb_s", bw)
        self.assertIn("effective_bw_utilization", bw)
        self.assertIn("embedding_table_bytes", bw)

        # Fused should use fewer bytes than naive
        self.assertLess(bw["fused_hbm_bytes"], bw["naive_hbm_bytes"])

        # Savings ratio should be > 1
        self.assertGreater(bw["bandwidth_savings_ratio"], 1.0)

        # Times should be positive
        self.assertGreater(bw["fused_estimated_time_us"], 0.0)
        self.assertGreater(bw["naive_estimated_time_us"], 0.0)

        # Fused should be faster
        self.assertLess(
            bw["fused_estimated_time_us"], bw["naive_estimated_time_us"]
        )

    def test_compute_grid(self):
        """Verify grid computation."""
        # batch=4, seq_len=1024 -> total_tokens=4096, grid=(4096, 1)
        grid = self.kernel.compute_grid(batch_size=4, seq_len=1024)
        self.assertEqual(grid, (4096, 1))

        # batch=1, seq_len=1 -> grid=(1, 1)
        grid2 = self.kernel.compute_grid(batch_size=1, seq_len=1)
        self.assertEqual(grid2, (1, 1))

    def test_get_tools(self):
        """Verify tool list."""
        tools = self.kernel.get_tools()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

        tool_names = [t["function"]["name"] for t in tools]
        self.assertIn("fused_embedding_estimate", tool_names)
        self.assertIn("fused_embedding_bandwidth", tool_names)


# ===========================================================================
# TestSecurityScan
# ===========================================================================


class TestSecurityScan(unittest.TestCase):
    """Tests for SecurityScanKernel scan time estimation, grid, and tools."""

    def setUp(self):
        self.kernel = SecurityScanKernel()

    def test_init(self):
        """Verify n_patterns=503, block/grid sizes."""
        self.assertEqual(self.kernel.n_patterns, 503)
        self.assertEqual(self.kernel.block_size, 128)
        # grid = ceil(503 / 128) = 4
        self.assertEqual(self.kernel.grid_size, (4,))
        self.assertEqual(self.kernel.max_pattern_len, 256)
        self.assertIsInstance(self.kernel.source, str)
        self.assertGreater(len(self.kernel.source), 0)

    def test_scan_time_estimate(self):
        """Verify < 100 us for small input."""
        # Small input: 1 KB
        time_us = self.kernel.estimate_scan_time_us(1024)
        self.assertGreater(time_us, 0.0)
        self.assertLess(time_us, 100.0)

        # Zero-length input should return 0
        self.assertEqual(self.kernel.estimate_scan_time_us(0), 0.0)

        # Larger input should take longer
        time_large = self.kernel.estimate_scan_time_us(1024 * 1024)
        self.assertGreater(time_large, time_us)

    def test_compute_grid(self):
        """Verify grid computation."""
        grid = self.kernel.compute_grid()
        self.assertEqual(grid, (4,))
        self.assertIsInstance(grid, tuple)

    def test_get_tools(self):
        """Verify tool list."""
        tools = self.kernel.get_tools()
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

        tool_names = [t["function"]["name"] for t in tools]
        self.assertIn("security_scan_estimate", tool_names)
        self.assertIn("security_scan_info", tool_names)


# ===========================================================================
# TestMultiGPU
# ===========================================================================


class TestMultiGPU(unittest.TestCase):
    """Tests for MultiGPUOrchestrator data parallelism, all-reduce,
    and NVLink detection."""

    def test_init(self):
        """Mock nvidia-smi, verify device list."""
        # When nvidia-smi fails, the constructor defaults to 2 GPUs
        with _mock_nvidia_smi_failure():
            orch = MultiGPUOrchestrator()

        self.assertEqual(len(orch._device_ids), 2)
        self.assertIn(0, orch._device_ids)
        self.assertIn(1, orch._device_ids)
        self.assertEqual(len(orch._devices), 2)

        # With explicit device_ids, nvidia-smi is still called for NVLink
        # detection but the device list comes from the argument
        with _mock_nvidia_smi_failure():
            orch2 = MultiGPUOrchestrator(device_ids=[0, 1, 2])

        self.assertEqual(len(orch2._device_ids), 3)

    def test_data_parallel_dispatch(self):
        """Dispatch to 2 GPUs, verify results."""
        with _mock_nvidia_smi_failure():
            orch = MultiGPUOrchestrator(device_ids=[0, 1])

        inputs = list(range(100))
        result = orch.data_parallel_dispatch(inputs, kernel="test_kernel")

        self.assertIsInstance(result, dict)
        self.assertEqual(result["strategy"], "data_parallel")
        self.assertEqual(result["kernel"], "test_kernel")
        self.assertEqual(result["n_gpus"], 2)
        self.assertEqual(result["total_inputs"], 100)
        self.assertGreater(result["compute_time_us"], 0.0)
        self.assertGreater(result["allreduce_time_us"], 0.0)
        self.assertGreater(result["total_time_us"], 0.0)
        self.assertGreater(result["throughput_items_per_sec"], 0.0)

        # Per-device results should exist
        self.assertEqual(len(result["per_device"]), 2)
        total_items = sum(d["items_processed"] for d in result["per_device"])
        self.assertEqual(total_items, 100)

    def test_all_reduce_sum(self):
        """Verify sum reduction."""
        with _mock_nvidia_smi_failure():
            orch = MultiGPUOrchestrator(device_ids=[0, 1])

        tensors = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        result = orch.all_reduce(tensors, op="sum")

        self.assertIsInstance(result, dict)
        self.assertEqual(result["operation"], "sum")
        self.assertEqual(result["n_gpus"], 2)
        self.assertEqual(result["algorithm"], "ring_allreduce")
        self.assertGreater(result["time_us"], 0.0)
        self.assertGreater(result["data_bytes"], 0)
        self.assertGreater(result["total_transferred_bytes"], 0)
        self.assertGreaterEqual(result["algorithm_bandwidth_gb_s"], 0.0)

    def test_all_reduce_mean(self):
        """Verify mean reduction."""
        with _mock_nvidia_smi_failure():
            orch = MultiGPUOrchestrator(device_ids=[0, 1, 2, 3])

        tensors = [[1.0] * 1000 for _ in range(4)]
        result = orch.all_reduce(tensors, op="avg")

        self.assertEqual(result["operation"], "avg")
        self.assertEqual(result["n_gpus"], 4)
        self.assertGreater(result["time_us"], 0.0)

        # With 4 GPUs, data_bytes = 1000 * 4 = 4000 (FP32)
        self.assertEqual(result["data_bytes"], 1000 * 4)

    def test_nvlink_detection(self):
        """Verify topology detection."""
        # Test fallback path (no nvidia-smi) -- should create full mesh
        with _mock_nvidia_smi_failure():
            orch = MultiGPUOrchestrator(device_ids=[0, 1, 2])

        # All pairs should have NVLink in the simulated mesh
        self.assertIn((0, 1), orch._nvlink_topology)
        self.assertIn((1, 0), orch._nvlink_topology)
        self.assertIn((0, 2), orch._nvlink_topology)
        self.assertIn((2, 0), orch._nvlink_topology)
        self.assertIn((1, 2), orch._nvlink_topology)
        self.assertIn((2, 1), orch._nvlink_topology)

        # Each device should list the others as NVLink peers
        self.assertIn(1, orch._devices[0].nvlink_peers)
        self.assertIn(2, orch._devices[0].nvlink_peers)
        self.assertIn(0, orch._devices[1].nvlink_peers)

        # Bandwidth should reflect NVLink for connected peers
        bw = orch._peer_bandwidth_gb_s(0, 1)
        self.assertEqual(bw, MultiGPUOrchestrator.NVLINK_BW_GB_S)


if __name__ == "__main__":
    unittest.main()
