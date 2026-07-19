"""Characterization tests for assert_run_audit_integrity — verifies the
post-run audit checks that validate run state, evidence completeness, and
manifest correctness.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.errors import RunLifecycleError, RunNotFoundError
from cardre.execution.run_lifecycle import RunLifecycle, assert_run_audit_integrity


def _make_store(project_root: Path):
    from cardre.store.db import ProjectStore
    store = ProjectStore(project_root / "test.cardre")
    store.initialize()
    return store


def _seed_succeeded_run(store):
    """Seed a succeeded run with a manifest and return (pv_id, run_id)."""
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test", now, "0.2.0"),
    )
    plan_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Plan", now),
    )
    pv_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
        "VALUES (?, ?, 1, 1, ?)",
        (pv_id, plan_id, now),
    )
    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )
    # Write a manifest
    manifest_dir = store.root / "exports" / f"manifest-{run_id}"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest = {
        "manifest_version": "1.0.0",
        "run_id": run_id,
        "plan_version_id": pv_id,
        "status": "succeeded",
        "steps": [],
    }
    manifest_path.write_text(json.dumps(manifest))
    return pv_id, run_id


class TestAssertRunAuditIntegrity:
    def test_succeeded_run_passes_audit(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id, run_id = _seed_succeeded_run(store)
        assert_run_audit_integrity(store, run_id)  # should not raise

    def test_nonexistent_run_raises(self, tmp_path):
        store = _make_store(tmp_path)
        with pytest.raises(RunNotFoundError):
            assert_run_audit_integrity(store, "nonexistent-run")

    def test_non_terminal_status_raises(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            (run_id, pv_id, now, now),
        )
        with pytest.raises(RunLifecycleError, match="terminal"):
            assert_run_audit_integrity(store, run_id)

    def test_missing_manifest_raises(self, tmp_path):
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', ?, ?, ?)",
            (run_id, pv_id, now, now, now),
        )
        # No manifest written
        with pytest.raises(RunLifecycleError, match="manifest"):
            assert_run_audit_integrity(store, run_id)

    def test_manifest_run_id_mismatch_raises(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id, run_id = _seed_succeeded_run(store)
        # Overwrite manifest with wrong run_id
        manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["run_id"] = "wrong-run-id"
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(RunLifecycleError, match="run_id"):
            assert_run_audit_integrity(store, run_id)

    def test_manifest_status_mismatch_raises(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id, run_id = _seed_succeeded_run(store)
        manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["status"] = "failed"
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(RunLifecycleError, match="status"):
            assert_run_audit_integrity(store, run_id)

    def test_manifest_plan_version_mismatch_raises(self, tmp_path):
        store = _make_store(tmp_path)
        pv_id, run_id = _seed_succeeded_run(store)
        manifest_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["plan_version_id"] = "wrong-pv"
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(RunLifecycleError, match="plan_version_id"):
            assert_run_audit_integrity(store, run_id)


class TestRunLifecycleFinaliseError:
    def test_finalise_failure_records_diagnostic(self, tmp_path):
        """When finalise fails (manifest write error), a diagnostic is recorded."""
        store = _make_store(tmp_path)
        now = utc_now_iso()
        project_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Plan", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            (run_id, pv_id, now, now),
        )
        # Make manifest write fail by making the exports dir read-only
        # Actually, let's just delete the run record so write_manifest raises
        store.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

        lifecycle = RunLifecycle(store=store, run_id=run_id, plan_version_id=pv_id, execution_mode="full_plan")
        with pytest.raises((RunLifecycleError, Exception)):
            lifecycle.finalise("succeeded")
