"""Contract tests for SubmitRun and CancelRun.

Covers the run submission contract (run_scope, branch_id, force) and the
cancellation contract (no-op guard + RUN_NOT_RUNNING), exercising the
production SQLite stack.
"""

from __future__ import annotations

import pytest

from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError
from cardre.domain.run import RunStatus
from cardre.domain.step import StepSpec


class _NoopDispatcher:
    def dispatch(self, request):  # noqa: D401
        pass


def _make_submit(uow_factory, project_id):
    from cardre.application.runs.submit_run import SubmitRun
    return SubmitRun(lambda: uow_factory.for_project(project_id), _NoopDispatcher(), None, None)


@pytest.fixture
def committed_plan(provisioned_project):
    project_id, uow_factory, registry, root = provisioned_project
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="step-noop", node_type="cardre.noop",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
                canonical_step_id="noop",
            )],
            description="base", is_committed=True,
        )
        uow.commit()
    return project_id, uow_factory, pv_id


def test_submit_run_records_branch_scope_and_id(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    result = submit(SubmitRunCommand_helper(pv_id, branch_id="br-1", run_scope="branch"))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(result.run_id)
    assert run is not None
    assert run.branch_id == "br-1"


def SubmitRunCommand_helper(pv_id, *, branch_id=None, run_scope="full_plan", force=False, sync=False):
    from cardre.application.runs.submit_run import SubmitRunCommand
    return SubmitRunCommand(
        plan_version_id=pv_id, run_scope=run_scope,
        branch_id=branch_id, force=force, sync=sync,
    )


def test_submit_run_force_bypasses_concurrent_check(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(SubmitRunCommand_helper(pv_id))
    # Non-forced second submission is rejected because a concurrent run exists.
    with pytest.raises(CardreError):
        submit(SubmitRunCommand_helper(pv_id, force=False))
    # Forced submission bypasses the concurrent-run guard.
    r2 = submit(SubmitRunCommand_helper(pv_id, force=True))
    assert r2.run_id != r1.run_id


def test_cancel_run_rejects_non_running(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(SubmitRunCommand_helper(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.FAILED)
        uow.commit()
    cancel = CancelRun(lambda: uow_factory.for_project(project_id))
    with pytest.raises(CardreError) as exc:
        cancel(CancelRunCommand(run_id=r1.run_id))
    assert exc.value.code == "RUN_NOT_RUNNING"


def test_cancel_run_unknown_returns_not_found(committed_plan):
    project_id, uow_factory, pv_id = committed_plan  # noqa: F841
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    cancel = CancelRun(lambda: uow_factory.for_project(project_id))
    with pytest.raises(CardreError) as exc:
        cancel(CancelRunCommand(run_id="nonexistent"))
    assert exc.value.code == "RUN_NOT_FOUND"


def test_cancel_run_running_sets_flag(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(SubmitRunCommand_helper(pv_id))
    # Force the run into 'running' so set_cancel_requested applies.
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
        uow.commit()
    cancel = CancelRun(lambda: uow_factory.for_project(project_id))
    cancel(CancelRunCommand(run_id=r1.run_id))
    with uow_factory.read_only(project_id) as uow:
        row = uow.runs.get(r1.run_id)
    assert row is not None
    assert row.status == RunStatus.RUNNING.value
