"""Phase 1 — Characterisation contract tests for run coordination.

These tests lock the run-coordination contract *before* the refactor.
Some will be GREEN immediately; one test (test 11) is intentionally RED
as the target for the consolidation sprint.

GREEN tests:
    1, 4, 8 (governance-gated), 9, 10, 12

xfail (not yet implemented):
    2, 3, 5, 6, 7, 13

RED (lands in phase 4):
    11 (governance-gated)
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from cardre.artifacts import write_json_artifact
from cardre.audit import RunStepRecord, StepSpec, json_logical_hash, utc_now_iso
from cardre.errors import CardreError
from cardre.services.run_worker import (
    DISPATCH_FAILED_CODE,
    RunRequest,
    RunWorker,
    SyncRunDispatcher,
    ThreadRunDispatcher,
    WORKER_FAILED_CODE,
)
from tests.test_run_worker import (
    _init_store,
    _one_step_plan,
    _RecordingDispatcher,
)


# ======================================================================
# Test 1 — Async dispatch uses precreated run_id  (GREEN)
# ======================================================================


def test_async_dispatch_uses_precreated_run_id(tmp_path: Path) -> None:
    """RunService passes a fully populated RunRequest to the dispatcher
    with a precreated run_id that matches the response."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    pv_id = _one_step_plan(store)
    recorder = _RecordingDispatcher()

    service = RunService(store, dispatcher=recorder)
    resp = service.run_plan(plan_version_id=pv_id, sync=False)

    assert recorder.dispatched, "dispatcher was not called"
    req = recorder.dispatched[0]
    assert req.run_id == resp.run_id
    assert req.plan_version_id == pv_id
    assert req.project_path == str(store.root)
    assert req.run_scope == "full_plan"
    assert store.get_run(resp.run_id)["status"] == "running"


# ======================================================================
# Test 2 — Worker delegates to RunService.execute_created_run  (xfail)
# ======================================================================


@pytest.mark.xfail(reason="lands in phase 3")
def test_worker_delegates_to_run_service_execute_created_run(
    tmp_path: Path, monkeypatch
) -> None:
    """RunWorker.execute must delegate to RunService.execute_created_run
    (not call run_orchestrator.execute_run directly)."""
    store = _init_store(tmp_path)
    pv_id = _one_step_plan(store)
    run_id = store.create_run(pv_id)

    calls: list[RunRequest] = []

    def fake_execute_created_run(self, request: RunRequest) -> None:
        calls.append(request)
        store.finish_run(request.run_id, "succeeded")

    monkeypatch.setattr(
        "cardre.services.run_service.RunService.execute_created_run",
        fake_execute_created_run,
    )

    RunWorker().execute(
        RunRequest(
            project_path=str(store.root),
            plan_version_id=pv_id,
            run_id=run_id,
        )
    )

    assert len(calls) == 1
    assert calls[0].run_id == run_id
    assert store.get_run(run_id)["status"] == "succeeded"


# ======================================================================
# Test 3 — Worker failure records diagnostic and fails run  (xfail)
# ======================================================================


@pytest.mark.xfail(reason="lands in phase 3")
def test_worker_failure_records_diagnostic_and_fails_run(
    tmp_path: Path, monkeypatch
) -> None:
    """When RunService.execute_created_run raises, the worker must
    record a RUN_WORKER_FAILED diagnostic and fail the run."""
    store = _init_store(tmp_path)
    pv_id = _one_step_plan(store)
    run_id = store.create_run(pv_id)

    def fake_execute_created_run(self, request: RunRequest) -> None:
        raise RuntimeError("executor exploded")

    monkeypatch.setattr(
        "cardre.services.run_service.RunService.execute_created_run",
        fake_execute_created_run,
    )

    RunWorker().execute(
        RunRequest(
            project_path=str(store.root),
            plan_version_id=pv_id,
            run_id=run_id,
        )
    )

    run = store.get_run(run_id)
    assert run["status"] == "failed"

    diags = store.get_run_diagnostics(run_id)
    codes = [d["code"] for d in diags]
    assert WORKER_FAILED_CODE in codes
    failed = next(d for d in diags if d["code"] == WORKER_FAILED_CODE)
    assert "executor exploded" in failed["message"]


# ======================================================================
# Test 4 — Dispatch startup failure records diagnostic and fails run  (GREEN)
# ======================================================================


def test_dispatch_startup_failure_records_diagnostic_and_fails_run(
    tmp_path: Path, monkeypatch
) -> None:
    """If the dispatcher fails at startup, the service raises
    CardreError(DISPATCH_FAILED_CODE) and the run is failed with a
    RUN_DISPATCH_FAILED diagnostic."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    pv_id = _one_step_plan(store)

    # Force ThreadRunDispatcher to fail at thread creation, which makes
    # it record the diagnostic and fail the run before raising.
    def _boom(*a, **k):
        raise OSError("cannot create thread")

    monkeypatch.setattr("cardre.services.run_worker.threading.Thread", _boom)

    service = RunService(store, dispatcher=ThreadRunDispatcher())

    with pytest.raises(CardreError) as ei:
        service.run_plan(pv_id, sync=False)
    assert ei.value.code == DISPATCH_FAILED_CODE

    # The run was created by run_plan and failed by ThreadRunDispatcher.
    runs = store.list_runs(plan_version_id=pv_id)
    assert len(runs) >= 1
    failed_run = runs[-1]
    assert failed_run["status"] == "failed"

    diags = store.get_run_diagnostics(failed_run["run_id"])
    codes = [d["code"] for d in diags]
    assert DISPATCH_FAILED_CODE in codes


# ======================================================================
# Test 5 — execute_created_run rejects missing run  (xfail)
# ======================================================================


def test_execute_created_run_rejects_missing_run(tmp_path: Path) -> None:
    """execute_created_run must raise CardreError(RUN_NOT_FOUND) for a
    non-existent run_id."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    pv_id = _one_step_plan(store)

    request = RunRequest(
        project_path=str(store.root),
        plan_version_id=pv_id,
        run_id="nonexistent-run-id",
    )
    with pytest.raises(CardreError) as ei:
        RunService(store).execute_created_run(request)
    assert ei.value.code == "RUN_NOT_FOUND"


# ======================================================================
# Test 6 — execute_created_run rejects plan_version mismatch  (xfail)
# ======================================================================


def test_execute_created_run_rejects_plan_version_mismatch(
    tmp_path: Path, monkeypatch
) -> None:
    """execute_created_run must raise CardreError(RUN_PLAN_VERSION_MISMATCH)
    when the request's plan_version_id does not match the run's."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")

    steps_a = [
        StepSpec(
            step_id="source_a",
            node_type="cardre.test.simple_source",
            node_version="1",
            category="transform",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        ),
    ]
    pv_a = store.create_plan_version(plan_id, steps_a)

    steps_b = [
        StepSpec(
            step_id="source_b",
            node_type="cardre.test.simple_source",
            node_version="1",
            category="transform",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        ),
    ]
    pv_b = store.create_plan_version(plan_id, steps_b)

    run_id = store.create_run(pv_a)

    request = RunRequest(
        project_path=str(store.root),
        plan_version_id=pv_b,
        run_id=run_id,
    )
    with pytest.raises(CardreError) as ei:
        RunService(store).execute_created_run(request)
    assert ei.value.code == "RUN_PLAN_VERSION_MISMATCH"


# ======================================================================
# Test 7 — execute_created_run rejects non-running status  (xfail)
# ======================================================================


def test_execute_created_run_rejects_non_running_status(tmp_path: Path) -> None:
    """execute_created_run must raise CardreError(RUN_NOT_RUNNING) when
    the run is already finished."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    pv_id = _one_step_plan(store)
    run_id = store.create_run(pv_id)
    store.finish_run(run_id, "succeeded")

    request = RunRequest(
        project_path=str(store.root),
        plan_version_id=pv_id,
        run_id=run_id,
    )
    with pytest.raises(CardreError) as ei:
        RunService(store).execute_created_run(request)
    assert ei.value.code == "RUN_NOT_RUNNING"


# ======================================================================
# Test 8 — Branch short circuit returns existing run for sync & worker
#          (governance-gated, GREEN)
# ======================================================================


@pytest.mark.governance
@pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)
def test_branch_short_circuit_returns_existing_run_for_sync_and_worker_paths(
    tmp_path: Path, monkeypatch
) -> None:
    """Both sync and async branch requests must return the same existing
    run_id when the branch is current (no stale steps)."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")

    steps = [
        StepSpec(
            step_id="source",
            node_type="cardre.test.simple_source",
            node_version="1",
            category="transform",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps)

    branch_id = str(uuid.uuid4())
    store.create_branch(
        project_id=prj_id,
        plan_id=plan_id,
        name="test-branch",
        branch_type="model_challenger",
        base_plan_version_id=pv_id,
        head_plan_version_id=pv_id,
        created_reason="contract test",
        branch_id=branch_id,
    )

    # Seed an existing successful branch run.
    existing_run_id = store.create_run(pv_id, branch_id=branch_id)
    art = write_json_artifact(
        store,
        artifact_type="report",
        role="artifact",
        stem="seed-source",
        payload={"step_id": "source"},
        metadata={},
    )
    store.save_run_step(
        RunStepRecord(
            run_step_id=str(uuid.uuid4()),
            run_id=existing_run_id,
            step_id="source",
            plan_version_id=pv_id,
            status="succeeded",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=[],
            output_artifact_ids=[art.artifact_id],
            execution_fingerprint={
                "params_hash": steps[0].params_hash,
                "node_type": "cardre.test.simple_source",
                "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [art.logical_hash],
            },
            warnings=[],
            errors=[],
        )
    )
    store.finish_run(existing_run_id, "succeeded")

    # Monkeypatch EvidencePolicyService.prepare_branch_evidence to return
    # a fake ctx with the short-circuit run_id.
    class _FakeBranchCtx:
        short_circuit_run_id = existing_run_id
        diagnostics: list = []
        steps = []
        branch_owned_step_ids: set = set()
        stale_branch_step_ids: list = []
        step_outputs: dict = {}
        run_step_records: dict = {}

    monkeypatch.setattr(
        "cardre.services.evidence_policy.EvidencePolicyService.prepare_branch_evidence",
        lambda self, pv, bid, force=False: _FakeBranchCtx(),
    )

    service = RunService(store, dispatcher=_RecordingDispatcher())
    sync = service.run_plan(
        pv_id,
        run_scope="branch",
        branch_id=branch_id,
        sync=True,
        force=False,
    )
    async_ = service.run_plan(
        pv_id,
        run_scope="branch",
        branch_id=branch_id,
        sync=False,
        force=False,
    )

    assert sync.run_id == existing_run_id
    assert async_.run_id == existing_run_id


# ======================================================================
# Test 9 — To-node short circuit parity sync and worker  (GREEN)
# ======================================================================


def test_to_node_short_circuit_parity_sync_and_worker(tmp_path: Path) -> None:
    """Both sync and async to-node requests must return the same existing
    run_id when the target step is current."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")

    steps = [
        StepSpec(
            step_id="source",
            node_type="cardre.test.simple_source",
            node_version="1",
            category="transform",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps)

    # Seed a prior successful full run with a run step for "source".
    prev_run_id = store.create_run(pv_id)
    art = write_json_artifact(
        store,
        artifact_type="report",
        role="artifact",
        stem="seed-source",
        payload={"step_id": "source"},
        metadata={},
    )
    store.save_run_step(
        RunStepRecord(
            run_step_id=str(uuid.uuid4()),
            run_id=prev_run_id,
            step_id="source",
            plan_version_id=pv_id,
            status="succeeded",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=[],
            output_artifact_ids=[art.artifact_id],
            execution_fingerprint={
                "params_hash": steps[0].params_hash,
                "node_type": "cardre.test.simple_source",
                "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [art.logical_hash],
            },
            warnings=[],
            errors=[],
        )
    )
    store.finish_run(prev_run_id, "succeeded")

    recorder = _RecordingDispatcher()
    service = RunService(store, dispatcher=recorder)

    sync = service.run_plan(
        pv_id,
        run_scope="to_node",
        target_step_id="source",
        sync=True,
    )

    # Async path: short-circuit happens before dispatch, so dispatcher
    # is never called.
    async_ = service.run_plan(
        pv_id,
        run_scope="to_node",
        target_step_id="source",
        sync=False,
    )

    assert sync.run_id == prev_run_id
    assert async_.run_id == prev_run_id


# ======================================================================
# Test 10 — Full plan executes via shared path  (GREEN)
# ======================================================================


def test_full_plan_executes_via_shared_path(tmp_path: Path, monkeypatch) -> None:
    """A full-plan run via RunService dispatches to PlanExecutor and
    succeeds."""
    from cardre.services.run_service import RunService
    from cardre.registry import NodeRegistry
    from tests.test_executor import SimpleSourceNode

    # Register SimpleSourceNode so the executor can find it.
    reg = NodeRegistry.with_defaults()
    reg.register(SimpleSourceNode)
    monkeypatch.setattr(
        "cardre.services.run_service.NodeRegistry.with_defaults",
        staticmethod(lambda: reg),
    )

    store = _init_store(tmp_path)
    pv_id = _one_step_plan(store)

    # The one-step plan uses "cardre.test.simple_source" which is now
    # in the patched registry.
    service = RunService(store, dispatcher=SyncRunDispatcher())
    resp = service.run_plan(pv_id, sync=True)

    assert resp.status == "succeeded"
    assert resp.executed_step_ids == ["source"]


# ======================================================================
# Test 11 — Branch placeholder cancellation writes manifest
#           (governance-gated, RED — lands in phase 4)
# ======================================================================


@pytest.mark.governance
@pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)
def test_branch_placeholder_cancellation_writes_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """RED: Branch placeholders currently use finish_run with no manifest.
    This test locks the intended behaviour: the cancelled placeholder
    must have a run_manifest artifact with status='cancelled' and
    execution_mode='branch'."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")

    steps = [
        StepSpec(
            step_id="source",
            node_type="cardre.test.simple_source",
            node_version="1",
            category="transform",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps)

    branch_id = str(uuid.uuid4())
    store.create_branch(
        project_id=prj_id,
        plan_id=plan_id,
        name="test-branch",
        branch_type="model_challenger",
        base_plan_version_id=pv_id,
        head_plan_version_id=pv_id,
        created_reason="contract test",
        branch_id=branch_id,
    )

    # Seed an existing successful branch run.
    existing_run_id = store.create_run(pv_id, branch_id=branch_id)
    art = write_json_artifact(
        store,
        artifact_type="report",
        role="artifact",
        stem="seed-source",
        payload={"step_id": "source"},
        metadata={},
    )
    store.save_run_step(
        RunStepRecord(
            run_step_id=str(uuid.uuid4()),
            run_id=existing_run_id,
            step_id="source",
            plan_version_id=pv_id,
            status="succeeded",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=[],
            output_artifact_ids=[art.artifact_id],
            execution_fingerprint={
                "params_hash": steps[0].params_hash,
                "node_type": "cardre.test.simple_source",
                "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [art.logical_hash],
            },
            warnings=[],
            errors=[],
        )
    )
    store.finish_run(existing_run_id, "succeeded")

    class _FakeBranchCtx:
        short_circuit_run_id = existing_run_id
        diagnostics: list = []
        steps = []
        branch_owned_step_ids: set = set()
        stale_branch_step_ids: list = []
        step_outputs: dict = {}
        run_step_records: dict = {}

    monkeypatch.setattr(
        "cardre.services.evidence_policy.EvidencePolicyService.prepare_branch_evidence",
        lambda self, pv, bid, force=False: _FakeBranchCtx(),
    )

    service = RunService(store, dispatcher=_RecordingDispatcher())
    service.run_plan(
        pv_id,
        run_scope="branch",
        branch_id=branch_id,
        sync=True,
        force=False,
    )

    # Find the cancelled placeholder run.
    placeholders = [
        r
        for r in store.list_runs(plan_version_id=pv_id)
        if r.get("status") == "cancelled"
    ]
    assert placeholders, "expected a cancelled placeholder"
    ph_id = placeholders[-1]["run_id"]

    manifests = [
        a
        for a in store.list_artifacts()
        if a.artifact_type == "run_manifest" and a.metadata.get("run_id") == ph_id
    ]
    assert len(manifests) == 1, (
        f"short-circuit placeholder must have exactly one manifest "
        f"(ADR 0004 atomic finalisation); got {len(manifests)}"
    )
    manifest = json.loads(store.artifact_path(manifests[0]).read_text())
    assert manifest["status"] == "cancelled"
    assert manifest["execution_mode"] == "branch"

    # RED: lands in phase 4 — currently branch placeholders use
    # store.finish_run directly without writing a manifest.


# ======================================================================
# Test 12 — To-node placeholder cancellation writes manifest  (GREEN)
# ======================================================================


def test_to_node_placeholder_cancellation_writes_manifest(tmp_path: Path) -> None:
    """A to-node short-circuit placeholder must have a manifest with
    status='cancelled' and execution_mode='to_node'."""
    from cardre.services.run_service import RunService

    store = _init_store(tmp_path)
    prj_id = store.create_project("test")
    plan_id = store.create_plan(prj_id, "test-plan")

    steps = [
        StepSpec(
            step_id="source",
            node_type="cardre.test.simple_source",
            node_version="1",
            category="transform",
            params={},
            params_hash=json_logical_hash({}),
            parent_step_ids=[],
            branch_label="",
            position=0,
        ),
    ]
    pv_id = store.create_plan_version(plan_id, steps)

    # Seed a prior successful full run with a run step for "source".
    prev_run_id = store.create_run(pv_id)
    art = write_json_artifact(
        store,
        artifact_type="report",
        role="artifact",
        stem="seed-source",
        payload={"step_id": "source"},
        metadata={},
    )
    store.save_run_step(
        RunStepRecord(
            run_step_id=str(uuid.uuid4()),
            run_id=prev_run_id,
            step_id="source",
            plan_version_id=pv_id,
            status="succeeded",
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            input_artifact_ids=[],
            output_artifact_ids=[art.artifact_id],
            execution_fingerprint={
                "params_hash": steps[0].params_hash,
                "node_type": "cardre.test.simple_source",
                "node_version": "1",
                "parent_output_logical_hashes_by_step": {},
                "output_artifact_logical_hashes": [art.logical_hash],
            },
            warnings=[],
            errors=[],
        )
    )
    store.finish_run(prev_run_id, "succeeded")

    service = RunService(store, dispatcher=SyncRunDispatcher())
    resp = service.run_plan(
        pv_id,
        run_scope="to_node",
        target_step_id="source",
        sync=True,
    )

    assert resp.run_id == prev_run_id, "must return existing run_id"

    placeholders = [
        r
        for r in store.list_runs(plan_version_id=pv_id)
        if r.get("status") == "cancelled"
    ]
    assert placeholders, "expected a cancelled placeholder"
    ph_id = placeholders[-1]["run_id"]

    manifests = [
        a
        for a in store.list_artifacts()
        if a.artifact_type == "run_manifest" and a.metadata.get("run_id") == ph_id
    ]
    assert len(manifests) == 1, (
        f"short-circuit placeholder must have exactly one manifest "
        f"(ADR 0004 atomic finalisation); got {len(manifests)}"
    )
    manifest = json.loads(store.artifact_path(manifests[0]).read_text())
    assert manifest["status"] == "cancelled"
    assert manifest["execution_mode"] == "to_node"


# ======================================================================
# Test 13 — Run orchestrator shim delegates to RunService  (xfail)
# ======================================================================


@pytest.mark.xfail(reason="lands in phase 5")
def test_run_orchestrator_shim_delegates_to_run_service(
    tmp_path: Path, monkeypatch
) -> None:
    """run_orchestrator.execute_run must delegate to RunService.run_plan
    (the future shim)."""
    from cardre.services.run_orchestrator import execute_run
    from cardre.services.run_service import RunResponse

    store = _init_store(tmp_path)
    pv_id = _one_step_plan(store)

    called: list[str] = []

    def fake_run_plan(
        self,
        plan_version_id: str,
        run_scope: str = "full_plan",
        branch_id: str | None = None,
        target_step_id: str | None = None,
        force: bool = False,
        sync: bool = False,
    ) -> RunResponse:
        called.append(plan_version_id)
        return RunResponse(
            run_id="delegated",
            plan_version_id=plan_version_id,
            status="succeeded",
            started_at="t",
            step_count=0,
        )

    monkeypatch.setattr(
        "cardre.services.run_service.RunService.run_plan",
        fake_run_plan,
    )

    result = execute_run(store, pv_id, run_scope="full_plan")
    assert result == "delegated"
    assert called == [pv_id]
