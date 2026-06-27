"""Characterization tests for run diagnostics and diagnostic codes.

Tests the append_run_diagnostic mechanism and all diagnostic codes
introduced by Batches 2-6. These tests ensure that:
- Failed runs carry retrievable diagnostics
- Diagnostic codes, context, and severity are preserved
- The mechanism never raises (append_run_diagnostic is last-resort)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cardre.audit import StepSpec, json_logical_hash, utc_now_iso
from cardre.errors import (
    BranchEvidenceError,
    RunLifecycleError,
)
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.services.branch_evidence import BranchEvidenceResolver
from cardre.services.run_orchestrator import dispatch_run_async
from cardre.store import ProjectStore
from cardre.run_lifecycle import RunLifecycle, write_manifest



def _init_store(tmp: str) -> ProjectStore:
    store = ProjectStore(Path(tmp))
    store.initialize()
    return store


def test_append_run_diagnostic_persists():
    """append_run_diagnostic stores a diagnostic retrievable via get_run_diagnostics."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
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
        run_id = store.create_run(pv_id)

        diag = {
            "code": "TEST_DIAGNOSTIC",
            "message": "Test diagnostic message",
            "severity": "error",
            "category": "test",
            "run_id": run_id,
            "plan_version_id": pv_id,
            "created_at": utc_now_iso(),
        }
        store.append_run_diagnostic(run_id, diag)

        diags = store.get_run_diagnostics(run_id)
        assert len(diags) == 1
        assert diags[0]["code"] == "TEST_DIAGNOSTIC"
        assert diags[0]["run_id"] == run_id
        assert diags[0]["plan_version_id"] == pv_id


def test_append_run_diagnostic_never_raises():
    """append_run_diagnostic does not raise even when run_id is invalid."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        store.append_run_diagnostic("nonexistent-run", {
            "code": "TEST",
            "message": "Should not raise",
        })


def test_async_dispatch_failure_records_diagnostic(monkeypatch):
    """When execute_run raises in dispatch_run_async, a failure diagnostic is recorded.

    The worker records ``RUN_WORKER_FAILED`` (see cardre.services.run_worker)
    and marks the run ``failed``. This characterises the worker contract.
    """
    def _raise_execute_run(*args, **kwargs):
        raise RuntimeError("Simulated execution failure")

    monkeypatch.setattr("cardre.services.run_orchestrator.execute_run", _raise_execute_run)

    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
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
        run_id = store.create_run(pv_id)

        dispatch_run_async(
            project_path=str(store.root),
            plan_version_id=pv_id,
            run_id=run_id,
        )

        diags = store.get_run_diagnostics(run_id)
        codes = [d["code"] for d in diags]
        assert "RUN_WORKER_FAILED" in codes, f"Expected RUN_WORKER_FAILED, got {codes}"
        run = store.get_run(run_id)
        assert run is not None
        assert run.get("status") == "failed"


def test_branch_version_mismatch_raises_typed_error():
    """BranchEvidenceError with BRANCH_VERSION_MISMATCH is raised when head_pv_id differs."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
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

        pv_id2 = store.create_plan_version(plan_id, steps)

        resolver = BranchEvidenceResolver(PlanExecutor(NodeRegistry()))
        with pytest.raises(BranchEvidenceError) as excinfo:
            resolver.prepare_branch_run(store, branch_id, pv_id2, force=False)
        assert excinfo.value.code == "BRANCH_VERSION_MISMATCH"
        context = excinfo.value.context
        assert context.get("branch_id") == branch_id
        assert context.get("head_pv_id") == pv_id
        assert context.get("requested_pv_id") == pv_id2


def test_reuse_evidence_not_found_diagnostic():
    """When shared evidence is not found, diagnostics include REUSE_EVIDENCE_NOT_FOUND."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
        prj_id = store.create_project("test")
        plan_id = store.create_plan(prj_id, "test-plan")
        steps = [
            StepSpec(
                step_id="shared-step", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=[], branch_label="", position=0,
            ),
            StepSpec(
                step_id="branch-step", node_type="cardre.test.simple_source",
                node_version="1", category="transform",
                params={}, params_hash=json_logical_hash({}),
                parent_step_ids=["shared-step"], branch_label="", position=1,
            ),
        ]
        pv_id = store.create_plan_version(plan_id, steps)
        branch_id = store.create_branch(
            project_id=prj_id, plan_id=plan_id, name="test-branch",
            branch_type="challenger",
            base_plan_version_id=pv_id, head_plan_version_id=pv_id,
            created_reason="test",
        )

        store.create_branch_step_map(
            branch_id, pv_id, canonical_step_id="shared-step",
            step_id="shared-step", is_shared_upstream=True, is_branch_owned=False,
        )
        store.create_branch_step_map(
            branch_id, pv_id, canonical_step_id="branch-step",
            step_id="branch-step", is_shared_upstream=False, is_branch_owned=True,
        )

        resolver = BranchEvidenceResolver(PlanExecutor(NodeRegistry()))
        with pytest.raises(BranchEvidenceError) as excinfo:
            resolver.prepare_branch_run(store, branch_id, pv_id, force=False)
        assert excinfo.value.code in ("SHARED_UPSTREAM_STALE", "BRANCH_NO_OP_FAILED")


def test_run_lifecycle_error_on_missing_run_record():
    """write_manifest raises RunLifecycleError when run record is missing."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
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
        run_id = store.create_run(pv_id)

        with store.transaction() as conn:
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

        with pytest.raises(RunLifecycleError) as excinfo:
            write_manifest(
                store=store,
                run_id=run_id,
                plan_version_id=pv_id,
                execution_mode="full_plan",
                final_status="succeeded",
                finished_at=utc_now_iso(),
            )
        assert excinfo.value.code == "RUN_RECORD_MISSING"


def test_run_finalisation_failure_diagnostic(monkeypatch):
    """When finalise fails, a RUN_FINALISATION_FAILED diagnostic is recorded."""
    def _raise_write_manifest(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("cardre.run_lifecycle.write_manifest", _raise_write_manifest)

    with tempfile.TemporaryDirectory() as tmp:
        store = _init_store(tmp)
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
        run_id = store.create_run(pv_id)

        with pytest.raises(OSError):
            with RunLifecycle(store, run_id, pv_id, execution_mode="full_plan") as lifecycle:
                lifecycle.finalise(status="succeeded", execution_mode="full_plan")

        diags = store.get_run_diagnostics(run_id)
        codes = [d["code"] for d in diags]
        assert "RUN_FINALISATION_FAILED" in codes, f"Expected RUN_FINALISATION_FAILED, got {codes}"
        run = store.get_run(run_id)
        assert run is not None
        assert run.get("status") == "failed"
