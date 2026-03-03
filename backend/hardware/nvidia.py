"""
NVIDIA GPU hardware monitor using pynvml.

Queries device index 0 for memory info.  nvmlShutdown() is called in __del__
as a cleanup hook.
"""

from __future__ import annotations

import logging

from backend.hardware.registry import HardwareMonitor

logger = logging.getLogger(__name__)


class NvidiaMonitor(HardwareMonitor):
    """Hardware monitor for NVIDIA GPUs via pynvml."""

    _nvml_initialised: bool = False

    @classmethod
    def is_available(cls) -> bool:
        try:
            import pynvml  # type: ignore[import-untyped]

            pynvml.nvmlInit()
            cls._nvml_initialised = True
            return True
        except (ImportError, Exception):
            return False

    def __init__(self) -> None:
        import pynvml  # type: ignore[import-untyped]

        if not self._nvml_initialised:
            pynvml.nvmlInit()
            self._nvml_initialised = True

        self._pynvml = pynvml
        self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)

        name = pynvml.nvmlDeviceGetName(self._handle)
        logger.info("NvidiaMonitor initialised: device=%s", name)

    def _mem_info(self):
        return self._pynvml.nvmlDeviceGetMemoryInfo(self._handle)

    def get_vram_total_bytes(self) -> int:
        return self._mem_info().total

    def get_vram_used_bytes(self) -> int:
        return self._mem_info().used

    def get_vram_free_bytes(self) -> int:
        return self._mem_info().free

    def __del__(self) -> None:
        try:
            if self._nvml_initialised:
                self._pynvml.nvmlShutdown()
        except Exception:
            pass
