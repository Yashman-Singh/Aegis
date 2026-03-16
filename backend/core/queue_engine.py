"""
Queue engine — asyncio.PriorityQueue consumer loop with V2 scheduling controls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from backend.core.database import (
    create_job,
    delete_stale_jobs,
    get_job_by_id,
    get_model_peak_samples,
    get_model_vram_profiles,
    update_job_fields,
    update_job_status,
    upsert_model_vram_profile,
)
from backend.core.ollama_client import OllamaClient
from backend.core.runtime_config import RuntimeConfig
from backend.hardware.model_registry import (
    RegistryEntry,
    get_model_vram_estimate,
    get_registry_rows,
    load_registry_cache,
    persist_registry_cache,
    set_empirical_registry,
)
from backend.hardware.registry import HardwareMonitor

logger = logging.getLogger(__name__)


class ModelState(Enum):
    IDLE = "idle"
    LOADED = "loaded"
    EVICTING = "evicting"


# ---------------------------------------------------------------------------
# Module-level state (initialised by init_queue_engine)
# ---------------------------------------------------------------------------

queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
inference_lock: asyncio.Lock = asyncio.Lock()
reservations_lock: asyncio.Lock = asyncio.Lock()
models_registry_lock: asyncio.Lock = asyncio.Lock()
runtime_state_lock: asyncio.Lock = asyncio.Lock()
registry_update_lock: asyncio.Lock = asyncio.Lock()

_monitor: HardwareMonitor | None = None
_ollama: OllamaClient | None = None
_config: RuntimeConfig | None = None

active_reservations: dict[str, int] = {}
model_locks: dict[str, asyncio.Lock] = {}
model_states: dict[str, ModelState] = {}
model_refcounts: dict[str, int] = {}
running_jobs: dict[str, str] = {}  # job_id -> model_name

warm_cache_active: bool = False
warm_cache_model: str | None = None
warm_cache_queue_depth: int = 0


def init_queue_engine(
    monitor: HardwareMonitor,
    ollama: OllamaClient,
    config: RuntimeConfig,
) -> None:
    """Bind runtime dependencies. Call once at startup."""
    global _monitor, _ollama, _config
    _monitor = monitor
    _ollama = ollama
    _config = config
    logger.info(
        "Queue engine initialised (max_concurrent=%d, warm_cache=%s, profiling=%s)",
        _config.max_concurrent_jobs,
        _config.warm_cache_effective,
        _config.profile_vram_effective,
    )


def get_worker_count() -> int:
    assert _config is not None
    return _config.max_concurrent_jobs


async def initialize_model_registry_state() -> None:
    """
    Load empirical profile rows from DB.
    If DB is empty, seed from JSON cache path and then hydrate in-memory state.
    """
    assert _config is not None

    profiles = await get_model_vram_profiles()
    if not profiles:
        cached = load_registry_cache(_config.model_registry_path)
        for entry in cached:
            await upsert_model_vram_profile(
                model_name=entry.model_name,
                p95_bytes=entry.p95_bytes,
                sample_count=entry.sample_count,
                source=entry.source,
            )
        profiles = await get_model_vram_profiles()

    entries = [
        RegistryEntry(
            model_name=row.model_name,
            p95_bytes=row.p95_bytes,
            sample_count=row.sample_count,
            source=row.source,
        )
        for row in profiles
    ]
    set_empirical_registry(entries)
    await _persist_registry_cache()


async def submit_job(model_name: str, priority: int, payload: dict) -> str:
    """Create a DB row (QUEUED) and enqueue. Returns the job_id."""
    job = await create_job(model_name, priority, payload)
    await queue.put((priority, job.created_at.timestamp(), job.id))
    logger.info("Job %s enqueued (model=%s, priority=%d)", job.id, model_name, priority)
    return job.id


async def get_model_lock(model_name: str) -> asyncio.Lock:
    async with models_registry_lock:
        if model_name not in model_locks:
            model_locks[model_name] = asyncio.Lock()
            model_states[model_name] = ModelState.IDLE
            model_refcounts[model_name] = 0
        return model_locks[model_name]


async def acquire_model(model_name: str) -> None:
    lock = await get_model_lock(model_name)
    async with lock:
        model_states[model_name] = ModelState.LOADED
        model_refcounts[model_name] += 1


async def release_model(model_name: str) -> None:
    assert _ollama is not None

    lock = await get_model_lock(model_name)
    async with lock:
        model_refcounts[model_name] -= 1
        if model_refcounts[model_name] <= 0:
            model_states[model_name] = ModelState.EVICTING
            await _ollama.evict(model_name)
            model_states[model_name] = ModelState.IDLE
            model_refcounts[model_name] = 0


async def try_reserve_vram(job_id: str, model_name: str) -> bool:
    """
    Atomically checks VRAM availability and writes reservation if safe.
    Both gates evaluated and reservation written inside one critical section.
    """
    assert _monitor is not None
    assert _config is not None

    estimated = get_model_vram_estimate(model_name)

    async with reservations_lock:
        total_reserved = sum(active_reservations.values())
        vram_threshold_bytes = _monitor.get_vram_total_bytes()
        if total_reserved + estimated > vram_threshold_bytes:
            return False

        live_free = _monitor.get_vram_free_bytes()
        if live_free < estimated + _config.emergency_vram_floor_bytes:
            return False

        active_reservations[job_id] = estimated
        return True


async def release_reservation(job_id: str) -> None:
    async with reservations_lock:
        active_reservations.pop(job_id, None)


async def _set_warm_cache_state(
    *,
    active: bool,
    model_name: str | None,
    queue_depth: int,
) -> None:
    global warm_cache_active, warm_cache_model, warm_cache_queue_depth
    async with runtime_state_lock:
        warm_cache_active = active
        warm_cache_model = model_name
        warm_cache_queue_depth = queue_depth


async def _mark_running(job_id: str, model_name: str) -> None:
    async with runtime_state_lock:
        running_jobs[job_id] = model_name


async def _unmark_running(job_id: str) -> None:
    async with runtime_state_lock:
        running_jobs.pop(job_id, None)


async def get_runtime_metrics_snapshot() -> dict:
    assert _monitor is not None
    assert _config is not None

    async with reservations_lock:
        reserved_total = sum(active_reservations.values())

    async with runtime_state_lock:
        running_count = len(running_jobs)
        running_models = sorted(set(running_jobs.values()))
        warm_active = warm_cache_active
        warm_model = warm_cache_model
        warm_depth = warm_cache_queue_depth

    async with models_registry_lock:
        loaded_models = sorted(
            model_name
            for model_name, count in model_refcounts.items()
            if count > 0
        )
        if not loaded_models:
            loaded_models = running_models

    return {
        "loaded_models": loaded_models,
        "currently_running": running_count,
        "active_reservations_bytes": reserved_total,
        "vram_available_for_scheduling": max(
            0,
            _monitor.get_vram_free_bytes() - _config.emergency_vram_floor_bytes,
        ),
        "warm_cache_active": warm_active,
        "warm_cache_model": warm_model,
        "warm_cache_queue_depth": warm_depth,
        "max_concurrent_jobs": _config.max_concurrent_jobs,
    }


async def _profile_vram_during_inference(job_id: str, infer_task: asyncio.Task) -> int:
    """Only reliable when max_concurrent_jobs == 1."""
    assert _monitor is not None
    assert _config is not None

    peak = 0
    interval = _config.profile_sample_interval_ms / 1000.0
    while not infer_task.done():
        current = _monitor.get_vram_used_bytes()
        peak = max(peak, current)
        await asyncio.sleep(interval)
    current = _monitor.get_vram_used_bytes()
    peak = max(peak, current)
    await update_job_fields(job_id, vram_actual_peak_bytes=peak)
    return peak


def _percentile_95(samples: list[int]) -> int:
    ordered = sorted(samples)
    idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[idx]


async def _persist_registry_cache() -> None:
    assert _config is not None
    rows = get_registry_rows()
    persist_registry_cache(_config.model_registry_path, rows)


async def _refresh_empirical_registry_for_model(model_name: str) -> None:
    """
    Recompute p95 from sampled completed jobs and persist profile once enough
    observations are available.
    """
    async with registry_update_lock:
        peaks = await get_model_peak_samples(model_name)
        if len(peaks) < 20:
            return
        p95 = _percentile_95(peaks)
        await upsert_model_vram_profile(
            model_name=model_name,
            p95_bytes=p95,
            sample_count=len(peaks),
            source="empirical",
        )

        profiles = await get_model_vram_profiles()
        set_empirical_registry(
            [
                RegistryEntry(
                    model_name=row.model_name,
                    p95_bytes=row.p95_bytes,
                    sample_count=row.sample_count,
                    source=row.source,
                )
                for row in profiles
            ]
        )
        await _persist_registry_cache()


async def _run_job(job_id: str, model_name: str, payload: dict) -> None:
    assert _ollama is not None
    assert _config is not None

    await update_job_status(job_id, "ALLOCATING")
    started = datetime.now(timezone.utc)
    await update_job_status(job_id, "RUNNING", started_at=started)
    await _mark_running(job_id, model_name)

    peak_value: int | None = None
    try:
        if _config.profile_vram_effective and _config.max_concurrent_jobs == 1:
            infer_task = asyncio.create_task(_ollama.generate(model_name, payload))
            peak_value = await _profile_vram_during_inference(job_id, infer_task)
            response = await infer_task
        else:
            response = await _ollama.generate(model_name, payload)

        completed = datetime.now(timezone.utc)
        if response.status_code == 200:
            await update_job_status(
                job_id,
                "COMPLETED",
                completed_at=completed,
                result=response.json(),
            )
            if peak_value is not None:
                await _refresh_empirical_registry_for_model(model_name)
        else:
            await update_job_status(
                job_id,
                "FAILED",
                completed_at=completed,
                error=f"Ollama returned {response.status_code}: {response.text[:500]}",
            )
    except Exception:
        logger.exception("Unhandled error processing job %s", job_id)
        await update_job_status(
            job_id,
            "FAILED",
            completed_at=datetime.now(timezone.utc),
            error="Internal error — see server logs",
        )
    finally:
        await _unmark_running(job_id)


async def _extract_same_model_jobs(
    model_name: str, current_batch_id: str
) -> list[tuple[str, dict]]:
    """
    Drain QUEUED jobs for the given model from the priority queue.
    Must only run in effective single-worker mode.
    """
    assert _config is not None

    same_model: list[tuple[str, dict]] = []
    remaining: list[tuple[int, float, str]] = []

    while not queue.empty():
        try:
            item = queue.get_nowait()
            priority, timestamp, job_id = item
            job = await get_job_by_id(job_id)

            if (
                job is not None
                and job.model_name == model_name
                and job.status == "QUEUED"
                and len(same_model) < _config.warm_cache_max_drain
            ):
                await update_job_fields(job_id, batch_id=current_batch_id)
                same_model.append((job_id, json.loads(job.payload)))
            else:
                remaining.append((priority, timestamp, job_id))

            queue.task_done()
        except asyncio.QueueEmpty:
            break

    for item in remaining:
        queue.put_nowait(item)

    return same_model


async def _run_warm_cache_batch(
    job_id: str,
    model_name: str,
    payload: dict,
) -> None:
    batch_id = str(uuid4())
    await update_job_fields(job_id, batch_id=batch_id)
    await _set_warm_cache_state(active=True, model_name=model_name, queue_depth=0)

    await acquire_model(model_name)
    try:
        await _run_job(job_id, model_name, payload)

        # Single-worker mode only; inference_lock guarantees exclusive queue drain section.
        async with inference_lock:
            same_model_jobs = await _extract_same_model_jobs(model_name, batch_id)

        await _set_warm_cache_state(
            active=True,
            model_name=model_name,
            queue_depth=len(same_model_jobs),
        )

        for queued_job_id, queued_payload in same_model_jobs:
            estimated = get_model_vram_estimate(model_name)
            await update_job_fields(queued_job_id, vram_estimated_bytes=estimated)
            await _run_job(queued_job_id, model_name, queued_payload)
    finally:
        await release_model(model_name)
        await _set_warm_cache_state(active=False, model_name=None, queue_depth=0)


async def queue_worker(inference_semaphore: asyncio.Semaphore) -> None:
    """Consume jobs from the priority queue."""
    assert _monitor is not None
    assert _config is not None

    logger.info("Queue worker started")

    while True:
        priority, timestamp, job_id = await queue.get()
        should_requeue = False
        try:
            job = await get_job_by_id(job_id)
            if job is None:
                logger.warning("Dequeued unknown job_id=%s; skipping", job_id)
                continue
            if job.status != "QUEUED":
                continue

            async with inference_semaphore:
                payload = json.loads(job.payload)
                if _config.max_concurrent_jobs == 1:
                    if _monitor.get_vram_free_bytes() < _config.min_free_vram_bytes:
                        should_requeue = True
                        continue

                    await update_job_fields(
                        job_id,
                        vram_estimated_bytes=get_model_vram_estimate(job.model_name),
                    )
                    if _config.warm_cache_effective:
                        await _run_warm_cache_batch(job_id, job.model_name, payload)
                    else:
                        await acquire_model(job.model_name)
                        try:
                            await _run_job(job_id, job.model_name, payload)
                        finally:
                            await release_model(job.model_name)
                    continue

                reserved = await try_reserve_vram(job_id, job.model_name)
                if not reserved:
                    should_requeue = True
                    continue

                try:
                    estimated = active_reservations.get(job_id)
                    if estimated is not None:
                        await update_job_fields(job_id, vram_estimated_bytes=estimated)

                    await acquire_model(job.model_name)
                    try:
                        await _run_job(job_id, job.model_name, payload)
                    finally:
                        await release_model(job.model_name)
                finally:
                    await release_reservation(job_id)
        finally:
            if should_requeue:
                # Refresh timestamp on requeue to avoid head-of-line blocking
                # from permanently/temporarily unschedulable jobs.
                await queue.put((priority, time.time(), job_id))
                await asyncio.sleep(2)
            queue.task_done()


async def cleanup_worker() -> None:
    """Purge completed/failed jobs older than AEGIS_JOB_RETENTION_HOURS."""
    retention_hours = int(os.getenv("AEGIS_JOB_RETENTION_HOURS", "24"))
    logger.info(
        "Cleanup worker started (retention=%dh, interval=60min)", retention_hours
    )

    while True:
        await asyncio.sleep(3600)
        try:
            deleted = await delete_stale_jobs(retention_hours)
            logger.info("Cleanup pass complete: %d records purged", deleted)
        except Exception:
            logger.exception("Cleanup worker error")
