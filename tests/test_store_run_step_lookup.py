from __future__ import annotations

import uuid

from cardre.domain.diagnostics import utc_now_iso
from cardre.domain.run import RunStep, RunStepStatus
from cardre.domain.step import StepSpec
from cardre.store.plan_repo import PlanRepository
from cardre.store.run_step_repo import RunStepRepository


def test_project_store_get_latest_successful_run_step_returns_run_step(store) -> None:
    now = utc_now_iso()
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

    run_id = str(uuid.uuid4())
    store.execute(
        "INSERT INTO runs (run_id, plan_version_id, status, created_at, started_at, finished_at) "
        "VALUES (?, ?, 'succeeded', ?, ?, ?)",
        (run_id, pv_id, now, now, now),
    )
    run_step = RunStep(
        run_step_id=str(uuid.uuid4()),
        run_id=run_id,
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
        warnings=[],
        errors=[],
    )
    RunStepRepository(store).save(run_step)

    found = store.get_latest_successful_run_step(pv_id, "step-a")

    assert found is not None
    assert isinstance(found, RunStep)
    assert found.run_step_id == run_step.run_step_id
    assert found.step_id == "step-a"
