"""GPU-accelerated security pattern scanning CUDA kernel for Orchestra."""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Tuple

log = logging.getLogger("orchestra.cuda.kernels.security_scan")

__all__ = ["SecurityScanKernel"]

KERNEL_SOURCE: str = r"""
// GPU-Accelerated Multi-Pattern Security Scanner
// Parallelised Aho-Corasick pattern matching on GPU for real-time
// content scanning against threat signature databases.

#include <cuda_runtime.h>
#include <stdint.h>

constexpr int BLOCK_SIZE       = 128;
constexpr int MAX_PATTERNS     = 1024;
constexpr int MAX_PATTERN_LEN  = 256;
constexpr int ALPHABET_SIZE    = 256;

// Aho-Corasick automaton state stored in constant memory
struct ACState {
    int  goto_table[ALPHABET_SIZE];   // transitions
    int  failure;                      // failure link
    int  output_pattern;               // pattern ID if match (-1 otherwise)
    int  output_next;                  // next output link
};

__constant__ ACState d_automaton[4096];  // max states
__constant__ int     d_n_states;
__constant__ int     d_n_patterns;

// Result buffer: one int per pattern indicating match position (-1 if none)
__global__ void security_scan_kernel(
    const uint8_t* __restrict__ input,
    const int                   input_len,
    int*           __restrict__ match_positions,  // [n_patterns]
    int*           __restrict__ match_count
) {
    const int tid       = blockIdx.x * blockDim.x + threadIdx.x;
    const int n_threads = gridDim.x * blockDim.x;

    // Each thread scans a sliding window of the input
    // with overlap to catch patterns spanning chunk boundaries
    const int chunk_size  = (input_len + n_threads - 1) / n_threads;
    const int overlap     = MAX_PATTERN_LEN - 1;
    const int start       = tid * chunk_size;
    const int end         = min(start + chunk_size + overlap, input_len);

    if (start >= input_len) return;

    int state = 0;  // Start at root of Aho-Corasick automaton

    for (int i = start; i < end; i++) {
        uint8_t c = input[i];

        // Follow failure links until a transition is found
        while (state != 0 && d_automaton[state].goto_table[c] == -1) {
            state = d_automaton[state].failure;
        }

        int next = d_automaton[state].goto_table[c];
        state = (next != -1) ? next : 0;

        // Check for pattern matches at this state
        int out_state = state;
        while (out_state != -1 && out_state != 0) {
            int pat_id = d_automaton[out_state].output_pattern;
            if (pat_id >= 0 && pat_id < d_n_patterns) {
                // Record the first match position for this pattern
                // Use atomicMin to keep the earliest match
                atomicMin(&match_positions[pat_id], i);
                atomicAdd(match_count, 1);
            }
            out_state = d_automaton[out_state].output_next;
        }
    }
}

// Batch scanner: process multiple inputs in parallel
__global__ void security_scan_batch_kernel(
    const uint8_t* __restrict__  inputs,           // concatenated inputs
    const int*     __restrict__  input_offsets,     // [batch_size + 1]
    const int                    batch_size,
    int*           __restrict__  match_positions,   // [batch_size * n_patterns]
    int*           __restrict__  match_counts       // [batch_size]
) {
    const int batch_idx  = blockIdx.y;
    const int tid        = blockIdx.x * blockDim.x + threadIdx.x;

    if (batch_idx >= batch_size) return;

    const int start = input_offsets[batch_idx];
    const int end   = input_offsets[batch_idx + 1];
    const int len   = end - start;

    const int n_threads = gridDim.x * blockDim.x;
    const int chunk     = (len + n_threads - 1) / n_threads;
    const int overlap   = MAX_PATTERN_LEN - 1;
    const int my_start  = start + tid * chunk;
    const int my_end    = min(my_start + chunk + overlap, end);

    if (my_start >= end) return;

    int state = 0;
    int* my_positions = match_positions + batch_idx * d_n_patterns;

    for (int i = my_start; i < my_end; i++) {
        uint8_t c = inputs[i];
        while (state != 0 && d_automaton[state].goto_table[c] == -1) {
            state = d_automaton[state].failure;
        }
        int next = d_automaton[state].goto_table[c];
        state = (next != -1) ? next : 0;

        int out_state = state;
        while (out_state != -1 && out_state != 0) {
            int pat_id = d_automaton[out_state].output_pattern;
            if (pat_id >= 0 && pat_id < d_n_patterns) {
                atomicMin(&my_positions[pat_id], i - start);
                atomicAdd(&match_counts[batch_idx], 1);
            }
            out_state = d_automaton[out_state].output_next;
        }
    }
}
"""


class SecurityScanKernel:
    """GPU-accelerated multi-pattern security scanner.

    Uses a parallelised Aho-Corasick algorithm to scan input data against
    a database of threat signature patterns.  Each thread processes a chunk
    of the input with overlap windows to guarantee no pattern is missed at
    chunk boundaries.
    """

    def __init__(self) -> None:
        """Initialise the security scan kernel with default parameters."""
        self.n_patterns: int = 503
        self.block_size: int = 128
        self.grid_size: Tuple[int, ...] = ((self.n_patterns + 127) // 128,)
        self.max_pattern_len: int = 256
        self.source = KERNEL_SOURCE
        log.info(
            "SecurityScanKernel: %d patterns, block=%d, grid=%s",
            self.n_patterns,
            self.block_size,
            self.grid_size,
        )

    def estimate_scan_time_us(self, input_length: int) -> float:
        """Estimate wall-clock scan time for a given input size.

        The estimate is based on:
        - Memory-bound read of the input at A100 HBM bandwidth (2039 GB/s)
          at ~70 % effective utilisation.
        - Per-byte automaton traversal overhead (~2 ns amortised per byte on
          GPU, dominated by random-access latency into constant memory).
        - Overlap overhead proportional to (n_threads * max_pattern_len).

        Args:
            input_length: Length of the input data in bytes.

        Returns:
            Estimated scan time in microseconds.
        """
        if input_length <= 0:
            return 0.0

        # A100 effective bandwidth
        effective_bw = 2039e9 * 0.70  # bytes/sec

        # Pure memory transfer time
        transfer_us = (input_length / effective_bw) * 1e6

        # Automaton traversal overhead: ~2 ns per byte
        traversal_us = input_length * 2e-3  # 2 ns = 0.002 us per byte

        # Overlap overhead: extra bytes re-scanned at chunk boundaries
        total_threads = self.grid_size[0] * self.block_size
        overlap_bytes = total_threads * (self.max_pattern_len - 1)
        overlap_us = (overlap_bytes / effective_bw) * 1e6

        # Kernel launch overhead
        launch_overhead_us = 3.5  # typical A100 kernel launch latency

        total_us = transfer_us + traversal_us + overlap_us + launch_overhead_us
        return round(total_us, 3)

    def compute_grid(self) -> Tuple[int, ...]:
        """Return the CUDA grid dimensions for the scanner.

        Returns:
            The grid dimensions tuple.
        """
        return self.grid_size

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return Orchestra tool definitions for the security scanner.

        Returns:
            A list of tool dictionaries for the Orchestra tool-calling interface.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "security_scan_estimate",
                    "description": (
                        "Estimate GPU scan time for the multi-pattern "
                        "Aho-Corasick security scanner given an input size."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input_length": {
                                "type": "integer",
                                "description": (
                                    "Length of input data in bytes to scan"
                                ),
                            },
                        },
                        "required": ["input_length"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "security_scan_info",
                    "description": (
                        "Return configuration details for the security "
                        "scan kernel including pattern count and grid size."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]
