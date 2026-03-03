"""
Queue engine — asyncio.PriorityQueue consumer loop with inference lock.

This is the heart of Aegis. Key invariants:
1. Only ONE job executes at a time (single asyncio.Lock).
2. Model eviction happens INSIDE the lock, before release.
3. Never sleep inside the lock.
4. Insufficient VRAM → re-queue + sleep OUTSIDE the lock.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from backend.core.database import (
    create_job,
    delete_stale_jobs,
    update_job_status,
)
from backend.core.ollama_client import OllamaClient
from backend.hardware.registry import HardwareMonitor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (initialised by init_queue_engine)
# ---------------------------------------------------------------------------

# PriorityQueue items: (priority: int, created_at_timestamp: float, job_id: str)
queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
inference_lock: asyncio.Lock = asyncio.Lock()

_monitor: HardwareMonitor | None = None
_ollama: OllamaClient | None = None
_min_free_vram: int = 0


def init_queue_engine(monitor: HardwareMonitor, ollama: OllamaClient) -> None:
    """Bind the hardware monitor and Ollama client. Call once at startup."""
    global _monitor, _ollama, _min_free_vram
    _monitor = monitor
    _ollama = ollama
    _min_free_vram = int(
        os.getenv("AEGIS_MIN_FREE_VRAM_BYTES", "536870912")  # 512 MB default
    )
    logger.info("Queue engine initialised (min_free_vram=%s bytes)", _min_free_vram)


# ---------------------------------------------------------------------------
# Job submission
# ---------------------------------------------------------------------------

async def submit_job(model_name: str, priority: int, payload: dict) -> str:
    """Create a DB row (QUEUED) and enqueue. Returns the job_id."""
    job = await create_job(model_name, priority, payload)
    await queue.put((priority, job.created_at.timestamp(), job.id))
    logger.info("Job %s enqueued (model=%s, priority=%d)", job.id, model_name, priority)
    return job.id


# ---------------------------------------------------------------------------
# Worker loop — follows the exact pseudocode from MASTER_SPEC
# ---------------------------------------------------------------------------

async def queue_worker() -> None:
    """
    Consume jobs from the priority queue, one at a time.

    The full lock/eviction protocol:
        acquire lock → check VRAM → state transitions → dispatch →
        evict (INSIDE lock) → release lock
    """
    assert _monitor is not None, "Call init_queue_engine() before starting worker"
    assert _ollama is not None, "Call init_queue_engine() before starting worker"

    logger.info("Queue worker started")

    while True:
        priority, timestamp, job_id = await queue.get()

        vram_sufficient = False

        # 1. Acquire inference lock — all work including eviction happens inside.
        async with inference_lock:
            free_vram = _monitor.get_vram_free_bytes()

            if free_vram >= _min_free_vram:
                vram_sufficient = True

                try:
                    # 2. QUEUED → ALLOCATING
                    await update_job_status(job_id, "ALLOCATING")

                    # 3. ALLOCATING → RUNNING
                    started = datetime.now(timezone.utc)
                    await update_job_status(job_id, "RUNNING", started_at=started)

                    # 4. Dispatch to Ollama
                    # Fetch model_name from DB (we only have job_id in the queue tuple)
                    from backend.core.database import get_job_by_id

                    job = await get_job_by_id(job_id)
                    if job is None:
                        logger.error("Job %s disappeared from DB", job_id)
                        queue.task_done()
                        continue

                    import json

                    payload = json.loads(job.payload)
                    model_name = job.model_name

                    response = await _ollama.generate(model_name, payload)

                    # 5. RUNNING → COMPLETED or FAILED
                    completed = datetime.now(timezone.utc)

                    if response.status_code == 200:
                        await update_job_status(
                            job_id,
                            "COMPLETED",
                            completed_at=completed,
                            result=response.json(),
                        )
                    else:
                        error_msg = (
                            f"Ollama returned {response.status_code}: "
                            f"{response.text[:500]}"
                        )
                        await update_job_status(
                            job_id,
                            "FAILED",
                            completed_at=completed,
                            error=error_msg,
                        )

                    # 6. Evict model — CRITICAL: BEFORE releasing the lock.
                    await _ollama.evict(model_name)

                except Exception:
                    logger.exception("Unhandled error processing job %s", job_id)
                    try:
                        await update_job_status(
                            job_id,
                            "FAILED",
                            completed_at=datetime.now(timezone.utc),
                            error="Internal error — see server logs",
                        )
                        # Still attempt eviction on failure
                        if job is not None:
                            await _ollama.evict(job.model_name)
                    except Exception:
                        logger.exception("Failed to mark job %s as FAILED", job_id)

        # Lock released here via context manager exit.

        # 7. Handle insufficient VRAM OUTSIDE the lock.
        if not vram_sufficient:
            await queue.put((priority, timestamp, job_id))
            await asyncio.sleep(2)  # Sleep without blocking lock acquisitions

        # 8. Mark dequeued item as processed.
        queue.task_done()


# ---------------------------------------------------------------------------
# Background cleanup task
# ---------------------------------------------------------------------------

async def cleanup_worker() -> None:
    """Purge completed/failed jobs older than AEGIS_JOB_RETENTION_HOURS.
    Runs every 60 minutes."""
    retention_hours = int(os.getenv("AEGIS_JOB_RETENTION_HOURS", "24"))
    logger.info(
        "Cleanup worker started (retention=%dh, interval=60min)", retention_hours
    )

    while True:
        await asyncio.sleep(3600)  # 60 minutes
        try:
            deleted = await delete_stale_jobs(retention_hours)
            logger.info("Cleanup pass complete: %d records purged", deleted)
        except Exception:
            logger.exception("Cleanup worker error")
