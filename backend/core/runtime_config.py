"""
Runtime configuration parsing and startup policy validation.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _as_bool(name: str, default: str) -> bool:
    raw = os.getenv(name, default).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _as_int(name: str, default: str, minimum: int) -> int:
    raw = os.getenv(name, default).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is invalid; using default=%s", name, raw, default)
        value = int(default)
    if value < minimum:
        logger.warning("%s=%s is below minimum %s; clamping", name, value, minimum)
        value = minimum
    return value


def _as_float(name: str, default: str, minimum: float) -> float:
    raw = os.getenv(name, default).strip()
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is invalid; using default=%s", name, raw, default)
        value = float(default)
    if value < minimum:
        logger.warning("%s=%s is below minimum %.2f; clamping", name, value, minimum)
        value = minimum
    return value


@dataclass(frozen=True)
class RuntimeConfig:
    max_concurrent_jobs: int
    concurrent_vram_buffer: float
    emergency_vram_floor_bytes: int
    model_registry_path: Path
    warm_cache_enabled: bool
    warm_cache_max_drain: int
    profile_vram_enabled: bool
    profile_sample_interval_ms: int
    min_free_vram_bytes: int
    fail_nonterminal_on_startup: bool
    warm_cache_effective: bool
    profile_vram_effective: bool


def load_runtime_config() -> RuntimeConfig:
    max_concurrent = _as_int("AEGIS_MAX_CONCURRENT_JOBS", "1", 1)
    warm_cache_enabled = _as_bool("AEGIS_WARM_CACHE_ENABLED", "true")
    profile_vram_enabled = _as_bool("AEGIS_PROFILE_VRAM", "true")

    warm_cache_effective = warm_cache_enabled
    profile_vram_effective = profile_vram_enabled

    if max_concurrent > 1 and warm_cache_enabled:
        logger.warning(
            "AEGIS_WARM_CACHE_ENABLED=true is incompatible with "
            "AEGIS_MAX_CONCURRENT_JOBS > 1. Warm cache disabled."
        )
        warm_cache_effective = False

    if max_concurrent > 1 and profile_vram_enabled:
        logger.warning(
            "AEGIS_PROFILE_VRAM=true produces unreliable per-job data when "
            "AEGIS_MAX_CONCURRENT_JOBS > 1 (global VRAM cannot be attributed "
            "per-job with concurrent inference). Profiling disabled."
        )
        profile_vram_effective = False

    registry_path = Path(
        os.getenv("AEGIS_MODEL_REGISTRY_PATH", "~/.aegis/model_registry.json")
    ).expanduser()

    return RuntimeConfig(
        max_concurrent_jobs=max_concurrent,
        concurrent_vram_buffer=_as_float("AEGIS_CONCURRENT_VRAM_BUFFER", "0.20", 0.0),
        emergency_vram_floor_bytes=_as_int(
            "AEGIS_EMERGENCY_VRAM_FLOOR_BYTES",
            "1073741824",
            0,
        ),
        model_registry_path=registry_path,
        warm_cache_enabled=warm_cache_enabled,
        warm_cache_max_drain=_as_int("AEGIS_WARM_CACHE_MAX_DRAIN", "10", 1),
        profile_vram_enabled=profile_vram_enabled,
        profile_sample_interval_ms=_as_int(
            "AEGIS_PROFILE_SAMPLE_INTERVAL_MS",
            "500",
            50,
        ),
        min_free_vram_bytes=_as_int("AEGIS_MIN_FREE_VRAM_BYTES", "536870912", 0),
        fail_nonterminal_on_startup=_as_bool("AEGIS_FAIL_NONTERMINAL_ON_STARTUP", "false"),
        warm_cache_effective=warm_cache_effective,
        profile_vram_effective=profile_vram_effective,
    )
