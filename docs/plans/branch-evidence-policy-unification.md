# Branch Evidence Policy Unification — Implementation Plan

> **Audience:** an LLM executor with moderate code-navigation skill. This
> document is self-contained: read it, then make the edits in the order
> given. Each section lists the exact files, the change to make, and a
> code snippet to drop in. Where a step is marked **[TDD]**, write the
> failing test first, watch it fail, then implement until it passes.
>
> **Goal:** make `cardre/services/evidence_policy.py::EvidencePolicyService`
> the single source of truth for branch evidence policy. Remove the
> duplicated `cardre/services/branch_evidence.py::BranchEvidenceResolver`.
> Make sync and async branch execution use identical preparation,
> short-circuit, parent-resolution, and diagnostics logic.
>
> **Non-goals:** do not touch `cardre/staleness.py` (pure functions,
> shared utility). Do not touch `RunService`'s governance gate at
> `cardre/services/run_service.py:74`. Do not change the SQLite schema.
>
> **Do not commit** unless explicitly asked. Run `ruff check` after every
> file edit. Run the listed pytest commands after each phase.

---

## 0. Reference facts the executor must rely on

These are verified-correct as of the start of this plan. Do not
re-derive them; cite them.

- `EvidencePolicyService` lives at `cardre/services/evidence_policy.py`.
  It already implements (correctly, as the canonical source):
  - `prepare_branch_evidence(plan_version_id, branch_id, force=False) -> BranchRunEvidence`
    (signature order: **plan_version_id first, then branch_id**).
  - `resolve_parent_evidence(ctx: BranchRunEvidence, spec: StepSpec) -> None`
    (uses `self._store`; no `store` argument).
  - `check_branch_current(plan_version_id, branch_id) -> ShortCircuitResult`.
  - `check_to_node_current(plan_version_id, target_step_id, branch_id=None)`.
  - `_find_shared_evidence(...)` — emits diagnostics with
    `source="EvidencePolicyService._find_shared_evidence"`.
  - Owns dataclasses `BranchRunEvidence` and `ShortCircuitResult`.
- `BranchEvidenceResolver` at `cardre/services/branch_evidence.py` is a
  **near-identical duplicate** with three differences only:
  1. `prepare_branch_run(store, branch_id, plan_version_id, force)` —
     signature order is **store, branch_id, plan_version_id**.
  2. `resolve_parent_evidence(store, ctx, spec)` — takes a `store` arg.
  3. Diagnostic `source="BranchEvidenceResolver._find_shared_evidence"`.
  It owns its own `BranchRunContext` dataclass (same fields as
  `BranchRunEvidence`). It takes `executor` in `__init__` but never uses it.
- `PlanExecutor.run_branch` is at `cardre/executor.py:105`. Today it
  accepts `branch_ctx: Any = None` and, when `None`, falls back to
  `BranchEvidenceResolver(self).prepare_branch_run(...)`. It then
  constructs `BranchEvidenceResolver(self)` a **second** time at
  `executor.py:165` for `resolve_parent_evidence` in `before_execute`
  hooks. Both import sites are `from cardre.services.branch_evidence
  import BranchEvidenceResolver` at `executor.py:116` and `:164`.
- Sync path: `RunService._execute_sync` at
  `cardre/services/run_service.py:112` already calls
  `self._evidence.prepare_branch_evidence(...)` and passes
  `branch_ctx=ctx` into `executor.run_branch`. It short-circuits by
  finishing the placeholder run as `"cancelled"` and returning the
  existing run — but it emits **no** `RUN_SHORT_CIRCUITED` diagnostic.
- Async path: `RunWorker.execute` →
  `cardre/services/run_orchestrator.py:execute_run` →
  `executor.run_branch(...)` with **no** `branch_ctx`. The executor falls
  back to `BranchEvidenceResolver`. `execute_run` also re-checks
  `_governance_enabled()` at `run_orchestrator.py:26` (redundant with
  `RunService.run_plan:74`).
- Governance gate: `RunService.run_plan` raises `GovernanceNotEnabled`
  at `cardre/services/run_service.py:74` when `run_scope == "branch"`
  and `CARDRE_GOVERNANCE != 1`. `EvidencePolicyService` itself does
  **not** check governance — so unit tests of the policy service run
  fine with governance off.
- The `governance` pytest marker is registered at `pyproject.toml:68`.
  Governance-marked tests use both `@pytest.mark.governance` and an
  `os.environ.get("CARDRE_GOVERNANCE", "0")... not in ("1","true")`
  `skipif`. Pattern is copied verbatim below.
- Test helpers: `from tests.helpers import make_store` returns
  `(ProjectStore, Path)` with an initialized store in a temp dir.
- `BranchEvidenceError(code, message=..., context=..., status_code=...)`
  is defined at `cardre/errors.py:145`.
- The two existing characterization tests of `run_branch` at
  `tests/test_executor_branch_execution.py` use `pytestmark =
  pytest.mark.integration` (not governance) and call
  `executor.run_branch(...)` directly. They will need a `branch_ctx`
  argument after the refactor.

---

## 1. Phase ordering

Execute strictly in this order. Each phase ends with all tests green
and `ruff check` clean.

| Phase | What | TDD? | Tests added/changed |
|-------|------|------|---------------------|
| P1 | Add `test_branch_evidence_unified.py` **unit** tests against `EvidencePolicyService` (no RunService, no governance gate) | Yes (red→green) | new file, tests U1–U6 |
| P2 | Make `executor.run_branch` require `branch_ctx` (keyword-only) and use `EvidencePolicyService.resolve_parent_evidence`; delete both `BranchEvidenceResolver` imports from executor | Refactor (keep-green) | update `test_executor_branch_execution.py` |
| P3 | Update `execute_run` to prepare ctx via `EvidencePolicyService` and pass `branch_ctx`; drop governance re-check; drop the branch short-circuit block | Yes for the new wiring | update `test_run_orchestrator.py` |
| P4 | Add `RUN_SHORT_CIRCUITED` diagnostic to sync path in `_execute_sync` | Yes (red→green) | new tests in `test_branch_evidence_unified.py` (S1, S2) |
| P5 | Delete `cardre/services/branch_evidence.py`; update `tests/test_run_diagnostics.py` | Refactor (keep-green) | update imports/calls |
| P6 | Add the parity + diagnostics-source tests through `RunService` (sync & async) | Yes (red→green) | new tests in `test_branch_evidence_unified.py` (P1–P4) |
| P7 | Docs + CI | n/a | none |

Run after each phase (substitute the phase's relevant test files):

```
CARDRE_GOVERNANCE=0 python3 -m pytest tests/test_branch_evidence_unified.py tests/test_executor_branch_execution.py tests/test_run_diagnostics.py tests/test_branch_consistency.py tests/test_run_orchestrator.py -q --no-cov
CARDRE_GOVERNANCE=1 python3 -m pytest tests/test_branch_evidence_unified.py tests/test_executor_branch_execution.py tests/test_run_diagnostics.py tests/test_branch_consistency.py tests/test_run_orchestrator.py tests/test_sidecar_api.py::TestPhase4BranchingFlow -q --no-cov
ruff check
```

---

## 2. Phase P1 — Unit-test the unified policy service  **[TDD]**

Create `tests/test_branch_evidence_unified.py`. These tests exercise
`EvidencePolicyService` directly (no `RunService`, no governance gate),
so they run under `CARDRE_GOVERNANCE=0`. They should **all pass before
any production change**, because `EvidencePolicyService` already
implements the contract — the point of writing them first is to lock the
contract so the later refactor cannot regress it, and to give the
executor a target for P2.

> Why TDD here: the tests are the *specification* of the unified
> contract. Write them, run them, confirm they pass against the existing
> `EvidencePolicyService`. If any fails, **stop** — the service is not
> actually canonical and you must fix it before proceeding.

### Imports and shared fixtures to put at the top of the file

```python
"""Unified branch evidence policy tests.

EvidencePolicyService is the single source of truth for branch evidence
preparation, short-circuit, parent resolution, and diagnostics. These
tests pin the contract so the BranchEvidenceResolver removal cannot
regress it. They run under CARDRE_GOVERNANCE=0 because they call the
policy service directly (the governance gate lives in RunService, not
here).
"""
from __future__ import annotations

import uuid
from pathlib import Path

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
from cardre.executor import PlanExecutor
from cardre.registry import NodeRegistry
from cardre.services.evidence_policy import (
    BranchRunEvidence,
    EvidencePolicyService,
)
from cardre.store import ProjectStore

from tests.helpers import make_store


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
    store.save_run_step(RunStepRecord(
        run_step_id=str(uuid.uuid4()), run_id=run_id, step_id=step_id,
        plan_version_id=pv_id, status="succeeded",
        started_at=utc_now_iso(), finished_at=utc_now_iso(),
        input_artifact_ids=[], output_artifact_ids=[],
        execution_fingerprint={
            "params_hash": params_hash,
            "node_type": "cardre.test.ubr_source",
            "node_version": "1",
            "parent_output_logical_hashes_by_step": {},
            "output_artifact_logical_hashes": [],
        },
        warnings=[], errors=[],
    ))


def _make_branch(store: ProjectStore, pv_id: str, *,
                 shared: list[str], owned: list[str],
                 source_branch_id: str | None = None,
                 status: str = "active",
                 head_pv_id: str | None = None) -> str:
    """Create a branch + step map. head_pv_id defaults to pv_id."""
    branch_id = store.create_branch(
        project_id=store.get_plan_version(pv_id)["plan_id"]
            and _project_id_for(store, pv_id),
        plan_id=store.get_plan_version(pv_id)["plan_id"],
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
    # branch_step_map rows default source_branch_id to None; if a
    # source_branch_id is required, update the shared rows.
    if source_branch_id is not None:
        store._connect().execute(
            "UPDATE branch_step_map SET source_branch_id=? "
            "WHERE branch_id=? AND is_shared_upstream=1",
            (source_branch_id, branch_id),
        )
    return branch_id


def _project_id_for(store: ProjectStore, pv_id: str) -> str:
    pv = store.get_plan_version(pv_id)
    plan = store.get_plan(pv["plan_id"])
    return plan["project_id"]
```

> **Note on `_make_branch`:** `store.create_branch` requires
> `project_id`. The helper reads it from the plan. If your store's
> `create_branch` signature differs, adapt the helper — but keep the
> step-map creation calls identical, those are the part under test.

### Tests to write (drop verbatim into the file after the helpers)

**U1 — missing branch raises BRANCH_NOT_FOUND:**
```python
def test_u1_missing_branch_raises_branch_not_found(tmp_path):
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
```

**U2 — inactive branch raises BRANCH_INACTIVE:**
```python
def test_u2_inactive_branch_raises_branch_inactive(tmp_path):
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
```

**U3 — stale shared upstream raises SHARED_UPSTREAM_STALE:**
```python
def test_u3_stale_shared_upstream_raises_shared_upstream_stale(tmp_path):
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    shared = _step("shared")
    owned = _step("owned", parents=["shared"])
    pv_id = store.create_plan_version(plan_id, [shared, owned])
    # No prior run → shared step is stale.
    branch_id = _make_branch(store, pv_id, shared=["shared"], owned=["owned"])

    svc = EvidencePolicyService(store)
    with pytest.raises(BranchEvidenceError) as ei:
        svc.prepare_branch_evidence(pv_id, branch_id, force=False)
    assert ei.value.code == "SHARED_UPSTREAM_STALE"
    assert ei.value.status_code == 409
    assert "shared" in ei.value.context.get("stale_shared_steps", [])
```

**U4 — reusable baseline evidence emits INHERITED_BASELINE_EVIDENCE:**
```python
def test_u4_reusable_baseline_evidence_emits_inherited_baseline_diagnostic(tmp_path):
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    shared = _step("shared")
    owned = _step("owned", parents=["shared"])
    pv_id = store.create_plan_version(plan_id, [shared, owned])

    # Establish baseline (branch_id=None) evidence for the shared step.
    base_run = store.create_run(pv_id)  # branch_id omitted => baseline
    _seed_run_step(store, base_run, pv_id, "shared", shared.params_hash)
    store.finish_run(base_run, "succeeded")

    # Point the shared step map at a source_branch_id that has NO evidence,
    # so the lookup falls back to branch_id=None and emits the diagnostic.
    branch_id = _make_branch(store, pv_id, shared=["shared"], owned=["owned"],
                              source_branch_id="br_noevidence_xxxx")

    # The branch-owned step is stale (never run) so prepare should succeed
    # (only the shared staleness gate is hard-fail; the diagnostic is a
    # warning). Force=False: owned is stale → not short-circuit.
    svc = EvidencePolicyService(store)
    ctx = svc.prepare_branch_evidence(pv_id, branch_id, force=False)
    assert isinstance(ctx, BranchRunEvidence)
    codes = [d.code for d in ctx.diagnostics]
    assert "INHERITED_BASELINE_EVIDENCE" in codes, codes
    srcs = [d.source for d in ctx.diagnostics if d.code == "INHERITED_BASELINE_EVIDENCE"]
    assert all(s == "EvidencePolicyService._find_shared_evidence" for s in srcs), srcs
```

> If U4 fails because `compute_staleness` marks the shared step stale
> even with baseline evidence present, check that the baseline run's
> fingerprint `params_hash` exactly equals `shared.params_hash`
> (`json_logical_hash({})`). The helper seeds it correctly. If it still
> fails, the issue is that `compute_staleness` for a branch looks for
> branch-scoped runs first; baseline evidence is found via
> `_find_shared_evidence`, not via `compute_staleness`, so the gate
> should pass. Confirm by reading `evidence_policy.py:132-147`.

**U5 — branch-owned parent evidence resolved before child execution:**
```python
def test_u5_branch_owned_parent_evidence_resolved_before_child(tmp_path):
    """A branch-owned chain A->B: after prepare, A has no pre-seeded
    evidence; resolve_parent_evidence(ctx, B_spec) seeds A from the
    branch's latest successful run step for A."""
    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    a = _step("a")
    b = _step("b", parents=["a"])
    pv_id = store.create_plan_version(plan_id, [a, b])

    branch_id = _make_branch(store, pv_id, shared=[], owned=["a", "b"])

    # Prior successful branch run with a run step for A only.
    prev_run = store.create_run(pv_id, branch_id=branch_id)
    _seed_run_step(store, prev_run, pv_id, "a", a.params_hash)
    store.finish_run(prev_run, "succeeded")

    svc = EvidencePolicyService(store)
    # B is stale (never run) and A is current → prepare succeeds, A is
    # pre-seeded as current branch-owned evidence. This test focuses on
    # resolve_parent_evidence being a no-op-when-already-seeded; see U5b
    # for the not-seeded case.
    ctx = svc.prepare_branch_evidence(pv_id, branch_id, force=False)
    assert "a" in ctx.step_outputs, "current branch-owned A should be pre-seeded"

    # resolve_parent_evidence on B should be a no-op (A already present).
    svc.resolve_parent_evidence(ctx, b)
    assert "a" in ctx.step_outputs


def test_u5b_resolve_parent_evidence_seeds_missing_branch_owned_parent(tmp_path):
    """When a branch-owned parent is NOT pre-seeded (force=True path),
    resolve_parent_evidence seeds it from the branch's latest run step."""
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
    # force=True → stale_branch_step_ids = all owned; A is NOT pre-seeded.
    ctx = svc.prepare_branch_evidence(pv_id, branch_id, force=True)
    assert "a" not in ctx.step_outputs, "force=True must not pre-seed current owned steps"

    svc.resolve_parent_evidence(ctx, b)
    assert "a" in ctx.step_outputs, "resolve_parent_evidence must seed missing branch-owned A"
    assert "a" in ctx.run_step_records
```

**U6 — diagnostics source string is always EvidencePolicyService:**
```python
def test_u6_diagnostics_source_string_is_evidence_policy_service(tmp_path):
    """No diagnostic produced by EvidencePolicyService may carry a
    source referencing BranchEvidenceResolver."""
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
    # Also exercise resolve_parent_evidence to capture its diagnostics.
    svc.resolve_parent_evidence(ctx, owned)

    for d in ctx.diagnostics:
        assert d.source is not None
        assert "BranchEvidenceResolver" not in d.source, d.source
        assert d.source.startswith("EvidencePolicyService"), d.source
```

### Run P1

```
CARDRE_GOVERNANCE=0 python3 -m pytest tests/test_branch_evidence_unified.py -q --no-cov
```

All six must pass. If any fails against the **unmodified**
`EvidencePolicyService`, stop and fix the service before continuing —
the service is supposed to already be canonical.

---

## 3. Phase P2 — Make `executor.run_branch` a pure consumer  **[keep-green refactor]**

> Not TDD: this is a refactor that must keep P1's tests green while
> removing the executor's policy fallback. The characterization tests
> in `test_executor_branch_execution.py` will break on the new
> `branch_ctx` requirement; update them as part of this phase.

### 3.1 Edit `cardre/executor.py`

**Replace the whole `run_branch` method** (currently lines 105–192)
with the version below. Key changes:

- `branch_ctx` is **keyword-only and required** (no `= None` default,
  no `Any` — use `BranchRunEvidence`). Keep the import inside the
  method to avoid circulars if any, but prefer a top-of-file import.
- Remove both `from cardre.services.branch_evidence import
  BranchEvidenceResolver` lines (at `:116` and `:164`).
- Remove the `BranchEvidenceError` catch-and-diagnose block
  (`:123-135`) — preparation now happens upstream and the caller
  already handles `BranchEvidenceError`.
- Use `EvidencePolicyService(store).resolve_parent_evidence(ctx, spec)`
  in the `before_execute` hook.

```python
    def run_branch(
        self,
        store: ProjectStore,
        plan_version_id: str,
        branch_id: str,
        *,
        run_id: str | None = None,
        force: bool = False,
        branch_ctx: "BranchRunEvidence",
    ) -> str:
        from cardre.run_lifecycle import RunLifecycle
        from cardre.services.evidence_policy import EvidencePolicyService

        ctx = branch_ctx
        if not force and ctx.short_circuit_run_id is not None:
            return ctx.short_circuit_run_id

        execution_mode = "force" if force else "branch"
        with RunLifecycle.start(
            store, plan_version_id, run_id=run_id,
            branch_id=branch_id, execution_mode=execution_mode,
            force=force,
        ) as lifecycle:
            run_id = lifecycle.run_id

            for d in ctx.diagnostics:
                store.append_run_diagnostic(run_id, {
                    "code": d.code,
                    "message": d.message,
                    "severity": d.severity,
                    "category": "execution",
                    "source": d.source,
                    "run_id": run_id,
                    "plan_version_id": plan_version_id,
                    "branch_id": branch_id,
                    "context": d.context,
                })

            policy = EvidencePolicyService(store)
            actions: list[_StepAction] = []
            for spec in ctx.steps:
                if spec.step_id not in ctx.branch_owned_step_ids:
                    actions.append(_StepAction(spec=spec, action="skip"))
                elif not force and spec.step_id not in ctx.stale_branch_step_ids:
                    actions.append(_StepAction(spec=spec, action="skip"))
                else:
                    actions.append(_StepAction(
                        spec=spec, action="execute",
                        before_execute=lambda s=spec: policy.resolve_parent_evidence(ctx, s),
                    ))

            has_failure, outputs, records = self._execute_actions(
                store, actions, plan_version_id, run_id,
                step_outputs=ctx.step_outputs,
                run_step_records=ctx.run_step_records,
                branch_id=branch_id,
            )
            status = self._compute_final_status(has_failure, actions)

            lifecycle.finalise(
                status=status, execution_mode=execution_mode,
                branch_id=branch_id,
            )
        return run_id
```

> **Type hint:** if you add `from cardre.services.evidence_policy
> import BranchRunEvidence` at the top of `executor.py`, you may create
> an import cycle (`evidence_policy` imports `staleness` which imports
> `store`, not `executor` — actually safe). Verify with `python3 -c
> "import cardre.executor"`. If a cycle appears, keep the hint as a
> string literal `"BranchRunEvidence"` and do not import it.

### 3.2 Update `tests/test_executor_branch_execution.py`

Both `executor.run_branch(store, pv_id, branch_id, force=True)` calls
(at line 113 and line 196) must now pass a `branch_ctx` built via
`EvidencePolicyService`. Add this helper near the top of the file and
use it in both tests:

```python
from cardre.services.evidence_policy import EvidencePolicyService

def _branch_ctx(store, pv_id, branch_id, force=True):
    return EvidencePolicyService(store).prepare_branch_evidence(
        pv_id, branch_id, force=force,
    )
```

Then change:
```python
branch_run_id = executor.run_branch(store, pv_id, branch_id, force=True)
```
to:
```python
branch_run_id = executor.run_branch(
    store, pv_id, branch_id, force=True,
    branch_ctx=_branch_ctx(store, pv_id, branch_id, force=True),
)
```
in **both** `test_shared_upstream_evidence_is_reused` and
`test_branch_owned_chain_consumes_fresh_evidence`.

> These tests are `@pytest.mark.integration`, not governance-marked, so
> they run under `CARDRE_GOVERNANCE=0`. `EvidencePolicyService` does
> not check governance, so this is fine.

### 3.3 Run P2

```
CARDRE_GOVERNANCE=0 python3 -m pytest tests/test_executor_branch_execution.py tests/test_branch_evidence_unified.py -q --no-cov
ruff check
```

Both files must pass. `cardre/services/branch_evidence.py` still exists
but is now **unused by the executor**; do not delete it yet (P5).

---

## 4. Phase P3 — Wire `execute_run` to prepare ctx via the policy service  **[TDD for the new wiring]**

> TDD: update `test_run_orchestrator.py` first so the new contract is
> expressed as failing tests, then implement.

### 4.1 Update `tests/test_run_orchestrator.py`

**4.1.1** `FakeExecutor.run_branch` (line 33) gains a keyword-only
`branch_ctx` param it records:

```python
    branch_ctx_received: list = []
    def run_branch(self, store, plan_version_id, branch_id, *,
                   run_id=None, force=False, branch_ctx=None):
        self.calls.append(("branch", run_id))
        self.branch_ctx_received.append(branch_ctx)
        return self.result_id
```

(Add `branch_ctx_received: list = []` as a class attribute next to
`calls` at line 19, and reset it in `_patch_executor` at line 39 with
`FakeExecutor.branch_ctx_received = []`.)

**4.1.2** The two governance-marked branch tests must now stub
`EvidencePolicyService.prepare_branch_evidence` so `execute_run` can
build a ctx without hitting the real store. Add a fake ctx class and a
patcher:

```python
class _FakeCtx:
    short_circuit_run_id = None
    diagnostics: list = []

@pytest.fixture
def _stub_branch_policy(monkeypatch):
    """Make EvidencePolicyService.prepare_branch_evidence return a
    minimal ctx so execute_run's branch path is unit-testable."""
    monkeypatch.setattr(
        "cardre.services.evidence_policy.EvidencePolicyService.prepare_branch_evidence",
        lambda self, pv, bid, force=False: _FakeCtx(),
    )
    return _FakeCtx
```

Update `test_execute_run_returns_created_run_id_for_sync_branch`:
```python
@pytest.mark.governance
@pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)
def test_execute_run_returns_created_run_id_for_sync_branch(monkeypatch):
    _patch_executor(monkeypatch)
    _stub_branch_policy(monkeypatch)

    run_id = run_orchestrator.execute_run(
        DummyStore(), "pv", run_scope="branch", branch_id="branch-1",
    )

    assert run_id == "created-run"
    assert FakeExecutor.calls == [("branch", None)]
    assert FakeExecutor.branch_ctx_received == [pytest.approx(...)] or \
           len(FakeExecutor.branch_ctx_received) == 1
```

> The exact assertion is "the executor received a non-None branch_ctx".
> Use: `assert FakeExecutor.branch_ctx_received == [_FakeCtx()]` if the
> fake ctx is the same instance, or
> `assert len(FakeExecutor.branch_ctx_received) == 1 and
> FakeExecutor.branch_ctx_received[0] is not None`.

Update `test_execute_run_preserves_precreated_async_run_id_on_branch_short_circuit`
to set `_FakeCtx.short_circuit_run_id = "existing-successful-run"` on
the class before the call (and reset after), so `execute_run` short-
circuits without calling the executor:

```python
@pytest.mark.governance
@pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)
def test_execute_run_preserves_precreated_async_run_id_on_branch_short_circuit(monkeypatch):
    _patch_executor(monkeypatch)
    monkeypatch.setattr(
        "cardre.services.evidence_policy.EvidencePolicyService.prepare_branch_evidence",
        lambda self, pv, bid, force=False: _FakeCtx(),
    )
    _FakeCtx.short_circuit_run_id = "existing-successful-run"
    FakeExecutor.result_id = "existing-successful-run"
    store = DummyStore()

    run_id = run_orchestrator.execute_run(
        store, "pv", run_id="precreated-run",
        run_scope="branch", branch_id="branch-1",
    )

    assert run_id == "precreated-run"
    assert store.finished == [("precreated-run", "cancelled")]
    assert FakeExecutor.calls == [], "short-circuit must not call the executor"
    _FakeCtx.short_circuit_run_id = None  # reset for other tests
```

> The `DummyStore` already has `finish_run`. The new `execute_run` will
> also call `store.append_run_diagnostic` — add that method to
> `DummyStore`:
> ```python
> def append_run_diagnostic(self, run_id, diag): self.diagnostics.append((run_id, diag))
> ```
> and `self.diagnostics: list = []` in `__init__`.

### 4.2 Edit `cardre/services/run_orchestrator.py`

**Replace the whole `execute_run` body** with:

```python
def execute_run(
    store: ProjectStore,
    plan_version_id: str,
    run_id: str | None = None,
    run_scope: Literal["full_plan", "branch", "to_node"] = "full_plan",
    branch_id: str | None = None,
    target_step_id: str | None = None,
    force: bool = False,
) -> str:
    """Execute a run synchronously. Returns the run_id.

    Branch evidence is prepared here via EvidencePolicyService (the
    single source of truth) and passed into executor.run_branch as
    branch_ctx. The executor does not prepare evidence itself.
    """
    executor = PlanExecutor(NodeRegistry.with_defaults())

    if run_scope == "branch" and branch_id:
        from cardre.services.evidence_policy import EvidencePolicyService
        ctx = EvidencePolicyService(store).prepare_branch_evidence(
            plan_version_id, branch_id, force=force,
        )
        if not force and ctx.short_circuit_run_id is not None:
            if run_id is not None:
                store.append_run_diagnostic(run_id, {
                    "code": "RUN_SHORT_CIRCUITED",
                    "message": f"Run {run_id} short-circuited because branch has no stale steps (existing run {ctx.short_circuit_run_id})",
                    "severity": "info",
                    "category": "lifecycle",
                    "run_id": run_id,
                    "plan_version_id": plan_version_id,
                    "branch_id": branch_id,
                    "created_at": utc_now_iso(),
                })
                store.finish_run(run_id, "cancelled")
                return run_id
            return ctx.short_circuit_run_id
        result_id = executor.run_branch(
            store, plan_version_id, branch_id,
            run_id=run_id, force=force, branch_ctx=ctx,
        )
        return _handle_short_circuit(store, run_id, result_id,
                                      plan_version_id, branch_id)

    if run_scope == "to_node" and target_step_id:
        result_id = executor.run_to_node(
            store, plan_version_id, target_step_id,
            run_id=run_id, force=force, branch_id=branch_id,
        )
    else:
        result_id = executor.run_plan_version(
            store, plan_version_id, run_id=run_id, force=force,
        )
    return _handle_short_circuit(store, run_id, result_id,
                                  plan_version_id, branch_id)


def _handle_short_circuit(
    store: ProjectStore, run_id: str | None, result_id: str,
    plan_version_id: str, branch_id: str | None,
) -> str:
    """If the executor returned a different run_id, record the
    short-circuit and cancel the placeholder run."""
    if run_id is not None and result_id != run_id:
        store.append_run_diagnostic(run_id, {
            "code": "RUN_SHORT_CIRCUITED",
            "message": f"Run {run_id} short-circuited (existing run {result_id})",
            "severity": "info",
            "category": "lifecycle",
            "run_id": run_id,
            "plan_version_id": plan_version_id,
            "branch_id": branch_id,
            "created_at": utc_now_iso(),
        })
        store.finish_run(run_id, "cancelled")
        return run_id
    return result_id
```

> **What was removed:**
> - The `from cardre.store.project_store import _governance_enabled`
>   re-check and its `GovernanceNotEnabled` raise. The gate lives in
>   `RunService.run_plan:74`. (The import line at the top of the old
>   block goes away too.)
> - The inline branch short-circuit block that wrapped
>   `result_id != run_id` — now handled explicitly before calling the
>   executor, and the to_node/full_plan case uses the shared
>   `_handle_short_circuit` helper.

### 4.3 Run P3

```
CARDRE_GOVERNANCE=1 python3 -m pytest tests/test_run_orchestrator.py -q --no-cov
ruff check
```

The two governance-marked tests now pass via the new wiring. The
non-governance tests (`test_execute_run_returns_created_run_id_for_sync_full_plan`,
`..._to_node`, and the `_is_*_current` tests) are unaffected.

---

## 5. Phase P4 — Add `RUN_SHORT_CIRCUITED` diagnostic to the sync path  **[TDD]**

> TDD: write the parity tests first (they will fail because the sync
> path emits nothing), then add the diagnostic.

### 5.1 Add tests S1 and S2 to `tests/test_branch_evidence_unified.py`

These go through `RunService` with `sync=True`/`sync=False`, so they
need the governance gate satisfied. Mark them governance and gate with
the standard `skipif`.

```python
import os

_GOVERNANCE_SKIP = pytest.mark.skipif(
    os.environ.get("CARDRE_GOVERNANCE", "0").strip().lower() not in ("1", "true"),
    reason="requires CARDRE_GOVERNANCE=1",
)


@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_s1_sync_branch_short_circuit_emits_diagnostic(tmp_path, monkeypatch):
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

    # Prior successful branch run → A is current → short-circuit.
    prev = store.create_run(pv_id, branch_id=branch_id)
    _seed_run_step(store, prev, pv_id, "a", a.params_hash)
    store.finish_run(prev, "succeeded")

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="branch", branch_id=branch_id, sync=True)

    assert resp.run_id == prev
    diags = store.get_run_diagnostics(resp.run_id)
    # The existing run may already have no diagnostics; the placeholder
    # run is the one that got cancelled. Find the cancelled placeholder.
    runs = [r for r in store.list_runs(plan_version_id=pv_id)
            if r.get("status") == "cancelled"]
    assert len(runs) >= 1
    placeholder = runs[-1]
    ph_diags = store.get_run_diagnostics(placeholder["run_id"])
    codes = [d["code"] for d in ph_diags]
    assert "RUN_SHORT_CIRCUITED" in codes, codes


@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_s2_async_branch_short_circuit_parity(tmp_path, monkeypatch):
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
```

> **Why `SyncRunDispatcher` for both:** it runs the worker inline so the
> test is deterministic. The async *dispatch* path is exercised even
> with `sync=False` because `RunService._dispatch_async` builds a
> `RunRequest` and calls `dispatcher.dispatch`, and `SyncRunDispatcher`
> runs `RunWorker.execute` → `execute_run` on the current thread. This
> is the intended test seam (see `run_worker.py:251`).

Run these now — both should **fail** (S1 fails because sync emits no
diagnostic; S2 may already pass if P3 is in place, since async already
emitted the diagnostic).

### 5.2 Edit `cardre/services/run_service.py` (`_execute_sync`)

At `run_service.py:121-123`, the current sync short-circuit block is:

```python
                if not force and ctx.short_circuit_run_id is not None:
                    self._store.finish_run(run_id, "cancelled")
                    return self._build_response(ctx.short_circuit_run_id)
```

Replace with:

```python
                if not force and ctx.short_circuit_run_id is not None:
                    self._store.append_run_diagnostic(run_id, {
                        "code": "RUN_SHORT_CIRCUITED",
                        "message": f"Run {run_id} short-circuited because branch has no stale steps (existing run {ctx.short_circuit_run_id})",
                        "severity": "info",
                        "category": "lifecycle",
                        "run_id": run_id,
                        "plan_version_id": plan_version_id,
                        "branch_id": branch_id,
                        "created_at": utc_now_iso(),
                    })
                    self._store.finish_run(run_id, "cancelled")
                    return self._build_response(ctx.short_circuit_run_id)
```

> `utc_now_iso` is already imported at the top of `run_service.py`
> (line 13). `branch_id` is in scope.

### 5.3 Run P4

```
CARDRE_GOVERNANCE=1 python3 -m pytest tests/test_branch_evidence_unified.py -q --no-cov
ruff check
```

S1 and S2 both pass now. Re-run P1's unit tests to confirm no
regression:

```
CARDRE_GOVERNANCE=0 python3 -m pytest tests/test_branch_evidence_unified.py -q --no-cov
```

---

## 6. Phase P5 — Delete `cardre/services/branch_evidence.py`  **[keep-green refactor]**

### 6.1 Update `tests/test_run_diagnostics.py`

This file imports `BranchEvidenceResolver` at line 24 and uses it at
lines 146 and 193. Replace:

```python
from cardre.services.branch_evidence import BranchEvidenceResolver
```
with:
```python
from cardre.services.evidence_policy import EvidencePolicyService
```

At line 146 (`test_branch_version_mismatch_raises_typed_error`), replace:
```python
        resolver = BranchEvidenceResolver(PlanExecutor(NodeRegistry()))
        with pytest.raises(BranchEvidenceError) as excinfo:
            resolver.prepare_branch_run(store, branch_id, pv_id2, force=False)
```
with:
```python
        svc = EvidencePolicyService(store)
        with pytest.raises(BranchEvidenceError) as excinfo:
            svc.prepare_branch_evidence(pv_id2, branch_id, force=False)
```

At line 193 (`test_reuse_evidence_not_found_diagnostic`), replace:
```python
        resolver = BranchEvidenceResolver(PlanExecutor(NodeRegistry()))
        with pytest.raises(BranchEvidenceError) as excinfo:
            resolver.prepare_branch_run(store, branch_id, pv_id, force=False)
```
with:
```python
        svc = EvidencePolicyService(store)
        with pytest.raises(BranchEvidenceError) as excinfo:
            svc.prepare_branch_evidence(pv_id, branch_id, force=False)
```

> The asserted error codes (`BRANCH_VERSION_MISMATCH`,
> `SHARED_UPSTREAM_STALE`/`BRANCH_NO_OP_FAILED`) are identical between
> the two implementations, so no assertion changes are needed.

### 6.2 Delete the file

```
git rm cardre/services/branch_evidence.py
```

### 6.3 Grep for any remaining references

```
rg "BranchEvidenceResolver|branch_evidence" cardre/ sidecar/ tests/
```

Expected results: none in `cardre/` or `sidecar/`. If any test still
imports it, update it the same way as 6.1. (There should be none after
6.1 and P2.)

### 6.4 Run P5

```
CARDRE_GOVERNANCE=0 python3 -m pytest tests/test_run_diagnostics.py tests/test_executor_branch_execution.py tests/test_branch_evidence_unified.py tests/test_branch_consistency.py -q --no-cov
CARDRE_GOVERNANCE=1 python3 -m pytest tests/test_run_diagnostics.py tests/test_run_orchestrator.py -q --no-cov
ruff check
```

---

## 7. Phase P6 — Sync/async parity through `RunService`  **[TDD]**

> These are the integration tests that prove the two paths share one
> preparation routine. Write them, watch them pass (P1–P5 already make
> them pass), and keep them as regression guards.

Add to `tests/test_branch_evidence_unified.py`:

**P-integration-1 — sync uses the unified policy:**
```python
@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_p1_sync_branch_run_uses_unified_policy(tmp_path, monkeypatch):
    """RunService sync branch path must call
    EvidencePolicyService.prepare_branch_evidence exactly once and
    never reference BranchEvidenceResolver."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

    store, _ = make_store()
    pid = store.create_project("p")
    plan_id = store.create_plan(pid, "plan")
    shared = _step("shared")
    owned = _step("owned", parents=["shared"])
    pv_id = store.create_plan_version(plan_id, [shared, owned])
    # Baseline shared evidence so the run can proceed.
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
    assert len(calls) == 1, f"expected exactly one prep call, got {calls}"
    assert calls[0] == (pv_id, branch_id, False)
```

**P-integration-2 — async uses the unified policy and passes a ctx:**
```python
@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_p2_async_branch_run_uses_unified_policy_and_passes_ctx(tmp_path, monkeypatch):
    """RunService async branch path must (a) call
    EvidencePolicyService.prepare_branch_evidence (inside execute_run)
    and (b) pass a non-None branch_ctx into executor.run_branch."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher
    from cardre.executor import PlanExecutor

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
    def _spy_branch(self, store_, pv, bid, *, run_id=None, force=False, branch_ctx=None):
        ctx_received.append(branch_ctx)
        return real_run_branch(self, store_, pv, bid, run_id=run_id,
                                force=force, branch_ctx=branch_ctx)
    monkeypatch.setattr(PlanExecutor, "run_branch", _spy_branch)

    svc = RunService(store, dispatcher=SyncRunDispatcher())
    resp = svc.run_plan(pv_id, run_scope="branch", branch_id=branch_id, sync=False)

    assert resp.status == "succeeded"
    assert len(prep_calls) == 1, prep_calls
    assert len(ctx_received) == 1 and ctx_received[0] is not None, ctx_received
```

**P-integration-3 — branch-owned parent evidence resolved during execution:**
```python
@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_p3_branch_owned_chain_consumes_fresh_evidence_through_unified_path(tmp_path):
    """End-to-end: a branch-owned A->B chain run via RunService must
    have B consume A's output from the current branch run, not from any
    prior baseline. This is the same invariant as
    test_executor_branch_execution.test_branch_owned_chain_consumes_fresh_evidence
    but exercised through the unified sync dispatch path."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

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
```

**P-integration-4 — diagnostics source parity:**
```python
@_GOVERNANCE_SKIP
@pytest.mark.governance
def test_p4_diagnostics_source_parity_sync_vs_async(tmp_path, monkeypatch):
    """Both sync and async branch runs must record diagnostics whose
    source field references EvidencePolicyService, never
    BranchEvidenceResolver."""
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import SyncRunDispatcher

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
    # Both must carry the inherited-baseline warning for the shared step.
    sync_codes = {d["code"] for d in sync_diags}
    async_codes = {d["code"] for d in async_diags}
    assert "INHERITED_BASELINE_EVIDENCE" in sync_codes, sync_codes
    assert "INHERITED_BASELINE_EVIDENCE" in async_codes, async_codes
```

### 7.1 Run P6

```
CARDRE_GOVERNANCE=1 python3 -m pytest tests/test_branch_evidence_unified.py -q --no-cov
CARDRE_GOVERNANCE=1 python3 -m pytest tests/test_sidecar_api.py::TestPhase4BranchingFlow -q --no-cov
```

The Phase 4 E2E test must still pass (it runs the branch through the
HTTP layer → `RunService` → now the unified path).

---

## 8. Phase P7 — Docs and CI

### 8.1 Update `docs/architecture/execution-and-staleness.md`

Replace the "Branch run" bullet in the "Plan Executor" list with:

> - **Branch run**: executes only branch-owned steps, reusing evidence from the baseline for shared upstream steps. **Branch evidence policy (validation, staleness, short-circuit, shared/branch-owned evidence seeding, and parent evidence resolution) is owned by `cardre/services/evidence_policy.py::EvidencePolicyService` — the single source of truth.** `PlanExecutor.run_branch` is a pure consumer: it requires a `BranchRunEvidence` prepared upstream and does not resolve policy itself. Both sync (`RunService._execute_sync`) and async (`run_orchestrator.execute_run` → `RunWorker`) paths prepare evidence via `EvidencePolicyService` and pass it as `branch_ctx`.

Add a short "Staleness Detection" note is already present; no change
needed there.

### 8.2 Update `docs/reference/feature-status.md`

No content change required, but confirm the `CARDRE_GOVERNANCE` row
still accurately describes behavior. It does.

### 8.3 Add a governance CI job to `.github/workflows/ci.yml`

Insert this job after `test-python` (around line 80):

```yaml
  test-python-governance:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      CARDRE_GOVERNANCE: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
          cache-dependency-path: pyproject.toml
      - name: Install dependencies
        run: pip install -e ".[sidecar,test]"
      - name: Run governance-marked tests
        run: python3 -m pytest -m governance -q --tb=short --no-cov
```

> **Why:** today's `test-python` job runs with `CARDRE_GOVERNANCE` unset,
> so every `@pytest.mark.governance` test is **skipped** in CI. That
> means the sync/async drift this plan fixes was invisible in CI. The
> new job runs only the governance-marked tests with the flag on, so
> the parity tests (S1, S2, P-integration-*) actually execute.

### 8.4 Update `docs/plans/README.md` or `docs/README.md` index

If there is an index of plans, add a one-line entry for this file. If
not, skip.

---

## 9. Final verification commands

Run all of these from the repo root. All must pass.

```
# Lint
ruff check

# Direct unit tests (governance OFF — EvidencePolicyService has no gate)
CARDRE_GOVERNANCE=0 python3 -m pytest \
  tests/test_branch_evidence_unified.py \
  tests/test_executor_branch_execution.py \
  tests/test_run_diagnostics.py \
  tests/test_branch_consistency.py \
  -q --no-cov

# Governance-marked + integration tests (governance ON)
CARDRE_GOVERNANCE=1 python3 -m pytest \
  tests/test_branch_evidence_unified.py \
  tests/test_executor_branch_execution.py \
  tests/test_run_diagnostics.py \
  tests/test_branch_consistency.py \
  tests/test_run_orchestrator.py \
  tests/test_sidecar_api.py::TestPhase4BranchingFlow \
  -q --no-cov

# Full suite, both modes, to catch anything missed
CARDRE_GOVERNANCE=0 python3 -m pytest tests/ -q --tb=short
CARDRE_GOVERNANCE=1 python3 -m pytest -m governance -q --tb=short

# Doc / line-count guards (CI runs these)
python3 scripts/check-line-counts.py
python3 scripts/check_doc_references.py
python3 scripts/check-sidecar-naming.py
```

If the full `CARDRE_GOVERNANCE=0` run skips the governance tests (it
will, via `skipif`), that is correct. The `CARDRE_GOVERNANCE=1 -m
governance` run covers them.

---

## 10. Deliverables checklist (for the executor to self-verify before finishing)

- [ ] `cardre/services/branch_evidence.py` is **deleted** (`git rm`).
- [ ] `rg "BranchEvidenceResolver|BranchRunContext|branch_evidence"` in
      `cardre/` and `sidecar/` returns **zero** matches.
- [ ] `cardre/executor.py::run_branch` signature is
      `run_branch(self, store, plan_version_id, branch_id, *, run_id=None, force=False, branch_ctx)`.
- [ ] `cardre/executor.py` has **no** `from cardre.services.branch_evidence` line.
- [ ] `cardre/services/run_orchestrator.py::execute_run` calls
      `EvidencePolicyService.prepare_branch_evidence` and passes
      `branch_ctx=` into `executor.run_branch`.
- [ ] `cardre/services/run_orchestrator.py` no longer imports
      `_governance_enabled` or raises `GovernanceNotEnabled`.
- [ ] `cardre/services/run_service.py::_execute_sync` emits
      `RUN_SHORT_CIRCUITED` before finishing the placeholder as
      `cancelled`.
- [ ] `tests/test_branch_evidence_unified.py` exists with tests
      U1–U6, S1, S2, P1–P4 (13 tests).
- [ ] `tests/test_executor_branch_execution.py` and
      `tests/test_run_diagnostics.py` use `EvidencePolicyService`, not
      `BranchEvidenceResolver`.
- [ ] `tests/test_run_orchestrator.py`'s `FakeExecutor.run_branch`
      accepts keyword-only `branch_ctx`.
- [ ] `docs/architecture/execution-and-staleness.md` updated.
- [ ] `.github/workflows/ci.yml` has a `test-python-governance` job.
- [ ] All commands in section 9 pass.
- [ ] **Do not commit** unless the user explicitly asks.

---

## 11. Remaining limitations (to communicate to the user at the end)

- `EvidencePolicyService` still depends on `cardre.staleness.compute_staleness`
  as a shared pure-function utility; that boundary is intentional and
  unchanged.
- Removing `BranchEvidenceResolver` is a breaking change for any
  external importer of the class. The repo is pre-1.0 and the class was
  internal, so this is acceptable.
- The `RUN_SHORT_CIRCUITED` diagnostic on the sync path is a **new
  emission**. If any existing test asserted the *absence* of
  diagnostics on sync branch short-circuit, it will need updating —
  none was found during planning, but re-run the full suite to confirm.
- `run_orchestrator.dispatch_run_async` remains as a compatibility
  wrapper for tests that monkeypatch `execute_run`; it is unchanged.
- The `execute_run` governance re-check removal means a caller that
  invokes `execute_run` **directly** (bypassing `RunService`) with
  `run_scope="branch"` under `CARDRE_GOVERNANCE=0` will no longer get a
  `GovernanceNotEnabled` error from `execute_run` itself. In production
  this is unreachable (`RunService.run_plan` gates first). If direct
  callers exist in tests, they must be updated to either go through
  `RunService` or set `CARDRE_GOVERNANCE=1`.

---

## 12. TDD summary (where red-green-refactor applies)

| Phase | TDD? | What's red before, green after |
|-------|------|--------------------------------|
| P1 | Yes (lock-in) | U1–U6 should pass immediately; they pin the contract. A failure means `EvidencePolicyService` is not yet canonical — fix it before proceeding. |
| P2 | No | Refactor; P1 + characterization tests stay green. |
| P3 | Yes | `test_run_orchestrator.py` governance tests fail on the new `branch_ctx` kwarg and `prepare_branch_evidence` call until `execute_run` is rewired. |
| P4 | Yes | S1 fails (sync emits nothing) until the `RUN_SHORT_CIRCUITED` diagnostic is added to `_execute_sync`. |
| P5 | No | Refactor; all prior tests stay green after the deletion. |
| P6 | Yes (regression) | P-integration tests should pass immediately after P1–P5; they exist to prevent future drift. If any fails, the unification is incomplete. |
| P7 | n/a | Docs + CI. |