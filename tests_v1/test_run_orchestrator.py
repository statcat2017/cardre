from __future__ import annotations

import os
import uuid

import pytest

from cardre.audit import RunStepRecord, utc_now_iso
from cardre.services import run_orchestrator
from cardre.services.run_service import RunResponse


class DummyStore:
    def __init__(self) -> None:
        self.finished: list[tuple[str, str]] = []
        self.diagnostics: list[tuple[str, dict]] = []

    def finish_run(self, run_id: str, status: str) -> None:
        self.finished.append((run_id, status))

    def append_run_diagnostic(self, run_id: str, diag: dict) -> None:
        self.diagnostics.append((run_id, diag))


# ---------------------------------------------------------------------------
# Delegation tests — assert that run_orchestrator.execute_run delegates
# to RunService.run_plan / RunService.execute_created_run.
# ---------------------------------------------------------------------------


def test_execute_run_returns_created_run_id_for_sync_full_plan(tmp_path, monkeypatch):
    """run_orchestrator.execute_run with no run_id delegates to
    RunService.run_plan and returns its run_id."""
    from tests.test_run_worker import _init_store

    store = _init_store(tmp_path)

    def fake_run_plan(
        self, plan_version_id, run_scope="full_plan",
        branch_id=None, target_step_id=None, force=False, sync=False,
    ):
        return RunResponse(
            run_id="delegated-full", plan_version_id=plan_version_id,
            status="succeeded", started_at="t", step_count=0,
        )

    monkeypatch.setattr(
        "cardre.services.run_service.RunService.run_plan", fake_run_plan,
    )

    run_id = run_orchestrator.execute_run(store, "pv", run_scope="full_plan")
    assert run_id == "delegated-full"


def test_execute_run_returns_created_run_id_for_sync_to_node(tmp_path, monkeypatch):
    from tests.test_run_worker import _init_store

    store = _init_store(tmp_path)

    def fake_run_plan(
        self, plan_version_id, run_scope="full_plan",
        branch_id=None, target_step_id=None, force=False, sync=False,
    ):
        return RunResponse(
            run_id="delegated-to-node", plan_version_id=plan_version_id,
            status="succeeded", started_at="t", step_count=0,
        )

    monkeypatch.setattr(
        "cardre.services.run_service.RunService.run_plan", fake_run_plan,
    )

    run_id = run_orchestrator.execute_run(
        store, "pv", run_scope="to_node", target_step_id="target",
    )
    assert run_id == "delegated-to-node"


@pytest.mark.governance
@pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)
def test_execute_run_returns_created_run_id_for_sync_branch(tmp_path, monkeypatch):
    from tests.test_run_worker import _init_store

    store = _init_store(tmp_path)

    def fake_run_plan(
        self, plan_version_id, run_scope="full_plan",
        branch_id=None, target_step_id=None, force=False, sync=False,
    ):
        return RunResponse(
            run_id="delegated-branch", plan_version_id=plan_version_id,
            status="succeeded", started_at="t", step_count=0,
        )

    monkeypatch.setattr(
        "cardre.services.run_service.RunService.run_plan", fake_run_plan,
    )

    run_id = run_orchestrator.execute_run(
        store, "pv", run_scope="branch", branch_id="branch-1",
    )
    assert run_id == "delegated-branch"


# ---------------------------------------------------------------------------
# Branch short-circuit tests — assert that the shim returns the existing
# run_id and cancels the placeholder when branch is current.
# ---------------------------------------------------------------------------


@pytest.mark.governance
@pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)
def test_execute_run_preserves_precreated_async_run_id_on_branch_short_circuit(
    tmp_path, monkeypatch,
):
    """The shim must return the existing successful run_id (not the
    placeholder) and cancel the placeholder when the branch short-circuits."""
    from cardre.audit import StepSpec, json_logical_hash
    from tests.test_run_worker import _init_store

    store = _init_store(tmp_path)
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")
    steps = [
        StepSpec(
            step_id="source", node_type="cardre.test.simple_source",
            node_version="1", category="transform",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps)

    branch_id = store.create_branch(
        project_id=prj_id, plan_id=plan_id, name="test-branch",
        branch_type="challenger",
        base_plan_version_id=pv_id, head_plan_version_id=pv_id,
        created_reason="test",
    )

    # Seed an existing successful branch run.
    existing_run_id = store.create_run(pv_id, branch_id=branch_id)
    store.save_run_step(
        RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=existing_run_id,
            step_id="source", plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[],
            execution_fingerprint={}, warnings=[], errors=[],
        ),
    )
    store.finish_run(existing_run_id, "succeeded")

    # Create a placeholder run.
    placeholder_id = store.create_run(pv_id, branch_id=branch_id)

    class _FakeCtx:
        short_circuit_run_id = existing_run_id
        diagnostics = []
        steps = []
        branch_owned_step_ids = set()
        stale_branch_step_ids = []
        step_outputs = {}
        run_step_records = {}

    monkeypatch.setattr(
        "cardre.services.evidence_policy.EvidencePolicyService.prepare_branch_evidence",
        lambda self, pv, bid, force=False: _FakeCtx(),
    )

    result = run_orchestrator.execute_run(
        store, pv_id, run_id=placeholder_id,
        run_scope="branch", branch_id=branch_id,
    )

    assert result == existing_run_id, (
        f"shim must return existing run_id, got {result!r}"
    )
    assert store.get_run(placeholder_id)["status"] == "cancelled", (
        "placeholder must be cancelled"
    )


@pytest.mark.governance
@pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)
def test_branch_short_circuit_worker_path_returns_existing_run_id(
    tmp_path, monkeypatch,
):
    """Explicit pin: the worker path (execute_run with run_id) returns the
    existing successful run_id on a branch short-circuit."""
    from cardre.audit import StepSpec, json_logical_hash
    from tests.test_run_worker import _init_store

    store = _init_store(tmp_path)
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")
    steps = [
        StepSpec(
            step_id="source", node_type="cardre.test.simple_source",
            node_version="1", category="transform",
            params={}, params_hash=json_logical_hash({}),
            parent_step_ids=[], branch_label="", position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps)

    branch_id = store.create_branch(
        project_id=prj_id, plan_id=plan_id, name="test-branch",
        branch_type="challenger",
        base_plan_version_id=pv_id, head_plan_version_id=pv_id,
        created_reason="test",
    )

    existing_run_id = store.create_run(pv_id, branch_id=branch_id)
    store.save_run_step(
        RunStepRecord(
            run_step_id=str(uuid.uuid4()), run_id=existing_run_id,
            step_id="source", plan_version_id=pv_id, status="succeeded",
            started_at=utc_now_iso(), finished_at=utc_now_iso(),
            input_artifact_ids=[], output_artifact_ids=[],
            execution_fingerprint={}, warnings=[], errors=[],
        ),
    )
    store.finish_run(existing_run_id, "succeeded")

    placeholder_id = store.create_run(pv_id, branch_id=branch_id)

    class _FakeCtx:
        short_circuit_run_id = existing_run_id
        diagnostics = []
        steps = []
        branch_owned_step_ids = set()
        stale_branch_step_ids = []
        step_outputs = {}
        run_step_records = {}

    monkeypatch.setattr(
        "cardre.services.evidence_policy.EvidencePolicyService.prepare_branch_evidence",
        lambda self, pv, bid, force=False: _FakeCtx(),
    )

    result = run_orchestrator.execute_run(
        store, pv_id, run_id=placeholder_id,
        run_scope="branch", branch_id=branch_id,
    )

    assert result == existing_run_id, (
        f"worker-path branch short-circuit must return existing run_id, "
        f"got {result!r}"
    )
    assert store.get_run(placeholder_id)["status"] == "cancelled"


# ---------------------------------------------------------------------------
# _is_branch_current tests — unchanged (test sidecar/routes/runs.py helpers)
# ---------------------------------------------------------------------------


def test_is_branch_current_returns_none_when_no_short_circuit(monkeypatch):
    """_is_branch_current returns None when prepare_branch_evidence has no short_circuit_run_id."""
    from sidecar.routes.runs import _is_branch_current
    from cardre.services.evidence_policy import ShortCircuitResult

    class NoShortCircuitResolver:
        def check_branch_current(self, plan_version_id, branch_id):
            return ShortCircuitResult()

    monkeypatch.setattr("sidecar.routes.runs.EvidencePolicyService", lambda store: NoShortCircuitResolver())

    result = _is_branch_current(DummyStore(), "pv", "branch-1")
    assert result is None


def test_is_branch_current_returns_run_id_when_short_circuit(monkeypatch):
    """_is_branch_current returns the short_circuit_run_id when branch is current."""
    from sidecar.routes.runs import _is_branch_current
    from cardre.services.evidence_policy import ShortCircuitResult

    class ShortCircuitResolver:
        def check_branch_current(self, plan_version_id, branch_id):
            return ShortCircuitResult(run_id="existing-run-42", reason="branch_current")

    monkeypatch.setattr("sidecar.routes.runs.EvidencePolicyService", lambda store: ShortCircuitResolver())

    result = _is_branch_current(DummyStore(), "pv", "branch-1")
    assert result == "existing-run-42"


def test_is_branch_current_returns_none_on_exception(monkeypatch):
    """_is_branch_current returns None when check_branch_current raises."""
    from sidecar.routes.runs import _is_branch_current
    from cardre.errors import CardreError

    class BrokenResolver:
        def check_branch_current(self, plan_version_id, branch_id):
            raise CardreError("branch not found", code="BRANCH_NOT_FOUND")

    monkeypatch.setattr("sidecar.routes.runs.EvidencePolicyService", lambda store: BrokenResolver())

    result = _is_branch_current(DummyStore(), "pv", "branch-1")
    assert result is None
