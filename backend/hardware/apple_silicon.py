"""
Apple Silicon hardware monitor using pyobjc-framework-Metal.

Uses MTLCreateSystemDefaultDevice().recommendedMaxWorkingSetSize() for the
VRAM capacity ceiling.  Current usage is approximated via psutil system RAM
pressure — this is an acknowledged V1 limitation on unified-memory systems.

IMPORTANT: Do NOT use psutil for GPU memory on Apple Silicon.  psutil reports
system RAM, not the unified-memory budget available to the GPU.  psutil is
used here ONLY as a rough proxy for current consumption.
"""

from __future__ import annotations

import logging
import os
import sys

import psutil

from backend.hardware.registry import HardwareMonitor

logger = logging.getLogger(__name__)


class AppleSiliconMonitor(HardwareMonitor):
    """Hardware monitor for Apple Silicon Macs via Metal."""

    # Cached at class level after first successful check
    _metal_device = None

    @classmethod
    def is_available(cls) -> bool:
        if sys.platform != "darwin":
            return False
        try:
            from Metal import MTLCreateSystemDefaultDevice  # type: ignore[import-untyped]

            device = MTLCreateSystemDefaultDevice()
            if device is None:
                return False
            cls._metal_device = device
            return True
        except ImportError:
            return False

    def __init__(self) -> None:
        if self._metal_device is None:
            from Metal import MTLCreateSystemDefaultDevice  # type: ignore[import-untyped]

            self._metal_device = MTLCreateSystemDefaultDevice()

        # Apple-recommended safe maximum working set size for GPU allocations
        self._recommended_max: int = self._metal_device.recommendedMaxWorkingSetSize()

        # Configurable safety threshold (fraction of recommendedMaxWorkingSetSize)
        threshold_str = os.getenv("AEGIS_VRAM_THRESHOLD", "0.75")
        self._threshold: float = max(0.0, min(1.0, float(threshold_str)))

        # The effective ceiling we treat as "total allocatable VRAM"
        self._effective_total: int = int(self._recommended_max * self._threshold)

        logger.info(
            "AppleSiliconMonitor initialised: recommendedMax=%s bytes, "
            "threshold=%.2f, effectiveTotal=%s bytes",
            self._recommended_max,
            self._threshold,
            self._effective_total,
        )

    def get_vram_total_bytes(self) -> int:
        """Effective total = recommendedMaxWorkingSetSize * threshold."""
        return self._effective_total

    def get_vram_used_bytes(self) -> int:
        """
        Approximate VRAM usage via system RAM pressure.

        On unified-memory Apple Silicon, GPU and CPU share the same physical
        RAM.  psutil.virtual_memory().used is an imprecise but usable proxy.
        This is a documented V1 limitation.
        """
        vm = psutil.virtual_memory()
        # Scale the system-wide used memory proportionally to our effective total
        used_fraction = vm.used / vm.total
        return int(self._effective_total * used_fraction)

    def get_vram_free_bytes(self) -> int:
        return self.get_vram_total_bytes() - self.get_vram_used_bytes()
