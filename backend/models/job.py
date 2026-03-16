"""
SQLAlchemy ORM models.

Represents:
- inference jobs with lifecycle tracking
- per-model VRAM profile records for V2 empirical scheduling
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, Integer, String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all Aegis ORM models."""
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-serialized
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="QUEUED"
    )
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-serialized
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    vram_estimated_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_actual_peak_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ModelVramProfile(Base):
    __tablename__ = "model_vram_profiles"

    model_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    p95_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="static_baseline")
