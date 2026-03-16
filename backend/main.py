"""
Aegis AI Inference Runtime — FastAPI application.
"""

from __future__ import annotations

# Load .env BEFORE any module reads os.getenv()
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.core.database import (
    cancel_queued_jobs,
    count_nonterminal_jobs,
    fail_nonterminal_jobs_on_startup,
    get_active_jobs,
    get_completed_stats,
    get_job_by_id,
    init_db,
)
from backend.core.ollama_client import OllamaClient
from backend.core.queue_engine import (
    cleanup_worker,
    get_runtime_metrics_snapshot,
    get_worker_count,
    init_queue_engine,
    initialize_model_registry_state,
    queue_worker,
    submit_job,
)
from backend.core.runtime_config import RuntimeConfig, load_runtime_config
from backend.hardware.model_registry import get_registry_rows
from backend.hardware.registry import MonitorRegistry
from backend.models.schemas import (
    HardwareMetrics,
    CancelQueuedResponse,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
    MetricsResponse,
    MetricsV2Response,
    ModelRegistryEntry,
    ModelRegistryResponse,
    QueueJobSummary,
    QueueMetrics,
    ThroughputMetrics,
    ConcurrencyMetrics,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level references (set during lifespan startup)
# ---------------------------------------------------------------------------
_registry: MonitorRegistry | None = None
_ollama: OllamaClient | None = None
_config: RuntimeConfig | None = None
_bg_tasks: list[asyncio.Task] = []


def _build_hardware_metrics(monitor) -> HardwareMetrics:
    vram_total = monitor.get_vram_total_bytes()
    vram_used = monitor.get_vram_used_bytes()
    vram_free = monitor.get_vram_free_bytes()
    vram_threshold = vram_total
    pressure = min((vram_used / vram_threshold) * 100, 100.0) if vram_threshold > 0 else 0.0

    return HardwareMetrics(
        provider=type(monitor).__name__,
        vram_total_bytes=vram_total,
        vram_used_bytes=vram_used,
        vram_free_bytes=vram_free,
        vram_threshold_bytes=vram_threshold,
        vram_pressure_percent=round(pressure, 1),
    )


async def _build_metrics_payload() -> dict:
    assert _registry is not None
    monitor = _registry.monitor

    hardware = _build_hardware_metrics(monitor)
    active_jobs = await get_active_jobs()

    queue_jobs = [
        QueueJobSummary(
            job_id=job.id,
            model_name=job.model_name,
            priority=job.priority,
            status=job.status,
            created_at=job.created_at,
            batch_id=job.batch_id,
        )
        for job in active_jobs
    ]
    queue_metrics = QueueMetrics(depth=len(queue_jobs), jobs=queue_jobs)

    stats = await get_completed_stats()
    throughput = ThroughputMetrics(**stats)

    runtime = await get_runtime_metrics_snapshot()
    loaded_models = runtime["loaded_models"]
    loaded_model = loaded_models[0] if loaded_models else None

    concurrency = ConcurrencyMetrics(
        max_concurrent_jobs=runtime["max_concurrent_jobs"],
        currently_running=runtime["currently_running"],
        active_reservations_bytes=runtime["active_reservations_bytes"],
        vram_available_for_scheduling=runtime["vram_available_for_scheduling"],
    )

    return {
        "hardware": hardware,
        "queue": queue_metrics,
        "throughput": throughput,
        "loaded_model": loaded_model,
        "loaded_models": loaded_models,
        "concurrency": concurrency,
        "warm_cache_active": runtime["warm_cache_active"],
        "warm_cache_model": runtime["warm_cache_model"],
        "warm_cache_queue_depth": runtime["warm_cache_queue_depth"],
    }


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _registry, _ollama, _config, _bg_tasks

    # 1. Runtime config
    _config = load_runtime_config()

    # 2. Database
    await init_db()
    if _config.fail_nonterminal_on_startup:
        recovered = await fail_nonterminal_jobs_on_startup()
        if recovered:
            logger.warning("Recovered %d stale non-terminal jobs from previous run", recovered)
    else:
        pending = await count_nonterminal_jobs()
        if pending:
            logger.warning(
                "Detected %d non-terminal jobs from prior run. "
                "Use POST /v1/jobs/cancel-queued to clear queued jobs "
                "or set AEGIS_FAIL_NONTERMINAL_ON_STARTUP=true.",
                pending,
            )

    # 3. Hardware
    _registry = MonitorRegistry()

    # 4. Ollama client
    _ollama = OllamaClient()
    healthy = await _ollama.health_check()
    if not healthy:
        logger.error(
            "Ollama is not reachable at startup. "
            "Jobs will fail until Ollama is available."
        )

    # 5. Queue engine + workers
    init_queue_engine(_registry.monitor, _ollama, _config)
    await initialize_model_registry_state()

    worker_count = get_worker_count()
    inference_semaphore = asyncio.Semaphore(worker_count)
    _bg_tasks = [
        asyncio.create_task(queue_worker(inference_semaphore))
        for _ in range(worker_count)
    ]
    _bg_tasks.append(asyncio.create_task(cleanup_worker()))

    logger.info("Aegis backend started (workers=%d)", worker_count)
    yield

    for task in _bg_tasks:
        task.cancel()
    await asyncio.gather(*_bg_tasks, return_exceptions=True)
    _bg_tasks = []

    if _ollama is not None:
        await _ollama.close()
    logger.info("Aegis backend shut down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Aegis AI Inference Runtime",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/v1/jobs/submit", response_model=JobSubmitResponse, status_code=202)
async def submit(request: JobSubmitRequest):
    """Submit a new inference job to the queue."""
    job_id = await submit_job(
        model_name=request.model_name,
        priority=request.priority,
        payload=request.payload,
    )
    return JobSubmitResponse(job_id=job_id, status="QUEUED")


@app.post("/v1/jobs/cancel-queued", response_model=CancelQueuedResponse)
async def cancel_queued(model_name: str | None = None):
    """
    Cancel all currently QUEUED jobs (or only for one model if model_name is provided).
    Running jobs are not interrupted.
    """
    cancelled = await cancel_queued_jobs(model_name=model_name)
    return CancelQueuedResponse(cancelled_count=cancelled)


@app.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    """Poll for a job's current status and result."""
    job = await get_job_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    result = None
    if job.result is not None:
        result = json.loads(job.result)

    return JobStatusResponse(
        job_id=job.id,
        model_name=job.model_name,
        priority=job.priority,
        status=job.status,
        result=result,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        latency_ms=job.latency_ms,
    )


@app.get("/v1/metrics", response_model=MetricsResponse)
async def get_metrics_v1():
    """Backwards-compatible metrics contract (additive changes only)."""
    payload = await _build_metrics_payload()
    return MetricsResponse(**payload)


@app.get("/v2/metrics", response_model=MetricsV2Response)
async def get_metrics_v2():
    """V2 metrics contract: loaded_models only (no loaded_model string)."""
    payload = await _build_metrics_payload()
    payload.pop("loaded_model", None)
    return MetricsV2Response(**payload)


@app.get("/v1/models/registry", response_model=ModelRegistryResponse)
async def get_model_registry():
    rows = []
    for row in get_registry_rows():
        p95 = int(row["p95_bytes"])
        rows.append(
            ModelRegistryEntry(
                model_name=row["model_name"],
                p95_bytes=p95,
                p95_gb=round(p95 / (1024 ** 3), 2),
                with_buffer_bytes=int(row["with_buffer_bytes"]),
                sample_count=int(row.get("sample_count", 0)),
                source=str(row.get("source", "static_baseline")),
            )
        )
    return ModelRegistryResponse(models=rows)
