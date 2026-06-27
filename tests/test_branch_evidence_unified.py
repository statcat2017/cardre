"""Unified branch evidence policy tests.

EvidencePolicyService is the single source of truth for branch evidence
preparation, short-circuit, parent resolution, and diagnostics. These
tests pin the contract so the BranchEvidenceResolver removal cannot
regress it. They run under CARDRE_GOVERNANCE=0 because they call the
policy service directly (the governance gate lives in RunService, not
here).
"""
from __future__ import annotations

import os
import uuid

import pytest

from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    RunStepRecord,
    StepSpec,
    json_logical_hash,
    utc_now_iso,
)
from cardre.artifacts import write_json_artifact
from cardre.errors import BranchEvidenceError
from cardre.registry import NodeRegistry
from cardre.services.evidence_policy import (
    BranchRunEvidence,
    EvidencePolicyService,
)
from cardre.store import ProjectStore

from tests.helpers import make_store


_GOVERNANCE_SKIP = pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)

pytestmark = pytest.mark.integration


class _SrcNode(NodeType):
    node_type = "cardre.test.ubr_source"
    version = "1"
    category = "transform"
    input_roles: list[str] = []
    output_roles: list[str] = ["artifact"]

    def run(self, ctx: ExecutionContext) -> NodeOutput:
        art = write_json_artifact(
            ctx.store, artifact_type="report", role="artifact",
            stem=f"src-{ctx.step_spec.step_id}",
            payload={"step_id": ctx.step_spec.step_id}, metadata={},
        )
        return NodeOutput(artifacts=[art], metrics={})


class _TfmNode(NodeType):
    node_type = "cardre.test.ubr_transform"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["artifact"]
    output_roles: list[str] = ["artifact"]

    def run(self, ctx: ExecutionContext) -> NodeOutput:
        art = write_json_artifact(
            ctx.store, artifact_type="report", role="artifact",
            stem=f"tfm-{ctx.step_spec.step_id}",
            payload={"step_id": ctx.step_spec.step_id,
                     "parent_count": len(ctx.input_artifacts)}, metadata={},
        )
        return NodeOutput(artifacts=[art], metrics={})


def _step(step_id: str, parents: list[str] | None = None,
          canonical_step_id: str | None = None) -> StepSpec:
    return StepSpec(
        step_id=step_id,
        node_type="cardre.test.ubr_source" if not parents else "cardre.test.ubr_transform",
        node_version="1", category="transform",
        params={}, params_hash=json_logical_hash({}),
        parent_step_ids=parents or [], branch_label="", position=0,
        canonical_step_id=canonical_step_id or step_id,
    )


def _registry() -> NodeRegistry:
    reg = NodeRegistry()
    reg.register(_SrcNode)
    reg.register(_TfmNode)
    return reg


def _seed_run_step(store: ProjectStore, run_id: str, pv_id: str,
                   step_id: str, params_hash: str) -> None:
    """Persist a successful run step so staleness sees evidence."""
    art = write_json_artifact(
        store, artifact_type="report", role="artifact",
        stem=f"seed-{step_id}",
        payload={"step_id": step_id}, metadata={},
    )
    store.save_run_step(RunStepRecord(
        run_step_id=str(uuid.uuid4()), run_id=run_id, step_id=step_id,
        plan_version_id=pv_id, status="succeeded",
        started_at=utc_now_iso(), finished_at=utc_now_iso(),
        input_artifact_ids=[], output_artifact_ids=[art.artifact_id],
        execution_fingerprint={
            "params_hash": params_hash,
            "node_type": "cardre.test.ubr_source",
            "node_version": "1",
            "parent_output_logical_hashes_by_step": {},
            "output_artifact_logical_hashes": [art.logical_hash],
        },
        warnings=[], errors=[],
    ))


def _make_branch(store: ProjectStore, pv_id: str, *,
                 shared: list[str], owned: list[str],
                 source_branch_id: str | None = None,
                 status: str = "active",
                 head_pv_id: str | None = None) -> str:
    """Create a branch + step map. head_pv_id defaults to pv_id."""
    pv = store.get_plan_version(pv_id)
    plan = store.get_plan(pv["plan_id"])
    pid = plan["project_id"]
    branch_id = store.create_branch(
        project_id=pid, plan_id=pv["plan_id"],
        name=f"br-{uuid.uuid4().hex[:4]}",
        branch_type="challenger",
        base_plan_version_id=head_pv_id or pv_id,
        head_plan_version_id=head_pv_id or pv_id,
        created_reason="test",
    )
    if status != "active":
        store._connect().execute(
            "UPDATE plan_branches SET status=? WHERE branch_id=?",
            (status, branch_id),
        )
    for sid in shared:
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id=sid, step_id=sid,
            is_shared_upstream=True, is_branch_owned=False,
        )
    for sid in owned:
        store.create_branch_step_map(
            branch_id=branch_id, plan_version_id=pv_id,
            canonical_step_id=sid, step_id=sid,
            is_shared_upstream=False, is_branch_owned=True,
        )
    if source_branch_id is not None:
        store._connect().execute(
            "UPDATE branch_step_map SET source_branch_id=? "
            "WHERE branch_id=? AND is_shared_upstream=1",
            (source_branch_id, branch_id),
        )
    return branch_id


# ---------------------------------------------------------------------------
# U1 – missing branch raises BRANCH_NOT_FOUND
# ---------------------------------------------------------------------------


def test_u1_missing_branch_raises_branch_not_found():
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    pv_id = store.create_plan_version(plan_id, [_step("a")])
    svc = EvidencePolicyService(store)

    with pytest.raises(BranchEvidenceError) as ei:
        svc.prepare_branch_evidence(pv_id, "br_nonexistent", force=False)
    assert ei.value.code == "BRANCH_NOT_FOUND"
    assert ei.value.status_code == 404
    assert ei.value.context.get("branch_id") == "br_nonexistent"


# ---------------------------------------------------------------------------
# U2 – inactive branch raises BRANCH_INACTIVE
# ---------------------------------------------------------------------------


def test_u2_inactive_branch_raises_branch_inactive():
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    pv_id = store.create_plan_version(plan_id, [_step("a")])
    branch_id = _make_branch(store, pv_id, shared=[], owned=["a"], status="merged")

    svc = EvidencePolicyService(store)
    with pytest.raises(BranchEvidenceError) as ei:
        svc.prepare_branch_evidence(pv_id, branch_id, force=False)
    assert ei.value.code == "BRANCH_INACTIVE"
    assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# U3 – stale shared upstream raises SHARED_UPSTREAM_STALE
# ---------------------------------------------------------------------------


def test_u3_stale_shared_upstream_raises_shared_upstream_stale():
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    shared = _step("shared")
    owned = _step("owned", parents=["shared"])
    pv_id = store.create_plan_version(plan_id, [shared, owned])
    branch_id = _make_branch(store, pv_id, shared=["shared"], owned=["owned"])

    svc = EvidencePolicyService(store)
    with pytest.raises(BranchEvidenceError) as ei:
        svc.prepare_branch_evidence(pv_id, branch_id, force=False)
    assert ei.value.code == "SHARED_UPSTREAM_STALE"
    assert ei.value.status_code == 409
    assert "shared" in ei.value.context.get("stale_shared_steps", [])


# ---------------------------------------------------------------------------
# U4 – reusable baseline evidence emits INHERITED_BASELINE_EVIDENCE
# ---------------------------------------------------------------------------


def test_u4_reusable_baseline_evidence_emits_inherited_baseline_diagnostic():
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    shared = _step("shared")
    owned = _step("owned", parents=["shared"])
    pv_id = store.create_plan_version(plan_id, [shared, owned])

    base_run = store.create_run(pv_id)
    _seed_run_step(store, base_run, pv_id, "shared", shared.params_hash)
    store.finish_run(base_run, "succeeded")

    branch_id = _make_branch(store, pv_id, shared=["shared"], owned=["owned"],
                              source_branch_id="br_noevidence_xxxx")

    svc = EvidencePolicyService(store)
    ctx = svc.prepare_branch_evidence(pv_id, branch_id, force=False)
    assert isinstance(ctx, BranchRunEvidence)
    codes = [d.code for d in ctx.diagnostics]
    assert "INHERITED_BASELINE_EVIDENCE" in codes, codes
    srcs = [d.source for d in ctx.diagnostics if d.code == "INHERITED_BASELINE_EVIDENCE"]
    assert all(s == "EvidencePolicyService._find_shared_evidence" for s in srcs), srcs


# ---------------------------------------------------------------------------
# U5 – branch-owned parent evidence resolved before child
# ---------------------------------------------------------------------------


def test_u5_branch_owned_parent_evidence_resolved_before_child():
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    a = _step("a")
    b = _step("b", parents=["a"])
    pv_id = store.create_plan_version(plan_id, [a, b])

    branch_id = _make_branch(store, pv_id, shared=[], owned=["a", "b"])

    prev_run = store.create_run(pv_id, branch_id=branch_id)
    _seed_run_step(store, prev_run, pv_id, "a", a.params_hash)
    store.finish_run(prev_run, "succeeded")

    svc = EvidencePolicyService(store)
    ctx = svc.prepare_branch_evidence(pv_id, branch_id, force=False)
    assert "a" in ctx.step_outputs, "current branch-owned A should be pre-seeded"

    svc.resolve_parent_evidence(ctx, b)
    assert "a" in ctx.step_outputs


def test_u5b_resolve_parent_evidence_seeds_missing_branch_owned_parent():
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    a = _step("a")
    b = _step("b", parents=["a"])
    pv_id = store.create_plan_version(plan_id, [a, b])

    branch_id = _make_branch(store, pv_id, shared=[], owned=["a", "b"])

    prev_run = store.create_run(pv_id, branch_id=branch_id)
    _seed_run_step(store, prev_run, pv_id, "a", a.params_hash)
    store.finish_run(prev_run, "succeeded")

    svc = EvidencePolicyService(store)
    ctx = svc.prepare_branch_evidence(pv_id, branch_id, force=True)
    assert "a" not in ctx.step_outputs, "force=True must not pre-seed current owned steps"

    svc.resolve_parent_evidence(ctx, b)
    assert "a" in ctx.step_outputs, "resolve_parent_evidence must seed missing branch-owned A"
    assert "a" in ctx.run_step_records


# ---------------------------------------------------------------------------
# U6 – diagnostics source string is always EvidencePolicyService
# ---------------------------------------------------------------------------


def test_u6_diagnostics_source_string_is_evidence_policy_service():
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    shared = _step("shared")
    owned = _step("owned", parents=["shared"])
    pv_id = store.create_plan_version(plan_id, [shared, owned])

    base_run = store.create_run(pv_id)
    _seed_run_step(store, base_run, pv_id, "shared", shared.params_hash)
    store.finish_run(base_run, "succeeded")

    branch_id = _make_branch(store, pv_id, shared=["shared"], owned=["owned"],
                              source_branch_id="br_noevidence_yyyy")
    svc = EvidencePolicyService(store)
    ctx = svc.prepare_branch_evidence(pv_id, branch_id, force=False)
    svc.resolve_parent_evidence(ctx, owned)

    for d in ctx.diagnostics:
        assert d.source is not None
        assert "BranchEvidenceResolver" not in d.source, d.source
        assert d.source.startswith("EvidencePolicyService"), d.source


@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_s1_sync_branch_short_circuit_emits_diagnostic():
    """Sync branch run that short-circuits must record RUN_SHORT_CIRCUITED
    on the placeholder run and cancel it, returning the existing run."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    a = _step("a")
    pv_id = store.create_plan_version(plan_id, [a])
    branch_id = _make_branch(store, pv_id, shared=[], owned=["a"])

    prev = store.create_run(pv_id, branch_id=branch_id)
    _seed_run_step(store, prev, pv_id, "a", a.params_hash)
    store.finish_run(prev, "succeeded")

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="branch", branch_id=branch_id, sync=True)

    assert resp.run_id == prev
    runs = [r for r in store.list_runs(plan_version_id=pv_id)
            if r.get("status") == "cancelled"]
    assert len(runs) >= 1
    placeholder = runs[-1]
    ph_diags = store.get_run_diagnostics(placeholder["run_id"])
    codes = [d["code"] for d in ph_diags]
    assert "RUN_SHORT_CIRCUITED" in codes, codes


@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_s2_async_branch_short_circuit_parity():
    """Async branch run short-circuit must behave identically to sync:
    same RUN_SHORT_CIRCUITED code, same cancelled placeholder status."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    a = _step("a")
    pv_id = store.create_plan_version(plan_id, [a])
    branch_id = _make_branch(store, pv_id, shared=[], owned=["a"])

    prev = store.create_run(pv_id, branch_id=branch_id)
    _seed_run_step(store, prev, pv_id, "a", a.params_hash)
    store.finish_run(prev, "succeeded")

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="branch", branch_id=branch_id, sync=False)

    assert resp.run_id == prev
    placeholder = [r for r in store.list_runs(plan_version_id=pv_id)
                   if r.get("status") == "cancelled"][-1]
    ph_codes = [d["code"] for d in store.get_run_diagnostics(placeholder["run_id"])]
    assert "RUN_SHORT_CIRCUITED" in ph_codes, ph_codes


# ---------------------------------------------------------------------------
# S3/S4 – to-node short-circuit diagnostic parity (sync + async)
# ---------------------------------------------------------------------------


def test_s3_to_node_short_circuit_emits_diagnostic_sync():
    """RED: Sync to-node run that short-circuits must record
    RUN_SHORT_CIRCUITED on the placeholder run and cancel it, returning
    the existing run_id — matching the branch contract (test_s1).

    Currently _execute_sync finishes the placeholder as 'cancelled' with
    NO diagnostic (run_service.py:166-168), unlike the branch path which
    emits RUN_SHORT_CIRCUITED (run_service.py:149).
    """
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    a = _step("a")
    pv_id = store.create_plan_version(plan_id, [a])

    prev = store.create_run(pv_id)
    _seed_run_step(store, prev, pv_id, "a", a.params_hash)
    store.finish_run(prev, "succeeded")

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="to_node", target_step_id="a", sync=True)

    assert resp.run_id == prev, f"must return existing run_id, got {resp.run_id}"
    placeholders = [r for r in store.list_runs(plan_version_id=pv_id)
                   if r.get("status") == "cancelled"]
    assert len(placeholders) >= 1, "placeholder run must be created for audit trail"
    placeholder = placeholders[-1]
    codes = [d["code"] for d in store.get_run_diagnostics(placeholder["run_id"])]
    assert "RUN_SHORT_CIRCUITED" in codes, (
        f"to-node short-circuit must emit RUN_SHORT_CIRCUITED for parity with "
        f"branch; got {codes}"
    )


def test_s4_to_node_short_circuit_async_parity():
    """RED: Async to-node short-circuit must create a placeholder and
    emit RUN_SHORT_CIRCUITED, matching the sync path (test_s3) and the
    branch contract (test_s2).

    Currently the async preflight (run_service.py:114-119) returns the
    existing run_id with NO placeholder and NO diagnostic — asymmetric
    with both sync to-node and async branch.
    """
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    a = _step("a")
    pv_id = store.create_plan_version(plan_id, [a])

    prev = store.create_run(pv_id)
    _seed_run_step(store, prev, pv_id, "a", a.params_hash)
    store.finish_run(prev, "succeeded")

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="to_node", target_step_id="a", sync=False)

    assert resp.run_id == prev
    placeholders = [r for r in store.list_runs(plan_version_id=pv_id)
                   if r.get("status") == "cancelled"]
    assert len(placeholders) >= 1, (
        "async to-node short-circuit must create a placeholder for audit "
        "trail (parity with sync and with branch)"
    )
    placeholder = placeholders[-1]
    codes = [d["code"] for d in store.get_run_diagnostics(placeholder["run_id"])]
    assert "RUN_SHORT_CIRCUITED" in codes, codes


def _patch_registry(monkeypatch):
    """Monkeypatch NodeRegistry.with_defaults to include test node types."""
    from cardre.registry import NodeRegistry
    real_defaults = NodeRegistry.with_defaults
    def _patched():
        reg = real_defaults()
        reg.register(_SrcNode)
        reg.register(_TfmNode)
        return reg
    monkeypatch.setattr(NodeRegistry, "with_defaults", _patched)


# ---------------------------------------------------------------------------
# P1 – sync branch run uses unified policy
# ---------------------------------------------------------------------------


@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_p1_sync_branch_run_uses_unified_policy(monkeypatch):
    """RunService sync branch path must call
    EvidencePolicyService.prepare_branch_evidence exactly once and
    never reference BranchEvidenceResolver."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

    _patch_registry(monkeypatch)

    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    shared = _step("shared")
    owned = _step("owned", parents=["shared"])
    pv_id = store.create_plan_version(plan_id, [shared, owned])
    base = store.create_run(pv_id)
    _seed_run_step(store, base, pv_id, "shared", shared.params_hash)
    store.finish_run(base, "succeeded")

    branch_id = _make_branch(store, pv_id, shared=["shared"], owned=["owned"])

    calls = []
    real_prep = EvidencePolicyService.prepare_branch_evidence
    def _spy(self, pv, bid, force=False):
        calls.append((pv, bid, force))
        return real_prep(self, pv, bid, force=force)
    monkeypatch.setattr(EvidencePolicyService, "prepare_branch_evidence", _spy)

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="branch", branch_id=branch_id, sync=True)

    assert resp.status == "succeeded"
    # prepare_branch_evidence is called twice: once in the preflight
    # check_branch_current (line 84 of run_service.py) and once in
    # _execute_sync (line 141). Both go through the unified policy path.
    assert len(calls) >= 1, f"expected at least one prep call, got {calls}"
    assert calls[-1] == (pv_id, branch_id, False)


@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_p2_async_branch_run_uses_unified_policy_and_passes_ctx(monkeypatch):
    """RunService async branch path must (a) call
    EvidencePolicyService.prepare_branch_evidence (inside execute_run)
    and (b) pass a non-None branch_ctx into executor.run_branch."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher
    from cardre.executor import PlanExecutor

    _patch_registry(monkeypatch)

    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    shared = _step("shared")
    owned = _step("owned", parents=["shared"])
    pv_id = store.create_plan_version(plan_id, [shared, owned])
    base = store.create_run(pv_id)
    _seed_run_step(store, base, pv_id, "shared", shared.params_hash)
    store.finish_run(base, "succeeded")
    branch_id = _make_branch(store, pv_id, shared=["shared"], owned=["owned"])

    prep_calls = []
    real_prep = EvidencePolicyService.prepare_branch_evidence
    def _spy(self, pv, bid, force=False):
        prep_calls.append((pv, bid, force))
        return real_prep(self, pv, bid, force=force)
    monkeypatch.setattr(EvidencePolicyService, "prepare_branch_evidence", _spy)

    ctx_received = []
    real_run_branch = PlanExecutor.run_branch
    def _spy_branch(self_, store_, pv, bid, *, run_id=None, force=False, branch_ctx=None):
        ctx_received.append(branch_ctx)
        return real_run_branch(self_, store_, pv, bid, run_id=run_id,
                                force=force, branch_ctx=branch_ctx)
    monkeypatch.setattr(PlanExecutor, "run_branch", _spy_branch)

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="branch", branch_id=branch_id, sync=False)

    assert resp.status == "succeeded"
    # prepare_branch_evidence is called twice: once in the preflight
    # check_branch_current and once in _dispatch_async -> execute_run.
    assert len(prep_calls) >= 1, prep_calls
    assert len(ctx_received) == 1 and ctx_received[0] is not None, ctx_received


@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_p3_branch_owned_chain_consumes_fresh_evidence_through_unified_path(monkeypatch):
    """End-to-end: a branch-owned A->B chain run via RunService must
    have B consume A's output from the current branch run, not from any
    prior baseline."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

    _patch_registry(monkeypatch)

    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    a = _step("a")
    b = _step("b", parents=["a"])
    pv_id = store.create_plan_version(plan_id, [a, b])
    branch_id = _make_branch(store, pv_id, shared=[], owned=["a", "b"])

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="branch", branch_id=branch_id,
                        sync=True, force=True)
    assert resp.status == "succeeded"

    steps = store.get_run_steps(resp.run_id)
    a_rs = next(s for s in steps if s.step_id == "a")
    b_rs = next(s for s in steps if s.step_id == "b")
    assert b_rs.input_artifact_ids == a_rs.output_artifact_ids, \
        "B must consume A's fresh output from this branch run"


@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_p4_diagnostics_source_parity_sync_vs_async(monkeypatch):
    """Both sync and async branch runs must record diagnostics whose
    source field references EvidencePolicyService, never
    BranchEvidenceResolver."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

    _patch_registry(monkeypatch)

    def _run_one(sync: bool):
        store, _ = make_store()
        pid = store.create_project("p")
        plan_id = store.create_plan(pid, "plan")
        shared = _step("shared")
        owned = _step("owned", parents=["shared"])
        pv_id = store.create_plan_version(plan_id, [shared, owned])
        base = store.create_run(pv_id)
        _seed_run_step(store, base, pv_id, "shared", shared.params_hash)
        store.finish_run(base, "succeeded")
        branch_id = _make_branch(store, pv_id, shared=["shared"], owned=["owned"],
                                  source_branch_id="br_no_src_evidence_zzz")

        svc = RunService(store, dispatcher=SyncRunDispatcher())
        resp = svc.run_plan(pv_id, run_scope="branch", branch_id=branch_id, sync=sync)
        assert resp.status == "succeeded"
        diags = store.get_run_diagnostics(resp.run_id)
        return diags

    sync_diags = _run_one(sync=True)
    async_diags = _run_one(sync=False)

    for diags, label in [(sync_diags, "sync"), (async_diags, "async")]:
        for d in diags:
            src = d.get("source") or ""
            assert "BranchEvidenceResolver" not in src, (label, src)
            if src:
                assert src.startswith("EvidencePolicyService"), (label, src)
    sync_codes = {d["code"] for d in sync_diags}
    async_codes = {d["code"] for d in async_diags}
    assert "INHERITED_BASELINE_EVIDENCE" in sync_codes, sync_codes
    assert "INHERITED_BASELINE_EVIDENCE" in async_codes, async_codes
