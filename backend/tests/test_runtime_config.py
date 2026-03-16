from __future__ import annotations

from backend.core.runtime_config import load_runtime_config


def test_runtime_config_disables_incompatible_features(monkeypatch):
    monkeypatch.setenv("AEGIS_MAX_CONCURRENT_JOBS", "2")
    monkeypatch.setenv("AEGIS_WARM_CACHE_ENABLED", "true")
    monkeypatch.setenv("AEGIS_PROFILE_VRAM", "true")

    cfg = load_runtime_config()

    assert cfg.max_concurrent_jobs == 2
    assert cfg.warm_cache_enabled is True
    assert cfg.profile_vram_enabled is True
    assert cfg.warm_cache_effective is False
    assert cfg.profile_vram_effective is False


def test_runtime_config_keeps_single_worker_defaults(monkeypatch):
    monkeypatch.setenv("AEGIS_MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("AEGIS_WARM_CACHE_ENABLED", "true")
    monkeypatch.setenv("AEGIS_PROFILE_VRAM", "true")

    cfg = load_runtime_config()

    assert cfg.warm_cache_effective is True
    assert cfg.profile_vram_effective is True
