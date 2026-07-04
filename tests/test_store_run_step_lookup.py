from __future__ import annotations

import uuid

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import RunStep, RunStepStatus
from cardre.domain.step import StepSpec
from cardre.store.plan_repo import PlanRepository
from cardre.store.run_step_repo import RunStepRepository


def test_project_store_get_latest_successful_run_step_returns_run_step(store) -> None:
    now = utc_now_iso()
    later = "2099-01-01T00:00:00+00:00"
    project_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO projects (project_id, name, created_at, cardre_version) VALUES (?, ?, ?, ?)",
        (project_id, "Project", now, "0.2.0"),
    )

    plan_repo = PlanRepository(store)
    plan_id = plan_repo.create_plan(project_id, "Plan")
    pv_id = plan_repo.create_version(
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
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, branch_id, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', NULL, ?, ?, ?)",
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
    RunStepRepository(store).save(baseline_step)

    branch_run_id = str(uuid.uuid4())
    branch_id = "branch-1"
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, branch_id, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?, ?)",
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
    RunStepRepository(store).save(branch_step)

    found = store.get_latest_successful_run_step(pv_id, "step-a")
    branch_found = store.get_latest_successful_run_step(pv_id, "step-a", branch_id=branch_id)
    missing = store.get_latest_successful_run_step(pv_id, "missing-step")

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
