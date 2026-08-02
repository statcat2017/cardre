"""Durable run dispatch — a crash between commit and in-memory dispatch must
not strand a run or wedge its plan version.

A pending dispatch row is committed atomically with run creation. If the
process dies before the worker claims the run, startup reconciliation
redispatches it; a run terminalized meanwhile has its stale row dropped.
"""
from __future__ import annotations

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.ports.run_dispatcher import RunRequest
from cardre.application.runs.reconcile_dispatches import ReconcileDispatches
from cardre.application.runs.submit_run import SubmitRun, SubmitRunCommand
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.run import RunStatus
from cardre.domain.step import StepSpec


class _RecordingDispatcher:
    def __init__(self):
        self.dispatched: list[RunRequest] = []

    def dispatch(self, request: RunRequest) -> None:
        self.dispatched.append(request)

    def get_status(self, run_id: str) -> str:
        return "completed"

    def shutdown(self) -> None:
        pass


def _provision(tmp_path):
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)
    with uow_factory.for_root(root) as uow:
        project_id = uow.projects.create("Project")
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )],
            is_committed=True,
        )
        uow.commit()
    registry.register(project_id, root)
    return project_id, uow_factory, pv_id, registry, root


def test_submit_records_durable_dispatch_before_inmemory_dispatch(tmp_path):
    """SubmitRun must commit the dispatch intent with run creation, even when
    the in-memory dispatch is a no-op (simulating a crash before it runs)."""
    project_id, uow_factory, pv_id, registry, _root = _provision(tmp_path)
    dispatcher = _RecordingDispatcher()

    submit = SubmitRun(
        lambda: uow_factory.for_project(project_id),
        dispatcher,
        None,
        None,
        governance_enabled=True,
        project_id=project_id,
    )
    result = submit(SubmitRunCommand(plan_version_id=pv_id, run_scope="full_plan"))

    with uow_factory.read_only(project_id) as uow:
        pending = uow.dispatches.list_pending()
    assert result.run_id in pending, "dispatch intent must be durable"

    # The worker would claim the row when it executes; simulate that here.
    with uow_factory.for_project(project_id) as uow:
        claimed = uow.dispatches.claim(result.run_id)
        uow.commit()
    assert claimed is True


def test_reconcile_dispatches_after_crash_redispatches_pending_runs(tmp_path):
    """Startup reconciliation must redispatch a run committed before a crash
    (pending dispatch row present, run still created)."""
    project_id, uow_factory, pv_id, registry, _root = _provision(tmp_path)
    dispatcher = _RecordingDispatcher()

    submit = SubmitRun(
        lambda: uow_factory.for_project(project_id),
        _RecordingDispatcher(),  # in-memory dispatch "never ran" (crashed)
        None,
        None,
        governance_enabled=True,
        project_id=project_id,
    )
    result = submit(SubmitRunCommand(plan_version_id=pv_id, run_scope="full_plan"))

    reconcile = ReconcileDispatches(uow_factory, registry, dispatcher)
    outcome = reconcile()

    assert outcome.dispatched >= 1, "pending dispatch must be redispatched on startup"
    assert any(r.run_id == result.run_id for r in outcome.results), (
        f"run {result.run_id} not redispatched: {outcome.results}"
    )


def test_reconcile_drops_dispatch_row_for_terminalized_run(tmp_path):
    """A pending dispatch for a run terminalized meanwhile (e.g. cancelled
    before claim) must not be redispatched into a live worker."""
    project_id, uow_factory, pv_id, registry, _root = _provision(tmp_path)

    # Simulate: run committed + dispatch row, then CancelRun terminalizes it.
    submit = SubmitRun(
        lambda: uow_factory.for_project(project_id),
        _RecordingDispatcher(),
        None,
        None,
        governance_enabled=True,
        project_id=project_id,
    )
    result = submit(SubmitRunCommand(plan_version_id=pv_id, run_scope="full_plan"))

    from cardre.application.runs.cancel_run import CancelRun, CancelRunCommand

    CancelRun(lambda: uow_factory.for_project(project_id))(
        CancelRunCommand(run_id=result.run_id),
    )

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(result.run_id)
        pending = uow.dispatches.list_pending()
    assert run is not None and run.status == RunStatus.CANCELLED.value
    assert result.run_id not in pending, "cancel must clear the dispatch row"

    dispatcher = _RecordingDispatcher()
    ReconcileDispatches(uow_factory, registry, dispatcher)()
    assert not any(r.run_id == result.run_id for r in dispatcher.dispatched), (
        "terminal run must not be redispatched"
    )


def test_claim_run_removes_dispatch_row_atomically(tmp_path):
    """ExecuteRun._claim_run must remove the durable dispatch row in the same
    transaction that transitions the run to running."""
    from cardre.adapters.filesystem.artifact_store import FsArtifactStore
    from cardre.application.runs.execute_run import ExecuteRun, ExecuteRunCommand
    from cardre.application.runs.finalize_run import FinalizeRun

    project_id, uow_factory, pv_id, _registry, root = _provision(tmp_path)
    with uow_factory.for_project(project_id) as uow:
        run_id = uow.runs.create(pv_id)
        uow.dispatches.enqueue(run_id)
        uow.commit()

    finalize = FinalizeRun(
        lambda: uow_factory.for_project(project_id),
        type("Pub", (), {"publish": lambda self, run_id, payload: None})(),
    )
    executor = ExecuteRun(
        lambda: uow_factory.for_project(project_id),
        lambda: uow_factory.read_only(project_id),
        None,
        None,
        finalize,
        lambda: FsArtifactStore(root / "objects"),
        heartbeat_interval_seconds=0.1,
    )

    # Claim only (the run has no steps, so claim succeeds then loop is empty).
    worker_generation = executor._claim_run(ExecuteRunCommand(run_id=run_id))
    assert worker_generation is not None

    with uow_factory.read_only(project_id) as uow:
        pending = uow.dispatches.list_pending()
        run = uow.runs.get(run_id)
    assert run is not None and run.status == RunStatus.RUNNING.value
    assert run_id not in pending, "claim must remove the dispatch row"


def _seed_pending_run(uow_factory, project_id, pv_id):
    with uow_factory.for_project(project_id) as uow:
        run_id = uow.runs.create(pv_id)
        uow.dispatches.enqueue(run_id)
        uow.commit()
    return run_id


def _seed_pending_runs_two_plans(uow_factory, project_id):
    """Create two committed plan versions and one pending run per plan, so the
    concurrent-run guard does not block the second."""
    with uow_factory.for_project(project_id) as uow:
        plan_a = uow.plans.create_plan(project_id, "Plan-A")
        pv_a = uow.plans.create_version(
            plan_a, [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )],
            is_committed=True,
        )
        plan_b = uow.plans.create_plan(project_id, "Plan-B")
        pv_b = uow.plans.create_version(
            plan_b, [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0, canonical_step_id="s1",
            )],
            is_committed=True,
        )
        uow.commit()
    run_1 = _seed_pending_run(uow_factory, project_id, pv_a)
    run_2 = _seed_pending_run(uow_factory, project_id, pv_b)
    return run_1, run_2


def test_reconcile_with_full_worker_pool_does_not_strand_pending_runs(tmp_path):
    """Finding 1: startup reconciliation with max_workers=1 and two pending runs
    must not permanently strand the second run. The dispatcher queues it and the
    worker picks it up once capacity frees."""
    from cardre.adapters.dispatch.thread_dispatcher import ThreadRunDispatcher

    project_id, uow_factory, pv_id, registry, _root = _provision(tmp_path)

    # Two committed runs (different plans) whose in-memory dispatch "crashed".
    run_1, run_2 = _seed_pending_runs_two_plans(uow_factory, project_id)

    import threading
    import time

    executed: list[str] = []
    release = threading.Event()
    started: list[threading.Event] = []

    def blocking_execute(request: RunRequest) -> None:
        ev = threading.Event()
        started.append(ev)
        ev.set()
        executed.append(request.run_id)
        release.wait(timeout=5)

    dispatcher = ThreadRunDispatcher(blocking_execute, max_workers=1)
    try:
        ReconcileDispatches(uow_factory, registry, dispatcher)()
        # First run occupies the sole worker; second is queued, not stranded.
        assert dispatcher.active_count == 1
        assert dispatcher.queued_count == 1, "second run must be queued"
        release.set()
        deadline = time.monotonic() + 5
        while len(executed) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sorted(executed) == sorted([run_1, run_2]), (
            f"both runs must execute: {executed}"
        )
    finally:
        release.set()
        dispatcher.shutdown()


def test_finalize_run_clears_dispatch_row_for_preclaim_terminal_run(tmp_path):
    """Finding 2: FinalizeRun must clear a created run's dispatch row when it
    terminalizes before claim (dispatch-failure / validation-failure path), so
    reconciliation never redispatches a terminal run."""
    from cardre.application.runs.finalize_run import FinalizeRun

    project_id, uow_factory, pv_id, _registry, _root = _provision(tmp_path)
    run_id = _seed_pending_run(uow_factory, project_id, pv_id)

    finalize = FinalizeRun(
        lambda: uow_factory.for_project(project_id),
        type("Pub", (), {"publish": lambda self, run_id, payload: None})(),
    )
    # Simulate the async dispatch-failure path: SubmitRun finalizes the created
    # run as failed with RUN_DISPATCH_FAILED.
    from cardre.application.runs.finalize_run import FinalizeDiagnostic

    finalize(run_id, "failed", diagnostic=FinalizeDiagnostic(
        code="RUN_DISPATCH_FAILED", message="Failed to dispatch run",
    ))

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        pending = uow.dispatches.list_pending()
    assert run is not None and run.status == RunStatus.FAILED.value
    assert run_id not in pending, "finalize must clear the pre-claim dispatch row"


def test_reconcile_clears_terminal_run_row_defensively(tmp_path):
    """Finding 2 (defense in depth): even if a stale dispatch row survives a
    terminal transition, reconciliation detects the terminal run and drops the
    row instead of redispatching it."""
    project_id, uow_factory, pv_id, registry, _root = _provision(tmp_path)
    run_id = _seed_pending_run(uow_factory, project_id, pv_id)

    # Manually terminalize WITHOUT clearing the dispatch row (simulating a path
    # that predates the FinalizeRun fix).
    with uow_factory.for_project(project_id) as uow:
        uow.runs.transition(run_id, RunStatus.FAILED, expected_from=(RunStatus.SUBMITTED,))
        uow.commit()

    dispatcher = _RecordingDispatcher()
    outcome = ReconcileDispatches(uow_factory, registry, dispatcher)()
    assert not any(r.run_id == run_id for r in dispatcher.dispatched), (
        "terminal run must not be redispatched"
    )
    with uow_factory.read_only(project_id) as uow:
        pending = uow.dispatches.list_pending()
    assert run_id not in pending, "stale dispatch row must be removed"
    assert any(r.run_id == run_id and r.state == "skipped" for r in outcome.results)
