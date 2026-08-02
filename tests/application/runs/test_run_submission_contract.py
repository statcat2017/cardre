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


class _FakeClock:
    def now_iso(self) -> str:
        return "2026-01-01T00:00:00Z"


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
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
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
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.runs.heartbeat(r1.run_id)
        uow.commit()
    from cardre.api.mappers import run_to_response
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.heartbeat_at is not None
    assert run.is_stale(stale_heartbeat_seconds=300) is False
    assert run_to_response(run, stale_heartbeat_seconds=300).is_stale is False


def test_old_heartbeat_is_stale(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    old = datetime.now(UTC) - timedelta(seconds=400)
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        # Set an old heartbeat directly via the repo writer path.
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?", (_iso(old), r1.run_id),
        )
        uow.commit()
    from cardre.api.mappers import run_to_response
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.status == RunStatus.RUNNING.value
    assert run.is_stale(stale_heartbeat_seconds=300) is True
    assert run_to_response(run, stale_heartbeat_seconds=300).is_stale is True


def test_running_run_with_no_heartbeat_is_stale(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = NULL WHERE run_id = ?", (r1.run_id,),
        )
        uow.commit()
    from cardre.api.mappers import run_to_response
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.is_stale(stale_heartbeat_seconds=300) is True
    assert run_to_response(run, stale_heartbeat_seconds=300).is_stale is True


def test_terminal_run_is_never_stale(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.FAILED)
        uow.commit()
    from cardre.api.mappers import run_to_response
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.is_stale(stale_heartbeat_seconds=300) is False
    assert run_to_response(run, stale_heartbeat_seconds=300).is_stale is False


# ---------------------------------------------------------------------------
# P1-1: stale sweep must not wedge submissions or kill live workers
# ---------------------------------------------------------------------------


def _submit_with_finalize(uow_factory, project_id):
    """A SubmitRun wired with a real FinalizeRun so the stale sweep can
    publish interrupted manifests."""
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    from cardre.application.runs.finalize_run import FinalizeRun
    from cardre.application.runs.submit_run import SubmitRun

    root = uow_factory._registry.resolve_root(project_id)
    finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), FsManifestPublisher(root), _FakeClock())
    return SubmitRun(
        lambda: uow_factory.for_project(project_id), _NoopDispatcher(), None, finalize,
        governance_enabled=True, project_id=project_id,
    )


def _set_old_heartbeat(uow_factory, project_id, run_id, age_seconds=400):
    from datetime import UTC, datetime, timedelta
    old = datetime.now(UTC) - timedelta(seconds=age_seconds)
    with uow_factory.for_project(project_id) as uow:
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?",
            (old.isoformat().replace("+00:00", "Z"), run_id),
        )
        uow.commit()


def test_sweep_stale_does_not_abort_new_submission(committed_plan):
    """A stale run that self-finalized before the sweep must not prevent the
    new submission from being created."""
    project_id, uow_factory, pv_id = committed_plan
    submit = _submit_with_finalize(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    _set_old_heartbeat(uow_factory, project_id, r1.run_id)
    # The run self-finalizes before the sweep runs.
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.SUCCEEDED)
        uow.commit()

    # A new submission must not be aborted by the stale sweep.
    r2 = submit(_cmd(pv_id))
    assert r2.run_id != r1.run_id
    with uow_factory.read_only(project_id) as uow:
        runs = uow.runs.list_for_plan_version(pv_id)
    assert any(r.run_id == r1.run_id and r.status == RunStatus.SUCCEEDED.value for r in runs)
    assert any(r.run_id == r2.run_id for r in runs)


def test_sweep_stale_does_not_interrupt_renewed_heartbeat(committed_plan):
    """A run whose heartbeat was renewed is not interrupted by the sweep."""
    project_id, uow_factory, pv_id = committed_plan
    submit = _submit_with_finalize(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    _set_old_heartbeat(uow_factory, project_id, r1.run_id, age_seconds=400)
    # Worker renews the heartbeat before the sweep.
    with uow_factory.for_project(project_id) as uow:
        uow.runs.heartbeat(r1.run_id)
        uow.commit()

    # The renewed run is legitimately active, so a second submission must be
    # forced; the point is the original run must NOT be interrupted.
    submit(_cmd(pv_id, force=True))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert str(run.status) == RunStatus.RUNNING.value, "renewed heartbeat must defeat the sweep"


def test_sweep_stale_interrupts_truly_stale_run(committed_plan):
    """A run whose heartbeat expired (and was not renewed) is interrupted, and
    the interruption is fully durable: RUN_STALE diagnostic, canonical manifest,
    and manifest outbox record are all produced atomically with the terminal
    transition (PR 373 review P1)."""
    project_id, uow_factory, pv_id = committed_plan
    submit = _submit_with_finalize(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    _set_old_heartbeat(uow_factory, project_id, r1.run_id, age_seconds=400)

    submit(_cmd(pv_id))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value

    # The interruption must carry its diagnostic, manifest, and outbox record.
    root = uow_factory._registry.resolve_root(project_id)
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    publisher = FsManifestPublisher(root)
    manifest = publisher.read(r1.run_id)
    assert manifest is not None, "interrupted run must publish a canonical manifest"
    assert manifest["status"] == "interrupted"

    with uow_factory.read_only(project_id) as uow:
        diags = uow.runs.get_diagnostics(r1.run_id)
        assert any(d.get("code") == "RUN_STALE" for d in diags), (
            "interrupted run must carry the RUN_STALE diagnostic"
        )
        outbox = uow.publications.list_by_run(r1.run_id)
        manifest_rows = [r for r in outbox if r["kind"] == "manifest"]
        assert manifest_rows, "interrupted run must have a manifest outbox record"
        assert manifest_rows[0]["state"] == "published"


def test_sweep_stale_interrupts_malformed_heartbeat(committed_plan):
    """A run with an unparsable heartbeat is classified as stale and
    interrupted atomically (PR 373 review P2), unless the worker renews it."""
    project_id, uow_factory, pv_id = committed_plan
    submit = _submit_with_finalize(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = 'not-a-timestamp' WHERE run_id = ?", (r1.run_id,)
        )
        uow.commit()

    submit(_cmd(pv_id))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value, "malformed heartbeat must be swept"

    root = uow_factory._registry.resolve_root(project_id)
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    assert FsManifestPublisher(root).read(r1.run_id) is not None


def test_sweep_stale_malformed_heartbeat_defeated_by_renewal(committed_plan):
    """A malformed heartbeat that is renewed before the sweep must not be
    interrupted — the compare-and-set fails safely (PR 373 review P2)."""
    project_id, uow_factory, pv_id = committed_plan
    submit = _submit_with_finalize(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = 'not-a-timestamp' WHERE run_id = ?", (r1.run_id,)
        )
        uow.commit()
    # Worker renews the heartbeat before the sweep.
    with uow_factory.for_project(project_id) as uow:
        uow.runs.heartbeat(r1.run_id)
        uow.commit()

    submit(_cmd(pv_id, force=True))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert str(run.status) == RunStatus.RUNNING.value, "renewal must defeat the sweep"


def _finalize_for(uow_factory, project_id):
    """A FinalizeRun wired to the real publisher for the project."""
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    from cardre.application.runs.finalize_run import FinalizeRun

    root = uow_factory._registry.resolve_root(project_id)
    return FinalizeRun(lambda: uow_factory.for_project(project_id), FsManifestPublisher(root), _FakeClock())


def test_stale_finalization_loses_after_heartbeat_renewal(committed_plan):
    """A stale finalization whose observed heartbeat was renewed before the
    compare-and-set loses: no status change, diagnostic, outbox row, or
    manifest (PR 373 review P2)."""
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher

    project_id, uow_factory, pv_id = committed_plan
    r1 = _make_submit(uow_factory, project_id)(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    _set_old_heartbeat(uow_factory, project_id, r1.run_id, age_seconds=400)
    observed = datetime.now(UTC) - timedelta(seconds=400)
    observed_iso = observed.isoformat().replace("+00:00", "Z")
    # Worker renews the heartbeat after the sweep observed the old value.
    with uow_factory.for_project(project_id) as uow:
        uow.runs.heartbeat(r1.run_id)
        uow.commit()

    from cardre.application.runs.finalize_run import FinalizeDiagnostic
    _finalize_for(uow_factory, project_id)(r1.run_id, "interrupted",
        diagnostic=FinalizeDiagnostic(code="RUN_STALE", message="stale"),
        stale_heartbeat_at=observed_iso)

    root = uow_factory._registry.resolve_root(project_id)
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
        diags = uow.runs.get_diagnostics(r1.run_id)
        outbox = uow.publications.list_by_run(r1.run_id)
    assert str(run.status) == RunStatus.RUNNING.value, "renewed heartbeat must defeat the transition"
    assert not any(d.get("code") == "RUN_STALE" for d in diags), "no false RUN_STALE on lost race"
    assert outbox == [], "no outbox record on lost stale race"
    assert FsManifestPublisher(root).read(r1.run_id) is None, "no manifest on lost stale race"


def test_stale_finalization_loses_with_observed_null_heartbeat(committed_plan):
    """A NULL observed heartbeat is distinct from 'stale mode not requested':
    if the worker renews a NULL heartbeat before the compare-and-set, the
    transition loses (PR 373 review P1)."""
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher

    project_id, uow_factory, pv_id = committed_plan
    r1 = _make_submit(uow_factory, project_id)(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = NULL WHERE run_id = ?", (r1.run_id,)
        )
        uow.commit()
    # Worker renews the (NULL) heartbeat after the sweep observed it as NULL.
    with uow_factory.for_project(project_id) as uow:
        uow.runs.heartbeat(r1.run_id)
        uow.commit()

    from cardre.application.runs.finalize_run import FinalizeDiagnostic
    _finalize_for(uow_factory, project_id)(r1.run_id, "interrupted",
        diagnostic=FinalizeDiagnostic(code="RUN_STALE", message="stale"),
        stale_heartbeat_at=None)

    root = uow_factory._registry.resolve_root(project_id)
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
        diags = uow.runs.get_diagnostics(r1.run_id)
        outbox = uow.publications.list_by_run(r1.run_id)
    assert str(run.status) == RunStatus.RUNNING.value, "renewal must defeat NULL-heartbeat sweep"
    assert not any(d.get("code") == "RUN_STALE" for d in diags), "no false RUN_STALE on lost race"
    assert outbox == [], "no outbox record on lost stale race"
    assert FsManifestPublisher(root).read(r1.run_id) is None, "no manifest on lost stale race"


def test_stale_finalization_loses_after_terminalization(committed_plan):
    """If the run terminalizes between stale discovery and stale finalization,
    the lost compare-and-set must not append a false RUN_STALE diagnostic
    (PR 373 review P2)."""
    project_id, uow_factory, pv_id = committed_plan
    r1 = _make_submit(uow_factory, project_id)(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    _set_old_heartbeat(uow_factory, project_id, r1.run_id, age_seconds=400)
    observed = datetime.now(UTC) - timedelta(seconds=400)
    observed_iso = observed.isoformat().replace("+00:00", "Z")
    # The run self-finalizes between discovery and stale finalization.
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.SUCCEEDED)
        uow.commit()

    from cardre.application.runs.finalize_run import FinalizeDiagnostic
    _finalize_for(uow_factory, project_id)(r1.run_id, "interrupted",
        diagnostic=FinalizeDiagnostic(code="RUN_STALE", message="stale"),
        stale_heartbeat_at=observed_iso)

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
        diags = uow.runs.get_diagnostics(r1.run_id)
    assert str(run.status) == RunStatus.SUCCEEDED.value, "terminalized run must stay terminal"
    assert not any(d.get("code") == "RUN_STALE" for d in diags), "no false RUN_STALE on lost race"


def test_transition_success_requires_worker_generation(committed_plan):
    """Success finalization must prove lease ownership (P2-1): calling
    transition_success without a generation is a TypeError."""
    project_id, uow_factory, pv_id = committed_plan
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        gen = uow.runs.begin_worker_generation(r1.run_id)
        uow.commit()

    with uow_factory.for_project(project_id) as uow:
        with pytest.raises(TypeError):
            uow.runs.transition_success(r1.run_id)  # no generation
        # With the correct generation it succeeds.
        assert uow.runs.transition_success(r1.run_id, gen) is True
        uow.commit()


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancel_persists_cancel_requested_and_preserves_running(committed_plan):
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.runs.heartbeat(r1.run_id)
        uow.commit()
    cancel = CancelRun(lambda: uow_factory.for_project(project_id))
    cancel(CancelRunCommand(run_id=r1.run_id))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert run.cancel_requested is True
    assert run.status == RunStatus.RUNNING.value


def test_cancel_rejects_terminal_run(committed_plan):
    """A terminal (failed) run cannot be cancelled — RUN_NOT_RUNNING."""
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.FAILED, expected_from=(RunStatus.SUBMITTED,))
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


def test_cancel_created_run_succeeds(committed_plan):
    """An async-submitted run is created before the worker claims it; a cancel
    arriving in that window must terminalize it as cancelled instead of
    RUN_NOT_RUNNING, and must free the concurrent-run guard (F7)."""
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    # The row is 'submitted' until ExecuteRun claims it.
    with uow_factory.read_only(project_id) as uow:
        assert uow.runs.get(r1.run_id).status == RunStatus.SUBMITTED.value

    cancel = CancelRun(lambda: uow_factory.for_project(project_id))
    cancel(CancelRunCommand(run_id=r1.run_id))

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert str(run.status) == RunStatus.CANCELLED.value, (
        "submitted run must be terminalized as cancelled"
    )

    # The concurrent-run guard must be freed: a normal (non-forced) submission
    # on the same plan version now succeeds.
    r2 = submit(_cmd(pv_id))
    assert r2.run_id != r1.run_id


def test_cancel_visible_on_subsequent_get(committed_plan):
    """cancel_requested persists and is visible on a fresh read."""
    project_id, uow_factory, pv_id = committed_plan
    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand
    submit = _make_submit(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
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


def test_sweep_stale_uses_configured_threshold(committed_plan):
    """The stale sweep must honour the injected stale_heartbeat_seconds, not a
    hard-coded 300s window (F6)."""
    project_id, uow_factory, pv_id = committed_plan
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    from cardre.application.runs.finalize_run import FinalizeRun
    from cardre.application.runs.submit_run import SubmitRun

    root = uow_factory._registry.resolve_root(project_id)
    finalize = FinalizeRun(lambda: uow_factory.for_project(project_id), FsManifestPublisher(root), _FakeClock())
    submit = SubmitRun(
        lambda: uow_factory.for_project(project_id), _NoopDispatcher(), None, finalize,
        governance_enabled=True, project_id=project_id,
        stale_heartbeat_seconds=60,
    )

    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    # 120s-old heartbeat: stale under the configured 60s window, fresh under
    # the hard-coded 300s default.
    _set_old_heartbeat(uow_factory, project_id, r1.run_id, age_seconds=120)

    submit(_cmd(pv_id))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value, (
        "120s-old heartbeat must be swept under a 60s threshold"
    )


def test_sweep_stale_respects_default_when_unconfigured(committed_plan):
    """With no explicit threshold, the default 300s window still governs."""
    project_id, uow_factory, pv_id = committed_plan
    submit = _submit_with_finalize(uow_factory, project_id)
    r1 = submit(_cmd(pv_id))
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(r1.run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    # 120s-old heartbeat: fresh under the default 300s window.
    _set_old_heartbeat(uow_factory, project_id, r1.run_id, age_seconds=120)

    submit(_cmd(pv_id, force=True))
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1.run_id)
    assert run is not None
    assert str(run.status) == RunStatus.RUNNING.value, (
        "120s-old heartbeat must NOT be swept under the default 300s window"
    )


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
    assert run.status in (RunStatus.SUBMITTED.value,)
