"""
Job SQLAlchemy ORM model.

Represents an inference job in the Aegis queue with full state machine
lifecycle tracking (QUEUED → ALLOCATING → RUNNING → COMPLETED / FAILED).
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
