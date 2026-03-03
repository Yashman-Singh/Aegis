"""
SQLAlchemy async engine, session factory, and WAL initialization.

SQLite is configured with:
- WAL journal mode (prevents 'database is locked' during concurrent reads/writes)
- Busy timeout of 5.0 seconds
- Database path from AEGIS_DB_PATH env var (default: ~/.aegis/aegis.db)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models.job import Base, Job

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


async def init_db() -> None:
    """Create all tables. Call once at application startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
    session_factory = get_session_factory()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            logger.warning("update_job_status: job %s not found", job_id)
            return

        job.status = status

        if started_at is not None:
            job.started_at = started_at

        if completed_at is not None:
            job.completed_at = completed_at
            # Compute latency if both timestamps exist.
            # SQLite strips timezone info, so job.started_at is naive.
            # Normalize both to naive UTC before subtraction.
            if job.started_at is not None:
                end = completed_at.replace(tzinfo=None) if completed_at.tzinfo else completed_at
                start = job.started_at.replace(tzinfo=None) if job.started_at.tzinfo else job.started_at
                delta = end - start
                job.latency_ms = delta.total_seconds() * 1000.0

        if result is not None:
            job.result = json.dumps(result)

        if error is not None:
            job.error_message = error

        await session.commit()


async def get_active_jobs() -> list[Job]:
    """Return all non-terminal jobs (QUEUED, ALLOCATING, RUNNING), sorted by
    priority ASC then created_at ASC."""
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(Job)
            .where(Job.status.in_(["QUEUED", "ALLOCATING", "RUNNING"]))
            .order_by(Job.priority.asc(), Job.created_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_completed_stats() -> dict:
    """Return throughput statistics from completed/failed jobs."""
    from sqlalchemy import func, select

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Total completed
        completed_count = (
            await session.execute(
                select(func.count()).where(Job.status == "COMPLETED")
            )
        ).scalar() or 0

        # Total failed
        failed_count = (
            await session.execute(
                select(func.count()).where(Job.status == "FAILED")
            )
        ).scalar() or 0

        # Avg latency of last 100 completed jobs
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

    cutoff = datetime.now(timezone.utc).replace(
        tzinfo=None
    )  # SQLite stores naive datetimes
    from datetime import timedelta

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
