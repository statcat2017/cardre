"""Integration tests for canonical run manifest finalisation.

These tests exercise the real FinalizeRun use case, the FsManifestPublisher
adapter, and the shared manifest hashing/verification domain functions.
No mocks around the integrity boundary.
"""

from __future__ import annotations

import json
import uuid

import pytest

from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
from cardre.application.runs.finalize_run import FinalizeDiagnostic, FinalizeRun
from cardre.domain.manifest import (
    MANIFEST_VERSION,
    compute_manifest_hash,
    compute_pathway_hash,
    deserialize_manifest,
    serialize_manifest,
)
from cardre.store.db import ProjectStore


@pytest.fixture
def store_with_run(tmp_path):
    """Create a store with a project, plan, committed version, and a running run."""
    from cardre.domain.diagnostics import utc_now_iso

    s = ProjectStore(tmp_path / "test.cardre")
    s.initialize()

    project_id = str(uuid.uuid4())
    plan_id = str(uuid.uuid4())
    pv_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    now = utc_now_iso()

    s.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Test Project", now, "0.2.0"),
    )
    s.execute(
        "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
        (plan_id, project_id, "Test Plan", now),
    )
    s.execute(
        "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at, description) "
        "VALUES (?, ?, 1, 1, ?, ?)",
        (pv_id, plan_id, now, "Base version"),
    )
    s.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, heartbeat_at) "
        "VALUES (?, ?, 'running', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )
    return s, project_id, run_id, pv_id, now


def _insert_run_step(store, run_id, pv_id, step_id, now):
    rs_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
        "started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
        "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
        (rs_id, run_id, step_id, pv_id, now, now),
    )
    return rs_id


def _insert_artifact(store, run_id, rs_id, pv_id, step_id, artifact_id, now):
    store.execute(
        "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, "
        "logical_hash, media_type, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, "json", "output", artifact_id, "phys_hash_1", "logical_hash_1",
         "application/json", now),
    )
    store.execute(
        "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, "
        "step_id, artifact_id, direction, created_at) VALUES (?, ?, ?, ?, ?, ?, 'output', ?)",
        (str(uuid.uuid4()), run_id, rs_id, pv_id, step_id, artifact_id, now),
    )


class TestFinalizeRunManifest:
    """End-to-end tests: finalisation publishes a valid canonical manifest."""

    def test_successful_finalisation_publishes_valid_manifest(self, store_with_run, tmp_path):
        store, project_id, run_id, pv_id, now = store_with_run
        rs_id = _insert_run_step(store, run_id, pv_id, "step-1", now)
        _insert_artifact(store, run_id, rs_id, pv_id, "step-1", "art-1", now)

        publisher = FsManifestPublisher(store.root)
        finalize = FinalizeRun(lambda: _uow(store), publisher)

        finalize(run_id, "succeeded")

        result = publisher.verify(run_id)
        assert result["valid"] is True
        manifest = result["manifest"]
        assert manifest["run_id"] == run_id
        assert manifest["plan_version_id"] == pv_id
        assert manifest["status"] == "succeeded"
        assert manifest["manifest_version"] == MANIFEST_VERSION
        assert manifest["manifest_hash"] != ""
        assert manifest["pathway_hash"] != ""
        assert len(manifest["steps"]) == 1
        assert manifest["steps"][0]["step_id"] == "step-1"
        assert "art-1" in manifest["steps"][0]["output_artifact_ids"]

    def test_manifest_self_hash_matches(self, store_with_run, tmp_path):
        store, project_id, run_id, pv_id, now = store_with_run
        _insert_run_step(store, run_id, pv_id, "step-1", now)

        publisher = FsManifestPublisher(store.root)
        finalize = FinalizeRun(lambda: _uow(store), publisher)
        finalize(run_id, "succeeded")

        data = publisher.read(run_id)
        expected = compute_manifest_hash(data)
        assert data["manifest_hash"] == expected

    def test_tampered_manifest_fails_verification(self, store_with_run, tmp_path):
        store, project_id, run_id, pv_id, now = store_with_run
        _insert_run_step(store, run_id, pv_id, "step-1", now)

        publisher = FsManifestPublisher(store.root)
        finalize = FinalizeRun(lambda: _uow(store), publisher)
        finalize(run_id, "succeeded")

        manifest_path = publisher.manifest_path(run_id)
        data = json.loads(manifest_path.read_text())
        data["status"] = "failed"
        manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

        result = publisher.verify(run_id)
        assert result["valid"] is False
        assert result["error"] == "ARTIFACT_HASH_UNRESOLVED"

    def test_missing_manifest_fails_verification(self, store_with_run, tmp_path):
        store, project_id, run_id, pv_id, now = store_with_run

        publisher = FsManifestPublisher(store.root)
        result = publisher.verify(run_id)
        assert result["valid"] is False
        assert result["error"] == "CANONICAL_MANIFEST_MISSING"

    def test_failed_finalisation_publishes_failed_status(self, store_with_run, tmp_path):
        store, project_id, run_id, pv_id, now = store_with_run
        _insert_run_step(store, run_id, pv_id, "step-1", now)

        publisher = FsManifestPublisher(store.root)
        finalize = FinalizeRun(lambda: _uow(store), publisher)

        finalize(run_id, "failed", diagnostic=FinalizeDiagnostic(
            code="RUN_EXECUTION_FAILED",
            message="Step failed",
        ))

        result = publisher.verify(run_id)
        assert result["valid"] is True
        assert result["manifest"]["status"] == "failed"
        diag = result["manifest"]["diagnostics"]
        assert any(d.get("code") == "RUN_EXECUTION_FAILED" for d in diag)

    def test_manifest_is_atomically_written(self, store_with_run, tmp_path):
        store, project_id, run_id, pv_id, now = store_with_run
        _insert_run_step(store, run_id, pv_id, "step-1", now)

        publisher = FsManifestPublisher(store.root)
        finalize = FinalizeRun(lambda: _uow(store), publisher)
        finalize(run_id, "succeeded")

        manifest_path = publisher.manifest_path(run_id)
        assert manifest_path.exists()
        temp_files = list(manifest_path.parent.glob(".manifest.json.tmp.*"))
        assert temp_files == []

    def test_pathway_hash_is_deterministic(self, store_with_run, tmp_path):
        store, project_id, run_id, pv_id, now = store_with_run
        _insert_run_step(store, run_id, pv_id, "step-1", now)

        publisher = FsManifestPublisher(store.root)
        finalize = FinalizeRun(lambda: _uow(store), publisher)
        finalize(run_id, "succeeded")

        data = publisher.read(run_id)
        recomputed = compute_pathway_hash(data["steps"])
        assert data["pathway_hash"] == recomputed


class TestManifestHashing:
    """Unit tests for the shared manifest hashing functions."""

    def test_compute_manifest_hash_is_deterministic(self):
        payload = {"manifest_version": MANIFEST_VERSION, "run_id": "r1", "manifest_hash": ""}
        h1 = compute_manifest_hash(payload)
        h2 = compute_manifest_hash(payload)
        assert h1 == h2

    def test_manifest_hash_ignores_manifest_hash_field(self):
        payload = {"run_id": "r1", "manifest_hash": "abc123"}
        h1 = compute_manifest_hash(payload)
        payload2 = {"run_id": "r1", "manifest_hash": "different"}
        h2 = compute_manifest_hash(payload2)
        assert h1 == h2

    def test_manifest_hash_changes_with_content(self):
        h1 = compute_manifest_hash({"run_id": "r1", "manifest_hash": ""})
        h2 = compute_manifest_hash({"run_id": "r2", "manifest_hash": ""})
        assert h1 != h2

    def test_serialize_deserialize_roundtrip(self):
        payload = {"manifest_version": MANIFEST_VERSION, "run_id": "r1", "steps": []}
        text = serialize_manifest(payload)
        restored = deserialize_manifest(text)
        assert restored == payload

    def test_pathway_hash_changes_with_different_steps(self):
        steps1 = [{"step_id": "s1", "node_type": "a", "status": "succeeded"}]
        steps2 = [{"step_id": "s1", "node_type": "b", "status": "succeeded"}]
        assert compute_pathway_hash(steps1) != compute_pathway_hash(steps2)

    def test_pathway_hash_changes_with_different_status(self):
        steps1 = [{"step_id": "s1", "node_type": "a", "status": "succeeded"}]
        steps2 = [{"step_id": "s1", "node_type": "a", "status": "failed"}]
        assert compute_pathway_hash(steps1) != compute_pathway_hash(steps2)


def _uow(store):
    """Create a UoW that wraps a raw ProjectStore's connection."""
    from cardre.adapters.sqlite.connection import SqliteUnitOfWork

    return SqliteUnitOfWork(store._db)
