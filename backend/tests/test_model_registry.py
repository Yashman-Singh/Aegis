from __future__ import annotations

from backend.hardware.model_registry import (
    MODEL_VRAM_REGISTRY,
    RegistryEntry,
    get_model_vram_estimate,
    set_empirical_registry,
)


def test_model_registry_prefix_and_default(monkeypatch):
    monkeypatch.setenv("AEGIS_CONCURRENT_VRAM_BUFFER", "0.20")
    set_empirical_registry([])

    expected_prefix = int(MODEL_VRAM_REGISTRY["llama3.2:3b"] * 1.2)
    expected_default = int(MODEL_VRAM_REGISTRY["__default__"] * 1.2)

    assert get_model_vram_estimate("llama3.2:3b-instruct") == expected_prefix
    assert get_model_vram_estimate("custom/unknown-model") == expected_default


def test_model_registry_prefers_empirical(monkeypatch):
    monkeypatch.setenv("AEGIS_CONCURRENT_VRAM_BUFFER", "0.0")
    set_empirical_registry(
        [
            RegistryEntry(
                model_name="llama3.2:3b",
                p95_bytes=3_333_333_333,
                sample_count=20,
                source="empirical",
            )
        ]
    )

    assert get_model_vram_estimate("llama3.2:3b") == 3_333_333_333
