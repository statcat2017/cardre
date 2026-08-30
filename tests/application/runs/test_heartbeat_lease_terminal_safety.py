"""Slice 4 — heartbeat write failure and non-cancellation lease loss are
terminally safe (crash-hypothesis rows #43 and #47).

Two lifecycle defects from the crash-hypothesis evaluation:

- **#43** `ExecuteRun._heartbeat` swallowed every heartbeat write failure, so a
  persistently failing persistent heartbeat left the Run silently ``running``
  and it could only be caught later by the stale sweep.
- **#47** a non-cancellation ``LeaseLost`` (e.g. lease ownership lost) returned
  from execution without terminalizing the Run, leaving it ``running`` forever.

The selected lifecycle policy (fixed here before GREEN, per the plan):

- A persistent heartbeat write failure is observable: after a bounded retry
  policy the Run is terminalized deterministically as ``interrupted`` with the
  ``RUN_HEARTBEAT_FAILED`` diagnostic.
- A non-cancellation ``LeaseLost`` while the Run is ``running`` terminalizes it
  race-safely as ``interrupted`` with the ``RUN_LEASE_LOST`` diagnostic. The
  conditional transition must not overwrite a Run another owner already
  terminalized, and must not append a false diagnostic in that case.

``interrupted`` was chosen over ``failed`` because these are lifecycle/lease
conditions, not execution failures: the vocabulary already reserves
``interrupted`` for a Run stopped by an external lifecycle authority (stale
recovery uses ``interrupted`` + ``RUN_STALE``). ``RUN_LEASE_LOST`` already
exists as an internal diagnostic code; ``RUN_HEARTBEAT_FAILED`` is added as an
internal-only code (never surfaced over HTTP).
"""

from __future__ import annotations

import time

from cardre.application.runs.execute_run import ExecuteRun, ExecuteRunCommand
from cardre.application.runs.finalize_run import FinalizeDiagnostic, FinalizeRun
from cardre.domain.artifacts import json_logical_hash
from cardre.domain.errors import LeaseLost
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
                node_type="cardre.noop",
                version=version,
                category="transform",
                description="",
                input_contract=ArtifactContract(),
                output_contract=ArtifactContract(),
            )

    return _FakeNode


class _NoopCatalogue:
    def resolve(self, node_type):
        return _fake_node("1")


class _SucceededRunner:
    """Returns a successful step with no staged artifacts or outputs."""

    def run_step(self, *args, **kwargs):
        from cardre.application.execution.step_runner import StepExecutionResult

        return StepExecutionResult(
            step_id="s1", node_type="cardre.noop", status=RunStepStatus.SUCCEEDED,
            fingerprint={}, input_artifact_ids=[], output_artifact_ids=[],
            staged_artifacts=[], parent_run_steps=[],
            input_artifact_ids_by_parent={},
        )


def _committed_noop_pv(uow_factory, project_id):
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
        uow.commit()
    return pv_id


def _run_id(uow_factory, project_id, pv_id):
    with uow_factory.for_project(project_id) as uow:
        run_id = uow.runs.create(pv_id)  # created; ExecuteRun claims RUNNING
        uow.commit()
    return run_id


def _finalize_for(uow_factory, project_id, root):
    return FinalizeRun(
        lambda: uow_factory.for_project(project_id),
        _NoopManifestPublisher(),
        _stub_publisher(uow_factory, project_id),
        _FakeClock(),
    )


# --- UoW proxies that fail only at the injected seam -------------------------


class _FailingHeartbeatRuns:
    """Delegates to a real RunRepo except the heartbeat write, which raises."""

    def __init__(self, inner, attempts: list[int]) -> None:
        self._inner = inner
        self._attempts = attempts

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def heartbeat(self, run_id: str) -> None:
        self._attempts.append(1)
        raise RuntimeError("injected persistent heartbeat write failure")


class _FailingHeartbeatUoW:
    def __init__(self, inner, attempts: list[int]) -> None:
        self._inner = inner
        self._attempts = attempts

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def runs(self):
        return _FailingHeartbeatRuns(self._inner.runs, self._attempts)

    def commit(self):
        self._inner.commit()

    def rollback(self):
        self._inner.rollback()

    def close(self):
        self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # Preserve normal with-block auto-commit semantics of the inner UoW.
        if exc[0] is None:
            self._inner.commit()
        self._inner.close()


class _FailingLeaseRuns:
    """Delegates to a real RunRepo except the lease fence, which raises a
    non-cancellation ``LeaseLost``."""

    def __init__(self, inner, run_id: str) -> None:
        self._inner = inner
        self._run_id = run_id

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def assert_running_lease(self, run_id: str, generation: int) -> None:
        # Non-cancellation: no "cancellation" in the message; the run row is
        # left ``running`` in the DB so the worker must terminalize it.
        raise LeaseLost(run_id, "lease ownership lost (worker generation mismatch)")


class _FailingLeaseUoW:
    def __init__(self, inner, run_id: str) -> None:
        self._inner = inner
        self._run_id = run_id

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def runs(self):
        return _FailingLeaseRuns(self._inner.runs, self._run_id)

    def commit(self):
        self._inner.commit()

    def rollback(self):
        self._inner.rollback()

    def close(self):
        self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # Preserve normal with-block auto-commit semantics of the inner UoW.
        if exc[0] is None:
            self._inner.commit()
        self._inner.close()


# ---------------------------------------------------------------------------
# RED #43 — persistent heartbeat write failure is observable and terminal
# ---------------------------------------------------------------------------


def test_persistent_heartbeat_failure_terminalizes_run(provisioned_project):
    """A persistent heartbeat write failure must not leave the Run silently
    running: after a bounded retry policy it ends ``interrupted`` with the
    ``RUN_HEARTBEAT_FAILED`` diagnostic."""
    project_id, uow_factory, _registry, root = provisioned_project
    pv_id = _committed_noop_pv(uow_factory, project_id)
    run_id = _run_id(uow_factory, project_id, pv_id)

    finalize = _finalize_for(uow_factory, project_id, root)

    attempts: list[int] = []

    def failing_write():
        return _FailingHeartbeatUoW(
            uow_factory.for_project(project_id), attempts,
        )

    executor = ExecuteRun(
        failing_write,
        lambda: uow_factory.read_only(project_id),
        _NoopCatalogue(),
        _SucceededRunner(),
        finalize,
        lambda: _NoopStore(),
        lambda: _stub_publisher(uow_factory, project_id),
        heartbeat_interval_seconds=0.1,
        heartbeat_max_retries=3,
    )
    executor(ExecuteRunCommand(run_id=run_id))

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        diags = uow.runs.get_diagnostics(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value, (
        "persistent heartbeat failure must terminalize the run"
    )
    assert any(d.get("code") == "RUN_HEARTBEAT_FAILED" for d in diags), (
        "interrupted run must carry the RUN_HEARTBEAT_FAILED diagnostic"
    )
    assert len(attempts) == 3, (
        "heartbeat retry policy must be bounded (attempted exactly the retry "
        f"count, got {len(attempts)})"
    )


class _FailingAfterFirstHeartbeatRuns:
    """Delegates to a real RunRepo except the heartbeat write, which succeeds
    once (the main loop's pre-step renewal) and then fails persistently (the
    background watchdog's renewals)."""

    def __init__(self, inner, attempts: list[int]) -> None:
        self._inner = inner
        self._attempts = attempts

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def heartbeat(self, run_id: str) -> None:
        self._attempts.append(1)
        if len(self._attempts) > 1:
            raise RuntimeError("injected persistent background heartbeat write failure")


class _FailingAfterFirstHeartbeatUoW:
    def __init__(self, inner, attempts: list[int]) -> None:
        self._inner = inner
        self._attempts = attempts

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def runs(self):
        return _FailingAfterFirstHeartbeatRuns(self._inner.runs, self._attempts)

    def commit(self):
        self._inner.commit()

    def rollback(self):
        self._inner.rollback()

    def close(self):
        self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self._inner.commit()
        self._inner.close()


class _FailingOnceHeartbeatRuns:
    """Delegates to a real RunRepo except the heartbeat write, which fails on
    exactly one call (a transient failure) and succeeds on every other. The
    call counter is shared across UoW instances so the single failure is
    injected once across the whole watchdog run."""

    def __init__(self, inner, state: dict) -> None:
        self._inner = inner
        self._state = state

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def heartbeat(self, run_id: str) -> None:
        self._state["calls"] += 1
        if self._state["calls"] == self._state["fail_on"]:
            raise RuntimeError("injected transient heartbeat write failure")


class _FailingOnceHeartbeatUoW:
    def __init__(self, inner, state: dict) -> None:
        self._inner = inner
        self._state = state

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def runs(self):
        return _FailingOnceHeartbeatRuns(self._inner.runs, self._state)

    def commit(self):
        self._inner.commit()

    def rollback(self):
        self._inner.rollback()

    def close(self):
        self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self._inner.commit()
        self._inner.close()


# ---------------------------------------------------------------------------
# RED #43 — persistent background heartbeat failure is observable and terminal
# ---------------------------------------------------------------------------


def test_persistent_background_heartbeat_failure_terminalizes_run(provisioned_project):
    """A persistently failing *background* heartbeat (the watchdog thread) must
    not be swallowed forever: after the bounded consecutive-failure threshold
    the Run is terminalized deterministically as ``interrupted`` with the
    ``RUN_HEARTBEAT_FAILED`` diagnostic, even while the main loop is blocked in
    a long-running node."""
    import threading

    project_id, uow_factory, _registry, root = provisioned_project
    pv_id = _committed_noop_pv(uow_factory, project_id)
    run_id = _run_id(uow_factory, project_id, pv_id)

    finalize = _finalize_for(uow_factory, project_id, root)

    node_returned = threading.Event()
    release_node = threading.Event()

    class _BlockingRunner:
        def run_step(self, *args, **kwargs):
            from cardre.application.execution.step_runner import StepExecutionResult

            node_returned.set()
            release_node.wait(timeout=5)
            return StepExecutionResult(
                step_id="s1", node_type="cardre.noop", status=RunStepStatus.SUCCEEDED,
                fingerprint={}, input_artifact_ids=[], output_artifact_ids=[],
                staged_artifacts=[], parent_run_steps=[],
                input_artifact_ids_by_parent={},
            )

    attempts: list[int] = []

    def failing_after_first():
        return _FailingAfterFirstHeartbeatUoW(
            uow_factory.for_project(project_id), attempts,
        )

    executor = ExecuteRun(
        failing_after_first,
        lambda: uow_factory.read_only(project_id),
        _NoopCatalogue(),
        _BlockingRunner(),
        finalize,
        lambda: _NoopStore(),
        lambda: _stub_publisher(uow_factory, project_id),
        heartbeat_interval_seconds=0.05,
        heartbeat_max_retries=3,
    )
    thread = threading.Thread(target=lambda: executor(ExecuteRunCommand(run_id=run_id)))
    thread.start()
    assert node_returned.wait(timeout=5), "node never started"

    # The main loop's pre-step heartbeat succeeded (attempt 1); the watchdog's
    # background renewals (attempts 2+) fail persistently. Wait for the
    # watchdog to cross the consecutive-failure threshold and terminalize.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with uow_factory.read_only(project_id) as uow:
            run = uow.runs.get(run_id)
        if run is not None and str(run.status) == RunStatus.INTERRUPTED.value:
            break
        time.sleep(0.05)
    release_node.set()
    thread.join(timeout=5)

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        diags = uow.runs.get_diagnostics(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value, (
        "persistent background heartbeat failure must terminalize the run"
    )
    assert any(d.get("code") == "RUN_HEARTBEAT_FAILED" for d in diags), (
        "interrupted run must carry the RUN_HEARTBEAT_FAILED diagnostic"
    )
    # The watchdog must not repeatedly finalize: exactly one RUN_HEARTBEAT_FAILED
    # diagnostic is appended.
    heartbeat_diags = [d for d in diags if d.get("code") == "RUN_HEARTBEAT_FAILED"]
    assert len(heartbeat_diags) == 1, (
        "watchdog must terminalize exactly once, not repeatedly"
    )


def test_single_transient_background_heartbeat_failure_does_not_terminalize(provisioned_project):
    """A single transient background heartbeat failure followed by a success
    must not trigger terminalization: the consecutive-failure counter resets
    and the Run completes normally."""
    from cardre.application.execution.heartbeat import HeartbeatWatchdog

    project_id, uow_factory, _registry, root = provisioned_project
    with uow_factory.for_project(project_id) as uow:
        plan_id = uow.plans.create_plan(project_id, "Plan")
        pv_id = uow.plans.create_version(plan_id, [], is_committed=True)
        run_id = uow.runs.create(pv_id)
        uow.runs.transition(run_id, RunStatus.RUNNING,
                            expected_from=(RunStatus.SUBMITTED,))
        uow.commit()

    failures: list[int] = []
    state = {"calls": 0, "fail_on": 1}

    def failing_once():
        return _FailingOnceHeartbeatUoW(
            uow_factory.for_project(project_id), state,
        )

    watchdog = HeartbeatWatchdog(
        failing_once,
        run_id,
        interval_seconds=0.05,
        on_failure=lambda: failures.append(1),
        max_consecutive_failures=3,
    )
    watchdog.start()
    try:
        # Let the watchdog run long enough to cross several intervals: the
        # first background write fails (transient), the rest succeed, so the
        # consecutive-failure counter never reaches the threshold.
        time.sleep(0.4)
    finally:
        watchdog.stop()

    assert failures == [], (
        "a single transient failure must not trigger the failure callback"
    )
    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.RUNNING.value, (
        "a transient failure must not terminalize a healthy run"
    )


# ---------------------------------------------------------------------------
# RED #47 — non-cancellation LeaseLost while running cannot leave it running
# ---------------------------------------------------------------------------


def test_non_cancellation_lease_lost_terminalizes_running_run(provisioned_project):
    """A non-cancellation ``LeaseLost`` while the Run is still ``running`` must
    not return leaving it permanently running: it ends ``interrupted`` with the
    ``RUN_LEASE_LOST`` diagnostic."""
    project_id, uow_factory, _registry, root = provisioned_project
    pv_id = _committed_noop_pv(uow_factory, project_id)
    run_id = _run_id(uow_factory, project_id, pv_id)

    finalize = _finalize_for(uow_factory, project_id, root)

    def failing_write():
        return _FailingLeaseUoW(uow_factory.for_project(project_id), run_id)

    executor = ExecuteRun(
        failing_write,
        lambda: uow_factory.read_only(project_id),
        _NoopCatalogue(),
        _SucceededRunner(),
        finalize,
        lambda: _NoopStore(),
        lambda: _stub_publisher(uow_factory, project_id),
        heartbeat_interval_seconds=0.1,
    )
    executor(ExecuteRunCommand(run_id=run_id))

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        diags = uow.runs.get_diagnostics(run_id)
        outbox = uow.publications.list_by_run(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value, (
        "non-cancellation lease loss while running must not leave the run running"
    )
    assert any(d.get("code") == "RUN_LEASE_LOST" for d in diags), (
        "interrupted run must carry the RUN_LEASE_LOST diagnostic"
    )
    # The terminalization is a full, durable finalization.
    assert any(r["kind"] == "manifest" for r in outbox), (
        "lease-lost run must enqueue a manifest outbox record"
    )


def test_lease_lost_does_not_overwrite_already_terminalized_run(provisioned_project):
    """A lost lease must not overwrite a Run another owner already terminalized,
    and must not append a false ``RUN_LEASE_LOST`` diagnostic."""
    import threading

    project_id, uow_factory, _registry, root = provisioned_project
    pv_id = _committed_noop_pv(uow_factory, project_id)
    run_id = _run_id(uow_factory, project_id, pv_id)

    finalize = _finalize_for(uow_factory, project_id, root)

    node_returned = threading.Event()
    release_node = threading.Event()

    class _BlockingRunner:
        def run_step(self, *args, **kwargs):
            from cardre.application.execution.step_runner import StepExecutionResult

            node_returned.set()
            release_node.wait(timeout=5)
            return StepExecutionResult(
                step_id="s1", node_type="cardre.noop", status=RunStepStatus.SUCCEEDED,
                fingerprint={}, input_artifact_ids=[], output_artifact_ids=[],
                staged_artifacts=[], parent_run_steps=[],
                input_artifact_ids_by_parent={},
            )

    def failing_write():
        return _FailingLeaseUoW(uow_factory.for_project(project_id), run_id)

    executor = ExecuteRun(
        failing_write,
        lambda: uow_factory.read_only(project_id),
        _NoopCatalogue(),
        _BlockingRunner(),
        finalize,
        lambda: _NoopStore(),
        lambda: _stub_publisher(uow_factory, project_id),
        heartbeat_interval_seconds=0.1,
    )
    thread = threading.Thread(target=lambda: executor(ExecuteRunCommand(run_id=run_id)))
    thread.start()
    assert node_returned.wait(timeout=5), "node never started"

    # Another owner terminalizes the run (exactly what stale recovery does:
    # FinalizeRun interrupted with its diagnostic + manifest), while the worker
    # is still running. The worker's later lease-lost must not overwrite it.
    finalize(run_id, "interrupted", diagnostic=FinalizeDiagnostic(
        code="RUN_STALE", message="Run was stale and has been interrupted",
    ))
    release_node.set()
    thread.join(timeout=5)

    with uow_factory.read_only(project_id) as uow:
        run = uow.runs.get(run_id)
        diags = uow.runs.get_diagnostics(run_id)
        outbox = uow.publications.list_by_run(run_id)
    assert run is not None
    assert str(run.status) == RunStatus.INTERRUPTED.value, (
        "already-terminalized run must stay in its terminal state"
    )
    assert not any(d.get("code") == "RUN_LEASE_LOST" for d in diags), (
        "no false RUN_LEASE_LOST diagnostic when another owner terminalized the run"
    )
    # The other owner's terminalization must not be duplicated or overwritten.
    manifest_rows = [r for r in outbox if r["kind"] == "manifest"]
    assert len(manifest_rows) == 1, (
        "already-terminalized run must not get a second manifest"
    )


class _NoopStore:
    def finalize(self, staged):
        return None

    def object_path(self, physical_hash):
        return "objects/x"
