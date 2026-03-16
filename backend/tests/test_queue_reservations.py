from __future__ import annotations

import asyncio

import pytest

from backend.core.queue_engine import (
    init_queue_engine,
    release_reservation,
    try_reserve_vram,
)
from backend.core.runtime_config import load_runtime_config


class _MonitorStub:
    def __init__(self, total_bytes: int, free_bytes: int) -> None:
        self._total = total_bytes
        self._free = free_bytes

    def get_vram_total_bytes(self) -> int:
        return self._total

    def get_vram_free_bytes(self) -> int:
        return self._free

    def get_vram_used_bytes(self) -> int:
        return self._total - self._free


class _OllamaStub:
    async def evict(self, model_name: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_atomic_reservation_prevents_overcommit(monkeypatch):
    monkeypatch.setenv("AEGIS_MAX_CONCURRENT_JOBS", "2")
    monkeypatch.setenv("AEGIS_CONCURRENT_VRAM_BUFFER", "0.0")
    monkeypatch.setenv("AEGIS_EMERGENCY_VRAM_FLOOR_BYTES", "0")
    monkeypatch.setenv("AEGIS_WARM_CACHE_ENABLED", "false")
    monkeypatch.setenv("AEGIS_PROFILE_VRAM", "false")

    cfg = load_runtime_config()
    monitor = _MonitorStub(total_bytes=4_000_000_000, free_bytes=4_000_000_000)
    init_queue_engine(monitor, _OllamaStub(), cfg)

    r1, r2 = await asyncio.gather(
        try_reserve_vram("job-a", "llama3.2:3b"),
        try_reserve_vram("job-b", "llama3.2:3b"),
    )

    assert sorted([r1, r2]) == [False, True]

    await release_reservation("job-a")
    await release_reservation("job-b")

    r3 = await try_reserve_vram("job-c", "llama3.2:3b")
    assert r3 is True
    await release_reservation("job-c")
