"""Tests for RunStatusInfo, DiagnosticEntry, and collector run-status population."""

from __future__ import annotations

import json
import uuid
import tempfile
from pathlib import Path

import pytest

from cardre.audit import RunStepRecord, utc_now_iso
from cardre.reporting.collector import generate_report_bundle
from cardre.reporting.schema import (
    ReportBundle,
    RunStatusInfo,
    DiagnosticEntry,
    RunManifest,
)
from cardre.run_lifecycle import compute_manifest_hash
from cardre.store import ProjectStore


@pytest.fixture
def project_and_plan(store):
    project_id = store.create_project("test-proj")
    plan_id = store.create_plan(project_id, "Scorecard Pathway")
    store.create_plan_version(plan_id, [], description="v1")
    return project_id, plan_id


class TestRunStatusInfo:
    def test_run_status_model_required_fields(self):
        r = RunStatusInfo(run_id="r1", status="succeeded")
        assert r.run_id == "r1"
        assert r.status == "succeeded"
        assert r.started_at == ""
        assert r.finished_at is None
        assert r.execution_mode == "unknown"
        assert r.diagnostics == []

    def test_diagnostic_entry_model(self):
        d = DiagnosticEntry(code="TEST_ERR", message="Something failed", severity="error")
        assert d.code == "TEST_ERR"
        assert d.message == "Something failed"
        assert d.severity == "error"
        assert d.category == ""

    def test_run_status_deterministic_serialization(self):
        r1 = RunStatusInfo(run_id="r1", status="succeeded", execution_mode="full")
        r2 = RunStatusInfo(run_id="r1", status="succeeded", execution_mode="full")
        assert r1.model_dump_json(indent=2) == r2.model_dump_json(indent=2)

    def test_report_bundle_has_run_status_field(self):
        b = ReportBundle(project_id="p1", run_id="r1", target_branch_id="main", report_mode="branch")
        assert b.run_status.run_id == ""
        assert b.run_status.status == ""


class TestCollectorRunStatus:
    """Collector populates run_status from store."""

    def test_succeeded_run_has_status(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id="nonexistent", report_mode="branch",
        )
        assert bundle.run_status.status == "succeeded"

    def test_failed_run_has_run_status_failed(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "failed")

        store.append_run_diagnostic(run_id, {
            "code": "RUNTIME_ERROR", "message": "Something blew up",
            "severity": "error", "category": "execution",
            "created_at": "2026-06-15T00:00:00Z",
        })

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id="nonexistent", report_mode="branch",
        )
        assert bundle.run_status.status == "failed"
        assert bundle.run_status.run_id == run_id

        diag_codes = [d.code for d in bundle.run_status.diagnostics]
        assert "RUNTIME_ERROR" in diag_codes

    def test_failed_run_emits_run_not_succeeded(self, store, project_and_plan):
        """Collector emits RUN_NOT_SUCCEEDED for a failed run, not MISSING_RUN_MANIFEST."""
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "failed")

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id="nonexistent", report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        assert "RUN_NOT_SUCCEEDED" in codes, (
            f"Expected RUN_NOT_SUCCEEDED, got {codes}"
        )
        assert "MISSING_RUN_MANIFEST" not in codes, (
            "MISSING_RUN_MANIFEST should be reserved for absent/unreadable runs"
        )

    def test_collector_populates_manifest_hash_from_manifest_json(self):
        """When manifest.json exists, collector reads hashes from it."""
        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.initialize()

        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test Plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="main", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=cid, step_id=cid,
                is_shared_upstream=False, is_branch_owned=True,
            )

        manifest = RunManifest(
            run_id=run_id, plan_version_id=pv_id, plan_id=plan_id,
            project_id=project_id, status="succeeded",
        )
        manifest.manifest_hash = compute_manifest_hash(manifest)
        manifest_dir = store.root / "exports" / f"manifest-{run_id}"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2)
        )

        for sid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.save_run_step(RunStepRecord(
                run_step_id=str(uuid.uuid4()), run_id=run_id, step_id=sid,
                plan_version_id=pv_id, status="succeeded",
                started_at=utc_now_iso(), finished_at=utc_now_iso(),
                input_artifact_ids=[], output_artifact_ids=[],
                execution_fingerprint={},
                warnings=[], errors=[],
            ))

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )

        assert bundle.source.run_manifest_hash == manifest.manifest_hash
        assert bundle.reproducibility.manifest_hash == manifest.manifest_hash

    def _setup_manifest_test(self):
        """Create a store with a succeeded run and a branch step map."""
        tmp = Path(tempfile.mkdtemp())
        store = ProjectStore(tmp / "test.cardre")
        store.initialize()

        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test Plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")

        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="main", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=cid, step_id=cid,
                is_shared_upstream=False, is_branch_owned=True,
            )

        for sid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.save_run_step(RunStepRecord(
                run_step_id=str(uuid.uuid4()), run_id=run_id, step_id=sid,
                plan_version_id=pv_id, status="succeeded",
                started_at=utc_now_iso(), finished_at=utc_now_iso(),
                input_artifact_ids=[], output_artifact_ids=[],
                execution_fingerprint={},
                warnings=[], errors=[],
            ))
        return store, project_id, plan_id, pv_id, run_id, branch_id

    def test_canonical_manifest_missing_emits_warning(self):
        """No manifest.json -> CANONICAL_MANIFEST_MISSING warning."""
        store, project_id, plan_id, pv_id, run_id, branch_id = self._setup_manifest_test()
        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        assert "CANONICAL_MANIFEST_MISSING" in codes, (
            f"Expected CANONICAL_MANIFEST_MISSING, got {codes}"
        )
        # Hash fields should be empty
        assert bundle.source.run_manifest_hash == ""
        assert bundle.reproducibility.manifest_hash == ""

    def test_canonical_manifest_invalid_json_blocks(self):
        """Invalid JSON in manifest.json -> CANONICAL_MANIFEST_UNREADABLE blocker."""
        store, project_id, plan_id, pv_id, run_id, branch_id = self._setup_manifest_test()
        manifest_dir = store.root / "exports" / f"manifest-{run_id}"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "manifest.json").write_text("not valid json")

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        assert "CANONICAL_MANIFEST_UNREADABLE" in codes, (
            f"Expected CANONICAL_MANIFEST_UNREADABLE, got {codes}"
        )

    def test_canonical_manifest_hash_mismatch_blocks(self):
        """Tampered manifest (wrong hash) -> ARTIFACT_HASH_UNRESOLVED blocker."""
        store, project_id, plan_id, pv_id, run_id, branch_id = self._setup_manifest_test()

        # Write manifest with correct hash
        manifest = RunManifest(
            run_id=run_id, plan_version_id=pv_id, plan_id=plan_id,
            project_id=project_id, status="succeeded",
        )
        correct_hash = compute_manifest_hash(manifest)
        manifest.manifest_hash = correct_hash
        manifest_dir = store.root / "exports" / f"manifest-{run_id}"
        manifest_dir.mkdir(parents=True, exist_ok=True)

        manifest_data = json.loads(manifest.model_dump_json(indent=2))
        manifest_data["manifest_hash"] = "000000" + correct_hash[6:]  # corrupt the hash
        (manifest_dir / "manifest.json").write_text(
            json.dumps(manifest_data, indent=2, sort_keys=True)
        )

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        assert "ARTIFACT_HASH_UNRESOLVED" in codes, (
            f"Expected ARTIFACT_HASH_UNRESOLVED, got {codes}"
        )

    def test_canonical_manifest_extra_field_causes_hash_mismatch(self):
        """Extra field not in the RunManifest model causes hash mismatch (raw-dict hashing)."""
        store, project_id, plan_id, pv_id, run_id, branch_id = self._setup_manifest_test()

        manifest = RunManifest(
            run_id=run_id, plan_version_id=pv_id, plan_id=plan_id,
            project_id=project_id, status="succeeded",
        )
        correct_hash = compute_manifest_hash(manifest)
        manifest_dir = store.root / "exports" / f"manifest-{run_id}"
        manifest_dir.mkdir(parents=True, exist_ok=True)

        manifest_data = json.loads(manifest.model_dump_json(indent=2))
        manifest_data["manifest_hash"] = correct_hash
        manifest_data["tampered_field"] = "extra data not in schema"

        (manifest_dir / "manifest.json").write_text(
            json.dumps(manifest_data, indent=2, sort_keys=True)
        )

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        # Extra field changes the raw-dict hash, so we get ARTIFACT_HASH_UNRESOLVED
        assert "ARTIFACT_HASH_UNRESOLVED" in codes, (
            f"Expected ARTIFACT_HASH_UNRESOLVED for manifest with extra field, got {codes}"
        )

    def test_canonical_manifest_schema_violation_blocks(self):
        """Manifest missing required field -> CANONICAL_MANIFEST_UNREADABLE blocker."""
        store, project_id, plan_id, pv_id, run_id, branch_id = self._setup_manifest_test()

        manifest = RunManifest(
            run_id=run_id, plan_version_id=pv_id, plan_id=plan_id,
            project_id=project_id, status="succeeded",
        )
        correct_hash = compute_manifest_hash(manifest)
        manifest_dir = store.root / "exports" / f"manifest-{run_id}"
        manifest_dir.mkdir(parents=True, exist_ok=True)

        manifest_data = json.loads(manifest.model_dump_json(indent=2))
        manifest_data["manifest_hash"] = correct_hash
        del manifest_data["run_id"]  # remove required field

        (manifest_dir / "manifest.json").write_text(
            json.dumps(manifest_data, indent=2, sort_keys=True)
        )

        bundle = generate_report_bundle(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {l.code for l in bundle.limitations}
        assert "CANONICAL_MANIFEST_UNREADABLE" in codes, (
            f"Expected CANONICAL_MANIFEST_UNREADABLE for schema-violating manifest, got {codes}"
        )
