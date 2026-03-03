"""
Hardware monitor registry — dynamic provider loading at startup.

Iterates registered HardwareMonitor subclasses in priority order, calls
each class's is_available() classmethod, and instantiates the first match.
The rest of the application interacts only with the abstract interface.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class HardwareMonitor(ABC):
    """Abstract base class for hardware telemetry providers."""

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Return True if this provider can run on the current platform."""
        ...

    @abstractmethod
    def get_vram_total_bytes(self) -> int:
        """Return total allocatable VRAM (or system RAM as proxy)."""
        ...

    @abstractmethod
    def get_vram_used_bytes(self) -> int:
        """Return currently used VRAM (or system RAM as proxy)."""
        ...

    @abstractmethod
    def get_vram_free_bytes(self) -> int:
        """Return currently free VRAM (or system RAM as proxy)."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class MonitorRegistry:
    """
    Instantiated at application startup. Iterates providers in priority order
    and activates the first one whose is_available() returns True.
    """

    def __init__(self) -> None:
        # Import here to avoid circular imports and to allow each provider
        # to import HardwareMonitor from this module.
        from backend.hardware.apple_silicon import AppleSiliconMonitor
        from backend.hardware.nvidia import NvidiaMonitor
        from backend.hardware.cpu_fallback import CpuFallbackMonitor

        providers = [AppleSiliconMonitor, NvidiaMonitor, CpuFallbackMonitor]

        self.monitor: HardwareMonitor | None = None

        for provider_cls in providers:
            try:
                if provider_cls.is_available():
                    self.monitor = provider_cls()
                    logger.info(
                        "Hardware provider activated: %s",
                        type(self.monitor).__name__,
                    )
                    break
            except Exception:
                logger.warning(
                    "Provider %s raised during availability check, skipping.",
                    provider_cls.__name__,
                    exc_info=True,
                )

        if self.monitor is None:
            raise RuntimeError(
                "No hardware monitor provider available. "
                "CpuFallbackMonitor should always succeed — this is a bug."
            )
