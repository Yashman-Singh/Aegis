from __future__ import annotations

import importlib

import pytest


@pytest.mark.asyncio
async def test_fail_nonterminal_jobs_on_startup(tmp_path, monkeypatch):
    db_file = tmp_path / "aegis_recovery.db"
    monkeypatch.setenv("AEGIS_DB_PATH", str(db_file))

    from backend.core import database

    importlib.reload(database)
    await database.init_db()

    j1 = await database.create_job("llama3.2:1b", 5, {"prompt": "a"})
    j2 = await database.create_job("llama3.2:1b", 5, {"prompt": "b"})
    await database.update_job_status(j2.id, "RUNNING")

    recovered = await database.fail_nonterminal_jobs_on_startup()
    assert recovered >= 2

    r1 = await database.get_job_by_id(j1.id)
    r2 = await database.get_job_by_id(j2.id)
    assert r1 is not None and r1.status == "FAILED"
    assert r2 is not None and r2.status == "FAILED"
    assert "Recovered on startup" in (r1.error_message or "")
    assert "Recovered on startup" in (r2.error_message or "")
