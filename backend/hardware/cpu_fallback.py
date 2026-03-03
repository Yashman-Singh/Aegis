"""
CPU fallback hardware monitor using psutil.

Reports system RAM as a stand-in for VRAM.  Always available — registered
last in the provider list so it only activates when no GPU provider matches.
Used on systems with no supported GPU (e.g., CI, testing).
"""

from __future__ import annotations

import logging

import psutil

from backend.hardware.registry import HardwareMonitor

logger = logging.getLogger(__name__)


class CpuFallbackMonitor(HardwareMonitor):
    """Fallback monitor that reports system RAM via psutil."""

    @classmethod
    def is_available(cls) -> bool:
        # Always available — last resort.
        return True

    def __init__(self) -> None:
        logger.info(
            "CpuFallbackMonitor initialised (no GPU detected, using system RAM)"
        )

    def get_vram_total_bytes(self) -> int:
        return psutil.virtual_memory().total

    def get_vram_used_bytes(self) -> int:
        return psutil.virtual_memory().used

    def get_vram_free_bytes(self) -> int:
        return psutil.virtual_memory().available
