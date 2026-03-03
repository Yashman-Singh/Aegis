"""
Pydantic request/response schemas for the Aegis API.

These are the data contracts for the JSON API — separate from the ORM models
to keep validation logic decoupled from persistence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Job submission
# ---------------------------------------------------------------------------

class JobSubmitRequest(BaseModel):
    """POST /v1/jobs/submit request body."""

    model_name: str = Field(..., description="Ollama model tag, e.g. 'llama3.2:3b'")
    priority: int = Field(
        default=5, ge=1, le=10,
        description="Lower integer = higher priority (1–10, default 5)",
    )
    payload: dict[str, Any] = Field(
        ..., description="Inference payload passed through to Ollama (must include 'prompt')",
    )


class JobSubmitResponse(BaseModel):
    """POST /v1/jobs/submit 202 response."""

    job_id: str
    status: str = "QUEUED"


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------

class JobStatusResponse(BaseModel):
    """GET /v1/jobs/{job_id} response."""

    job_id: str
    model_name: str
    priority: int
    status: str
    result: Any | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: float | None = None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class HardwareMetrics(BaseModel):
    provider: str
    vram_total_bytes: int
    vram_used_bytes: int
    vram_free_bytes: int
    vram_threshold_bytes: int
    vram_pressure_percent: float


class QueueJobSummary(BaseModel):
    job_id: str
    model_name: str
    priority: int
    status: str
    created_at: datetime


class QueueMetrics(BaseModel):
    depth: int
    jobs: list[QueueJobSummary]


class ThroughputMetrics(BaseModel):
    jobs_completed_total: int
    jobs_failed_total: int
    avg_latency_ms_last_100: float | None = None


class MetricsResponse(BaseModel):
    """GET /v1/metrics response."""

    hardware: HardwareMetrics
    queue: QueueMetrics
    loaded_model: str | None = None
    throughput: ThroughputMetrics
