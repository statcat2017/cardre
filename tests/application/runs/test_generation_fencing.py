"""P1 — worker-generation fencing must cover heartbeat renewal and
worker-originated terminalization.

These are real-SQLite regression tests: they mutate the stored generation from
N to N+1 while the Run remains running, then prove generation-N cannot
heartbeat, emit terminal diagnostics, transition terminal state, or persist
outputs. No fake repository that throws while the DB stays at generation N.
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

from cardre.application.execution.heartbeat import HeartbeatWatchdog
from cardre.application.runs.execute_run import ExecuteRun, ExecuteRunCommand
from cardre.application.runs.finalize_run import FinalizeRun
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.run import RunStatus, RunStepStatus
from cardre.domain.step import StepSpec


class _FakeClock:
    def now_iso(self) -> str:
        return "2026-01-01T00:00:00Z"


class _NoopManifestPublisher:
    def publish(self, run_id, payload):
        return None


def _stub_publisher(uow_factory, project_id):
    from cardre.application.publications.publisher import PublicationPublisher

    return PublicationPublisher(lambda: uow_factory.for_project(project_id))


def _fake_node(version: str):
    from cardre.nodes.contracts import ArtifactContract, NodeDefinition

    class _FakeNode:
        @classmethod
        def node_definition(cls) -> NodeDefinition:
            return NodeDefinition(
                node_type="cardre.noop", version=version, category="transform",
                description="", input_contract=ArtifactContract(),
                output_contract=ArtifactContract(),
            )

    return _FakeNode


def _provision_running_run(provisioned_project):
    """Create a plan + a running run with a fresh worker generation.

    Returns ``(project_id, uow_factory, root, run_id, generation)``.
    """
    project_id, uow_factory, _registry, root = provisioned_project
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], position=0, canonical_step_id="s1",
            )],
            is_committed=True,
        )
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.RUNNING,
                            expected_from=(RunStatus.SUBMITTED,))
        generation = uow.runs.begin_worker_generation(run_id)
        uow.commit()
    return project_id, uow_factory, root, run_id, generation


def _provision_submitted_run(provisioned_project):
    """Create a plan + a submitted run (ExecuteRun will claim it)."""
    project_id, uow_factory, _registry, root = provisioned_project
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(
            plan_id,
            [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], position=0, canonical_step_id="s1",
            )],
            is_committed=True,
        )
        run_id = uow.runs.create(pv_id)
        uow.commit()
    return project_id, uow_factory, root, run_id


def _bump_generation(uow_factory, project_id, run_id):
    """Simulate a stale recovery bumping the generation while the run stays running."""
    with uow_factory.for_project(project_id) as uow:
        uow.runs.begin_worker_generation(run_id)
        uow.commit()


def _current_generation(uow_factory, project_id, run_id) -> int:
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    assert run is not None
    return run.worker_generation


def _set_old_heartbeat(uow_factory, project_id, run_id) -> str:
    old = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
    with uow_factory.for_project(project_id) as uow:
        uow.runs._conn.execute(
            "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?", (old, run_id),
        )
        uow.commit()
    return old


# ---------------------------------------------------------------------------
# Heartbeat ownership-CAS
# ---------------------------------------------------------------------------


def test_heartbeat_fenced_rejects_obsolete_generation(provisioned_project):
    """A worker of generation N cannot refresh the lease after the stored
    generation was bumped to N+1 while the run stays running."""
    project_id, uow_factory, _root, run_id, gen = _provision_running_run(provisioned_project)
    _bump_generation(uow_factory, project_id, run_id)  # N -> N+1
    old = _set_old_heartbeat(uow_factory, project_id, run_id)

    with uow_factory.for_project(project_id) as uow:
        renewed = uow.runs.heartbeat_fenced(run_id, gen)  # obsolete generation
        uow.commit()
    assert renewed is False, "obsolete generation must not refresh the lease"
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    assert run is not None and run.heartbeat_at == old, "heartbeat must not change"

    # The current generation can still renew.
    with uow_factory.for_project(project_id) as uow:
        renewed = uow.runs.heartbeat_fenced(
            run_id, _current_generation(uow_factory, project_id, run_id),
        )
        uow.commit()
    assert renewed is True, "current generation must renew the lease"


def test_watchdog_uses_fenced_heartbeat_and_stops_on_generation_bump(provisioned_project):
    """The HeartbeatWatchdog carries the worker generation and cannot refresh
    another generation's lease after a recovery bump."""
    project_id, uow_factory, _root, run_id, gen = _provision_running_run(provisioned_project)
    old = _set_old_heartbeat(uow_factory, project_id, run_id)

    watchdog = HeartbeatWatchdog(
        lambda: uow_factory.for_project(project_id), run_id,
        interval_seconds=0.1, worker_generation=gen,
    )
    watchdog.start()
    try:
        # Let the watchdog renew at least once with the correct generation.
        deadline = time.monotonic() + 5.0
        renewed = False
        while time.monotonic() < deadline:
            with uow_factory.read_only(project_id) as uow:
                run = uow.runs.get(run_id)
            assert run is not None and run.heartbeat_at is not None
            if run.heartbeat_at != old:
                renewed = True
                break
            time.sleep(0.05)
        assert renewed, "watchdog should renew with the correct generation"
        renewed_after = run.heartbeat_at

        # Bump the generation while the run stays running.
        _bump_generation(uow_factory, project_id, run_id)

        # The obsolete watchdog must NOT refresh the lease.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with uow_factory.read_only(project_id) as uow:
                run = uow.runs.get(run_id)
            assert run is not None and run.heartbeat_at is not None
            assert run.heartbeat_at == renewed_after, (
                "obsolete watchdog must not refresh another generation's lease"
            )
            time.sleep(0.05)
    finally:
        watchdog.stop()


# ---------------------------------------------------------------------------
# Generation-mismatch LeaseLost stops the old worker
# ---------------------------------------------------------------------------


def test_generation_mismatch_lease_lost_stops_worker_without_diagnostic_or_transition(
    provisioned_project,
):
    """A generation-mismatch LeaseLost makes the old worker stop; it must not
    append RUN_LEASE_LOST or transition the Run."""
    project_id, uow_factory, root, run_id = _provision_submitted_run(provisioned_project)

    finalize = FinalizeRun(
        lambda: uow_factory.for_project(project_id),
        _NoopManifestPublisher(),
        _stub_publisher(uow_factory, project_id),
        _FakeClock(),
    )

    node_returned = threading.Event()
    release_node = threading.Event()

    class _BlockingRunner:
        def run_step(self, *args, **kwargs):
            node_returned.set()
            release_node.wait(timeout=5)
            from cardre.application.execution.step_runner import StepExecutionResult

            return StepExecutionResult(
                step_id="s1", node_type="cardre.noop", status=RunStepStatus.SUCCEEDED,
                fingerprint={}, input_artifact_ids=[], output_artifact_ids=[],
                staged_artifacts=[],
            )

    class _NoopCatalogue:
        def resolve(self, node_type):
            return _fake_node("1")

    persisted = {"count": 0}

    class _CountingStore:
        def finalize(self, staged):
            persisted["count"] += 1

    executor = ExecuteRun(
        lambda: uow_factory.for_project(project_id),
        lambda: uow_factory.read_only(project_id),
        _NoopCatalogue(),
        _BlockingRunner(),
        finalize,
        lambda: _CountingStore(),
        lambda: _stub_publisher(uow_factory, project_id),
        heartbeat_interval_seconds=0.1,
    )

    thread_errors: list[BaseException] = []

    def _run_executor():
        try:
            executor(ExecuteRunCommand(run_id=run_id))
        except BaseException as exc:  # pragma: no cover - diagnostic
            thread_errors.append(exc)

    thread = threading.Thread(target=_run_executor)
    thread.start()
    assert node_returned.wait(timeout=10), f"node never started; thread_errors={thread_errors}"
    # The worker claimed the run and captured its generation.

    # Bump the generation while the run stays running (stale recovery).
    _bump_generation(uow_factory, project_id, run_id)
    release_node.set()
    thread.join(timeout=5)
    assert not thread_errors, f"worker thread raised: {thread_errors}"

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        diags = uow.runs.get_diagnostics(run_id)
        steps = uow.run_steps.get_for_run(run_id)
        artifacts = uow.artifacts.output_artifact_ids_for_run(run_id)
        outbox = uow.publications.list_by_run(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.RUNNING.value, (
        "generation mismatch must not transition the run"
    )
    assert not any(d.get("code") == "RUN_LEASE_LOST" for d in diags), (
        "generation mismatch must not append RUN_LEASE_LOST"
    )
    assert steps == [], "obsolete worker must not persist run steps"
    assert artifacts == [], "obsolete worker must not persist artifacts"
    assert outbox == [], "obsolete worker must not persist outbox records"
    assert persisted["count"] == 0, "obsolete worker must not finalize artifacts"


def test_failed_finalization_is_generation_fenced(provisioned_project):
    """A generation-N worker whose node raises after the stored generation was
    bumped to N+1 (while the run stays running) must not terminalize the run:
    ExecuteRun returns cleanly, the run stays running, and no
    RUN_EXECUTION_FAILED diagnostic or manifest is written."""
    project_id, uow_factory, root, run_id = _provision_submitted_run(provisioned_project)

    finalize = FinalizeRun(
        lambda: uow_factory.for_project(project_id),
        _NoopManifestPublisher(),
        _stub_publisher(uow_factory, project_id),
        _FakeClock(),
    )

    node_started = threading.Event()
    release_node = threading.Event()

    class _RaisingRunner:
        def run_step(self, *args, **kwargs):
            node_started.set()
            release_node.wait(timeout=5)
            raise RuntimeError("node crashed")

    class _NoopCatalogue:
        def resolve(self, node_type):
            return _fake_node("1")

    class _NoopStore:
        def finalize(self, staged):
            return None

        def object_path(self, physical_hash):
            return "objects/x"

    executor = ExecuteRun(
        lambda: uow_factory.for_project(project_id),
        lambda: uow_factory.read_only(project_id),
        _NoopCatalogue(),
        _RaisingRunner(),
        finalize,
        lambda: _NoopStore(),
        lambda: _stub_publisher(uow_factory, project_id),
        heartbeat_interval_seconds=0.1,
    )

    thread_errors: list[BaseException] = []

    def _run_executor():
        try:
            executor(ExecuteRunCommand(run_id=run_id))
        except BaseException as exc:  # pragma: no cover - diagnostic
            thread_errors.append(exc)

    thread = threading.Thread(target=_run_executor)
    thread.start()
    assert node_started.wait(timeout=10), f"node never started; thread_errors={thread_errors}"
    # A stale recovery bumps the generation while the run stays running.
    _bump_generation(uow_factory, project_id, run_id)
    release_node.set()
    thread.join(timeout=5)
    assert not thread_errors, f"worker thread raised: {thread_errors}"

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        diags = uow.runs.get_diagnostics(run_id)
        outbox = uow.publications.list_by_run(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.RUNNING.value, (
        "generation mismatch must not transition the run to failed"
    )
    assert not any(d.get("code") == "RUN_EXECUTION_FAILED" for d in diags), (
        "obsolete worker must not append RUN_EXECUTION_FAILED"
    )
    assert outbox == [], "obsolete worker must not enqueue a manifest"


# ---------------------------------------------------------------------------
# Generation-fenced interrupted transition
# ---------------------------------------------------------------------------


def test_transition_interrupted_fenced_requires_matching_generation(provisioned_project):
    """A generation-fenced interrupted transition fires only for the current
    generation; an obsolete worker cannot terminalize a run it no longer owns."""
    project_id, uow_factory, _root, run_id, gen = _provision_running_run(provisioned_project)
    _bump_generation(uow_factory, project_id, run_id)

    # Obsolete generation cannot transition.
    with uow_factory.for_project(project_id) as uow:
        transitioned = uow.runs.transition_interrupted_fenced(run_id, gen)
        uow.commit()
    assert transitioned is False, "obsolete generation must not transition"
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    assert run is not None and str(run.status) == RunStatus.RUNNING.value

    # Current generation can transition.
    with uow_factory.for_project(project_id) as uow:
        transitioned = uow.runs.transition_interrupted_fenced(
            run_id, _current_generation(uow_factory, project_id, run_id),
        )
        uow.commit()
    assert transitioned is True, "current generation must transition"
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    assert run is not None and str(run.status) == RunStatus.INTERRUPTED.value


def test_persistent_heartbeat_failure_terminalization_is_generation_fenced(provisioned_project):
    """Persistent background heartbeat failure terminalization carries the
    generation and uses a generation-fenced interrupted transition: an
    obsolete worker cannot terminalize a run it no longer owns."""
    project_id, uow_factory, _root, run_id, gen = _provision_running_run(provisioned_project)
    # A recovery bumps the generation while the run stays running.
    _bump_generation(uow_factory, project_id, run_id)
    _set_old_heartbeat(uow_factory, project_id, run_id)

    finalize = FinalizeRun(
        lambda: uow_factory.for_project(project_id),
        _NoopManifestPublisher(),
        _stub_publisher(uow_factory, project_id),
        _FakeClock(),
    )

    watchdog = HeartbeatWatchdog(
        lambda: uow_factory.for_project(project_id), run_id,
        interval_seconds=0.05, worker_generation=gen,
        max_failed_heartbeats=2, finalize_run=finalize,
    )
    watchdog.start()
    watchdog.stop()

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        diags = uow.runs.get_diagnostics(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.RUNNING.value, (
        "obsolete worker must not terminalize a run it no longer owns"
    )
    assert not any(d.get("code") == "RUN_HEARTBEAT_FAILED" for d in diags), (
        "obsolete worker must not append RUN_HEARTBEAT_FAILED"
    )


def test_persistent_heartbeat_failure_current_generation_terminalizes(provisioned_project):
    """A current-generation worker that persistently fails to renew its lease
    terminalizes the run it owns via a generation-fenced interrupted
    transition, carrying the RUN_HEARTBEAT_FAILED diagnostic."""
    project_id, uow_factory, _root, run_id, gen = _provision_running_run(provisioned_project)

    finalize = FinalizeRun(
        lambda: uow_factory.for_project(project_id),
        _NoopManifestPublisher(),
        _stub_publisher(uow_factory, project_id),
        _FakeClock(),
    )

    class _FailingHeartbeatUoW:
        """A UoW whose heartbeat always fails (persistent DB failure), while
        FinalizeRun's own factory still works."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        @property
        def runs(self):
            class _Runs:
                def heartbeat_fenced(self, *a, **k):
                    raise RuntimeError("persistent heartbeat failure")

            return _Runs()

    def failing_factory():
        return _FailingHeartbeatUoW(uow_factory.for_project(project_id))

    watchdog = HeartbeatWatchdog(
        failing_factory, run_id,
        interval_seconds=0.05, worker_generation=gen,
        max_failed_heartbeats=2, finalize_run=finalize,
    )
    watchdog.start()
    try:
        # Wait for the watchdog to accumulate failures and terminalize.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with uow_factory.read_only(project_id) as uow:
                run = uow.runs.get(run_id)
            assert run is not None
            if str(run.status) == RunStatus.INTERRUPTED.value:
                break
            time.sleep(0.05)
    finally:
        watchdog.stop()

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        diags = uow.runs.get_diagnostics(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value, (
        "current-generation worker must terminalize on persistent heartbeat failure"
    )
    assert any(d.get("code") == "RUN_HEARTBEAT_FAILED" for d in diags), (
        "terminalization must carry the RUN_HEARTBEAT_FAILED diagnostic"
    )
