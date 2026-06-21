from __future__ import annotations

from cardre.services import run_orchestrator


class DummyStore:
    def __init__(self) -> None:
        self.finished: list[tuple[str, str]] = []

    def finish_run(self, run_id: str, status: str) -> None:
        self.finished.append((run_id, status))


class FakeExecutor:
    calls: list[tuple[str, str | None]] = []
    result_id = "created-run"

    def __init__(self, registry) -> None:
        self.registry = registry

    def run_plan_version(self, store, plan_version_id, run_id=None, force=False):
        self.calls.append(("full_plan", run_id))
        return self.result_id

    def run_to_node(self, store, plan_version_id, target_step_id, run_id=None, force=False):
        self.calls.append(("to_node", run_id))
        return self.result_id

    def run_branch(self, store, plan_version_id, branch_id, run_id=None, force=False):
        self.calls.append(("branch", run_id))
        return self.result_id


def _patch_executor(monkeypatch) -> None:
    FakeExecutor.calls = []
    FakeExecutor.result_id = "created-run"
    monkeypatch.setattr(run_orchestrator, "PlanExecutor", FakeExecutor)
    monkeypatch.setattr(run_orchestrator.NodeRegistry, "with_defaults", staticmethod(lambda: object()))


def test_execute_run_returns_created_run_id_for_sync_full_plan(monkeypatch):
    _patch_executor(monkeypatch)

    run_id = run_orchestrator.execute_run(DummyStore(), "pv", run_scope="full_plan")

    assert run_id == "created-run"
    assert FakeExecutor.calls == [("full_plan", None)]


def test_execute_run_returns_created_run_id_for_sync_to_node(monkeypatch):
    _patch_executor(monkeypatch)

    run_id = run_orchestrator.execute_run(
        DummyStore(), "pv", run_scope="to_node", target_step_id="target",
    )

    assert run_id == "created-run"
    assert FakeExecutor.calls == [("to_node", None)]


def test_execute_run_returns_created_run_id_for_sync_branch(monkeypatch):
    _patch_executor(monkeypatch)

    run_id = run_orchestrator.execute_run(
        DummyStore(), "pv", run_scope="branch", branch_id="branch-1",
    )

    assert run_id == "created-run"
    assert FakeExecutor.calls == [("branch", None)]


def test_execute_run_preserves_precreated_async_run_id_on_branch_short_circuit(monkeypatch):
    _patch_executor(monkeypatch)
    FakeExecutor.result_id = "existing-successful-run"
    store = DummyStore()

    run_id = run_orchestrator.execute_run(
        store, "pv", run_id="precreated-run", run_scope="branch", branch_id="branch-1",
    )

    assert run_id == "precreated-run"
    assert store.finished == [("precreated-run", "cancelled")]
