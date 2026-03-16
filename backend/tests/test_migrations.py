from __future__ import annotations

import importlib
import sqlite3

import pytest


@pytest.mark.asyncio
async def test_init_db_runs_additive_migrations(tmp_path, monkeypatch):
    db_file = tmp_path / "aegis_v1.db"
    monkeypatch.setenv("AEGIS_DB_PATH", str(db_file))

    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            model_name TEXT NOT NULL,
            priority INTEGER NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            result TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            latency_ms REAL
        )
        """
    )
    conn.commit()
    conn.close()

    from backend.core import database

    importlib.reload(database)
    await database.init_db()
    await database.init_db()  # idempotency check

    conn = sqlite3.connect(db_file)
    job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "batch_id" in job_columns
    assert "vram_estimated_bytes" in job_columns
    assert "vram_actual_peak_bytes" in job_columns

    model_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='model_vram_profiles'"
    ).fetchone()
    assert model_table is not None
    conn.close()
