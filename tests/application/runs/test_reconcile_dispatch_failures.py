"""Slice 1 — ReconcileDispatches must surface a per-Project pending-read failure
instead of silently skipping the Project.

A corrupted or unreadable Project database must not make startup reconciliation
silently drop that Project's pending dispatch work. Reconciliation must continue
to the remaining Projects and expose an observable failed outcome for the
unreadable Project, without falsely claiming its pending Runs were dispatched.
"""

from __future__ import annotations

from cardre.adapters.sqlite.connection import SqliteUnitOfWorkFactory
from cardre.adapters.sqlite.project_provisioner import SqliteProjectProvisioner
from cardre.adapters.system.project_registry import JsonProjectRegistry
from cardre.application.ports.run_dispatcher import RunRequest
from cardre.application.runs.reconcile_dispatches import ReconcileDispatches
from cardre.domain.step import StepSpec


class _FakeCapabilityProbe:
    def project_root_exists(self, root: str) -> bool:
        return True


class _RecordingDispatcher:
    def __init__(self):
        self.dispatched: list[RunRequest] = []

    def dispatch(self, request: RunRequest) -> None:
        self.dispatched.append(request)

    def get_status(self, run_id: str) -> str:
        return "completed"

    def shutdown(self) -> None:
        pass


class _FailingReadUoWFactory:
    """Wrapper that raises on ``read_only`` for one Project and delegates to the
    real factory otherwise. This is the existing ``uow_factory`` seam."""

    def __init__(self, real, fail_project_id: str) -> None:
        self._real = real
        self._fail_project_id = fail_project_id

    def read_only(self, project_id: str):
        if project_id == self._fail_project_id:
            raise RuntimeError("injected pending dispatch read failure")
        return self._real.read_only(project_id)

    def for_project(self, project_id: str):
        return self._real.for_project(project_id)


def _provision(tmp_path):
    """Provision one real Project with a pending dispatch row, and register a
    second (failing) Project id first so reconciliation must skip past it."""
    registry = JsonProjectRegistry(tmp_path / "registry.json")
    provisioner = SqliteProjectProvisioner()
    root = tmp_path / "project"
    provisioner.initialize(root)
    uow_factory = SqliteUnitOfWorkFactory(registry)

    with uow_factory.for_root(root) as uow:
        good_project_id = uow.projects.create("Good Project")
        plan_id = uow.plans.create_plan(good_project_id, "Plan")
        pv_id = uow.plans.create_version(
            plan_id, [StepSpec(
                step_id="s1", node_type="cardre.noop", node_version="1",
                category="transform", params={}, params_hash="",
                parent_step_ids=[], position=0, canonical_step_id="s1",
            )],
            is_committed=True,
        )
        run_id = uow.runs.create(pv_id)
        uow.dispatches.enqueue(run_id)
        uow.commit()

    # Failing Project registered first so reconciliation must continue past it.
    registry.register("failing-project", root)
    registry.register(good_project_id, root)
    return good_project_id, run_id, uow_factory, registry


def test_reconcile_continues_and_records_project_read_failure(tmp_path):
    """A per-Project pending-read failure is recorded and does not block or
    falsely dispatch other Projects."""
    good_project_id, run_id, uow_factory, registry = _provision(tmp_path)
    failing = _FailingReadUoWFactory(uow_factory, "failing-project")
    dispatcher = _RecordingDispatcher()

    outcome = ReconcileDispatches(failing, registry, dispatcher, _FakeCapabilityProbe())()

    # The good Project's pending Run was still redispatched.
    assert any(
        r.run_id == run_id and r.state == "dispatched"
        for r in outcome.results
    ), f"expected good run redispatched: {outcome.results}"

    # The failing Project surfaced an observable failure instead of silence.
    failed = [r for r in outcome.results if r.project_id == "failing-project"]
    assert len(failed) == 1, f"expected one failed project result: {outcome.results}"
    assert failed[0].state == "error"
    assert "injected pending dispatch read failure" in failed[0].error

    # No false claim that the failing Project's Runs were dispatched.
    assert not any(
        r.project_id == "failing-project" and r.state == "dispatched"
        for r in outcome.results
    )
