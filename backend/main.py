"""
Aegis AI Inference Runtime — FastAPI application.

Lifespan startup:
1. Initialise the database (create tables, WAL mode).
2. Detect hardware provider via MonitorRegistry.
3. Initialise the Ollama client.
4. Start the queue worker and cleanup worker as background tasks.
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
    get_active_jobs,
    get_completed_stats,
    get_job_by_id,
    init_db,
)
from backend.core.ollama_client import OllamaClient
from backend.core.queue_engine import (
    cleanup_worker,
    init_queue_engine,
    queue_worker,
    submit_job,
)
from backend.hardware.registry import MonitorRegistry
from backend.models.schemas import (
    HardwareMetrics,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
    MetricsResponse,
    QueueJobSummary,
    QueueMetrics,
    ThroughputMetrics,
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


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _registry, _ollama

    # 1. Database
    await init_db()

    # 2. Hardware
    _registry = MonitorRegistry()

    # 3. Ollama client
    _ollama = OllamaClient()
    healthy = await _ollama.health_check()
    if not healthy:
        logger.error(
            "Ollama is not reachable at startup. "
            "Jobs will fail until Ollama is available."
        )

    # 4. Queue engine
    init_queue_engine(_registry.monitor, _ollama)
    asyncio.create_task(queue_worker())
    asyncio.create_task(cleanup_worker())

    logger.info("Aegis backend started")
    yield

    # Graceful shutdown
    if _ollama is not None:
        await _ollama.close()
    logger.info("Aegis backend shut down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Aegis AI Inference Runtime",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Dashboard runs on a different port
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
async def get_metrics():
    """Aggregated metrics for the observability dashboard."""
    assert _registry is not None
    monitor = _registry.monitor

    # Hardware telemetry
    vram_total = monitor.get_vram_total_bytes()
    vram_used = monitor.get_vram_used_bytes()
    vram_free = monitor.get_vram_free_bytes()

    # For threshold_bytes, use the total (already threshold-adjusted for Apple Silicon)
    vram_threshold = vram_total

    # Pressure: (used / threshold) * 100, capped at 100
    pressure = min((vram_used / vram_threshold) * 100, 100.0) if vram_threshold > 0 else 0.0

    hardware = HardwareMetrics(
        provider=type(monitor).__name__,
        vram_total_bytes=vram_total,
        vram_used_bytes=vram_used,
        vram_free_bytes=vram_free,
        vram_threshold_bytes=vram_threshold,
        vram_pressure_percent=round(pressure, 1),
    )

    # Queue state
    active_jobs = await get_active_jobs()
    loaded_model = None
    queue_jobs = []

    for job in active_jobs:
        if job.status == "RUNNING":
            loaded_model = job.model_name
        queue_jobs.append(
            QueueJobSummary(
                job_id=job.id,
                model_name=job.model_name,
                priority=job.priority,
                status=job.status,
                created_at=job.created_at,
            )
        )

    queue_metrics = QueueMetrics(depth=len(queue_jobs), jobs=queue_jobs)

    # Throughput
    stats = await get_completed_stats()
    throughput = ThroughputMetrics(**stats)

    return MetricsResponse(
        hardware=hardware,
        queue=queue_metrics,
        loaded_model=loaded_model,
        throughput=throughput,
    )
