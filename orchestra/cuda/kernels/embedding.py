"""Fused embedding lookup + positional encoding CUDA kernel for Orchestra."""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Tuple

log = logging.getLogger("orchestra.cuda.kernels.embedding")

__all__ = ["FusedEmbeddingKernel"]

KERNEL_SOURCE: str = r"""
// Fused Embedding Lookup + RoPE Positional Encoding Kernel
// Combines token embedding table lookup with rotary positional embeddings
// in a single HBM pass, eliminating an intermediate write-read cycle.

#include <cuda_fp16.h>
#include <cuda_bf16.h>

constexpr int THREADS_PER_BLOCK = 256;
constexpr float ROPE_THETA = 10000.0f;

template <int EMBED_DIM, typename scalar_t>
__global__ void fused_embedding_rope_kernel(
    const int*       __restrict__ token_ids,     // [B, N]
    const scalar_t*  __restrict__ embed_table,   // [V, D]
    scalar_t*        __restrict__ output,        // [B, N, D]
    const int B,
    const int N,
    const int V,
    const int D
) {
    // Each block handles one token position
    const int global_idx = blockIdx.x;
    const int batch_idx  = global_idx / N;
    const int seq_idx    = global_idx % N;

    if (batch_idx >= B) return;

    const int token_id = token_ids[batch_idx * N + seq_idx];
    if (token_id < 0 || token_id >= V) return;

    const scalar_t* embed_row = embed_table + token_id * D;
    scalar_t* out_row = output + (batch_idx * N + seq_idx) * D;

    // Coalesced embedding lookup + RoPE in pairs
    for (int d = threadIdx.x * 2; d < D; d += blockDim.x * 2) {
        if (d + 1 < D) {
            float x0 = float(embed_row[d]);
            float x1 = float(embed_row[d + 1]);

            // RoPE: rotate pairs of dimensions
            float freq = 1.0f / powf(ROPE_THETA, float(d) / float(D));
            float angle = float(seq_idx) * freq;
            float cos_a = cosf(angle);
            float sin_a = sinf(angle);

            float y0 = x0 * cos_a - x1 * sin_a;
            float y1 = x0 * sin_a + x1 * cos_a;

            out_row[d]     = scalar_t(y0);
            out_row[d + 1] = scalar_t(y1);
        }
    }
}

template <int EMBED_DIM, typename scalar_t>
__global__ void fused_embedding_layernorm_kernel(
    const int*       __restrict__ token_ids,
    const scalar_t*  __restrict__ embed_table,
    const scalar_t*  __restrict__ ln_weight,    // [D]
    const scalar_t*  __restrict__ ln_bias,      // [D]
    scalar_t*        __restrict__ output,
    const int B,
    const int N,
    const int V,
    const int D,
    const float eps
) {
    extern __shared__ float smem[];

    const int global_idx = blockIdx.x;
    const int batch_idx  = global_idx / N;
    const int seq_idx    = global_idx % N;

    if (batch_idx >= B) return;

    const int token_id = token_ids[batch_idx * N + seq_idx];
    if (token_id < 0 || token_id >= V) return;

    const scalar_t* embed_row = embed_table + token_id * D;
    scalar_t* out_row = output + (batch_idx * N + seq_idx) * D;

    // Phase 1: Load embedding and compute partial sums for mean/variance
    float local_sum  = 0.0f;
    float local_sum2 = 0.0f;
    for (int d = threadIdx.x; d < D; d += blockDim.x) {
        float val = float(embed_row[d]);
        smem[d] = val;
        local_sum  += val;
        local_sum2 += val * val;
    }

    // Warp-level reduction for mean and variance
    __shared__ float shared_sum[32];
    __shared__ float shared_sum2[32];
    int lane = threadIdx.x % 32;
    int warp = threadIdx.x / 32;

    for (int offset = 16; offset > 0; offset >>= 1) {
        local_sum  += __shfl_down_sync(0xffffffff, local_sum, offset);
        local_sum2 += __shfl_down_sync(0xffffffff, local_sum2, offset);
    }
    if (lane == 0) { shared_sum[warp] = local_sum; shared_sum2[warp] = local_sum2; }
    __syncthreads();

    if (threadIdx.x == 0) {
        float total = 0.0f, total2 = 0.0f;
        int num_warps = (blockDim.x + 31) / 32;
        for (int i = 0; i < num_warps; i++) { total += shared_sum[i]; total2 += shared_sum2[i]; }
        shared_sum[0]  = total / float(D);
        shared_sum2[0] = total2 / float(D) - (total / float(D)) * (total / float(D));
    }
    __syncthreads();

    float mean = shared_sum[0];
    float var  = shared_sum2[0];
    float inv_std = rsqrtf(var + eps);

    // Phase 2: Normalize and apply affine transform
    for (int d = threadIdx.x; d < D; d += blockDim.x) {
        float normed = (smem[d] - mean) * inv_std;
        out_row[d] = scalar_t(normed * float(ln_weight[d]) + float(ln_bias[d]));
    }
}
"""


class FusedEmbeddingKernel:
    """Fused embedding lookup with rotary positional encoding.

    Combines the embedding table lookup and RoPE application into a single
    GPU kernel to eliminate an intermediate HBM read-write cycle, roughly
    halving the memory traffic for this stage of the transformer.
    """

    def __init__(
        self,
        vocab_size: int = 128256,
        embed_dim: int = 4096,
    ) -> None:
        """Initialise the fused embedding kernel parameters.

        Args:
            vocab_size: Size of the token vocabulary V.
            embed_dim: Embedding dimension D.
        """
        self.vocab_size = vocab_size
        self.embed_dim = embed_dim
        self.threads_per_block = 256
        self.source = KERNEL_SOURCE
        log.info(
            "FusedEmbeddingKernel: vocab=%d, dim=%d", vocab_size, embed_dim
        )

    def estimate_bandwidth_utilization(
        self, batch_size: int, seq_len: int
    ) -> Dict[str, Any]:
        """Estimate HBM bandwidth utilisation for the fused kernel.

        The fused kernel reads the embedding rows and writes the output in
        a single pass.  A naive (unfused) approach would write embeddings
        to HBM and then read them back for RoPE, doubling the traffic.

        Args:
            batch_size: Batch size B.
            seq_len: Sequence length N.

        Returns:
            A dict with bandwidth estimates and the fused-vs-naive ratio.
        """
        elem = 2  # FP16
        tokens = batch_size * seq_len

        # Fused: read embed table rows + write output (one pass)
        embed_read = tokens * self.embed_dim * elem
        output_write = tokens * self.embed_dim * elem
        # Also read token_ids (int32)
        token_id_read = tokens * 4
        fused_bytes = embed_read + output_write + token_id_read

        # Naive: embed read + embed write + embed read (for RoPE) + output write
        naive_bytes = embed_read + output_write + embed_read + output_write + token_id_read

        # A100 HBM bandwidth: 2039 GB/s
        a100_bw = 2039e9  # bytes/sec
        fused_time_us = (fused_bytes / a100_bw) * 1e6
        naive_time_us = (naive_bytes / a100_bw) * 1e6

        # Effective bandwidth utilization (assume 80% of peak)
        effective_bw_pct = 0.80
        fused_time_us_eff = fused_time_us / effective_bw_pct

        return {
            "fused_hbm_bytes": fused_bytes,
            "naive_hbm_bytes": naive_bytes,
            "bandwidth_savings_ratio": round(naive_bytes / fused_bytes, 2) if fused_bytes > 0 else 0.0,
            "fused_estimated_time_us": round(fused_time_us_eff, 3),
            "naive_estimated_time_us": round(naive_time_us / effective_bw_pct, 3),
            "a100_peak_bw_gb_s": 2039,
            "effective_bw_utilization": effective_bw_pct,
            "embedding_table_bytes": self.vocab_size * self.embed_dim * elem,
        }

    def compute_grid(
        self, batch_size: int, seq_len: int
    ) -> Tuple[int, int]:
        """Compute CUDA grid dimensions for the fused kernel.

        Each block handles one token position (one embedding row + RoPE).

        Args:
            batch_size: Batch size B.
            seq_len: Sequence length N.

        Returns:
            A tuple ``(grid_x, grid_y)`` where *grid_x* is the total
            number of tokens and *grid_y* is 1.
        """
        total_tokens = batch_size * seq_len
        grid_x = total_tokens
        grid_y = 1
        return (grid_x, grid_y)

    def estimate_flops(self, batch_size: int, seq_len: int) -> float:
        """Estimate total FLOPs for the fused embedding + RoPE pass.

        RoPE applies a rotation to each pair of embedding dimensions,
        requiring 6 FLOPs per pair (2 multiplies, 1 add for each of the
        two output components) plus trigonometric computations.

        Args:
            batch_size: Batch size B.
            seq_len: Sequence length N.

        Returns:
            Total FLOPs as a float.
        """
        tokens = batch_size * seq_len
        # Embedding lookup: essentially zero FLOPs (memory-bound gather)
        # RoPE per pair of dimensions: cos, sin, 4 muls, 2 adds = ~8 ops
        pairs_per_token = self.embed_dim // 2
        rope_flops_per_token = pairs_per_token * 8.0
        # trig: ~20 ops each for sin/cos approximation
        trig_flops_per_token = pairs_per_token * 40.0
        total = tokens * (rope_flops_per_token + trig_flops_per_token)
        return total

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return Orchestra tool definitions for this kernel.

        Returns:
            A list of tool dictionaries for the Orchestra tool-calling interface.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "fused_embedding_estimate",
                    "description": (
                        "Estimate bandwidth utilization, FLOPs, and grid "
                        "dimensions for the fused embedding + RoPE kernel."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "batch_size": {
                                "type": "integer",
                                "description": "Batch size B",
                            },
                            "seq_len": {
                                "type": "integer",
                                "description": "Sequence length N",
                            },
                        },
                        "required": ["batch_size", "seq_len"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fused_embedding_bandwidth",
                    "description": (
                        "Compare HBM bandwidth usage between fused and "
                        "naive embedding + RoPE implementations."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "batch_size": {
                                "type": "integer",
                                "description": "Batch size B",
                            },
                            "seq_len": {
                                "type": "integer",
                                "description": "Sequence length N",
                            },
                        },
                        "required": ["batch_size", "seq_len"],
                    },
                },
            },
        ]
