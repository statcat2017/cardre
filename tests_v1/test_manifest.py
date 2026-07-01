"""Tests for the canonical RunManifest model and manifest.json generation."""

from __future__ import annotations

import json
import uuid

from cardre.audit import json_logical_hash, utc_now_iso
from cardre.run_lifecycle import compute_manifest_hash, write_manifest
from cardre.reporting.schema import RunManifest, RunManifestStep

from cardre.audit import RunStepRecord
from tests.helpers import make_store


class TestRunManifestModel:
    """RunManifest Pydantic model contract."""

    def test_required_fields(self):
        m = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        assert m.manifest_version == "cardre.run_manifest.v1"
        assert m.run_id == "r1"
        assert m.plan_version_id == "pv1"
        assert m.plan_id == "p1"
        assert m.project_id == "prj1"
        assert m.manifest_hash == ""
        assert m.status == ""
        assert m.execution_mode == "unknown"

    def test_serializes_deterministically(self):
        m1 = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        m2 = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        assert m1.model_dump_json(indent=2) == m2.model_dump_json(indent=2)

    def test_steps_roundtrip(self):
        step = RunManifestStep(
            step_id="fit-model",
            canonical_step_id="logistic-regression",
            node_type="cardre.logistic_regression",
            status="succeeded",
            action="executed",
            params_hash="abc123",
            output_artifact_ids=["art_1"],
        )
        m = RunManifest(
            run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1",
            steps=[step],
        )
        d = m.model_dump(mode="json", by_alias=False)
        steps = d["steps"]
        assert len(steps) == 1
        assert steps[0]["step_id"] == "fit-model"
        assert steps[0]["action"] == "executed"
        assert steps[0]["canonical_step_id"] == "logistic-regression"

    def test_manifest_hash_is_sha256_hex(self):
        m = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        h = compute_manifest_hash(m)
        assert isinstance(h, str)
        assert len(h) == 64
        int(h, 16)  # must be valid hex

    def test_manifest_hash_stable_for_identical_manifest(self):
        m1 = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        m2 = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        h1 = compute_manifest_hash(m1)
        h2 = compute_manifest_hash(m2)
        assert h1 == h2

    def test_manifest_hash_differs_when_content_differs(self):
        m1 = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        m2 = RunManifest(run_id="r2", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        assert compute_manifest_hash(m1) != compute_manifest_hash(m2)

    def test_manifest_hash_blanks_own_field(self):
        """manifest_hash is computed with the manifest_hash field blanked."""
        m = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        h = compute_manifest_hash(m)
        payload = m.model_dump(mode="json", by_alias=False)
        payload["manifest_hash"] = ""
        expected = json_logical_hash(payload)
        assert h == expected

    def test_model_roundtrip_from_json(self):
        m1 = RunManifest(run_id="r1", plan_version_id="pv1", plan_id="p1", project_id="prj1")
        h = compute_manifest_hash(m1)
        m1.manifest_hash = h
        data = m1.model_dump(mode="json")
        m2 = RunManifest(**data)
        assert m2.manifest_hash == h
        assert m2.run_id == "r1"


class TestWriteManifestJson:
    """write_manifest must produce a canonical manifest.json alongside the run_manifest artifact."""

    def test_manifest_json_written_alongside_run_manifest(self):
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)

        # Simulate a run step so the manifest has content
        store.save_run_step(RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=run_id, step_id="source",
            plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[],
            execution_fingerprint={
                "params_hash": "abc", "node_type": "test", "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [],
            },
            warnings=[], errors=[],
        ))

        store.finish_run(run_id, status="succeeded")

        write_manifest(
            store,
            run_id=run_id,
            plan_version_id=pv_id,
            execution_mode="full",
            final_status="succeeded",
            finished_at=utc_now_iso(),
        )

        # Assert run_manifest artifact exists
        manifest_arts = [a for a in store.list_artifacts() if a.artifact_type == "run_manifest"]
        assert len(manifest_arts) >= 1

        # Assert manifest.json exists on disk
        manifest_json_path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert manifest_json_path.exists(), f"Expected {manifest_json_path} to exist"

        # Read and validate
        manifest_data = json.loads(manifest_json_path.read_text())
        assert manifest_data["run_id"] == run_id
        assert manifest_data["manifest_version"] == "cardre.run_manifest.v1"
        assert len(manifest_data["manifest_hash"]) == 64
        assert manifest_data["status"] == "succeeded"
        assert manifest_data["execution_mode"] == "full"
        assert len(manifest_data["steps"]) == 1

        # Verify hash integrity: recompute and compare
        actual_hash = manifest_data["manifest_hash"]
        manifest_data_copy = dict(manifest_data)
        manifest_data_copy["manifest_hash"] = ""
        expected_hash = json_logical_hash(manifest_data_copy)
        assert actual_hash == expected_hash, "manifest_hash must be self-consistent"

    def test_manifest_json_hash_differs_across_two_writes(self):
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id1 = store.create_run(pv_id)

        store.save_run_step(RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=run_id1, step_id="source",
            plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[],
            execution_fingerprint={
                "params_hash": "abc", "node_type": "test", "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [],
            },
            warnings=[], errors=[],
        ))
        store.finish_run(run_id1, status="succeeded")

        run_id2 = store.create_run(pv_id)
        store.save_run_step(RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=run_id2, step_id="source",
            plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[],
            execution_fingerprint={
                "params_hash": "abc", "node_type": "test", "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [],
            },
            warnings=[], errors=[],
        ))
        store.finish_run(run_id2, status="succeeded")

        # Write manifests for both runs and compare hashes
        hashes = []
        for i, rid in enumerate((run_id1, run_id2)):
            write_manifest(
                store,
                run_id=rid,
                plan_version_id=pv_id,
                execution_mode="full",
                final_status="succeeded",
                finished_at=utc_now_iso(),
            )
            manifest_json_path = store.root / "exports" / f"manifest-{rid}" / "manifest.json"
            manifest_data = json.loads(manifest_json_path.read_text())
            hashes.append(manifest_data["manifest_hash"])

        # Different run_ids -> different hashes
        assert hashes[0] != hashes[1]

    def test_manifest_json_path_in_exports(self):
        """The manifest.json is written under exports/ for discoverability."""
        store, tmp = make_store()
        store.initialize()
        project_id = store.create_project("test")
        plan_id = store.create_plan(project_id, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)

        store.save_run_step(RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=run_id, step_id="source",
            plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[],
            execution_fingerprint={
                "params_hash": "abc", "node_type": "test", "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [],
            },
            warnings=[], errors=[],
        ))
        store.finish_run(run_id, status="succeeded")

        write_manifest(
            store,
            run_id=run_id,
            plan_version_id=pv_id,
            execution_mode="full",
            final_status="succeeded",
            finished_at=utc_now_iso(),
        )

        path = store.root / "exports" / f"manifest-{run_id}" / "manifest.json"
        assert path.is_relative_to(store.root / "exports")
