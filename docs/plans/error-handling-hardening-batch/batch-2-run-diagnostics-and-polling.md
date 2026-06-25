# Batch 2 — Run diagnostics + polling display

## Goal

Persist run-level diagnostics for failures that occur **outside** a
normal step (async dispatch, thread start, lifecycle finalisation, stale
run recovery, preflight), expose them on `RunResponse`, and render them
in the frontend so a failed run is always actionable.

After this batch, no failed run has zero step errors and zero run
diagnostics unless it was explicitly cancelled by the user.

## Findings addressed

- **RO-1** — `_fail_run_if_running` swallows failure-to-mark.
- **RO-2** — `dispatch_run_async` catches `BaseException`, prints only,
  no persistent diagnostic.
- **RO-3** — run-id mismatch cancelled with no explanation.
- **RUN-1** (completion) — sync execution exception persists a run
  diagnostic with the run_id.
- **RUN-2** — async thread-start failure records
  `RUN_DISPATCH_FAILED`.
- **RUN-3** — global run lookup skip logged with optional diagnostic.
- **LIFE-1, LIFE-2, LIFE-3** — manifest write / context exit / finalise
  failure all persist diagnostics with exception chaining.
- **FE-2** (completion) — `useRunProgress` displays last poll `ApiError`.
- **FE-3** — frontend shows first failed step error + expandable
  diagnostics.
- **Missed case: stale-run recovery** — startup recovery writes
  `RUN_INTERRUPTED_RECOVERY`.
- **Missed case: preflight swallow** — `_is_branch_current` preflight
  failure surfaces as a diagnostic instead of an opaque failed run.

## Context you must read first

- `cardre/store/project_store.py:50-57` — `runs.metadata_json TEXT NOT NULL
  DEFAULT '{}'` is the chosen diagnostic store (zero-migration, matches
  `run_steps.errors_json` pattern). Confirmed never written by
  `create_run`/`finish_run`.
- `cardre/store/project_store.py:14-20` — `_fail_run_if_running`
  swallows both `get_run` and `finish_run` failures.
- `cardre/store/project_store.py:180-191` — stale-run recovery on startup
  silently marks runs `interrupted`.
- `cardre/services/run_orchestrator.py:60-84` — `dispatch_run_async`
  catches `BaseException`, prints traceback, calls `_fail_run_if_running`.
- `cardre/run_lifecycle.py:237-251` — `__exit__` finalises as failed
  with no diagnostic and does not chain the body exception.
- `cardre/run_lifecycle.py:310-328` — `finalise` catches `Exception`,
  marks failed, re-raises the **manifest-write** exception (masks the
  original).
- `cardre/run_lifecycle.py:95-116` — `write_manifest` silently returns
  if run record is missing.
- `cardre/executor.py:376-427` — `_execute_step` failure recording can
  itself fail if `save_run_step` raises.
- `sidecar/routes/runs.py:21-52` — `_is_branch_current` /
  `_is_to_node_current` swallow preflight errors.
- `sidecar/routes/runs.py:55-67` — `_build_run_response` is the single
  place to add diagnostics/`latest_error`.
- `frontend/src/hooks/useRunProgress.ts:108-121` — failed run currently
  only logs `Run ${run.status}`; never reads `steps.errors`.
- `frontend/src/types.ts` / `frontend/src/api/schema.d.ts` — `RunStepItem`
  has `errors: Array<{ code, message, traceback?, category? }>`.
- `docs/plans/error-handling-hardening-batch/README.md` — cross-cutting
  rules (no silent degrade; diagnostics carry context; 600-line
  ceiling).

## Changes

### 1. `cardre/store/project_store.py` — diagnostic read/write helpers

Add helpers that read/write `runs.metadata_json.diagnostics` (a JSON
array). Do **not** add a new table.

```python
def append_run_diagnostic(self, run_id: str, diagnostic: dict) -> None:
    """Append a run-level diagnostic to runs.metadata_json.diagnostics.

    Best-effort: if the run is missing or the store is unavailable, log
    and continue (do not raise) — this is the last-resort path and must
    not mask the original failure.
    """
    try:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                logger.warning("append_run_diagnostic: run %s not found", run_id)
                return
            meta = json.loads(row["metadata_json"] or "{}")
            diags = meta.get("diagnostics", [])
            diags.append(diagnostic)
            meta["diagnostics"] = diags
            conn.execute(
                "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
                (json.dumps(meta, sort_keys=True), run_id),
            )
    except Exception as e:
        logger.exception("append_run_diagnostic failed for run %s: %s", run_id, e)

def get_run_diagnostics(self, run_id: str) -> list[dict]:
    row = self._connect().execute(
        "SELECT metadata_json FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None: return []
    meta = json.loads(row["metadata_json"] or "{}")
    return meta.get("diagnostics", [])
```

Add a `latest_error` denormalised view: when appending, if the diagnostic
`severity == "error"`, also set `meta["latest_error"] = diagnostic` so
`_build_run_response` is O(1) and the polling endpoint stays cheap.

Rules:
- `append_run_diagnostic` **never raises**. It is the last-resort path.
  If it fails, it logs; the original failure is preserved upstream.
- Diagnostics carry: `code`, `message`, `severity`, `category`,
  `exception_type`, `run_id`, `plan_version_id`, `branch_id`, `step_id`,
  `traceback`, `created_at`.

### 2. `cardre/services/run_orchestrator.py` — async dispatch diagnostic

Rewrite `dispatch_run_async`:

- Catch `Exception` (not `BaseException` — let `KeyboardInterrupt`/
  `SystemExit` propagate; the stale-run recovery at startup handles
  interrupted runs).
- On exception, build a diagnostic:
  ```python
  diag = {
      "code": "RUN_ASYNC_FAILED",
      "message": str(exc) or exc.__class__.__name__,
      "severity": "error",
      "category": exc.__class__.__name__,
      "exception_type": exc.__class__.__name__,
      "run_id": run_id,
      "plan_version_id": plan_version_id,
      "branch_id": branch_id,
      "traceback": traceback.format_exc(),
      "created_at": utc_now_iso(),
  }
  store.append_run_diagnostic(run_id, diag)
  _fail_run_if_running(store, run_id)  # also fixed below
  ```
- Log the structured error with `run_id` and traceback.
- `_fail_run_if_running` (below) is fixed to record its own diagnostic.

Note on `SystemExit`: catching `Exception` means a sidecar shutdown during
a run leaves the run `running`; `project_store.py:191` recovery marks it
`interrupted` on next open. This is the accepted trade-off — see the
sprint README.

### 3. `cardre/services/run_orchestrator.py` — `_fail_run_if_running` last-resort

Rewrite `_fail_run_if_running` to record a diagnostic when it cannot
mark the run failed:

```python
def _fail_run_if_running(store, run_id):
    try:
        run = store.get_run(run_id)
        if run and run.get("status") == "running":
            store.finish_run(run_id, "failed")
    except Exception as e:
        # Last resort: log with run_id so the failure is at least visible.
        # Do NOT re-raise — this is a cleanup path.
        import logging, traceback as tb
        logging.getLogger(__name__).exception(
            "_fail_run_if_running failed for run %s: %s\n%s",
            run_id, e, tb.format_exc(),
        )
```

If `store.append_run_diagnostic` is reachable here, attempt it
best-effort (it itself never raises). If the store is fully
unavailable, the log is the only record — that is acceptable for the
recursive-failure case noted in the sprint README.

### 4. `cardre/services/run_orchestrator.py` — run-id mismatch diagnostic (RO-3)

In `execute_run` (lines 44-57), when `result_id != run_id`, record a
`RUN_SHORT_CIRCUITED` diagnostic on the supplied `run_id` before
finishing it as `cancelled`:

```python
if run_id is not None and result_id != run_id:
    store.append_run_diagnostic(run_id, {
        "code": "RUN_SHORT_CIRCUITED",
        "message": f"Executor returned run {result_id}; requested {run_id} cancelled.",
        "severity": "info",
        "run_id": run_id,
        "context": {"returned_run_id": result_id, "requested_run_id": run_id},
        "created_at": utc_now_iso(),
    })
    store.finish_run(run_id, "cancelled")
    return run_id
```

### 5. `cardre/run_lifecycle.py` — `write_manifest` fail hard (LIFE-1)

`write_manifest` (lines 95-116) silently returns when the run record is
missing. Replace with:

```python
run_record = store.get_run(run_id)
if run_record is None:
    raise CardreError(
        "RUN_RECORD_MISSING",
        message=f"Cannot write manifest: run {run_id} not found.",
        context={"run_id": run_id, "plan_version_id": plan_version_id},
        status_code=500,
    )
```

Use the `RunLifecycleError` declared in Batch 0 if you prefer a typed
subclass; either is acceptable as long as it is a `CardreError`.

### 6. `cardre/run_lifecycle.py` — `__exit__` records diagnostic + chains (LIFE-2)

`__exit__` (lines 237-251) currently finalises as failed with no
diagnostic and swallows the body exception's role. Fix:

```python
def __exit__(self, exc_type, exc_val, exc_tb):
    if not self._finalised:
        if exc_val is not None:
            # Record the body exception as a run diagnostic before
            # finalising as failed.
            import traceback as tb
            self.store.append_run_diagnostic(self.run_id, {
                "code": "RUN_BODY_EXCEPTION",
                "message": f"{exc_val.__class__.__name__}: {exc_val}",
                "severity": "error",
                "exception_type": exc_val.__class__.__name__,
                "run_id": self.run_id,
                "plan_version_id": self.plan_version_id,
                "traceback": "".join(tb.format_exception(exc_type, exc_val, exc_tb)),
                "created_at": utc_now_iso(),
            })
        self.finalise(
            status="failed",
            execution_mode=self._execution_mode,
            branch_id=self._branch_id,
            target_step_id=self._target_step_id,
            in_scope_step_ids=self._in_scope_step_ids,
        )
    return None  # do not suppress
```

### 7. `cardre/run_lifecycle.py` — `finalise` chains exceptions (LIFE-3)

`finalise` (lines 310-328) catches `Exception`, marks failed, and
re-raises the manifest-write exception, masking the original. Fix:

```python
def finalise(self, status, execution_mode, *, branch_id=None, ...):
    if self._finalised: return
    now = utc_now_iso()
    finalisation_exc = None
    try:
        finalise_run(self.store, RunFinalisation(...))
    except Exception as e:
        finalisation_exc = e
        # Record the finalisation failure as a diagnostic before marking failed.
        self.store.append_run_diagnostic(self.run_id, {
            "code": "RUN_FINALISATION_FAILED",
            "message": f"Finalisation failed: {e}",
            "severity": "error",
            "exception_type": e.__class__.__name__,
            "run_id": self.run_id,
            "traceback": traceback.format_exc(),
            "created_at": now,
        })
        try:
            self.store.finish_run(self.run_id, "failed")
        except Exception:
            logger.exception("finish_run also failed for %s", self.run_id)
    self._finalised = True
    if finalisation_exc is not None:
        raise finalisation_exc
```

If `finalise` was called from `__exit__` with a body exception already
recorded, and finalisation **also** fails, the body diagnostic and the
finalisation diagnostic both exist on the run; the re-raised
`finalisation_exc` masks the body exception in Python's stack but both
are visible in `runs.metadata_json.diagnostics`. This is the accepted
trade-off documented in the sprint README; the diagnostics are the
source of truth, not the Python stack.

### 8. `cardre/store/project_store.py:191` — stale-run recovery diagnostic

In the startup recovery that marks `running` runs as `interrupted`,
append a `RUN_INTERRUPTED_RECOVERY` diagnostic to each recovered run:

```python
for rd in running_rows:
    self.append_run_diagnostic(rd["run_id"], {
        "code": "RUN_INTERRUPTED_RECOVERY",
        "message": "Run was left running after a sidecar exit; marked interrupted on recovery.",
        "severity": "error",
        "run_id": rd["run_id"],
        "created_at": utc_now_iso(),
    })
    self.finish_run(rd["run_id"], "interrupted")
```

### 9. `sidecar/routes/runs.py` — preflight diagnostics

`_is_branch_current` (lines 21-30) and `_is_to_node_current` (33-52)
swallow all exceptions and return `None`. Fix:

- Catch `Exception` and log with `run_id` context, but still return
  `None` (preflight is non-blocking — the run proceeds and will fail
  inside the thread with a proper diagnostic). **However**, when the
  preflight raises a `BranchEvidenceError` (Batch 6) or a
  `SHARED_UPSTREAM_STALE`-equivalent, the subsequent thread execution
  will re-raise it; `dispatch_run_async` (fixed in step 2) records the
  diagnostic. So the preflight swallow is acceptable **only if** the
  thread path records diagnostics, which it now does.
- Do **not** write a preflight diagnostic to the run — the run may not
  exist yet (preflight runs before `store.create_run` at line 139). The
  diagnostic is recorded when the thread re-raises.

### 10. `sidecar/routes/runs.py` — `_build_run_response` adds diagnostics

Extend `_build_run_response` (lines 55-67) to populate
`diagnostics` and `latest_error`:

```python
def _build_run_response(store, run_id, executed_ids=None):
    run = store.get_run(run_id)
    steps = store.get_run_steps(run_id)
    diags = store.get_run_diagnostics(run_id)
    latest_error = next((d for d in reversed(diags) if d.get("severity") == "error"), None)
    return RunResponse(
        run_id=run["run_id"],
        plan_version_id=run["plan_version_id"],
        status=run["status"],
        started_at=run["started_at"],
        finished_at=run.get("finished_at"),
        step_count=len(steps),
        branch_id=run.get("branch_id"),
        executed_step_ids=executed_ids or [],
        diagnostics=[RunDiagnostic(**_normalise_diag(d)) for d in diags],
        latest_error=RunDiagnostic(**_normalise_diag(latest_error)) if latest_error else None,
    )
```

`_normalise_diag` ensures required fields are present (filling
`run_id`, `created_at` if missing) and drops fields not in
`RunDiagnostic`.

`get_run_steps` (line 175-205) already returns `RunStepItem.errors` —
unchanged. The frontend will read it in step 12.

### 11. `cardre/executor.py` — recording-failure guard (missed case)

`_execute_step` (376-427) can lose the original node error if
`store.save_run_step` raises. Wrap the recording in a guard:

```python
try:
    rs = self._record_run_step(...)
except Exception as record_exc:
    import logging, traceback as tb
    logging.getLogger(__name__).exception(
        "Failed to record step evidence for %s: %s\nOriginal error: %s",
        spec.step_id, record_exc, tb.format_exc(),
    )
    # Build a minimal rs so the executor loop can continue/fail.
    rs = RunStepRecord(..., status=STATUS_FAILED, errors=[error_entry, {
        "code": "STEP_RECORDING_FAILED",
        "message": f"Could not persist step evidence: {record_exc}",
        "category": "InternalExecutionError",
    }])
return rs
```

The original `error_entry` is preserved in the in-memory `rs.errors`;
even if it is not persisted (store unavailable), it is logged. This
addresses the missed recursive-failure case.

### 12. `frontend/src/hooks/useRunProgress.ts` — display diagnostics

On failed run, read `run.diagnostics` and `steps[].errors`:

```tsx
if (run.status !== "running") {
  // ... existing cleanup ...
  const runDiag = run.latest_error;
  const firstFailedStep = steps.steps.find((s) => s.status === "failed");
  const stepErr = firstFailedStep?.errors?.[0];
  if (runDiag) {
    addDiagnostic(`Run failed: ${runDiag.code} — ${runDiag.message}`);
  } else if (stepErr) {
    addDiagnostic(`Step ${firstFailedStep.step_id} failed: ${stepErr.category} — ${stepErr.message}`);
  } else {
    addDiagnostic(`Run ${run.status}`);
  }
  setLastRunError(runDiag ?? null);
  onRunComplete();
}
```

Expose `lastRunError: RunDiagnostic | null` on the hook return.

### 13. Frontend — render failed-run diagnostics

Add a collapsible `RunDiagnosticsPanel` (new file under
`frontend/src/components/` to stay under the 600-line ceiling) that:

- Shows `run.latest_error.code` + `message` prominently when
  `run.status === "failed"`.
- Lists `run.diagnostics` (expandable) with `code`, `message`,
  `exception_type`, `created_at`.
- Lists failed `steps[].errors` (expandable) with `category`, `message`,
  and a `<details>` for the raw `traceback`.

Wire it into `StepInspector` / `RunHistoryTab` where the run is shown.
Keep it behind `run.status === "failed"` so it does not clutter successful
runs.

## Tests

Backend (`tests/test_run_orchestrator.py`, `tests/test_run_lifecycle.py`):
- `dispatch_run_async` with an executor patched to raise records a
  `RUN_ASYNC_FAILED` diagnostic on the run; run ends `failed`.
- `_fail_run_if_running` with a store patched to raise on `get_run` logs
  and does not propagate.
- `execute_run` with a branch short-circuit returning a different
  `result_id` records `RUN_SHORT_CIRCUITED` and marks the requested run
  `cancelled`.
- `RunLifecycle.__exit__` with a body that raises records a
  `RUN_BODY_EXCEPTION` diagnostic; run ends `failed`; the diagnostic's
  `traceback` contains the body exception.
- `finalise` with a `write_manifest` patched to raise records
  `RUN_FINALISATION_FAILED` and re-raises; run is `failed`.
- `write_manifest` with a missing run raises `RUN_RECORD_MISSING`
  (`CardreError`).
- Stale-run recovery: a store opened with a `running` run marks it
  `interrupted` and appends `RUN_INTERRUPTED_RECOVERY`.
- `_execute_step` with `save_run_step` patched to raise returns an `rs`
  with both the original `STEP_FAILED` and `STEP_RECORDING_FAILED`
  errors (in-memory).

Backend (`tests/test_api_contracts.py`):
- `GET /runs/{run_id}` for a failed run includes `diagnostics` and
  `latest_error` with the expected codes.
- Polling cost: `_build_run_response` does not issue extra queries
  beyond `get_run`, `get_run_steps`, `get_run_diagnostics` (verify via
  mocked store call counts).

Frontend:
- `useRunProgress` with a run that transitions to `failed` with a
  `latest_error` sets `lastRunError` and adds a diagnostic containing the
  `code`.
- `useRunProgress` with a failed run and no `latest_error` but a failed
  step reads `steps[].errors[0]` and adds a step diagnostic.
- `RunDiagnosticsPanel` renders `latest_error` and expandable
  `diagnostics` for a failed run; renders nothing for a succeeded run.
- `SIDECAR_UNREACHABLE` poll error (from Batch 1) surfaces in
  `lastPollError` and the UI shows it.

## Acceptance criteria

- `runs.metadata_json.diagnostics` is written for: async dispatch
  failure, thread-start failure, lifecycle `__exit__` body exception,
  `finalise` manifest-write failure, stale-run recovery, run-id
  short-circuit, and sync execution exception (via lifecycle).
- `RunResponse.diagnostics` and `RunResponse.latest_error` are populated
  for failed runs.
- No failed run has zero step errors and zero run diagnostics unless it
  was explicitly cancelled.
- `dispatch_run_async` no longer prints-only; it persists a diagnostic.
- `_fail_run_if_running` does not swallow its own failure silently.
- `write_manifest` raises `RUN_RECORD_MISSING` instead of silently
  returning.
- `finalise` records `RUN_FINALISATION_FAILED` before re-raising.
- Stale-run recovery writes `RUN_INTERRUPTED_RECOVERY`.
- Frontend shows `latest_error` for failed runs; expandable diagnostics
  available.
- `make lint && make typecheck && make test` pass.
- `frontend/src/api/schema.d.ts` regenerated and committed (RunResponse
  fields added).

## Out of scope

- Branch-evidence pre-run `ValueError` → typed error conversion (Batch 6
  completes the preflight→diagnostic chain for branch-specific codes).
- Workflow guidance degraded-state diagnostics (Batch 3).
- Manual-binning annotation diagnostics (Batch 4).
- Report metadata corruption vs missing (Batch 5).