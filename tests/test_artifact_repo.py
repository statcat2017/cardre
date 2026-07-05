from __future__ import annotations

import uuid

from cardre.domain.artifacts import ArtifactRef
from cardre.domain.diagnostics import utc_now_iso


class TestArtifactRepository:
    def test_register_and_get(self, store):
        from cardre.store.artifact_repo import ArtifactRepository
        repo = ArtifactRepository(store)
        ref = ArtifactRef(
            artifact_id=str(uuid.uuid4()), artifact_type="test", role="test",
            path="/tmp/test.json", physical_hash="ph", logical_hash="lh",
            media_type="application/json", created_at=utc_now_iso(),
            metadata={"key": "value"},
        )
        returned_id = repo.register(ref)
        assert returned_id == ref.artifact_id
        got = repo.get(ref.artifact_id)
        assert got is not None
        assert got.artifact_id == ref.artifact_id
        assert got.metadata == {"key": "value"}

        missing = repo.get("nonexistent")
        assert missing is None

    def test_list(self, store):
        from cardre.store.artifact_repo import ArtifactRepository
        repo = ArtifactRepository(store)
        ref1 = ArtifactRef(
            artifact_id="a1", artifact_type="t1", role="r1", path="/p1",
            physical_hash="ph1", logical_hash="lh1", created_at=utc_now_iso(),
        )
        ref2 = ArtifactRef(
            artifact_id="a2", artifact_type="t2", role="r2", path="/p2",
            physical_hash="ph2", logical_hash="lh2", created_at=utc_now_iso(),
        )
        repo.register(ref1)
        repo.register(ref2)
        all_artifacts = repo.list()
        assert len(all_artifacts) == 2

    def test_register_lineage(self, store):
        from cardre.store.artifact_repo import ArtifactRepository
        from cardre.store.run_repo import RunRepository
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = RunRepository(store).create(pv_id)
        store.execute(
            "INSERT INTO run_steps "
            "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
            " execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            ("rs-1", run_id, "step-a", pv_id, now, now),
        )
        art_id = "art-lineage-1"
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (art_id, "test", "test", "/tmp", "ph", "lh", "application/json", now),
        )
        repo = ArtifactRepository(store)
        lineage_id = repo.register_lineage(
            run_id=run_id, run_step_id="rs-1", plan_version_id=pv_id,
            step_id="step-a", artifact_id=art_id, direction="output",
        )
        assert lineage_id is not None
        lineage = repo.get_lineage_for_run_step("rs-1")
        assert len(lineage) >= 1
        assert any(item["direction"] == "output" for item in lineage)

    def test_list_for_project(self, store):
        from cardre.store.artifact_repo import ArtifactRepository
        from cardre.store.run_repo import RunRepository

        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        plan_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plans (plan_id, project_id, name, created_at) VALUES (?, ?, ?, ?)",
            (plan_id, project_id, "Test", now),
        )
        pv_id = str(uuid.uuid4())
        store.execute(
            "INSERT INTO plan_versions (plan_version_id, plan_id, version_number, is_committed, created_at) "
            "VALUES (?, ?, 1, 1, ?)",
            (pv_id, plan_id, now),
        )
        run_id = RunRepository(store).create(pv_id)
        step_id = "step-output"
        store.execute(
            "INSERT INTO plan_steps (step_id, plan_version_id, node_type, node_version, category, "
            " params_json, params_hash, branch_label, position, canonical_step_id) "
            "VALUES (?, ?, 'cardre.noop', '1', 'fit', '{}', 'h', '', 0, ?)",
            (step_id, pv_id, step_id),
        )
        store.execute(
            "INSERT INTO run_steps "
            "(run_step_id, run_id, step_id, plan_version_id, status, started_at, finished_at, "
            " execution_fingerprint_json, warnings_json, errors_json) "
            "VALUES (?, ?, ?, ?, 'succeeded', ?, ?, '{}', '[]', '[]')",
            ("rs-out", run_id, step_id, pv_id, now, now),
        )
        art_id = "project-art-1"
        store.execute(
            "INSERT INTO artifacts (artifact_id, artifact_type, role, path, physical_hash, logical_hash, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (art_id, "scorecard", "scorecard", "/tmp/sc", "ph", "lh", "application/json", now),
        )
        store.execute(
            "INSERT INTO artifact_lineage (lineage_id, run_id, run_step_id, plan_version_id, step_id, artifact_id, direction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run_id, "rs-out", pv_id, step_id, art_id, "output", now),
        )
        repo = ArtifactRepository(store)
        project_artifacts = repo.list_for_project(project_id)
        assert len(project_artifacts) >= 1

        filtered_by_role = repo.list_for_project(project_id, role="scorecard")
        assert any(a.artifact_id == art_id for a in filtered_by_role)

        filtered_by_type = repo.list_for_project(project_id, artifact_type="scorecard")
        assert any(a.artifact_id == art_id for a in filtered_by_type)

        filtered_by_step = repo.list_for_project(project_id, producing_step_id=step_id)
        assert any(a.artifact_id == art_id for a in filtered_by_step)

        filtered_by_run = repo.list_for_project(project_id, run_id=run_id)
        assert any(a.artifact_id == art_id for a in filtered_by_run)
