"""Flash Attention v2 CUDA kernel implementation for Orchestra."""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Tuple

log = logging.getLogger("orchestra.cuda.kernels.attention")

__all__ = ["FlashAttentionKernel"]

KERNEL_SOURCE: str = r"""
// Flash Attention v2 - Tiled Online Softmax with IO-Awareness
// Based on Dao et al. (2023) "FlashAttention-2: Faster Attention with Better
// Parallelism and Work Partitioning"

#include <cuda_fp16.h>
#include <cuda_bf16.h>
#include <mma.h>

using namespace nvcuda;

constexpr int BLOCK_ROW = 128;
constexpr int BLOCK_COL = 64;
constexpr int WARP_SIZE = 32;
constexpr int NUM_WARPS = 4;

template <int HEAD_DIM, typename scalar_t>
__global__ void flash_attention_v2_kernel(
    const scalar_t* __restrict__ Q,     // [B, H, N, D]
    const scalar_t* __restrict__ K,     // [B, H, N, D]
    const scalar_t* __restrict__ V,     // [B, H, N, D]
    scalar_t*       __restrict__ O,     // [B, H, N, D]
    float*          __restrict__ L,     // [B, H, N] log-sum-exp
    const int N,
    const float scale
) {
    extern __shared__ char smem[];

    const int batch_head = blockIdx.y;
    const int block_row  = blockIdx.x;

    const int row_start = block_row * BLOCK_ROW;
    const int row_end   = min(row_start + BLOCK_ROW, N);

    // Pointers into shared memory for Q, K, V tiles
    scalar_t* sQ = reinterpret_cast<scalar_t*>(smem);
    scalar_t* sK = sQ + BLOCK_ROW * HEAD_DIM;
    scalar_t* sV = sK + BLOCK_COL * HEAD_DIM;
    float*    sS = reinterpret_cast<float*>(sV + BLOCK_COL * HEAD_DIM);

    // Thread identification
    const int tid     = threadIdx.x;
    const int warp_id = tid / WARP_SIZE;
    const int lane_id = tid % WARP_SIZE;

    // Load Q tile into shared memory (persistent across K/V tiles)
    for (int i = tid; i < BLOCK_ROW * HEAD_DIM; i += blockDim.x) {
        int row = row_start + i / HEAD_DIM;
        int col = i % HEAD_DIM;
        sQ[i] = (row < N) ? Q[batch_head * N * HEAD_DIM + row * HEAD_DIM + col]
                           : scalar_t(0);
    }
    __syncthreads();

    // Online softmax accumulators
    float row_max[BLOCK_ROW / (NUM_WARPS * WARP_SIZE) + 1];
    float row_sum[BLOCK_ROW / (NUM_WARPS * WARP_SIZE) + 1];
    float out_acc[BLOCK_ROW / (NUM_WARPS * WARP_SIZE) + 1][HEAD_DIM];

    // Initialize
    #pragma unroll
    for (int i = 0; i < BLOCK_ROW / blockDim.x + 1; i++) {
        row_max[i] = -INFINITY;
        row_sum[i] = 0.0f;
        for (int d = 0; d < HEAD_DIM; d++) out_acc[i][d] = 0.0f;
    }

    // Iterate over K/V column tiles
    for (int col_start = 0; col_start < N; col_start += BLOCK_COL) {
        int col_end = min(col_start + BLOCK_COL, N);

        // Load K tile
        for (int i = tid; i < BLOCK_COL * HEAD_DIM; i += blockDim.x) {
            int row = col_start + i / HEAD_DIM;
            int col = i % HEAD_DIM;
            sK[i] = (row < N) ? K[batch_head * N * HEAD_DIM + row * HEAD_DIM + col]
                               : scalar_t(0);
        }
        // Load V tile
        for (int i = tid; i < BLOCK_COL * HEAD_DIM; i += blockDim.x) {
            int row = col_start + i / HEAD_DIM;
            int col = i % HEAD_DIM;
            sV[i] = (row < N) ? V[batch_head * N * HEAD_DIM + row * HEAD_DIM + col]
                               : scalar_t(0);
        }
        __syncthreads();

        // Compute S = Q @ K^T * scale (tiled matmul in shared memory)
        // Then apply online softmax and accumulate O = softmax(S) @ V
        for (int r = tid; r < (row_end - row_start); r += blockDim.x) {
            float local_max = row_max[r / blockDim.x];
            float local_sum = row_sum[r / blockDim.x];

            for (int c = 0; c < (col_end - col_start); c++) {
                float dot = 0.0f;
                #pragma unroll
                for (int d = 0; d < HEAD_DIM; d++) {
                    dot += float(sQ[r * HEAD_DIM + d]) * float(sK[c * HEAD_DIM + d]);
                }
                dot *= scale;

                // Causal masking
                if (row_start + r < col_start + c) dot = -INFINITY;

                sS[r * BLOCK_COL + c] = dot;

                float new_max = fmaxf(local_max, dot);
                float exp_diff = expf(local_max - new_max);
                local_sum = local_sum * exp_diff + expf(dot - new_max);

                // Rescale running output accumulator
                for (int d = 0; d < HEAD_DIM; d++) {
                    out_acc[r / blockDim.x][d] *= exp_diff;
                    out_acc[r / blockDim.x][d] += expf(dot - new_max) * float(sV[c * HEAD_DIM + d]);
                }
                local_max = new_max;
            }
            row_max[r / blockDim.x] = local_max;
            row_sum[r / blockDim.x] = local_sum;
        }
        __syncthreads();
    }

    // Write output: O = out_acc / row_sum, L = log(row_sum) + row_max
    for (int r = tid; r < (row_end - row_start); r += blockDim.x) {
        int global_row = row_start + r;
        float inv_sum = 1.0f / row_sum[r / blockDim.x];
        for (int d = 0; d < HEAD_DIM; d++) {
            O[batch_head * N * HEAD_DIM + global_row * HEAD_DIM + d] =
                scalar_t(out_acc[r / blockDim.x][d] * inv_sum);
        }
        L[batch_head * N + global_row] =
            row_max[r / blockDim.x] + logf(row_sum[r / blockDim.x]);
    }
}
"""


class FlashAttentionKernel:
    """Flash Attention v2 kernel with tiled online softmax.

    Provides methods to compute launch parameters, estimate resource usage,
    and expose tools for Orchestra integration.
    """

    def __init__(
        self,
        head_dim: int = 128,
        block_row: int = 128,
        block_col: int = 64,
    ) -> None:
        """Initialise Flash Attention kernel parameters.

        Args:
            head_dim: Dimension of each attention head.
            block_row: Tile size along the query (row) dimension.
            block_col: Tile size along the key/value (column) dimension.
        """
        self.head_dim = head_dim
        self.block_row = block_row
        self.block_col = block_col
        self.source = KERNEL_SOURCE
        log.info(
            "FlashAttentionKernel: head_dim=%d, block_row=%d, block_col=%d",
            head_dim,
            block_row,
            block_col,
        )

    def compute_grid(
        self, batch_size: int, n_heads: int, seq_len: int
    ) -> Tuple[int, int]:
        """Compute the CUDA grid dimensions for a given input shape.

        Args:
            batch_size: Batch size B.
            n_heads: Number of attention heads H.
            seq_len: Sequence length N.

        Returns:
            A tuple ``(grid_x, grid_y)`` where *grid_x* is the number of
            row-tile blocks and *grid_y* is ``B * H``.
        """
        grid_x = math.ceil(seq_len / self.block_row)
        grid_y = batch_size * n_heads
        return (grid_x, grid_y)

    def estimate_shared_memory(self) -> int:
        """Estimate the shared memory requirement per block in bytes.

        The layout stores Q-tile, K-tile, V-tile, and the partial score
        matrix in shared memory (all in FP16 / 2 bytes per element, scores
        in FP32 / 4 bytes).

        Returns:
            Shared memory in bytes.
        """
        bytes_per_elem = 2  # FP16
        q_tile = self.block_row * self.head_dim * bytes_per_elem
        k_tile = self.block_col * self.head_dim * bytes_per_elem
        v_tile = self.block_col * self.head_dim * bytes_per_elem
        score_tile = self.block_row * self.block_col * 4  # FP32 scores
        total = q_tile + k_tile + v_tile + score_tile
        return total

    def estimate_flops(
        self, batch_size: int, n_heads: int, seq_len: int
    ) -> float:
        """Estimate total floating-point operations for one forward pass.

        Flash Attention is O(N^2 * d) per head per batch element, same as
        standard attention, but with far fewer HBM accesses.

        Two main matmuls: Q@K^T and softmax(S)@V, each is 2*N*N*d FLOPs.

        Args:
            batch_size: Batch size B.
            n_heads: Number of attention heads H.
            seq_len: Sequence length N.

        Returns:
            Total FLOPs as a float.
        """
        # Q @ K^T: 2 * N * N * d  (multiply-add = 2 ops per element)
        qk_flops = 2.0 * seq_len * seq_len * self.head_dim
        # softmax(S) @ V: 2 * N * N * d
        sv_flops = 2.0 * seq_len * seq_len * self.head_dim
        # Softmax itself: ~5 * N * N (exp, sub, div, etc.)
        softmax_flops = 5.0 * seq_len * seq_len
        per_head = qk_flops + sv_flops + softmax_flops
        total = per_head * batch_size * n_heads
        return total

    def estimate_memory_bytes(
        self, batch_size: int, n_heads: int, seq_len: int
    ) -> Dict[str, Any]:
        """Estimate HBM memory usage and compare against naive attention.

        Flash Attention avoids materialising the full N x N attention matrix,
        requiring only O(N) auxiliary memory for the log-sum-exp vector
        instead of O(N^2) for the score matrix.

        Args:
            batch_size: Batch size B.
            n_heads: Number of attention heads H.
            seq_len: Sequence length N.

        Returns:
            A dict with byte estimates for each tensor and a comparison
            against naive attention.
        """
        elem = 2  # FP16 bytes per element
        bh = batch_size * n_heads

        # Input Q, K, V: each is [B, H, N, D]
        qkv_input = 3 * bh * seq_len * self.head_dim * elem
        # Output O: [B, H, N, D]
        output = bh * seq_len * self.head_dim * elem
        # Log-sum-exp L: [B, H, N] in FP32
        log_sum_exp = bh * seq_len * 4

        flash_total = qkv_input + output + log_sum_exp

        # Naive attention materialises N x N score matrix per head
        naive_score_matrix = bh * seq_len * seq_len * elem
        naive_total = qkv_input + output + naive_score_matrix

        savings_factor = naive_total / flash_total if flash_total > 0 else 0.0

        return {
            "qkv_input": qkv_input,
            "output": output,
            "log_sum_exp": log_sum_exp,
            "total": flash_total,
            "vs_naive_attention": naive_total,
            "memory_savings_factor": round(savings_factor, 2),
        }

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return Orchestra tool definitions for this kernel.

        Returns:
            A list of tool dictionaries compatible with the Orchestra
            tool-calling interface.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "flash_attention_estimate",
                    "description": (
                        "Estimate FLOPs, memory, and grid dimensions for "
                        "Flash Attention v2 given input shapes."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "batch_size": {
                                "type": "integer",
                                "description": "Batch size B",
                            },
                            "n_heads": {
                                "type": "integer",
                                "description": "Number of attention heads H",
                            },
                            "seq_len": {
                                "type": "integer",
                                "description": "Sequence length N",
                            },
                        },
                        "required": ["batch_size", "n_heads", "seq_len"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "flash_attention_shared_mem",
                    "description": (
                        "Return shared memory requirements for the Flash "
                        "Attention kernel with current tile sizes."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]
