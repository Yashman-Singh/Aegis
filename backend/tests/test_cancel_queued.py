from __future__ import annotations

import importlib

import pytest


@pytest.mark.asyncio
async def test_cancel_queued_jobs_only_affects_queued(tmp_path, monkeypatch):
    db_file = tmp_path / "aegis_cancel.db"
    monkeypatch.setenv("AEGIS_DB_PATH", str(db_file))

    from backend.core import database

    importlib.reload(database)
    await database.init_db()

    queued = await database.create_job("llama3.2:1b", 5, {"prompt": "a"})
    running = await database.create_job("llama3.2:3b", 5, {"prompt": "b"})
    await database.update_job_status(running.id, "RUNNING")

    cancelled = await database.cancel_queued_jobs()
    assert cancelled >= 1

    queued_after = await database.get_job_by_id(queued.id)
    running_after = await database.get_job_by_id(running.id)
    assert queued_after is not None and queued_after.status == "FAILED"
    assert "Cancelled by operator request." in (queued_after.error_message or "")
    assert running_after is not None and running_after.status == "RUNNING"
