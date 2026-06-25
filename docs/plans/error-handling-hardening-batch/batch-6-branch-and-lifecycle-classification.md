# Batch 6 — Branch errors + executor/lifecycle classification

## Goal

Replace the `ValueError("CODE: ...")` pattern in `branch_service.py` and
`branch_evidence.py` with typed `CardreError` subclasses, route them
through the Batch 0 envelope, persist run diagnostics for branch pre-run
failures in both sync and async paths, complete the executor category
map, add the reuse-miss diagnostic, and finalise the `write_manifest` /
`finalise` / `_execute_step` recording guards from Batch 2 for the
branch-specific paths.

This is the final batch; it closes ST-1, EXE-1, EXE-2, EXE-3, BR-1,
BR-2, BR-3, and completes the lifecycle classification work.

## Findings addressed

- **BR-1** — `branch_service.py` `ValueError` → typed
  `BranchValidationError`; route normalises to 4xx structured error.
- **BR-2** — `branch_evidence.py` async pre-run failures raise typed
  `BranchEvidenceError`; run diagnostics written in the async path.
- **BR-3** — missing parent evidence lookup records diagnostic context
  listing the lookup policies tried (branch, source branch, full plan,
  across-plan).
- **EXE-1** — `RoleAccessError` / `LeakageProtectionError` added to the
  executor category map.
- **EXE-2** — branch preparation failure (pre-`RunLifecycle.start`) writes
  a run diagnostic in both sync and async paths.
- **EXE-3** — `_reuse_run_step` returning `None` records a non-blocking
  `REUSE_EVIDENCE_NOT_FOUND` diagnostic before execution.
- **LIFE-1** (completion) — `write_manifest` fails hard on missing run
  record (Batch 2 did the raise; this batch verifies the branch path).
- **ST-1** (completion) — `validate_topology` raises
  `GraphValidationError`; branch-evidence routes it through the typed
  hierarchy.

## Context you must read first

- `cardre/services/branch_service.py:34-138` — `create_branch` raises
  `ValueError("BRANCH_POINT_NOT_ALLOWED: ...")`, `ValueError(
  "BRANCH_TYPE_MISMATCH: ...")`, etc. in ~10 places.
- `cardre/services/branch_evidence.py:58-164` — `prepare_branch_run`
  raises `ValueError` at lines 76, 78, 82, 133, 161 with embedded codes.
- `cardre/services/branch_evidence.py:233-263` — `_find_shared_evidence`
  returns `None` quietly when all lookup policies miss (BR-3).
- `cardre/executor.py:106-158` — `run_branch` calls
  `prepare_branch_run` **before** `RunLifecycle.start`, so a
  `BranchEvidenceError` raises with no run record yet in the sync path.
- `cardre/executor.py:257-274` — `_execute_actions` reuse branch calls
  `_reuse_run_step` and falls back to execute when it returns `None`
  (EXE-3).
- `cardre/executor.py:376-427` — `_execute_step` category map at 381-396;
  `RoleAccessError`/`LeakageProtectionError` (from Batch 0) must be added
  **before** the `CardreError` catch-all.
- `cardre/executor.py:690-741` — `_reuse_run_step` returns `None` when no
  reusable evidence exists.
- `cardre/services/run_orchestrator.py:60-84` — `dispatch_run_async` now
  records `RUN_ASYNC_FAILED` (Batch 2); this batch ensures the
  `BranchEvidenceError` code is preserved in the diagnostic.
- `sidecar/routes/branches.py:110-139` — `create_branch` does not catch
  `ValueError`; currently bubbles to the generic handler.
- `sidecar/routes/runs.py:21-30` — `_is_branch_current` preflight
  swallows `ValueError`/`Exception`; Batch 2 left the swallow in place
  because the thread path records diagnostics.
- `cardre/topology.py:12-58` — `validate_topology` now raises
  `GraphValidationError` (Batch 3).
- `cardre/errors.py` — `BranchValidationError`, `BranchEvidenceError`,
  `GraphValidationError`, `RoleAccessError`, `LeakageProtectionError`
  (from Batch 0).
- `docs/plans/error-handling-hardening-batch/README.md` — cross-cutting
  rules; note the sync-vs-async branch failure asymmetry documented in
  the sprint README.

## Changes

### 1. `cardre/services/branch_service.py` — typed `BranchValidationError`

Replace each `raise ValueError("CODE: message")` with
`raise BranchValidationError("CODE", message="...", context={...})`.
`BranchValidationError` (declared in Batch 0) has `status_code=400`.

Map each site:

| Line | Current `ValueError` code | New call (sketch) |
|------|---------------------------|-------------------|
| 58 | `BRANCH_POINT_NOT_ALLOWED` | `BranchValidationError("BRANCH_POINT_NOT_ALLOWED", message=..., context={"branch_point_step_id": branch_point_step_id})` |
| 65 | `BRANCH_TYPE_MISMATCH` | context includes `branch_point_step_id`, `expected_type`, `got_type` |
| 71 | `BRANCH_NAME_REQUIRED` | context includes `plan_id` |
| 74 | `BRANCH_REASON_REQUIRED` | context includes `plan_id`, `name` |
| 78 | `SEGMENT_FILTER_REQUIRED` | context includes `branch_type` |
| 87 | `PLAN_NOT_FOUND` | context includes `plan_id` |
| 89 | `PLAN_PROJECT_MISMATCH` | context includes `plan_id`, `project_id`, `actual_project_id` |
| 94 | `BASE_BRANCH_NOT_FOUND` | context includes `base_branch_id` |
| 99 | `STALE_BASE_VERSION` | context includes `base_plan_version_id`, `head_pv_id` |
| 105 | `BASE_BRANCH_INACTIVE` | context includes `base_branch_id`, `status` |
| 115 | `BRANCH_POINT_NOT_IN_PLAN` | context includes `branch_point_step_id`, `head_pv_id` |
| 126 | `REJECT_INFERENCE_CHALLENGER_MISSING_SAMPLE_DEF` | context includes `plan_id` |
| 133 | `REJECT_INFERENCE_CHALLENGER_REQUIRES_TTD` | context includes `sample_domain` |

Also convert the `_validate_segment_filter_rules` `ValueError`s (lines
261, 270, 272, 275, 279, 283) to `BranchValidationError` with the same
codes, adding `context.column` / `context.operator` where applicable.

### 2. `cardre/services/branch_evidence.py` — typed `BranchEvidenceError`

`prepare_branch_run` raises `ValueError` at 76, 78, 82, 133, 161. Replace
each with `BranchEvidenceError(code, message=..., context={...})`.
`BranchEvidenceError` (Batch 0) has `status_code=409` (conflict-like:
state mismatch) for the version/stale cases; use `status_code=400` for
the not-found/inactive cases. Decide per-site:

| Line | Code | `status_code` |
|------|------|---------------|
| 76 | `BRANCH_NOT_FOUND` | 404 |
| 78 | `BRANCH_INACTIVE` | 400 |
| 82 | `BRANCH_VERSION_MISMATCH` | 409 |
| 133 | `SHARED_UPSTREAM_STALE` | 409 |
| 161 | `BRANCH_NO_OP_FAILED` | 409 |

`BranchEvidenceError` can carry a per-instance `status_code` (override
the class default) — set it at construction. The Batch 0 handler reads
`exc.status_code`.

### 3. BR-2 — async branch pre-run failure writes a run diagnostic

`prepare_branch_run` raises before `RunLifecycle.start` in `run_branch`
(`executor.py:117`). In the **async** path, the run was already created
by `runs.py:139 store.create_run(...)` before dispatch, so a run record
exists. `dispatch_run_async` (Batch 2) catches `Exception` and records
`RUN_ASYNC_FAILED`. Enhance it to preserve the typed code:

```python
except Exception as exc:
    code = getattr(exc, "code", None) or "RUN_ASYNC_FAILED"
    diag = {
        "code": code,
        "message": str(exc) or exc.__class__.__name__,
        "severity": "error",
        "category": exc.__class__.__name__,
        "exception_type": exc.__class__.__name__,
        "run_id": run_id,
        "plan_version_id": plan_version_id,
        "branch_id": branch_id,
        "context": getattr(exc, "context", {}),
        "traceback": traceback.format_exc(),
        "created_at": utc_now_iso(),
    }
    store.append_run_diagnostic(run_id, diag)
    _fail_run_if_running(store, run_id)
```

So a `SHARED_UPSTREAM_STALE` failure records `code="SHARED_UPSTREAM_STALE"`
with the stale step ids in `context`.

In the **sync** path (`runs.py:101 execute_run(..., run_id=None)`), no
run exists yet when `prepare_branch_run` raises. The route's
`except ValueError` (Batch 1 may have mapped it) now catches
`BranchEvidenceError` (a `CardreError`, so it goes to the Batch 0
handler) and returns a 409/400/404 with `detail.code` and
`detail.context`. No run record is created — acceptable, since the
branch validation failed before any work began.

### 4. `sidecar/routes/branches.py:110-139` — `create_branch` typed errors

`create_branch` does not catch `ValueError`; after step 1 it raises
`BranchValidationError` (a `CardreError`), which the Batch 0 handler
serialises as a 400 with `detail.code` and `detail.context`. No local
handler needed. Confirm the route returns 400 (not 500) for an invalid
branch request via a test.

### 5. `sidecar/routes/runs.py:21-30` — preflight typed-error awareness

`_is_branch_current` catches `(ValueError, Exception): pass`. After
this batch, `prepare_branch_run` raises `BranchEvidenceError`. The
preflight catch stays (preflight is non-blocking), but **log the typed
code** so the eventual thread failure is correlated:

```python
except CardreError as e:
    import logging
    logging.getLogger(__name__).debug(
        "branch preflight non-blocking failure: %s (%s)", e.code, e.message,
        extra={"branch_id": branch_id, "plan_version_id": plan_version_id},
    )
    return None
except Exception:
    return None
```

The thread path records the real diagnostic when it re-raises.

### 6. BR-3 — `_find_shared_evidence` records lookup-policy context

`branch_evidence.py:233-263` `_find_shared_evidence` returns `None`
quietly when all lookup policies miss. The later executor fails with a
generic `MissingInputArtifactError` (`executor.py:440`). Add a
non-blocking diagnostic with the policies tried:

```python
def _find_shared_evidence(self, store, plan_id, plan_version_id, step_id,
                           source_branch_id=None) -> RunStepRecord | None:
    tried = []
    lookup_branch = source_branch_id or None
    rs = store.get_latest_successful_run_step_for_step_across_plan(plan_id, step_id, branch_id=lookup_branch)
    tried.append({"policy": "source_branch", "branch_id": lookup_branch, "found": rs is not None})
    if rs is not None: return rs
    if lookup_branch is not None:
        rs = store.get_latest_successful_run_step_for_step_across_plan(plan_id, step_id, branch_id=None)
        tried.append({"policy": "any_branch", "branch_id": None, "found": rs is not None})
        if rs is not None: return rs
    plan_run_id = store.get_latest_successful_run_id_for_plan(plan_id)
    tried.append({"policy": "latest_plan_run", "run_id": plan_run_id, "found": plan_run_id is not None})
    if plan_run_id is not None:
        for prs in store.get_run_steps(plan_run_id):
            if prs.step_id == step_id and prs.status == STATUS_SUCCEEDED:
                return prs
    # Record a non-blocking diagnostic so the eventual MissingInputArtifactError
    # can reference the policies tried. Attach to the caller's context via exception.
    self._last_shared_lookup_diagnostic = Diagnostic(
        code="REUSE_EVIDENCE_NOT_FOUND",
        message=f"No successful evidence for shared step {step_id} across tried policies.",
        severity="warning",
        context={"step_id": step_id, "plan_id": plan_id, "lookup_policies": tried},
    )
    return None
```

`prepare_branch_run` / `resolve_parent_evidence` callers can collect
these diagnostics and attach them to the `BranchRunContext` (add a
`diagnostics: list[Diagnostic]` field to `BranchRunContext`). The
executor can surface them as run diagnostics or step warnings.

### 7. EXE-1 — executor category map

`executor.py:381-396` `_CATEGORY_MAP`. Add `RoleAccessError` and
`LeakageProtectionError` **before** the `CardreError` catch-all:

```python
_CATEGORY_MAP = (
    (GraphValidationError, "GraphValidationError"),
    (MissingInputArtifactError, "MissingInputArtifactError"),
    (ParameterValidationError, "ParameterValidationError"),
    (ArtifactReadError, "ArtifactReadError"),
    (ArtifactWriteError, "ArtifactWriteError"),
    (NodeExecutionError, "NodeExecutionError"),
    (ContractViolationError, "ContractViolationError"),
    (RoleAccessError, "RoleAccessError"),
    (LeakageProtectionError, "LeakageProtectionError"),
    (CardreError, "CardreError"),
)
```

Order matters: specific classes first. `RoleAccessError` and
`LeakageProtectionError` are now `CardreError` subclasses (Batch 0); if
they came after `CardreError` they'd be misclassified as `CardreError`.

### 8. EXE-2 — branch preparation failure diagnostic (sync path)

`executor.py:117 ctx = resolver.prepare_branch_run(...)` raises before
`RunLifecycle.start` (line 122). In the **async** path, the run exists
(step 3 handles it). In the **sync** path (`run_branch` called from
`execute_run` with `run_id=None`), no run exists — the exception
propagates to the route. No diagnostic to write (no run). This is
acceptable; the route returns the typed error.

For the case where `run_id` is supplied to `run_branch` (re-execution of
an existing run), the run exists and is `running`; catch
`BranchEvidenceError` around `prepare_branch_run` and record a
diagnostic before re-raising:

```python
try:
    ctx = resolver.prepare_branch_run(store, branch_id, plan_version_id, force=force)
except BranchEvidenceError as e:
    if run_id is not None:
        store.append_run_diagnostic(run_id, {
            "code": e.code,
            "message": e.message,
            "severity": "error",
            "category": "BranchEvidenceError",
            "run_id": run_id,
            "branch_id": branch_id,
            "context": e.context,
            "traceback": traceback.format_exc(),
            "created_at": utc_now_iso(),
        })
    raise
```

### 9. EXE-3 — reuse-miss diagnostic

`executor.py:257-274` reuse branch: when `_reuse_run_step` returns `None`,
fall back to execute with no explanation. Add a non-blocking step warning:

```python
if rs is not None:
    records[action.spec.step_id] = rs
    outputs[action.spec.step_id] = resolve_output_artifacts(store, rs)
else:
    # Reuse miss: record a non-blocking diagnostic and execute.
    # Attach to the run via append_run_diagnostic with severity=warning,
    # OR collect into a per-run warnings list surfaced in the manifest.
    store.append_run_diagnostic(run_id, {
        "code": "REUSE_EVIDENCE_NOT_FOUND",
        "message": f"Planned reuse for step {action.spec.step_id!r} found no prior evidence; executing.",
        "severity": "warning",
        "run_id": run_id,
        "step_id": action.spec.step_id,
        "created_at": utc_now_iso(),
    })
    if action.before_execute is not None: action.before_execute()
    store.run_heartbeat(run_id)
    rs = self._execute_step(...)
    ...
```

This makes reuse-vs-reexecute decisions explainable in the run
diagnostics.

### 10. `cardre/topology.py` / `staleness.py` — verify typed errors in branch path

Batch 3 made `validate_topology` raise `GraphValidationError` and
`_find_spec` raise `GraphValidationError`. Confirm
`branch_evidence.py:97 validate_topology(steps)` and the staleness walk
in `prepare_branch_run` propagate the typed error. The
`BranchEvidenceError`/`BranchValidationError` hierarchy does **not**
catch `GraphValidationError` (different branch); it propagates as a
`GraphValidationError` with `status_code=500` (topology defect is a
server-side plan corruption, not user input). This is the ST-1
completion: broken graph topology blocks execution/guidance with a typed
error, never a silent `KeyError` or `ValueError`.

## Tests

- Invalid branch point returns 400 `BRANCH_POINT_NOT_ALLOWED` with
  `context.branch_point_step_id` (no 500).
- Wrong branch type returns 400 `BRANCH_TYPE_MISMATCH` with
  `context.expected_type`/`context.got_type`.
- `BRANCH_VERSION_MISMATCH` returns 409 with `context`.
- `SHARED_UPSTREAM_STALE` in the async path records a run diagnostic with
  `code="SHARED_UPSTREAM_STALE"` and `context` listing stale steps; run
  ends `failed`; `GET /runs/{id}` shows the diagnostic.
- `BRANCH_NO_OP_FAILED` returns 409; no run created in sync path.
- `_find_shared_evidence` returning `None` records a
  `REUSE_EVIDENCE_NOT_FOUND` warning diagnostic with `lookup_policies`
  in `context`.
- `_execute_step` with a `RoleAccessError` records
  `category="RoleAccessError"` (not `InternalExecutionError`/`CardreError`).
- `_execute_step` with a `LeakageProtectionError` records
  `category="LeakageProtectionError"`.
- `_execute_actions` reuse miss records a `REUSE_EVIDENCE_NOT_FOUND`
  warning diagnostic and then executes (run still succeeds if step
  succeeds).
- `run_branch` with `run_id` supplied and a `BranchEvidenceError` from
  `prepare_branch_run` records a run diagnostic before re-raising.
- `validate_topology` cycle in branch path raises `GraphValidationError`
  with `status_code=500` and step context; no `ValueError` leaks.
- `_find_spec` missing parent raises `GraphValidationError` with
  `context.missing_step_id` and `context.known_step_ids`.

## Acceptance criteria

- `rg "raise ValueError\(.*BRANCH_|raise ValueError\(.*SEGMENT_" cardre/
  sidecar/` returns zero matches.
- `rg "raise ValueError\(.*SHARED_UPSTREAM|BRANCH_NO_OP|BRANCH_VERSION" cardre/`
  returns zero matches.
- `BranchValidationError` and `BranchEvidenceError` are `CardreError`
  subclasses; the Batch 0 handler serialises them with `code`, `context`,
  `status_code`.
- `RoleAccessError` and `LeakageProtectionError` appear in
  `_CATEGORY_MAP` before `CardreError`; tests confirm correct
  categorisation.
- Async branch failures are visible from `GET /runs/{run_id}` with the
  typed `code` preserved in the diagnostic.
- `validate_topology` and `_find_spec` raise `GraphValidationError`; no
  `KeyError`/`ValueError` leaks from the topology/staleness path.
- `make lint && make typecheck && make test` pass.
- Sprint-wide DoD (see `README.md`) satisfied.

## Out of scope

- New branch points (product scope).
- Branch comparison snapshot error handling (separate area).
- Frontend branch-creation form error rendering beyond what Batch 1's
  `ApiError` typing already provides (the typed `code`/`context` is
  available; rendering is a UI polish follow-up).

## Sprint completion

This batch closes the last findings. After it merges, run the sprint
Definition of Done checklist in `README.md`:

1. `rg "except Exception:\s*pass|except:\s*pass" cardre/services/ cardre/
   executor.py cardre/run_lifecycle.py cardre/staleness.py cardre/
   topology.py sidecar/routes/` returns zero matches.
2. `rg "await res\.json\(\)" frontend/src/api/client.ts` returns zero
   matches (Batch 1 replaced it with text-then-parse).
3. Every failed run in the test fixtures has at least one step error or
   run diagnostic unless explicitly cancelled.
4. `X-Cardre-Request-Id` present on all test responses.
5. `errors`/`warnings` tables absent from a fresh store.
6. `make lint && make typecheck && make test` green.