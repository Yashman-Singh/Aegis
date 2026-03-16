"""
SQLAlchemy async engine, session factory, WAL initialization, and DB helpers.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models.job import Base, Job, ModelVramProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine & session factory (module-level singletons, initialised lazily)
# ---------------------------------------------------------------------------

_engine = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_db_path() -> str:
    """Resolve the database file path, creating parent dirs if needed."""
    raw = os.getenv("AEGIS_DB_PATH", "~/.aegis/aegis.db")
    db_path = Path(raw).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return str(db_path)


def _build_engine():
    """Create the async engine with WAL mode and busy timeout."""
    db_path = _get_db_path()
    url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(url, echo=False)

    # Set WAL mode and busy timeout on every raw DBAPI connection.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")  # 5 seconds in ms
        cursor.close()

    return engine


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False
        )
    return _async_session_factory


async def _add_column_if_missing(
    conn,
    table: str,
    column: str,
    column_type: str,
) -> None:
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    columns = [row[1] for row in result.fetchall()]
    if column in columns:
        return
    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))
    logger.info("Migration: added column %s.%s", table, column)


async def run_migrations(engine) -> None:
    """
    Idempotent migration runner. Safe to call on every startup.
    create_all() handles new tables. This handles new columns on existing tables.
    """
    async with engine.begin() as conn:
        await _add_column_if_missing(conn, "jobs", "batch_id", "TEXT")
        await _add_column_if_missing(conn, "jobs", "vram_estimated_bytes", "INTEGER")
        await _add_column_if_missing(conn, "jobs", "vram_actual_peak_bytes", "INTEGER")


async def init_db() -> None:
    """Create all tables and run idempotent schema migrations."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations(engine)

    # Verify WAL mode
    async with engine.connect() as conn:
        result = await conn.execute(text("PRAGMA journal_mode;"))
        mode = result.scalar()
        logger.info("Database initialised at %s (journal_mode=%s)", _get_db_path(), mode)


# ---------------------------------------------------------------------------
# Job helper functions
# ---------------------------------------------------------------------------

async def create_job(
    model_name: str, priority: int, payload: dict
) -> Job:
    """Insert a new job in QUEUED state. Returns the ORM instance."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        job = Job(
            model_name=model_name,
            priority=priority,
            payload=json.dumps(payload),
            status="QUEUED",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job


async def get_job_by_id(job_id: str) -> Job | None:
    """Fetch a single job by ID, or None if not found."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await session.get(Job, job_id)


async def update_job_fields(job_id: str, **fields: Any) -> None:
    """Patch any set of fields on a job row by ID."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            logger.warning("update_job_fields: job %s not found", job_id)
            return

        for key, value in fields.items():
            if not hasattr(job, key):
                logger.warning("update_job_fields: unknown field %s", key)
                continue
            setattr(job, key, value)

        if "completed_at" in fields and fields["completed_at"] is not None and job.started_at:
            completed_at = fields["completed_at"]
            end = (
                completed_at.replace(tzinfo=None)
                if completed_at.tzinfo
                else completed_at
            )
            start = (
                job.started_at.replace(tzinfo=None)
                if job.started_at.tzinfo
                else job.started_at
            )
            job.latency_ms = (end - start).total_seconds() * 1000.0

        await session.commit()


async def update_job_status(
    job_id: str,
    status: str,
    *,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Transition a job to a new status and update related fields."""
    fields: dict[str, Any] = {"status": status}
    if started_at is not None:
        fields["started_at"] = started_at
    if completed_at is not None:
        fields["completed_at"] = completed_at
    if result is not None:
        fields["result"] = json.dumps(result)
    if error is not None:
        fields["error_message"] = error
    await update_job_fields(job_id, **fields)


async def get_active_jobs() -> list[Job]:
    """Return all non-terminal jobs (QUEUED, ALLOCATING, RUNNING), sorted by
    priority ASC then created_at ASC."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(Job)
            .where(Job.status.in_(["QUEUED", "ALLOCATING", "RUNNING"]))
            .order_by(Job.priority.asc(), Job.created_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def count_nonterminal_jobs() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        count = (
            await session.execute(
                select(func.count()).where(Job.status.in_(["QUEUED", "ALLOCATING", "RUNNING"]))
            )
        ).scalar()
        return int(count or 0)


async def cancel_queued_jobs(model_name: str | None = None) -> int:
    """
    Mark QUEUED jobs as FAILED with a cancellation reason.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        now = datetime.now(timezone.utc)
        stmt = (
            update(Job)
            .where(Job.status == "QUEUED")
            .values(
                status="FAILED",
                completed_at=now,
                error_message="Cancelled by operator request.",
            )
        )
        if model_name:
            stmt = stmt.where(Job.model_name == model_name)
        result = await session.execute(stmt)
        await session.commit()
        return int(result.rowcount or 0)


async def get_completed_stats() -> dict:
    """Return throughput statistics from completed/failed jobs."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        completed_count = (
            await session.execute(
                select(func.count()).where(Job.status == "COMPLETED")
            )
        ).scalar() or 0

        failed_count = (
            await session.execute(
                select(func.count()).where(Job.status == "FAILED")
            )
        ).scalar() or 0

        stmt = (
            select(Job.latency_ms)
            .where(Job.status == "COMPLETED", Job.latency_ms.isnot(None))
            .order_by(Job.completed_at.desc())
            .limit(100)
        )
        result = await session.execute(stmt)
        latencies = [row[0] for row in result.all()]
        avg_latency = sum(latencies) / len(latencies) if latencies else None

        return {
            "jobs_completed_total": completed_count,
            "jobs_failed_total": failed_count,
            "avg_latency_ms_last_100": avg_latency,
        }


async def delete_stale_jobs(retention_hours: int = 24) -> int:
    """Delete completed/failed jobs older than retention_hours. Returns count deleted."""
    from sqlalchemy import delete

    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            delete(Job)
            .where(
                Job.status.in_(["COMPLETED", "FAILED"]),
                Job.completed_at.isnot(None),
                Job.completed_at < cutoff,
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount
        if deleted:
            logger.info("Purged %d stale job records", deleted)
        return deleted


async def fail_nonterminal_jobs_on_startup() -> int:
    """
    Mark unfinished jobs from previous process lifetimes as FAILED.
    These jobs are not recoverable because the in-memory queue is reset on restart.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        now = datetime.now(timezone.utc)
        stmt = (
            update(Job)
            .where(Job.status.in_(["QUEUED", "ALLOCATING", "RUNNING"]))
            .values(
                status="FAILED",
                completed_at=now,
                error_message=(
                    "Recovered on startup: previous Aegis process terminated before "
                    "job completion; resubmit if needed."
                ),
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        updated = result.rowcount or 0
        if updated:
            logger.warning("Startup recovery: marked %d non-terminal jobs as FAILED", updated)
        return updated


async def get_model_peak_samples(model_name: str) -> list[int]:
    """Fetch all non-null sampled peak VRAM values for completed jobs by model."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(Job.vram_actual_peak_bytes)
            .where(
                Job.model_name == model_name,
                Job.status == "COMPLETED",
                Job.vram_actual_peak_bytes.isnot(None),
            )
            .order_by(Job.completed_at.asc())
        )
        result = await session.execute(stmt)
        return [int(row[0]) for row in result.all() if row[0] is not None]


# ---------------------------------------------------------------------------
# Model profile table helpers
# ---------------------------------------------------------------------------

async def upsert_model_vram_profile(
    model_name: str,
    p95_bytes: int,
    sample_count: int,
    source: str,
) -> ModelVramProfile:
    session_factory = get_session_factory()
    async with session_factory() as session:
        profile = await session.get(ModelVramProfile, model_name)
        if profile is None:
            profile = ModelVramProfile(
                model_name=model_name,
                p95_bytes=p95_bytes,
                sample_count=sample_count,
                source=source,
                last_updated=datetime.now(timezone.utc),
            )
            session.add(profile)
        else:
            profile.p95_bytes = p95_bytes
            profile.sample_count = sample_count
            profile.source = source
            profile.last_updated = datetime.now(timezone.utc)

        await session.commit()
        await session.refresh(profile)
        return profile


async def get_model_vram_profile(model_name: str) -> ModelVramProfile | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await session.get(ModelVramProfile, model_name)


async def get_model_vram_profiles() -> list[ModelVramProfile]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(ModelVramProfile).order_by(ModelVramProfile.model_name.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())
