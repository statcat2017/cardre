from __future__ import annotations

import uuid

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import RunStep, RunStepStatus
from cardre.domain.step import StepSpec


def test_project_store_get_latest_successful_run_step_returns_run_step(provisioned_project) -> None:
    project_id, uow_factory, _, _ = provisioned_project
    now = utc_now_iso()
    later = "2099-01-01T00:00:00+00:00"

    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            steps=[
                StepSpec(
                    step_id="step-a",
                    node_type="cardre.noop",
                    node_version="1",
                    category="transform",
                    params={},
                    params_hash="hash-step-a",
                    parent_step_ids=[],
                    position=0,
                    canonical_step_id="step-a",
                )
            ],
            is_committed=True,
        )

        baseline_run_id = str(uuid.uuid4())
        uow._conn.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, branch_id, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', 'full_plan', NULL, ?, ?, ?)",
            (baseline_run_id, pv_id, now, now, now),
        )
        baseline_step = RunStep(
            run_step_id=str(uuid.uuid4()),
            run_id=baseline_run_id,
            step_id="step-a",
            plan_version_id=pv_id,
            status=RunStepStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
            execution_fingerprint={
                "params_hash": "hash-step-a",
                "node_type": "cardre.noop",
                "node_version": "1",
            },
            warnings=[{"code": "BASELINE_WARNING"}],
            errors=[{"code": "BASELINE_ERROR"}],
        )
        uow.run_steps.insert(baseline_step)

        branch_run_id = str(uuid.uuid4())
        branch_id = "branch-1"
        uow._conn.execute(
            "INSERT INTO runs (run_id, plan_version_id, status, run_scope, branch_id, created_at, started_at, finished_at) "
            "VALUES (?, ?, 'succeeded', 'branch', ?, ?, ?, ?)",
            (branch_run_id, pv_id, branch_id, now, later, later),
        )
        branch_step = RunStep(
            run_step_id=str(uuid.uuid4()),
            run_id=branch_run_id,
            step_id="step-a",
            plan_version_id=pv_id,
            status=RunStepStatus.SUCCEEDED,
            started_at=later,
            finished_at=later,
            execution_fingerprint={
                "params_hash": "hash-step-a-branch",
                "node_type": "cardre.noop",
                "node_version": "1",
            },
            warnings=[{"code": "BRANCH_WARNING"}],
            errors=[{"code": "BRANCH_ERROR"}],
        )
        uow.run_steps.insert(branch_step)

        found = uow.run_steps.get_latest_successful_step(pv_id, "step-a")
        branch_found = uow.run_steps.get_latest_successful_step(pv_id, "step-a", branch_id=branch_id)
        missing = uow.run_steps.get_latest_successful_step(pv_id, "missing-step")

        assert found is not None
        assert isinstance(found, RunStep)
        assert found.run_step_id == baseline_step.run_step_id
        assert found.step_id == "step-a"
        assert found.warnings == [{"code": "BASELINE_WARNING"}]
        assert found.errors == [{"code": "BASELINE_ERROR"}]
        assert found.execution_fingerprint["params_hash"] == "hash-step-a"

        assert branch_found is not None
        assert branch_found.run_step_id == branch_step.run_step_id
        assert branch_found.warnings == [{"code": "BRANCH_WARNING"}]
        assert branch_found.errors == [{"code": "BRANCH_ERROR"}]
        assert branch_found.execution_fingerprint["params_hash"] == "hash-step-a-branch"

        assert missing is None
