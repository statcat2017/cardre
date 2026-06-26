# Batch D — Run Currentness and Orchestrator-Owned Submission

## Goal

Make branch/to-node no-op detection, async dispatch, diagnostics, and final
run status consistent by moving currentness preflight and run creation out of
the route and into a `RunCurrentnessService` and an orchestrator-owned
`submit_run`.

## Context you must read first

- `sidecar/routes/runs.py:59` — `_is_branch_current`. Swallows all
  non-`CardreError` exceptions at `:71`.
- `sidecar/routes/runs.py:76` — `_is_to_node_current`. Returns any existing
  successful run for the plan version when the closure is non-stale
  (`:90-92`), not necessarily a run matching the requested branch/to-node
  scope.
- `sidecar/routes/runs.py:127` — `run_plan`. The route owns governance check
  (`:137-155`), sync execution (`:158-196`), async preflight (`:202-211`),
  stale-run recovery (`:214-216`), placeholder creation (`:218`), and thread
  creation (`:221-234`). Thread-start failure at `:235` marks the run failed
  with a `CardreError` but no run diagnostic.
- `cardre/services/run_orchestrator.py:25` — `execute_run`. Short-circuit
  handling at `:48-60` cancels the placeholder run with a
  `RUN_SHORT_CIRCUITED` diagnostic when the executor returns a different run
  id.
- `cardre/services/run_orchestrator.py:82` — `dispatch_run_async`. Owns async
  failure diagnostics (`:104-125`).
- `cardre/staleness.py:44` — `compute_staleness` and the across-plan
  substitution at `step_is_stale:75`.
- `cardre/services/branch_evidence.py:113` — `prepare_branch_run` computes
  branch staleness then separately checks shared-upstream staleness.
- `cardre/step_graph.py` — `ancestor_closure` (used by `_is_to_node_current`).
- `tests/test_staleness.py`, `tests/test_run_diagnostics.py`,
  `tests/test_executor_branch_execution.py` — existing coverage.
- `docs/plans/consolidation-launch-sprint/README.md` — cross-cutting rules.

## Prerequisite

Batch A must land first. `RunCurrentnessService` consumes
`EvidenceResolver` to avoid re-implementing the across-plan substitution
that `step_is_stale` does today.

## Changes

### 1. Create `RunCurrentnessService`

New file `cardre/services/run_currentness_service.py`.

```python
from dataclasses import dataclass
from typing import Literal
from cardre.errors import Diagnostic
from cardre.store import ProjectStore


@dataclass
class CurrentnessResult:
    run_scope: Literal["full_plan", "branch", "to_node"]
    existing_run_id: str | None
    stale_step_ids: list[str]
    blocked_shared_steps: list[str]
    reason_by_step: dict[str, str]
    evidence_sources: dict[str, str]
    diagnostics: list[Diagnostic]


class RunCurrentnessService:
    def __init__(self, store: ProjectStore) -> None: ...

    def evaluate_currentness(
        self,
        plan_version_id: str,
        run_scope: Literal["full_plan", "branch", "to_node"],
        branch_id: str | None,
        target_step_id: str | None,
        force: bool,
    ) -> CurrentnessResult: ...
```

Behavior:

- `run_scope="branch"` — mirrors `prepare_branch_run` staleness: branch-owned
  staleness via `compute_staleness(branch_id=branch_id)`, shared-upstream
  staleness via `EvidenceResolver` (policy
  `source_branch_then_full_then_plan`). When all branch-owned steps are
  current and a prior successful branch run exists,
  `existing_run_id` is set. `blocked_shared_steps` lists any stale shared
  upstream (the current `SHARED_UPSTREAM_STALE` raise becomes a blocker
  list, not an exception, so the route can decide).
- `run_scope="to_node"` — computes ancestor closure via
  `step_graph.ancestor_closure`, then staleness for the closure only.
  `existing_run_id` is set only when a prior successful run exists **for the
  requested scope** (branch-scoped when `branch_id` is set, full-plan
  otherwise). This fixes the `_is_to_node_current` bug that returns an
  unrelated full run.
- `run_scope="full_plan"` — full-plan staleness; `existing_run_id` from the
  latest successful full-plan run.

`reason_by_step` uses the same reasons as `_staleness_reason`
  (`never_run`, `params_changed`, `node_version_changed`,
  `upstream_artifact_changed`, `upstream_stale`) but computed from the
  evidence `EvidenceResolver` actually selected, not the collected map that
  `staleness_detail` uses. This fixes the misleading-reason bug.

`evidence_sources` records which policy produced each step's evidence
  (`branch`, `full_plan`, `across_plan`, `latest_plan_run`, `missing`) so
  the frontend can show "inherited from branch X" consistently.

### 2. Move preflight out of the route

In `sidecar/routes/runs.py`, delete `_is_branch_current:59` and
`_is_to_node_current:76`. Replace the preflight calls at `:202-211` with
`RunCurrentnessService.evaluate_currentness`. When
`result.existing_run_id` is set and `force` is false, return that run.
When `result.blocked_shared_steps` is non-empty, raise
`SHARED_UPSTREAM_STALE` (preserve the current `BranchEvidenceError` shape so
existing callers and tests stay green).

### 3. Add `submit_run` to the orchestrator

In `cardre/services/run_orchestrator.py`, add:

```python
@dataclass
class SubmittedRun:
    existing_run_id: str | None
    created_run_id: str | None
    status: str
    diagnostics: list[dict]


def submit_run(
    project_path: str,
    plan_version_id: str,
    run_scope: str,
    branch_id: str | None,
    target_step_id: str | None,
    force: bool,
    sync: bool,
) -> SubmittedRun: ...
```

`submit_run` owns:

1. Governance check (currently in the route at `:137-155` and in
   `execute_run:37-43` — consolidate here, keep `execute_run` raising
   `GovernanceNotEnabled` for the sync path).
2. Currentness preflight via `RunCurrentnessService`. Short-circuit returns
   `SubmittedRun(existing_run_id=..., created_run_id=None, status="succeeded",
   diagnostics=[])`.
3. Stale-run recovery (currently `_maybe_recover_stale_run` in the route).
4. Placeholder run creation (`store.create_run`).
5. Execution: sync calls `execute_run` inline; async spawns the thread with
   `dispatch_run_async`.
6. Thread-start failure diagnostics: on failure, append a
   `RUN_DISPATCH_FAILED` run diagnostic **and** fail the run. Today the route
   raises a `CardreError` but writes no run diagnostic, so the run shows
   "failed" with no reason.
7. Return `SubmittedRun` with the final status and diagnostics.

### 4. Slim the route to DTO mapping

`run_plan` in `sidecar/routes/runs.py` becomes:

```python
def run_plan(body: RunRequest, sync: bool = Query(default=False)):
    store = get_store_for_project(body.project_id)
    pv = store.get_plan_version(body.plan_version_id)
    if pv is None:
        raise HTTPException(status_code=404, detail={
            "code": "PLAN_VERSION_NOT_FOUND", "message": "Plan version not found"})
    submitted = submit_run(
        project_path=str(store.root),
        plan_version_id=body.plan_version_id,
        run_scope=body.run_scope,
        branch_id=body.branch_id,
        target_step_id=body.target_step_id,
        force=body.force,
        sync=sync,
    )
    run_id = submitted.existing_run_id or submitted.created_run_id
    return _build_run_response(store, run_id)
```

The sync `ValueError` parsing at `:176-185` is removed — Batch E converts
services to `CardreError`, and the central handler covers it. If Batch E has
not landed yet, keep a temporary `ValueError` → `CardreError` bridge here and
delete it in Batch E.

## Tests

### New: `tests/test_run_currentness_service.py`

- Current branch with prior successful branch run → `existing_run_id` set,
  `stale_step_ids` empty.
- Current branch with only full-plan evidence → `existing_run_id` from
  full-plan run, `evidence_sources` records `full_plan`.
- Current branch with inherited source-branch evidence →
  `evidence_sources` records `across_plan`, diagnostics include
  `INHERITED_BASELINE_EVIDENCE`.
- To-node current closure but no prior matching run → `existing_run_id` is
  `None` (not an unrelated full run). This is the regression test for the
  `_is_to_node_current` bug.
- To-node with a prior branch-scoped run → `existing_run_id` set.
- `reason_by_step` for a step resolved via across-plan fallback says
  `upstream_stale` only when the fallback is also stale — not `never_run`
  when across-plan evidence exists.

### New: `tests/test_submit_run.py`

- Async thread-start failure writes a `RUN_DISPATCH_FAILED` run diagnostic
  and fails the run (today it fails with no diagnostic).
- Branch no-op returns the prior successful run via `existing_run_id`, no
  placeholder created.
- Sync and async branch no-op paths produce the same final status and
  diagnostics for the same inputs.
- To-node currentness does not return an unrelated run.
- Governance disabled + branch scope → `GovernanceNotEnabled` raised by
  `submit_run`, not the route.

### Update: `tests/test_run_diagnostics.py`

- Assert a `RUN_DISPATCH_FAILED` diagnostic appears on the run when thread
  start fails.

## Verification

```bash
pytest tests/test_run_currentness_service.py \
       tests/test_submit_run.py \
       tests/test_staleness.py \
       tests/test_run_diagnostics.py \
       tests/test_executor_branch_execution.py
```

## Definition of done

1. `RunCurrentnessService` exists and evaluates branch/to-node/full currentness
   in one place.
2. `_is_branch_current` and `_is_to_node_current` are deleted from the route.
3. `submit_run` owns governance, preflight, placeholder creation, dispatch,
   and thread-start failure diagnostics.
4. `run_plan` is DTO mapping only.
5. Sync and async branch no-op paths produce equivalent status and
   diagnostics.
6. To-node currentness never returns an unrelated full run.
7. All listed tests are green.

## Files touched

- `cardre/services/run_currentness_service.py` (new)
- `cardre/services/run_orchestrator.py`
- `sidecar/routes/runs.py`
- `tests/test_run_currentness_service.py` (new)
- `tests/test_submit_run.py` (new)
- `tests/test_run_diagnostics.py` (updated)

## Depends on

Batch A (EvidenceResolver)

## Unblocks

Batch H (parity tests include currentness).