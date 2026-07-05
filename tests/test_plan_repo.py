from __future__ import annotations

import uuid

from cardre.domain.diagnostics import utc_now_iso


class TestPlanRepository:
    def test_create_and_get_plan(self, store):
        from cardre.domain.artifacts import json_logical_hash
        from cardre.domain.step import StepSpec
        from cardre.store.plan_repo import PlanRepository
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        repo = PlanRepository(store)
        plan_id = repo.create_plan(project_id, "test-plan")
        assert plan_id is not None
        plan = repo.get_plan(plan_id)
        assert plan is not None
        assert plan["name"] == "test-plan"

        steps = [
            StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )
        ]
        pv_id = repo.create_version(plan_id, steps, description="v1", is_committed=True)
        assert pv_id is not None
        pv = repo.get_version(pv_id)
        assert pv is not None
        assert pv["is_committed"] == 1
        assert pv["description"] == "v1"

        version_steps = repo.get_version_steps(pv_id)
        assert len(version_steps) >= 1

        plans = repo.list_for_project(project_id)
        assert any(p["plan_id"] == plan_id for p in plans)

        versions = repo.list_versions(plan_id)
        assert any(v["plan_version_id"] == pv_id for v in versions)

        latest = repo.get_latest_version_id(plan_id)
        assert latest == pv_id
        assert repo.get_latest_version_id("nonexistent") is None

        commit_resp = repo.commit_version(pv_id)
        assert commit_resp is None

    def test_get_plan_not_found(self, store):
        from cardre.store.plan_repo import PlanRepository
        repo = PlanRepository(store)
        assert repo.get_plan("nonexistent") is None
        assert repo.get_version("nonexistent") is None
        assert repo.list_for_project("nonexistent") == []
        assert repo.list_versions("nonexistent") == []
        assert repo.get_version_steps("nonexistent") == []

    def test_get_plan_id_for_version(self, store):
        from cardre.store.plan_repo import PlanRepository
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        repo = PlanRepository(store)
        plan_id = repo.create_plan(project_id, "test-plan")
        pv_id = repo.create_version(plan_id, [], description="v1", is_committed=True)
        assert repo.get_plan_id_for_version(pv_id) == plan_id
        assert repo.get_plan_id_for_version("nonexistent") is None

    def test_commit_version_and_update_description(self, store):
        from cardre.store.plan_repo import PlanRepository
        project_id = str(uuid.uuid4())
        now = utc_now_iso()
        store.execute(
            "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
            (project_id, "Test", now, "0.2.0"),
        )
        repo = PlanRepository(store)
        plan_id = repo.create_plan(project_id, "test-plan")
        pv_id = repo.create_version(plan_id, [], description="v1", is_committed=False)
        repo.commit_version(pv_id)
        pv = repo.get_version(pv_id)
        assert pv["is_committed"] == 1

        repo.update_version_description(pv_id, "Updated description")
        pv = repo.get_version(pv_id)
        assert pv["description"] == "Updated description"
