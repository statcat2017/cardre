"""Repository parity tests — verify that new repositories match ProjectStore behaviour.

Creates data through the public ProjectStore API, then asserts the new
repository classes return the same objects, ordering, and null/empty
behaviours.
"""

from __future__ import annotations


from cardre.audit import ArtifactRef, StepSpec, json_logical_hash
from cardre.store import (
    ArtifactRepository,
    BranchRepository,
    PlanRepository,
    ProjectRepository,
    RunRepository,
)
from tests.helpers import make_store


class TestProjectRepositoryParity:

    def test_create_and_get_project(self):
        store, tmp = make_store()
        repo = ProjectRepository(store)

        pid = store.create_project("parity-test")
        assert repo.get(pid) is not None
        assert repo.get(pid)["name"] == "parity-test"

    def test_get_project_none_for_missing(self):
        store, tmp = make_store()
        repo = ProjectRepository(store)
        assert repo.get("nonexistent") is None


class TestArtifactRepositoryParity:

    def test_register_and_list(self):
        store, tmp = make_store()
        store.initialize()
        repo = ArtifactRepository(store)

        art = ArtifactRef(
            artifact_id="a1", artifact_type="report", role="test",
            path="test.json", physical_hash="abc", logical_hash="def",
            media_type="application/json",
            metadata={},
        )
        store.register_artifact(art)

        listed = repo.list()
        assert len(listed) == 1
        assert listed[0].artifact_id == "a1"

    def test_get_none_for_missing(self):
        store, tmp = make_store()
        store.initialize()
        repo = ArtifactRepository(store)
        assert repo.get("nonexistent") is None


class TestPlanRepositoryParity:

    def test_create_and_get_plan(self):
        store, tmp = make_store()
        repo = PlanRepository(store)

        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")

        assert repo.get(plan_id) is not None
        assert repo.get(plan_id)["name"] == "test-plan"

    def test_create_and_get_version(self):
        store, tmp = make_store()
        repo = PlanRepository(store)

        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        steps = [
            StepSpec(
                step_id="s1", node_type="t", node_version="1", category="t",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        got = repo.get_version(pv_id)
        assert got is not None
        assert got["plan_id"] == plan_id


class TestRunRepositoryParity:

    def test_create_and_get_run(self):
        store, tmp = make_store()
        repo = RunRepository(store)

        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], "empty")

        run_id = store.create_run(pv_id)
        got = repo.get(run_id)
        assert got is not None
        assert got["status"] == "running"

    def test_latest_successful_returns_none_when_no_run(self):
        store, tmp = make_store()
        repo = RunRepository(store)

        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], "empty")

        assert repo.get_latest_successful_id(pv_id) is None


class TestBranchRepositoryParity:

    def test_create_and_get_branch(self):
        store, tmp = make_store()
        repo = BranchRepository(store)

        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], "empty")

        bid = store.create_branch(
            project_id=pid, plan_id=plan_id, name="test-branch",
            branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )
        got = repo.get(bid)
        assert got is not None
        assert got["name"] == "test-branch"

    def test_list_branches(self):
        store, tmp = make_store()
        repo = BranchRepository(store)

        pid = store.create_project("test")
        plan_id = store.create_plan(pid, "test-plan")
        pv_id = store.create_plan_version(plan_id, [], "empty")
        store.create_branch(
            project_id=pid, plan_id=plan_id, name="b1",
            branch_type="model_challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        listed = repo.list(pid)
        assert len(listed) >= 1
        names = {b["name"] for b in listed}
        assert "b1" in names
