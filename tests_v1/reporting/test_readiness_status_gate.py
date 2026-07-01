"""Tests for the RUN_NOT_SUCCEEDED readiness gate."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cardre.readiness import check_report_readiness
from cardre.store import ProjectStore


@pytest.fixture
def store():
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    return store


@pytest.fixture
def project_and_plan(store):
    project_id = store.create_project("test-proj")
    plan_id = store.create_plan(project_id, "Scorecard Pathway")
    store.create_plan_version(plan_id, [], description="v1")
    return project_id, plan_id


class TestReadinessStatusGate:
    """Readiness must block when run status is not succeeded."""

    def _setup_branch_with_run(self, store, project_id, plan_id, pv_id, run_id, branch_id):
        for cid in ("final-woe-iv", "model-fit", "score-scaling", "validation-metrics"):
            store.create_branch_step_map(
                branch_id=branch_id, plan_version_id=pv_id,
                canonical_step_id=cid, step_id=cid,
                is_shared_upstream=False, is_branch_owned=True,
            )

    def test_blocks_on_failed_run(self):
        store = ProjectStore(Path(tempfile.mkdtemp()) / "test.cardre")
        store.initialize()
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test Plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "failed")
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        self._setup_branch_with_run(store, project_id, plan_id, pv_id, run_id, branch_id)
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {str(b.code) for b in result.blockers}
        assert "RUN_NOT_SUCCEEDED" in codes, f"Expected RUN_NOT_SUCCEEDED, got {codes}"

    def test_blocks_on_interrupted_run(self):
        store = ProjectStore(Path(tempfile.mkdtemp()) / "test.cardre")
        store.initialize()
        project_id = store.create_project("Test")
        plan_id = store.create_plan(project_id, "Test Plan")
        pv_id = store.create_plan_version(plan_id, [], description="v1")
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "interrupted")
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        self._setup_branch_with_run(store, project_id, plan_id, pv_id, run_id, branch_id)
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {str(b.code) for b in result.blockers}
        assert "RUN_NOT_SUCCEEDED" in codes

    def test_no_status_blocker_for_succeeded_run(self, store, project_and_plan):
        project_id, plan_id = project_and_plan
        pv_id = store.get_latest_plan_version_id(plan_id)
        run_id = store.create_run(pv_id)
        store.finish_run(run_id, "succeeded")
        branch_id = store.create_branch(
            project_id=project_id, plan_id=plan_id,
            name="Branch", branch_type="baseline",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="Test.",
        )
        self._setup_branch_with_run(store, project_id, plan_id, pv_id, run_id, branch_id)
        result = check_report_readiness(
            store=store, project_id=project_id, run_id=run_id,
            target_branch_id=branch_id, report_mode="branch",
        )
        codes = {str(b.code) for b in result.blockers}
        assert "RUN_NOT_SUCCEEDED" not in codes
