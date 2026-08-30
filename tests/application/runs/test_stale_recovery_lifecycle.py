"""Slice 3 lifecycle tests: independent stale-Run recovery trigger.

An abandoned running Run (old heartbeat, no later Run submission) must be
interrupted by an explicit, periodically invoked recovery trigger rather than
only being swept on the *next* submission. Recovery is driven by an injected
``ClockPort`` — no direct wall-clock reads in the recovery path — and
finalization reuses ``FinalizeRun``'s stale compare-and-set so a renewed lease
is never interrupted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from cardre.application.ports.clock import ClockPort
from cardre.application.runs.recover_stale_runs import RecoverStaleRuns, StaleRunRecoveryWatchdog
from cardre.application.runs.submit_run import SubmitRun, SubmitRunCommand
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.run import RunStatus
from cardre.domain.step import StepSpec


class _AdvanceableClock(ClockPort):
    """A ClockPort whose time can be advanced for deterministic stale checks."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now_iso(self) -> str:
        return self._now.isoformat().replace("+00:00", "Z")

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


class _NoopDispatcher:
    def dispatch(self, request):  # noqa: D401
        pass


def _committed_pv(uow_factory, project_id):
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Test Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="step-noop", node_type="cardre.noop",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], position=0, canonical_step_id="noop",
            )],
            description="base", is_committed=True,
        )
        uow.commit()
    return pv_id


def _submit_running(uow_factory, project_id, pv_id):
    submit = SubmitRun(
        lambda: uow_factory.for_project(project_id), _NoopDispatcher(), None, None,
        project_id=project_id,
    )
    result = submit(SubmitRunCommand(plan_version_id=pv_id))
    run_id = result.run_id
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(run_id, RunStatus.RUNNING, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()
    return run_id


def _set_heartbeat(uow_factory, project_id, run_id, iso):
    """Set the persisted heartbeat directly (the repo has no write-arbitrary API)."""
    with uow_factory.for_project(project_id) as uow:
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?", (iso, run_id),
        )
        uow.commit()


def _finalize_for(uow_factory, project_id, clock, root):
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    from cardre.application.publications.publisher import PublicationPublisher
    from cardre.application.runs.finalize_run import FinalizeRun

    uow_lambda = lambda: uow_factory.for_project(project_id)  # noqa: E731
    return FinalizeRun(
        uow_lambda,
        FsManifestPublisher(root),
        PublicationPublisher(uow_lambda),
        clock,
    )


def _recover(uow_factory, registry, project_id, clock, root):
    return RecoverStaleRuns(
        uow_factory,
        registry,
        lambda pid: _finalize_for(uow_factory, project_id, clock, root),
        clock=clock,
        stale_heartbeat_seconds=300,
    )


def _assert_no_manifest(root, run_id):
    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    assert FsManifestPublisher(root).read(run_id) is None


# ---------------------------------------------------------------------------
# RED: independent recovery trigger interrupts an abandoned run
# ---------------------------------------------------------------------------


def test_recovery_interrupts_abandoned_run_without_submission(provisioned_project):
    """A running run with an old heartbeat and NO later Run submission is
    interrupted by the recovery trigger, with its stale diagnostic, canonical
    manifest, and outbox record all produced."""
    project_id, uow_factory, registry, root = provisioned_project
    pv_id = _committed_pv(uow_factory, project_id)
    r1 = _submit_running(uow_factory, project_id, pv_id)

    clock = _AdvanceableClock()
    _set_heartbeat(uow_factory, project_id, r1, clock.now_iso())
    clock.advance(700)  # well past the 300s stale window

    # Invoke the recovery trigger directly — no new Run is submitted.
    _recover(uow_factory, registry, project_id, clock, root)()

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1)
        diags = uow.runs.get_diagnostics(r1)
        outbox = uow.publications.list_by_run(r1)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value
    assert any(d.get("code") == "RUN_STALE" for d in diags), (
        "recovered run must carry the RUN_STALE diagnostic"
    )
    manifest_rows = [r for r in outbox if r["kind"] == "manifest"]
    assert manifest_rows and manifest_rows[0]["state"] == "published", (
        "recovered run must publish a manifest outbox record"
    )

    from cardre.adapters.filesystem.manifest_publisher import FsManifestPublisher
    manifest = FsManifestPublisher(root).read(r1)
    assert manifest is not None and manifest["status"] == "interrupted"


def test_recovery_leaves_recent_heartbeat_untouched(provisioned_project):
    """A running run with a recent heartbeat is not interrupted by recovery."""
    project_id, uow_factory, registry, root = provisioned_project
    pv_id = _committed_pv(uow_factory, project_id)
    r1 = _submit_running(uow_factory, project_id, pv_id)

    clock = _AdvanceableClock()
    _set_heartbeat(uow_factory, project_id, r1, clock.now_iso())
    clock.advance(100)  # inside the 300s stale window

    _recover(uow_factory, registry, project_id, clock, root)()

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1)
        diags = uow.runs.get_diagnostics(r1)
    assert run is not None
    assert str(run.status) == RunStatus.RUNNING.value, "recent heartbeat must stay untouched"
    assert not any(d.get("code") == "RUN_STALE" for d in diags)


def test_recovery_cas_preserved_when_worker_renews_during_pass(provisioned_project):
    """If a worker renews the heartbeat after the recovery trigger observed the
    stale value but before finalization, the compare-and-set loses: the run
    stays running with no diagnostic, manifest, or outbox record."""
    project_id, uow_factory, registry, root = provisioned_project
    pv_id = _committed_pv(uow_factory, project_id)
    r1 = _submit_running(uow_factory, project_id, pv_id)

    clock = _AdvanceableClock()
    _set_heartbeat(uow_factory, project_id, r1, clock.now_iso())
    clock.advance(700)

    real_finalize = _finalize_for(uow_factory, project_id, clock, root)

    def racing_finalize(run_id: str, status: str, **kw: Any) -> None:
        # The worker renews the lease between the module's read and finalize.
        _set_heartbeat(uow_factory, project_id, run_id, clock.now_iso())
        real_finalize(run_id, status, **kw)

    recover = RecoverStaleRuns(
        uow_factory,
        registry,
        lambda pid: racing_finalize,
        clock=clock,
        stale_heartbeat_seconds=300,
    )
    outcome = recover()

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(r1)
        diags = uow.runs.get_diagnostics(r1)
        outbox = uow.publications.list_by_run(r1)
    assert str(run.status) == RunStatus.RUNNING.value, "renewed lease must defeat recovery"
    assert not any(d.get("code") == "RUN_STALE" for d in diags), "no false RUN_STALE on lost race"
    assert outbox == [], "no outbox record on lost stale race"
    _assert_no_manifest(root, r1)
    assert outcome.results[0].state == "fresh", "recovery must report the run as untouched"


# ---------------------------------------------------------------------------
# RED: lifecycle-owned recovery thread starts and stops cleanly
# ---------------------------------------------------------------------------


def test_recovery_watchdog_starts_and_stops_cleanly():
    """The recovery watchdog runs the recovery Module periodically from a
    lifecycle-owned thread and stops/joins it on request."""
    import time

    calls: list[bool] = []
    wd = StaleRunRecoveryWatchdog(lambda: calls.append(True), interval_seconds=0.01)
    wd.start()
    assert wd._thread is not None and wd._thread.is_alive()

    deadline = time.time() + 1.0
    while time.time() < deadline and not calls:
        time.sleep(0.01)
    assert calls, "watchdog must invoke the recovery module periodically"

    wd.stop()
    assert wd._thread is None, "watchdog thread must be cleared on stop"
    count_after_stop = len(calls)
    time.sleep(0.05)
    assert len(calls) == count_after_stop, "watchdog must not invoke after stop"
