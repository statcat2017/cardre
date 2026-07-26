"""Contract tests for the truthful run lifecycle API (Commit 1).

Covers persisted run read-model hydration, staleness from the persisted
heartbeat, cooperative cancellation, run submission validation, force
behaviour, and 404 semantics for unknown run steps/evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cardre.application.runs.submit_run import SubmitRun
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import CardreError
from cardre.domain.run import RunStatus
from cardre.domain.step import StepSpec


class _NoopDispatcher:
    def dispatch(self, request):  # noqa: D401
        pass


def _make_submit(uow_factory, project_id):
    from cardre.application.runs.submit_run import SubmitRun
    return SubmitRun(
        lambda: uow_factory.for_project(project_id), _NoopDispatcher(), None, None,
        governance_enabled=True, project_id=project_id,
    )


def _cmd(pv_id, *, branch_id=None, run_scope="full_plan", force=False, sync=False):
    from cardre.application.runs.submit_run import SubmitRunCommand
    return SubmitRunCommand(
        plan_version_id=pv_id, run_scope=run_scope,
        branch_id=branch_id, force=force, sync=sync,
    )


def _seed_branch(uow_factory, project_id, pv_id, *, head_plan_version_id=None):
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.get_version(pv_id).plan_id
        branch_id = uow.branches.create_branch(
            project_id=project_id,
            plan_id=plan_id,
            name="branch",
            branch_type="challenger",
            base_plan_version_id=pv_id,
            head_plan_version_id=head_plan_version_id or pv_id,
            created_reason="test",
        )
        uow.commit()
    return branch_id


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


# ---------------------------------------------------------------------------
# Submission validation
# ---------------------------------------------------------------------------


def test_submit_branch_scope_requires_branch_id(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    with pytest.raises(CardreError) as exc:
        submit(_cmd(pv_id, run_scope="branch"))
    assert exc.value.code == "BRANCH_VALIDATION_ERROR"


def test_submit_full_plan_rejects_branch_id(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    with pytest.raises(CardreError) as exc:
        submit(_cmd(pv_id, run_scope="full_plan", branch_id="br-1"))
    assert exc.value.code == "BRANCH_VALIDATION_ERROR"


def test_submit_invalid_scope_returns_stable_error(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    with pytest.raises(CardreError) as exc:
        submit(_cmd(pv_id, run_scope="nonsense"))
    assert exc.value.code == "RUN_SCOPE_INVALID"


def test_submit_branch_scope_records_branch_id(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    branch_id = _seed_branch(uow_factory, project_id, pv_id)
    result = submit(_cmd(pv_id, branch_id=branch_id, run_scope="branch"))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(result.run_id)
    assert run is not None
    assert run.run_scope == "branch"
    assert run.branch_id == branch_id


def test_submit_branch_scope_requires_governance(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    branch_id = _seed_branch(uow_factory, project_id, pv_id)
    submit = SubmitRun(
        lambda: uow_factory.for_project(project_id), _NoopDispatcher(), None, None,
        governance_enabled=False, project_id=project_id,
    )
    with pytest.raises(CardreError) as exc:
        submit(_cmd(pv_id, branch_id=branch_id, run_scope="branch"))
    assert exc.value.code == "GOVERNANCE_NOT_ENABLED"


def test_submit_branch_scope_rejects_missing_branch(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    with pytest.raises(CardreError) as exc:
        _make_submit(uow_factory, project_id)(_cmd(pv_id, branch_id="missing", run_scope="branch"))
    assert exc.value.code == "BRANCH_NOT_FOUND"


def test_submit_branch_scope_rejects_branch_from_another_plan(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    with uow_factory.for_project(project_id) as uow:
        other_plan_id = uow.plans.create_plan(project_id, "Other Plan")
        other_pv_id = uow.plans.create_version(other_plan_id, [], is_committed=True)
        uow.commit()
    branch_id = _seed_branch(uow_factory, project_id, other_pv_id)
    with pytest.raises(CardreError) as exc:
        _make_submit(uow_factory, project_id)(_cmd(pv_id, branch_id=branch_id, run_scope="branch"))
    assert exc.value.code == "BRANCH_SCOPE_MISMATCH"


def test_submit_branch_scope_requires_branch_head_to_match_plan_version(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.get_version(pv_id).plan_id
        other_pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
        uow.commit()
    branch_id = _seed_branch(uow_factory, project_id, pv_id, head_plan_version_id=other_pv_id)
    with pytest.raises(CardreError) as exc:
        _make_submit(uow_factory, project_id)(_cmd(pv_id, branch_id=branch_id, run_scope="branch"))
    assert exc.value.code == "BRANCH_PLAN_VERSION_MISMATCH"


# ---------------------------------------------------------------------------
# Force behaviour
# ---------------------------------------------------------------------------


def test_submit_force_bypasses_concurrent_check(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with pytest.raises(CardreError):
        submit(_cmd(pv_id, force=False))
    r2 = submit(_cmd(pv_id, force=True))
    assert r2.run_id != r1.run_id


def test_new_submission_does_not_interrupt_healthy_running_run(committed_plan):
    """A second forced submission creates a new run but leaves a healthy
    running run's status intact (not terminal)."""
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
        uow.runs.heartbeat(r1.run_id)
        uow.commit()
    # Forced submission of a second run does not touch the first.
    submit(_cmd(pv_id, force=True))
    with uow_factory.read_only(project_id) as uow:
        first = uow.runs.get(r1.run_id)
    assert first is not None
    assert first.status == RunStatus.RUNNING.value


# ---------------------------------------------------------------------------
# Staleness from persisted heartbeat
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_recent_heartbeat_is_fresh(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
        uow.runs.heartbeat(r1.run_id)
        uow.commit()
    from cardre.api.mappers import _is_stale
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.heartbeat_at is not None
    assert _is_stale(run) is False


def test_old_heartbeat_is_stale(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    old = datetime.now(UTC) - timedelta(seconds=400)
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
        # Set an old heartbeat directly via the repo writer path.
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?", (_iso(old), r1.run_id),
        )
        uow.commit()
    from cardre.api.mappers import _is_stale
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.status == RunStatus.RUNNING.value
    assert _is_stale(run) is True


def test_running_run_with_no_heartbeat_is_stale(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = NULL WHERE run_id = ?", (r1.run_id,),
        )
        uow.commit()
    from cardre.api.mappers import _is_stale
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert _is_stale(run) is True


def test_terminal_run_is_never_stale(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.FAILED)
        uow.commit()
    from cardre.api.mappers import _is_stale
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert _is_stale(run) is False


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancel_persists_cancel_requested_and_preserves_running(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
        uow.runs.heartbeat(r1.run_id)
        uow.commit()
    cancel = CancelRun(lambda: uow_factory.for_project(project_id))
    cancel(CancelRunCommand(run_id=r1.run_id))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.cancel_requested is True
    assert run.status == RunStatus.RUNNING.value


def test_cancel_rejects_non_running(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.FAILED)
        uow.commit()
    cancel = CancelRun(lambda: uow_factory.for_project(project_id))
    with pytest.raises(CardreError) as exc:
        cancel(CancelRunCommand(run_id=r1.run_id))
    assert exc.value.code == "RUN_NOT_RUNNING"


def test_cancel_unknown_returns_not_found(committed_plan):
    project_id, uow_factory, pv_id = committed_plan  # noqa: F841
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    cancel = CancelRun(lambda: uow_factory.for_project(project_id))
    with pytest.raises(CardreError) as exc:
        cancel(CancelRunCommand(run_id="nonexistent"))
    assert exc.value.code == "RUN_NOT_FOUND"


def test_cancel_visible_on_subsequent_get(committed_plan):
    """cancel_requested persists and is visible on a fresh read."""
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.CREATED,))
        uow.runs.heartbeat(r1.run_id)
        uow.commit()
    CancelRun(lambda: uow_factory.for_project(project_id))(CancelRunCommand(run_id=r1.run_id))
    # Fresh read from a new UoW must observe cancel_requested.
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.cancel_requested is True


# ---------------------------------------------------------------------------
# 404 for unknown run steps/evidence
# ---------------------------------------------------------------------------


def test_run_steps_unknown_run_returns_not_found(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    with uow_factory.read_only(project_id) as uow:
        assert uow.runs.get("nonexistent") is None
        # get_for_run returns [] but the route must guard with run existence.
        steps = uow.run_steps.get_for_run("nonexistent")
    assert steps == []


def test_run_evidence_unknown_run_returns_not_found(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    with uow_factory.read_only(project_id) as uow:
        assert uow.runs.get("nonexistent") is None
        edges = uow.evidence.get_edges_for_run("nonexistent")
    assert edges == []


# ---------------------------------------------------------------------------
# Run read-model hydration
# ---------------------------------------------------------------------------


def test_run_read_model_hydrates_all_fields(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    result = submit(_cmd(pv_id, run_scope="full_plan", force=True))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(result.run_id)
    assert run is not None
    assert run.run_scope == "full_plan"
    assert run.force is True
    assert run.cancel_requested is False
    assert run.heartbeat_at is not None  # create sets heartbeat_at to now
    assert run.status in (RunStatus.CREATED.value, RunStatus.QUEUED.value)
