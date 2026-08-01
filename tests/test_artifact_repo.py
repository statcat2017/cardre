from __future__ import annotations

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso


class TestArtifactRepository:
    def test_register_and_get(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            ref = ArtifactRef(
                artifact_id="art-reg", artifact_type="test", role="test",
                path="/tmp/test.json", physical_hash="ph", logical_hash="lh",
                media_type="application/json", created_at=utc_now_iso(),
                metadata={"key": "value"},
            )
            returned_id = uow.artifacts.register(ref)
            assert returned_id == ref.artifact_id
            got = uow.artifacts.get(ref.artifact_id)
            assert got is not None
            assert got.artifact_id == ref.artifact_id
            assert got.metadata["key"] == "value"

            missing = uow.artifacts.get("nonexistent")
            assert missing is None

    def test_register_same_bytes_different_role_creates_two_descriptors(self, provisioned_project):
        """Two descriptors with identical bytes but different role/type must be
        kept as separate descriptors referencing one shared blob (finding 3)."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            ref1 = ArtifactRef(
                artifact_id="a1", artifact_type="t1", role="r1", path="/p1",
                physical_hash="ph-shared", logical_hash="lh1", created_at=utc_now_iso(),
            )
            ref2 = ArtifactRef(
                artifact_id="a2", artifact_type="t2", role="r2", path="/p2",
                physical_hash="ph-shared", logical_hash="lh2", created_at=utc_now_iso(),
            )
            first = uow.artifacts.register(ref1)
            second = uow.artifacts.register(ref2)
            # Different role/type => distinct descriptors, one shared blob.
            assert first == "a1"
            assert second == "a2"
            assert uow.artifacts.get("a1") is not None
            assert uow.artifacts.get("a2") is not None
            blob = uow.artifacts.get_blob("ph-shared")
            assert blob is not None
            assert blob["physical_hash"] == "ph-shared"

    def test_register_identical_descriptor_is_idempotent(self, provisioned_project):
        """An exact duplicate descriptor (same semantic identity) returns the
        same id and does not create a second descriptor or blob."""
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            ref = ArtifactRef(
                artifact_id="a1", artifact_type="t1", role="r1", path="/p1",
                physical_hash="ph-shared", logical_hash="lh1", created_at=utc_now_iso(),
            )
            first = uow.artifacts.register(ref)
            second = uow.artifacts.register(ref)
            assert first == second == "a1"
            rows = uow._conn.execute(
                "SELECT artifact_id FROM artifacts WHERE physical_hash = ?", ("ph-shared",)
            ).fetchall()
            assert len(rows) == 1
            blobs = uow._conn.execute(
                "SELECT physical_hash FROM blobs WHERE physical_hash = ?", ("ph-shared",)
            ).fetchall()
            assert len(blobs) == 1

    def test_list_for_project(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "Test")
            pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
            run_id = uow.runs.create(pv_id)
            uow._conn.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
                ("rs-out", run_id, "step-output", pv_id, utc_now_iso(), utc_now_iso()),
            )
            ref1 = ArtifactRef(
                artifact_id="a1", artifact_type="t1", role="r1", path="/p1",
                physical_hash="ph1", logical_hash="lh1", created_at=utc_now_iso(),
            )
            ref2 = ArtifactRef(
                artifact_id="a2", artifact_type="t2", role="r2", path="/p2",
                physical_hash="ph2", logical_hash="lh2", created_at=utc_now_iso(),
            )
            uow.artifacts.register(ref1)
            uow.artifacts.register(ref2)
            uow.artifacts.register_lineage(
                run_id=run_id, run_step_id="rs-out", plan_version_id=pv_id,
                step_id="step-output", artifact_id="a1", direction="output",
            )
            uow.artifacts.register_lineage(
                run_id=run_id, run_step_id="rs-out", plan_version_id=pv_id,
                step_id="step-output", artifact_id="a2", direction="output",
            )

            all_artifacts = uow.artifacts.list_for_project(project_id)
            assert {a.artifact_id for a in all_artifacts} == {"a1", "a2"}

            filtered_by_role = uow.artifacts.list_for_project(project_id, role="r1")
            assert [a.artifact_id for a in filtered_by_role] == ["a1"]

            filtered_by_type = uow.artifacts.list_for_project(project_id, artifact_type="t2")
            assert [a.artifact_id for a in filtered_by_type] == ["a2"]

    def test_register_lineage(self, provisioned_project):
        project_id, uow_factory, _, _ = provisioned_project
        with uow_factory.for_project(project_id) as uow:
            plan_id = uow.plans.create_plan(project_id, "Test")
            pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
            run_id = uow.runs.create(pv_id)
            uow._conn.execute(
                "INSERT INTO run_steps (run_step_id, run_id, step_id, plan_version_id, status, "
                " started_at, finished_at, execution_fingerprint_json, warnings_json, errors_json) "
                "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
                ("rs-1", run_id, "step-a", pv_id, utc_now_iso(), utc_now_iso()),
            )
            art_id = "art-lineage-1"
            uow.artifacts.register(ArtifactRef(
                artifact_id=art_id, artifact_type="test", role="test", path="/tmp",
                physical_hash="ph", logical_hash="lh", created_at=utc_now_iso(),
            ))
            uow.artifacts.register_lineage(
                run_id=run_id, run_step_id="rs-1", plan_version_id=pv_id,
                step_id="step-a", artifact_id=art_id, direction="output",
            )

            ids = uow.artifacts.output_artifact_ids_for_run_step("rs-1")
            assert ids == [art_id]
            refs = uow.artifacts.output_artifacts_for_run_step("rs-1")
            assert [ref.artifact_id for ref in refs] == [art_id]
            run_ids = uow.artifacts.output_artifact_ids_for_run(run_id)
            assert run_ids == [art_id]

            for direction, ref in uow.artifacts.artifacts_for_run_step("rs-1"):
                assert direction == "output"
                assert ref.artifact_id == art_id

            assert uow.artifacts.get_for_project(project_id, art_id) is not None
            assert uow.artifacts.get_for_project("nonexistent", art_id) is None
