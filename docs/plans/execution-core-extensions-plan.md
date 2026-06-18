# Execution Core Extensions Plan

This plan captures the genuine gaps identified during review of the "Unify the
Cardre Execution Core" proposal. It builds on `PlanExecutor` and surrounding
modules at their current state (Phase 5A). No rewrite, no parallel module tree,
no term drift.

References:
- `docs/adr/0002-extend-plan-executor-not-rewrite.md` — the architectural
  decision this plan implements.

## Objective

Fill the eight gaps between the existing `PlanExecutor` and what the rewrite
proposal correctly identified as missing, without regressing on dual hashing,
computed staleness, role enforcement, or the settled step/run vocabulary.

## Scope

| # | Task | Effort | Risk |
|---|---|---|---|---|
| 1 | Structured error categories | Small | Low |
| 2 | `to_node` execution mode | Small | Low |
| 3 | `force` rerun mode | Small | Low |
| 4 | Staleness endpoint | Small | Low |
| 5 | Live cancellation (`CancellationToken` + `POST .../cancel`) | Small | Medium |
| 6 | Run manifest artifact | Small | Low |
| 7 | Node executor contract test suite | Medium | Low |

Tasks 1–7 are this delivery. A future ADR covers the tighter node contract
(see §Future Work at the end of this document).

## Task 1: Structured error categories

**Why**: Today every error is an ad-hoc `{code, message, traceback}` dict
(`cardre/executor.py:238`). Named exception types with standard fields
(`node_id`, `recoverable`, `details`) make error handling and API responses
predictable.

**What**: Create `cardre/errors.py` with:

```python
class CardreError(Exception):
    message: str
    details: dict | None
    recoverable: bool

class GraphValidationError(CardreError): ...
class MissingInputArtifactError(CardreError): ...
class ParameterValidationError(CardreError): ...
class ArtifactReadError(CardreError): ...
class ArtifactWriteError(CardreError): ...
class NodeExecutionError(CardreError): ...
class ContractViolationError(CardreError): ...
class CancellationError(CardreError): ...
```

Wire into `PlanExecutor._execute_step` so the existing `error_entry` dict
includes the category name. Existing exception classes (`RoleAccessError`,
`EvidenceError` and subclasses) stay where they are — this is additive.

**Files**:
- **New**: `cardre/errors.py`
- **Edit**: `cardre/executor.py` (wrap errors in `_execute_step`)

**Acceptance**:
- Every error raised during execution carries a named category.
- API error responses include the category in the detail payload.
- Existing tests continue to pass (error dicts gain a `category` field).

---

## Task 2: `to_node` execution mode

**Why**: Users need to run everything required to produce a specific downstream
node's output without running unrelated terminal nodes. The rewrite plan calls
this "run to node."

**Scope**: The scope of a `run_to_node` run is the **target step + all its
transitive ancestors** (the ancestor closure). Steps not in the closure are
out of scope — they are neither run nor reused. This is different from a
full-plan run (all steps in scope) and different from a branch run (branch
steps in scope, shared upstream reused).

**What**: Add `PlanExecutor.run_to_node(store, plan_version_id, target_step_id)`
that:
1. Loads plan-version steps and validates topology.
2. Computes the ancestor closure of `target_step_id` via
   `PlanExecutor.find_ancestors` (already exists, `cardre/executor.py:598`).
3. Topologically sorts the ancestor set.
4. For each ancestor, checks staleness. Reuses non-stale steps (seeding their
   outputs from the latest successful run), executes stale ones.
5. Creates run-step records for the ancestor closure only. Steps outside the
   closure get no run-step record in this run.
6. Finishes the run.

**Manifest semantics**: The run manifest for a `run_to_node` run records:
- `execution_mode: "to_node"`
- `target_step_id`: the step the user requested
- `in_scope_step_ids`: the ancestor closure — every step the run could have
  touched
- Per-step records for every step in the ancestor closure, with the usual
  status/reason information
- Steps outside the ancestor closure are *not* listed in the manifest — they
  were explicitly excluded from scope, not forgotten

The run `status` reflects the outcome of the in-scope steps only.

**Files**:
- **Edit**: `cardre/executor.py` (add method `run_to_node`)

**Acceptance**:
- `run_to_node("validation_metrics")` after changing `split` params executes
  split through validation only; a sibling profile path is untouched.
- `run_to_node("validation_metrics")` with no changes reuses everything,
  short-circuits.
- Run record `status` is `succeeded` even though other terminal nodes were
  never run (they were out of scope, not failures).
- `test_run_to_node` passes with German Credit fixture.

---

## Task 3: `force` rerun mode

**Why**: Users need to regenerate all artifacts from scratch — equivalent to
"ignore all cached outputs." Useful for reproducibility audits and debugging.

**What**: Add `force: bool = False` parameter to `run_plan_version`,
`run_branch`, and `run_to_node`. When `True`, the staleness check is bypassed
entirely — every in-scope step is executed unconditionally, regardless of
whether its fingerprint matches the last successful run.

`force` is an execution-time flag, not part of the step's semantic identity.
The execution fingerprint is computed **identically** to a normal run: same
`params_hash`, same `input_artifact_logical_hashes`, same `node_version`, etc.
Two runs of the same plan version — one normal, one forced — produce the same
fingerprints for each step. The difference is only whether the runner chose to
reuse an existing artifact or regenerate it. The manifest records
`execution_mode: "force"` so the fact of forced execution is still auditable,
but fingerprints remain reproducible.

**Files**:
- **Edit**: `cardre/executor.py` (`run_plan_version`, `run_branch`,
  `run_to_node`)

**Acceptance**:
- `force=True` on an unchanged plan regenerates every in-scope artifact from
  scratch (new artifact IDs, same logical hashes for deterministic nodes).
- `force=False` on unchanged plan reuses all steps (short-circuits).
- Step execution fingerprints are identical between a normal run and a forced
  run on the same plan version.
- `test_force_rerun` passes with German Credit fixture.

---

## Task 4: Staleness endpoint

**Why**: The UI needs a discrete staleness query for polling status panels.
The rewrite plan proposes `GET /projects/{project_id}/branches/{branch_id}/staleness`.
`compute_staleness()` exists in `cardre/staleness.py` — this is just an API
wrapper.

**What**: Add a route or extend the existing branch/plan route to return a
per-step staleness map:

```
GET /plans/{plan_id}/versions/{plan_version_id}/staleness?branch_id=...
```

Response shape (a list, not a dict, for JSON-friendliness):

```json
{
  "plan_version_id": "...",
  "nodes": [
    {"step_id": "import", "is_stale": false, "reason": null},
    {"step_id": "binning", "is_stale": true, "reason": "upstream_artifact_changed"}
  ]
}
```

The `reason` field is derived from `step_is_stale`'s internal checks (params
changed / upstream changed / node-version changed / never run).

**Files**:
- **Edit**: `cardre/staleness.py` (add `staleness_detail()` returning reasons)
- **Edit**: `sidecar/routes/plans.py` or `sidecar/routes/branches.py` (add
  staleness sub-route)

**Acceptance**:
- `GET .../staleness` returns `is_stale: true` for nodes whose upstream params
  changed.
- `is_stale: false` for untouched nodes after a successful run.
- Reason strings enumerate the actual cause.

---

## Task 5: Live cancellation

**Why**: Long-running nodes (OptBinning on large datasets, hyperparameter
tuning) need interruption. The rewrite plan proposes a `CancellationToken`
and a cancel endpoint.

**What**:

1. **`CancellationToken`** — a thin wrapper around `threading.Event`:

```python
# cardre/cancellation.py
class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
    def cancel(self) -> None: self._event.set()
    def is_cancelled(self) -> bool: return self._event.is_set()
    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise CancellationError("Run was cancelled")
```

2. Store tokens keyed by `run_id` in a module-level dict
   (`_cancellation_tokens: dict[str, CancellationToken]`).

3. Add `cancellation_token: CancellationToken | None` to `ExecutionContext`
   (`cardre/audit.py:128`).

4. In `PlanExecutor.run_plan_version` and `run_branch`, create a token, store
   it, pass it into the context, and remove it in `finally`.

5. Between each step iteration, call `token.raise_if_cancelled()`. Nodes that
   do long-running work should optionally check the token too.

6. Add `POST /runs/{run_id}/cancel` to `sidecar/routes/runs.py` — looks up
   the token and calls `token.cancel()`, sets run status to `cancelling`.

7. `PlanExecutor` transitions run status to `cancelled` on `CancellationError`.

**Files**:
- **New**: `cardre/cancellation.py`
- **Edit**: `cardre/audit.py` (add `cancellation_token` field to `ExecutionContext`)
- **Edit**: `cardre/executor.py` (create/store/check/remove token; handle
  `CancellationError`)
- **Edit**: `sidecar/routes/runs.py` (add cancel endpoint)

**Acceptance**:
- `POST .../cancel` sets run status to `cancelled`.
- Cancelled run does not mark incomplete step outputs as latest.
- Run steps for completed nodes remain in the run.
- `test_cancellation` passes: start a run with a long-sleep dummy node, cancel
  mid-execution, verify status and step records.

---

## Task 6: Run manifest artifact

**Why**: The rewrite plan's §16 "Run manifest" is a good idea. Today the
manifest data lives in `run_steps` + `execution_fingerprint_json` but isn't
packaged as a queryable artifact. An explicit manifest simplifies audit export,
replay validation, and branch comparison.

**What**: At the end of `run_plan_version`, `run_branch`, and `run_to_node`,
after all steps complete (succeeded or failed), generate a manifest artifact via
`write_json_artifact`:

```python
{
  "manifest_version": "1.0.0",
  "run_id": "...",
  "plan_version_id": "...",
  "branch_id": "...",
  "started_at": "...",
  "finished_at": "...",
  "status": "succeeded" | "failed" | "cancelled",
  "execution_mode": "full" | "branch" | "to_node" | "force",
  "cardre_version": "0.1.0",
  "steps": [
    {
      "step_id": "...",
      "node_type": "...",
      "node_version": "...",
      "status": "succeeded" | "failed" | "reused" | "cancelled",
      "params_hash": "...",
      "input_artifact_ids": ["..."],
      "output_artifact_ids": ["..."],
      "execution_fingerprint": {...},
      "warnings": [...],
      "errors": [...],
    }
  ]
}
```

The manifest artifact gets an `artifact_type = "run_manifest"`, `role = "audit"`,
and is registered in the artifact store. Its `artifact_id` is stored on the run
record (add `manifest_artifact_id` column if wanted, or derive from
`artifact_type` lookup later — the artifact already has `run_id` in metadata).

**Files**:
- **Edit**: `cardre/executor.py` (`run_plan_version`, `run_branch` — call
  `_generate_manifest` before `finish_run`)
- **Edit**: `sidecar/routes/runs.py` (optional: add `GET .../manifest` route
  that reads the manifest artifact)

**Acceptance**:
- Every completed run produces a `run_manifest` artifact.
- Manifest contains every step record for that run.
- `GET .../manifest` returns the assembled JSON.
- Golden-manifest test: fixed dataset + fixed params produce stable manifest
  (same step order, same node types, same param hashes, same artifact lineage).

---

## Task 7: Node executor contract test suite

**Why**: The rewrite plan's §20.2 proposes every `NodeType` pass a common
contract test: validates params, resolves required inputs, returns declared
output types, does not write artifacts directly, returns structured warnings,
fails with structured errors. This catches contract drift early.

**What**: Add a pytest base class or parametrized fixture in
`tests/contracts/test_node_contracts.py`:

```python
class NodeContractTestBase:
    # Subclasses define:
    node_type: type[NodeType]
    good_params: dict
    bad_params: dict
    valid_context_factory: Callable[[], ExecutionContext]
    expected_output_roles: set[str]

    def test_validates_good_params(self): ...
    def test_rejects_bad_params(self): ...
    def test_returns_declared_output_roles(self): ...
    def test_output_artifacts_are_registered(self): ...
    def test_metrics_are_json_serializable(self): ...
    def test_warnings_are_structured(self): ...
    def test_fails_with_structured_errors_on_bad_inputs(self): ...
```

Register one concrete subclass per node type. Use a shared German Credit
fixture for the context.

**Files**:
- **New**: `tests/contracts/__init__.py`
- **New**: `tests/contracts/test_node_contracts.py`
- **New**: `tests/contracts/conftest.py` (shared ExecutionContext factory)

**Acceptance**:
- Every `NodeType` registered in `NodeRegistry.with_defaults()` has a
  corresponding contract test subclass.
- `test_validates_good_params` passes for every node.
- `test_returns_declared_output_roles` passes for every node.
- `test_output_artifacts_are_registered` passes for every node.
- Contract test failures are easy to diagnose (which node, which assertion).

---

## Task 8: Tighter node contract (runner persists outputs)

**⚠ Not part of this delivery. Requires its own ADR and migration plan.**

The rewrite plan's §10 proposes a stricter contract: nodes return typed
payloads, and the runner persists them via `write_json_artifact` /
`write_parquet_artifact`. Today nodes call those helpers themselves through
`cardre/artifacts.py`. This is already centralised but the runner-owned
persistence model would be a cleaner contract. It is a ~40-node migration,
outside the scope of tasks 1–7.

This will be proposed in a separate ADR after tasks 1–7 ship. Do not start
before the core is stable and contract tests are green.

---

## Implementation Sequence

```
 Task 1: Structured errors          (no deps)
    │
    ▼
 Task 2: to_node mode               (no deps)
 Task 3: force rerun mode           (no deps)
    │
    ▼
 Task 4: Staleness endpoint         (depends on staleness.py, no other deps)
    │
    ▼
 Task 5: Live cancellation          (depends on Executor having token hook)
    │
    ▼
 Task 6: Run manifest artifact      (depends on structured run completion)
    │
    ▼
 Task 7: Node contract tests        (depends on structured errors + manifest)
```

Tasks 2, 3, and 4 are independent of each other and can be developed in
parallel PRs after task 1 lands.

## Files Changed

| File | Tasks | Change type |
|---|---|---|
| `cardre/errors.py` | 1 | **New** |
| `cardre/cancellation.py` | 5 | **New** |
| `cardre/executor.py` | 1, 2, 3, 5, 6 | **Edit** |
| `cardre/audit.py` | 5 | **Edit** (ExecutionContext field) |
| `cardre/staleness.py` | 4 | **Edit** (reason strings) |
| `sidecar/routes/runs.py` | 4 (or plans), 5, 6 | **Edit** |
| `sidecar/routes/branches.py` or `plans.py` | 4 | **Edit** |
| `tests/contracts/` | 7 | **New** |
| `tests/test_executor.py` | 2, 3, 5, 6 | **Edit** (add cases) |
| `tests/test_sidecar_api.py` | 4, 5, 6 | **Edit** (add cases) |

## What stays untouched

- `cardre/store.py` — schema is sufficient; no new tables.
- `cardre/registy.py` — no competing registry.
- `cardre/topology.py` — reused by `run_to_node`.
- `cardre/evidence.py` — no change.
- `cardre/nodes/` — no change.
- `cardre/engine/binning/` — no change.
- `frontend/` — new endpoints consumed via regenerated OpenAPI types.

## Acceptance Criteria

After tasks 1–7 ship:

1. Errors from `PlanExecutor` carry a structured `category` field.
2. `run_to_node(target_step_id)` executes only the ancestor closure; steps
   outside scope are neither run nor recorded as failures.
3. `run_plan_version(force=True)` regenerates all artifacts; step fingerprints
   are identical to a normal run with the same params and inputs.
4. `GET .../staleness` returns per-step staleness with reasons.
5. `POST .../cancel` stops a mid-flight run; incomplete steps are not
   marked as latest outputs.
6. Every run produces a `run_manifest` artifact recording the execution mode,
   scope, and per-step status/reason.
7. Every `NodeType` passes the shared contract test suite.
8. All existing tests continue to pass.
9. No new DB tables, no term drift, no parallel module tree.
