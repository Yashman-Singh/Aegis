"""
Static + empirical VRAM estimate registry.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MODEL_VRAM_REGISTRY = {
    "llama3.2:1b": 800_000_000,
    "llama3.2:3b": 2_200_000_000,
    "llama3:8b": 5_500_000_000,
    "llama3:70b": 42_000_000_000,
    "qwen2.5:1.5b": 1_200_000_000,
    "qwen2.5:7b": 5_000_000_000,
    "gemma:2b": 1_800_000_000,
    "gemma:7b": 5_200_000_000,
    "phi3:mini": 2_300_000_000,
    "__default__": 6_000_000_000,
}


@dataclass
class RegistryEntry:
    model_name: str
    p95_bytes: int
    sample_count: int
    source: str


_empirical_registry: dict[str, RegistryEntry] = {}


def _buffer_multiplier() -> float:
    raw = os.getenv("AEGIS_CONCURRENT_VRAM_BUFFER", "0.20")
    try:
        buffer_value = float(raw)
    except ValueError:
        buffer_value = 0.20
    return 1.0 + max(0.0, buffer_value)


def set_empirical_registry(entries: list[RegistryEntry]) -> None:
    _empirical_registry.clear()
    for entry in entries:
        _empirical_registry[entry.model_name] = entry


def load_registry_cache(path: Path) -> list[RegistryEntry]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        logger.exception("Failed to read registry cache at %s", path)
        return []

    entries: list[RegistryEntry] = []
    for row in data.get("models", []):
        try:
            entries.append(
                RegistryEntry(
                    model_name=str(row["model_name"]),
                    p95_bytes=int(row["p95_bytes"]),
                    sample_count=int(row.get("sample_count", 0)),
                    source=str(row.get("source", "empirical")),
                )
            )
        except Exception:
            logger.warning("Skipping invalid cached registry row: %s", row)
    return entries


def persist_registry_cache(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"models": rows}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _match_registry(model_name: str, source: dict[str, int]) -> tuple[str, int] | None:
    if model_name in source:
        return model_name, source[model_name]
    for key, value in source.items():
        if key == "__default__":
            continue
        if model_name.startswith(key):
            return key, value
    return None


def get_model_vram_estimate(model_name: str) -> int:
    """
    Return P95 estimate + configured safety buffer.
    Preference order: empirical registry -> static registry -> __default__.
    """
    multiplier = _buffer_multiplier()

    if model_name in _empirical_registry:
        return int(_empirical_registry[model_name].p95_bytes * multiplier)
    for key, entry in _empirical_registry.items():
        if model_name.startswith(key):
            return int(entry.p95_bytes * multiplier)

    matched = _match_registry(model_name, MODEL_VRAM_REGISTRY)
    base = matched[1] if matched else MODEL_VRAM_REGISTRY["__default__"]
    return int(base * multiplier)


def get_registry_rows() -> list[dict[str, Any]]:
    """
    Return rows for the registry endpoint and cache persistence.
    Empirical rows are shown when available; static rows otherwise.
    """
    multiplier = _buffer_multiplier()
    rows: list[dict[str, Any]] = []

    if _empirical_registry:
        for model_name, entry in sorted(_empirical_registry.items()):
            rows.append(
                {
                    "model_name": model_name,
                    "p95_bytes": entry.p95_bytes,
                    "with_buffer_bytes": int(entry.p95_bytes * multiplier),
                    "sample_count": entry.sample_count,
                    "source": entry.source,
                }
            )
        return rows

    for model_name, p95 in sorted(MODEL_VRAM_REGISTRY.items()):
        if model_name == "__default__":
            continue
        rows.append(
            {
                "model_name": model_name,
                "p95_bytes": p95,
                "with_buffer_bytes": int(p95 * multiplier),
                "sample_count": 0,
                "source": "static_baseline",
            }
        )
    return rows
