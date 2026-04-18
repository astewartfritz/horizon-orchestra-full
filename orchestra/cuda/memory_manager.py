"""GPU memory allocation, pooling, peer-to-peer transfers, and unified memory."""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger("orchestra.cuda.memory_manager")

__all__ = [
    "GPUMemoryManager",
    "GPUAllocation",
    "MemoryStats",
    "UnifiedAllocation",
]

# Valid pool names
POOL_NAMES: Set[str] = {"default", "pinned", "managed", "peer"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GPUAllocation:
    """Represents a single GPU memory allocation."""

    ptr: int
    size_bytes: int
    pool: str
    device_id: int
    allocated_at: float
    tag: str = ""


@dataclass
class UnifiedAllocation:
    """Represents a unified (managed) memory allocation visible to CPU and GPU."""

    ptr: int
    size_bytes: int
    cpu_resident: bool
    gpu_resident: bool
    allocated_at: float


@dataclass
class MemoryStats:
    """Snapshot of GPU memory usage statistics."""

    device_id: int
    total_bytes: int
    allocated_bytes: int
    free_bytes: int
    peak_allocated_bytes: int
    n_allocations: int
    pool_breakdown: Dict[str, int]
    fragmentation_estimate: float
    unified_allocations: int
    unified_total_bytes: int


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class GPUMemoryManager:
    """Manages simulated GPU memory allocation, pools, and transfers.

    Each device maintains independent allocation tracking with support for
    multiple memory pools, peer-to-peer copies, and unified memory.
    """

    # A100 SXM4 total memory in bytes (80 GB)
    DEFAULT_TOTAL_BYTES: int = 80 * 1024 * 1024 * 1024

    # NVLink 3.0 bidirectional bandwidth for A100 SXM pairs (bytes/sec)
    NVLINK_BW_BYTES_PER_SEC: float = 600.0 * 1e9  # 600 GB/s

    def __init__(self, device_ids: Optional[List[int]] = None) -> None:
        """Initialise the memory manager for one or more devices.

        Args:
            device_ids: GPU ordinal indices to manage.  Defaults to ``[0]``.
        """
        if device_ids is None:
            device_ids = [0]

        self._device_ids = device_ids

        # Per-device allocation tracking: device_id -> {ptr -> GPUAllocation}
        self._allocations: Dict[int, Dict[int, GPUAllocation]] = {
            d: {} for d in device_ids
        }

        # Per-device total memory
        self._total_bytes: Dict[int, int] = {
            d: self.DEFAULT_TOTAL_BYTES for d in device_ids
        }

        # Pointer counter (simulates device pointers)
        self._ptr_counter: int = 0x7F00_0000_0000

        # Peak usage tracking per device
        self._peak_bytes: Dict[int, int] = {d: 0 for d in device_ids}

        # Defragment counter per device (tracks accumulated fragmentation)
        self._frag_ops: Dict[int, int] = {d: 0 for d in device_ids}

        # Unified memory allocations (not device-specific)
        self._unified: Dict[int, UnifiedAllocation] = {}

        log.info("GPUMemoryManager initialised for devices %s", device_ids)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_ptr(self) -> int:
        """Return the next simulated device pointer."""
        self._ptr_counter += 256  # 256-byte alignment
        return self._ptr_counter

    def _allocated_bytes(self, device_id: int) -> int:
        """Sum of all allocation sizes on a device."""
        return sum(a.size_bytes for a in self._allocations[device_id].values())

    def _validate_device(self, device_id: int) -> None:
        """Raise if *device_id* is not managed."""
        if device_id not in self._allocations:
            raise ValueError(
                f"Device {device_id} is not managed. "
                f"Available: {self._device_ids}"
            )

    # ------------------------------------------------------------------
    # Allocate / Free
    # ------------------------------------------------------------------

    def allocate(
        self,
        size_bytes: int,
        *,
        device_id: int = 0,
        pool: str = "default",
        tag: str = "",
    ) -> GPUAllocation:
        """Allocate GPU memory from the specified pool.

        Args:
            size_bytes: Number of bytes to allocate.
            device_id: Target GPU device ordinal.
            pool: Memory pool name (``default``, ``pinned``, ``managed``,
                or ``peer``).
            tag: Optional human-readable tag for debugging.

        Returns:
            A :class:`GPUAllocation` describing the new allocation.

        Raises:
            ValueError: If the pool name is invalid or the device is unknown.
            MemoryError: If insufficient free memory remains.
        """
        self._validate_device(device_id)

        if pool not in POOL_NAMES:
            raise ValueError(
                f"Unknown pool '{pool}'. Valid pools: {sorted(POOL_NAMES)}"
            )

        used = self._allocated_bytes(device_id)
        available = self._total_bytes[device_id] - used

        if size_bytes > available:
            raise MemoryError(
                f"Allocation of {size_bytes} bytes exceeds available "
                f"{available} bytes on device {device_id}"
            )

        ptr = self._next_ptr()
        alloc = GPUAllocation(
            ptr=ptr,
            size_bytes=size_bytes,
            pool=pool,
            device_id=device_id,
            allocated_at=time.time(),
            tag=tag,
        )
        self._allocations[device_id][ptr] = alloc

        # Update peak
        new_used = used + size_bytes
        if new_used > self._peak_bytes[device_id]:
            self._peak_bytes[device_id] = new_used

        # Increment fragmentation counter
        self._frag_ops[device_id] += 1

        log.debug(
            "Allocated %d bytes on device %d pool=%s ptr=0x%X tag='%s'",
            size_bytes,
            device_id,
            pool,
            ptr,
            tag,
        )
        return alloc

    def free(self, allocation: GPUAllocation) -> None:
        """Free a previously allocated GPU memory block.

        Args:
            allocation: The allocation to release.

        Raises:
            ValueError: If the allocation is not found on the expected device.
        """
        device_id = allocation.device_id
        self._validate_device(device_id)

        if allocation.ptr not in self._allocations[device_id]:
            raise ValueError(
                f"Allocation ptr=0x{allocation.ptr:X} not found on device {device_id}"
            )

        del self._allocations[device_id][allocation.ptr]
        self._frag_ops[device_id] += 1

        log.debug(
            "Freed %d bytes on device %d ptr=0x%X",
            allocation.size_bytes,
            device_id,
            allocation.ptr,
        )

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------

    def peer_to_peer_copy(
        self,
        src_allocation: GPUAllocation,
        dst_device_id: int,
        *,
        pool: str = "peer",
    ) -> GPUAllocation:
        """Copy an allocation from one GPU to another over NVLink.

        Calculates the expected transfer time based on NVLink 3.0 bandwidth
        for A100 SXM pairs (600 GB/s bidirectional).

        Args:
            src_allocation: The source allocation to copy.
            dst_device_id: Destination GPU ordinal.
            pool: Pool to allocate into on the destination device.

        Returns:
            A new :class:`GPUAllocation` on the destination device.
        """
        self._validate_device(dst_device_id)

        if dst_device_id == src_allocation.device_id:
            log.warning("P2P copy to same device %d is a no-op", dst_device_id)

        transfer_time_s = src_allocation.size_bytes / self.NVLINK_BW_BYTES_PER_SEC
        transfer_time_us = transfer_time_s * 1e6

        dst_alloc = self.allocate(
            src_allocation.size_bytes,
            device_id=dst_device_id,
            pool=pool,
            tag=f"p2p_from_dev{src_allocation.device_id}:{src_allocation.tag}",
        )

        log.info(
            "P2P copy %d bytes dev%d -> dev%d in %.2f us (%.2f GB/s effective)",
            src_allocation.size_bytes,
            src_allocation.device_id,
            dst_device_id,
            transfer_time_us,
            (src_allocation.size_bytes / transfer_time_s / 1e9)
            if transfer_time_s > 0
            else 0.0,
        )
        return dst_alloc

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_memory_stats(self, device_id: int = 0) -> MemoryStats:
        """Retrieve memory usage statistics for a device.

        Args:
            device_id: GPU ordinal to query.

        Returns:
            A :class:`MemoryStats` snapshot.
        """
        self._validate_device(device_id)

        allocations = self._allocations[device_id]
        allocated = self._allocated_bytes(device_id)
        total = self._total_bytes[device_id]

        # Pool breakdown
        pool_breakdown: Dict[str, int] = {}
        for alloc in allocations.values():
            pool_breakdown[alloc.pool] = (
                pool_breakdown.get(alloc.pool, 0) + alloc.size_bytes
            )

        # Fragmentation estimate: ratio of ops to allocations, capped at 1.0
        n_allocs = len(allocations)
        if n_allocs > 0 and self._frag_ops[device_id] > 0:
            frag = min(
                1.0,
                (self._frag_ops[device_id] - n_allocs) / (self._frag_ops[device_id] + n_allocs),
            )
            frag = max(0.0, frag)
        else:
            frag = 0.0

        # Unified stats
        unified_count = len(self._unified)
        unified_bytes = sum(u.size_bytes for u in self._unified.values())

        stats = MemoryStats(
            device_id=device_id,
            total_bytes=total,
            allocated_bytes=allocated,
            free_bytes=total - allocated,
            peak_allocated_bytes=self._peak_bytes[device_id],
            n_allocations=n_allocs,
            pool_breakdown=pool_breakdown,
            fragmentation_estimate=round(frag, 4),
            unified_allocations=unified_count,
            unified_total_bytes=unified_bytes,
        )
        log.debug(
            "Memory stats dev%d: %d/%d bytes used (%.1f%%), frag=%.2f%%",
            device_id,
            allocated,
            total,
            (allocated / total * 100) if total > 0 else 0.0,
            frag * 100,
        )
        return stats

    # ------------------------------------------------------------------
    # Defragment
    # ------------------------------------------------------------------

    def defragment(self, device_id: int = 0) -> Dict[str, Any]:
        """Compact allocations on a device to reduce fragmentation.

        Simulates moving all allocations into a contiguous block starting
        from the base pointer, and resets the fragmentation counter.

        Args:
            device_id: GPU ordinal to defragment.

        Returns:
            A dict summarising the defragmentation results.
        """
        self._validate_device(device_id)

        allocs = list(self._allocations[device_id].values())
        n_before = self._frag_ops[device_id]

        # Sort by allocation time and reassign contiguous pointers
        allocs.sort(key=lambda a: a.allocated_at)
        new_map: Dict[int, GPUAllocation] = {}
        current_ptr = 0x7F00_0000_0000 + (device_id * 0x10_0000_0000)

        for alloc in allocs:
            new_alloc = GPUAllocation(
                ptr=current_ptr,
                size_bytes=alloc.size_bytes,
                pool=alloc.pool,
                device_id=alloc.device_id,
                allocated_at=alloc.allocated_at,
                tag=alloc.tag,
            )
            new_map[current_ptr] = new_alloc
            current_ptr += alloc.size_bytes
            # Align to 256 bytes
            remainder = current_ptr % 256
            if remainder != 0:
                current_ptr += 256 - remainder

        self._allocations[device_id] = new_map
        self._frag_ops[device_id] = len(allocs)  # Reset counter

        result = {
            "device_id": device_id,
            "allocations_compacted": len(allocs),
            "fragmentation_ops_before": n_before,
            "fragmentation_ops_after": len(allocs),
            "contiguous_range_start": f"0x{0x7F00_0000_0000 + (device_id * 0x10_0000_0000):X}",
            "contiguous_range_end": f"0x{current_ptr:X}",
        }
        log.info(
            "Defragmented device %d: compacted %d allocations, frag ops %d -> %d",
            device_id,
            len(allocs),
            n_before,
            len(allocs),
        )
        return result

    # ------------------------------------------------------------------
    # Unified Memory
    # ------------------------------------------------------------------

    def enable_unified_memory(
        self,
        size_bytes: int,
        *,
        cpu_resident: bool = True,
        gpu_resident: bool = True,
    ) -> UnifiedAllocation:
        """Create a unified (managed) memory allocation.

        Unified memory is accessible from both CPU and GPU with automatic
        page migration handled by the CUDA runtime.

        Args:
            size_bytes: Number of bytes to allocate.
            cpu_resident: Whether data initially resides on CPU.
            gpu_resident: Whether data initially resides on GPU.

        Returns:
            A :class:`UnifiedAllocation` tracking residency.
        """
        ptr = self._next_ptr()

        alloc = UnifiedAllocation(
            ptr=ptr,
            size_bytes=size_bytes,
            cpu_resident=cpu_resident,
            gpu_resident=gpu_resident,
            allocated_at=time.time(),
        )
        self._unified[ptr] = alloc

        log.info(
            "Unified allocation: %d bytes ptr=0x%X cpu=%s gpu=%s",
            size_bytes,
            ptr,
            cpu_resident,
            gpu_resident,
        )
        return alloc

    def free_unified(self, allocation: UnifiedAllocation) -> None:
        """Free a unified memory allocation.

        Args:
            allocation: The unified allocation to release.

        Raises:
            ValueError: If the allocation is not tracked.
        """
        if allocation.ptr not in self._unified:
            raise ValueError(
                f"Unified allocation ptr=0x{allocation.ptr:X} not found"
            )
        del self._unified[allocation.ptr]
        log.debug("Freed unified allocation ptr=0x%X", allocation.ptr)

    def migrate_unified(
        self,
        allocation: UnifiedAllocation,
        *,
        to_cpu: bool = False,
        to_gpu: bool = False,
    ) -> UnifiedAllocation:
        """Migrate a unified allocation's residency.

        Args:
            allocation: The unified allocation to migrate.
            to_cpu: Set CPU residency.
            to_gpu: Set GPU residency.

        Returns:
            The updated :class:`UnifiedAllocation`.
        """
        if allocation.ptr not in self._unified:
            raise ValueError(
                f"Unified allocation ptr=0x{allocation.ptr:X} not found"
            )

        updated = UnifiedAllocation(
            ptr=allocation.ptr,
            size_bytes=allocation.size_bytes,
            cpu_resident=to_cpu if to_cpu or to_gpu else allocation.cpu_resident,
            gpu_resident=to_gpu if to_cpu or to_gpu else allocation.gpu_resident,
            allocated_at=allocation.allocated_at,
        )
        self._unified[allocation.ptr] = updated

        log.info(
            "Migrated unified ptr=0x%X: cpu=%s gpu=%s",
            allocation.ptr,
            updated.cpu_resident,
            updated.gpu_resident,
        )
        return updated
