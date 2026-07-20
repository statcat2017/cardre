"""Tests that the runs table has all required request columns."""
from __future__ import annotations

from cardre.store.db import ProjectStore


def test_runs_table_has_request_columns(tmp_path):
    s = ProjectStore(tmp_path / "test.cardre")
    s.initialize()
    cols = {r[1] for r in s.execute("PRAGMA table_info(runs)").fetchall()}
    s.close()
    required = {
        "run_id", "plan_version_id", "status",
        "run_scope", "branch_id", "force",
        "requested_by", "request_id",
        "created_at", "queued_at", "started_at", "finished_at",
        "heartbeat_at",
    }
    missing = required - cols
    assert not missing, f"runs table missing columns: {sorted(missing)}"
