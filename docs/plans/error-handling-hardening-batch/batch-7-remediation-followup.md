# Batch 7 — Remediation follow-up

## Goal

Close the 12 residual findings left by Batches 0-6: the governance-gate
bypass, the misleading HTTP 201, the collector silent-omit cluster, the
branch-evidence silent-baseline fallback, and the diagnostic test debt.
Land the three out-of-original-scope production gaps (health,
export-continues-on-failure, fairness false-all-clear). No new modelling
or evidence scope; no new endpoints.

## Findings addressed

- **REM-1** (was #3, Blocker) — `compute_manual_binning_blockers` runs
  against an empty `variable_summaries` list when WOE/IV evidence is
  unreadable, returning "no blockers". The review gate can conclude
  despite broken evidence.
- **REM-2** (was #2, Blocker) — Async route returns HTTP 201 with
  `status:"failed"` when `threading.Thread.start()` raises.
- **REM-3** (was #5, High) — `BranchEvidenceResolver._find_shared_evidence`
  silently falls back from `source_branch_id` to `branch_id=None` (baseline)
  when source-branch evidence is missing, with no limitation.
- **REM-4** (was #6, High) — Sync run endpoint catches broad `Exception`
  and returns a context-free 500.
- **REM-5** (was #13, High) — Collector silently omits required evidence
  (model coefficients, score scaling, validation metrics, modelling
  metadata) when the run step exists but the artifact is wrong/missing.
- **REM-6** (was #14 twin, High) — `collector.py:_get_latest_review_annotation`
  still `except Exception: return None`; report silently omits review
  audit fields.
- **REM-7** (was #16, Medium) — `_is_to_node_current` preflight swallows
  staleness errors with no diagnostic logged.
- **REM-8** (was #19, Low/Medium) — Executor error_entry `code` is always
  `"STEP_FAILED"` regardless of classified `category`.
- **REM-9** (was #20, Low/Medium) — `generic_exception_handler` returns
  generic message with only exception type; no method/path, no exception
  message in dev mode.
- **REM-10** (missed, High) — `/health` returns `status="ok"` with
  zeroed booleans when registry/node/governance load fails.
- **REM-11** (missed, High) — `export_service` appends `REPORT_FAILED`
  diagnostic and continues; returns a successful export missing a
  branch's report.
- **REM-12** (missed, Blocker) — `fairness.py` sets `df = None` on
  train-parquet read failure and produces an all-clear fairness report.
- **TEST-1** (cross-cutting) — Zero characterization tests for
  `append_run_diagnostic`, `RUN_DISPATCH_FAILED`,
  `RUN_FINALISATION_FAILED`, `REUSE_EVIDENCE_NOT_FOUND`, etc.

## Context you must read first

### Established patterns (from Batches 0-6) — use these, do not invent new ones

- `cardre/errors.py:11-18` — `Diagnostic` dataclass with `code`,
  `message`, `source`, `exception_type`, `severity`, `context`.
- `cardre/errors.py:166-219` — `Ok`/`Degraded`/`Fail`/`Result` type and
  `unwrap_or_raise` / `unwrap_or_degrade` helpers.
- `cardre/errors.py:145-160` — `BranchEvidenceError(code, message,
  context=, status_code=)` constructor pattern.
- `cardre/store/project_store.py:205-228` — `store.append_run_diagnostic(
  run_id, diag_dict)`. Never raises (logs on its own failure).
- `cardre/readiness/limitation_codes.py:12-92` — `LimitationCode`
  StrEnum with `blocker_codes()` / `warning_codes()` classmethods.
- `cardre/reporting/collector.py:90` — `self.limitations:
  list[Limitation]`, appended via `Limitation(severity=, code=,
  message=)`.
- `tests/test_workflow_guidance_scaffold.py:262-326` — canonical
  monkeypatch test pattern: monkeypatch the function to raise,
  call `svc.build(...)`, assert `result.degraded is True` and
  `result.diagnostics` contains the expected code.

### Residual code sites

- `cardre/readiness/manual_binning.py:37-93` —
  `compute_manual_binning_blockers` iterates `variable_summaries`; when
  the list is empty (evidence unreadable) the loop body is skipped and
  no blockers are returned.
- `cardre/services/manual_binning_service.py:296-326` — the `except
  Exception` block appends a `VARIABLE_SUMMARY_UNAVAILABLE` warning but
  does not set `result.ready = False` or add a blocking issue; control
  flows to `compute_manual_binning_blockers` with empty summaries.
- `sidecar/routes/runs.py:165-182` — async dispatch: `except Exception:
  store.finish_run(run_id, "failed")` then `return _build_run_response(
  store, run_id)` → HTTP 201.
- `sidecar/routes/runs.py:142-146` — sync: `except Exception:
  HTTPException(500, code="RUN_EXECUTION_FAILED", message="Run execution
  failed unexpectedly.")`.
- `cardre/services/branch_evidence.py:268-302` —
  `_find_shared_evidence`: tries `source_branch_id`, then `None`, then
  `latest_plan_run`; records `REUSE_EVIDENCE_NOT_FOUND` only when all
  policies fail. A successful baseline fallback (lines 276-282) returns
  silently.
- `cardre/reporting/collector.py:401-402` — `_collect_model`:
  `read_step_output_optional` + no `else`/limitation when artifact
  missing.
- `cardre/reporting/collector.py:428-433` — `_collect_modelling_metadata`:
  two bare returns, no limitation.
- `cardre/reporting/collector.py:450-451` — `_collect_score_scaling`:
  `if scaling is not None:` with no `else`/limitation.
- `cardre/reporting/collector.py:475-479` — `_collect_validation`: bare
  return when both optional reads return `None`.
- `cardre/reporting/collector.py:498-510` — `_collect_cutoff`: same
  pattern (warning severity, not blocker).
- `cardre/reporting/collector.py:719-737` —
  `_get_latest_review_annotation`: `except Exception: return None`.
- `sidecar/routes/runs.py:56-57` — `_is_to_node_current`:
  `except Exception: pass` with no diagnostic.
- `cardre/executor.py:440-445` — `error_entry["code"] = "STEP_FAILED"`
  always; `category` is computed but not used in `code`.
- `sidecar/error_handling.py:161-181` —
  `generic_exception_handler`: diagnostics carry only `exception_type`.
- `sidecar/routes/health.py:15-41` — three `except Exception:` blocks
  zeroing booleans; `status="ok"` returned unconditionally.
- `cardre/services/export_service.py:306-310` — `except Exception as
  exc: diagnostics.append(...)` then continues to checksums.
- `cardre/nodes/fairness.py:344-347` and `:478-482` — train parquet
  read `except Exception: df = None` / `pass`; downstream code treats
  `df is None` as "no sensitive columns found" → false all-clear.

## Implementation plan

The 12 fixes split into 6 independent PRs that can land in parallel
(no cross-PR dependencies). TEST-1 is a 7th PR that can also land in
parallel but should be merged before declaring the sprint done.

### PR A — REM-1: Manual-binning review-gate bypass (Blocker)

**File:** `cardre/readiness/manual_binning.py`,
`cardre/services/manual_binning_service.py`

**Change:**

1. In `compute_manual_binning_blockers` (`manual_binning.py:22`), add a
   guard before the `for vs in variable_summaries` loop:

   ```python
   if selected_variables and not variable_summaries:
       blockers.append({
           "code": "VARIABLE_SUMMARY_UNREADABLE",
           "message": (
               "Final WOE/IV evidence could not be loaded for "
               f"{len(selected_variables)} selected variable(s). "
               "Review cannot be completed while evidence is unreadable."
           ),
           "step_id": step_id,
       })
       return blockers
   ```

2. No change needed in `manual_binning_service.py` — the warning
   already carries context. The guard in the blocker function is the
   enforcement point.

**Test** (`tests/test_manual_binning_phase4.py` or new
`tests/test_manual_binning_gate.py`):

- Build an editor state where `selected_variables = ["x", "y"]` and
  `variable_summaries = []` (simulating unreadable evidence).
- Assert `compute_manual_binning_blockers(...)` returns a blocker with
  code `VARIABLE_SUMMARY_UNREADABLE`.
- Assert `ManualBinningService.save_with_review(reviewed=True)` raises
  `PlanValidationError("REVIEW_COMPLETION_BLOCKED")` containing that
  blocker.

### PR B — REM-2 + REM-4 + REM-7: Run route diagnostics (Blocker + High + Medium)

**File:** `sidecar/routes/runs.py`

**Changes:**

1. **REM-2** (async 201, line 180-182): Replace the bare
   `except Exception: store.finish_run(run_id, "failed")` with:

   ```python
   except Exception as exc:
       store.finish_run(run_id, "failed")
       raise CardreError(
           f"Failed to start background run thread: {exc}",
           code="RUN_DISPATCH_FAILED",
           context={
               "project_id": body.project_id,
               "plan_version_id": body.plan_version_id,
               "run_id": run_id,
               "run_scope": body.run_scope,
               "branch_id": body.branch_id,
           },
       ) from exc
   ```

   The run is marked failed (preserving the existing diagnostic path
   from Batch 2), but the HTTP response is now 500 with structured
   context rather than 201.

2. **REM-4** (sync 500, lines 142-146): Replace the broad
   `except Exception:` with a `CardreError` wrap that carries context:

   ```python
   except Exception as exc:
       raise CardreError(
           f"Run execution failed: {exc}",
           code="RUN_EXECUTION_FAILED",
           context={
               "project_id": body.project_id,
               "plan_version_id": body.plan_version_id,
               "run_scope": body.run_scope,
               "branch_id": body.branch_id,
           },
       ) from exc
   ```

   The `generic_exception_handler` will serialise this into the
   standard envelope. (Do not raise `HTTPException` — let
   `CardreError` flow through the existing handler which already
   includes `request_id` and `error_id`.)

3. **REM-7** (to_node preflight, lines 56-57): Replace
   `except Exception: pass` with a structured log:

   ```python
   except Exception as exc:
       import logging
       logging.getLogger(__name__).warning(
           "_is_to_node_current preflight degraded for "
           "plan_version_id=%s target_step_id=%s branch_id=%s: %s",
           plan_version_id, target_step_id, branch_id, exc,
       )
   ```

   Do not block execution — this is an optimisation path. The
   structured log is the surface.

**Tests** (`tests/test_sidecar_api.py` or new
`tests/test_run_routes.py`):

- Monkeypatch `threading.Thread.start` to raise `RuntimeError("no
  threads")`. Assert POST `/runs` returns 500 (not 201) with code
  `RUN_DISPATCH_FAILED` and context includes `run_id`.
- Monkeypatch `execute_run` to raise `RuntimeError("db locked")` in
  sync mode. Assert response code is `RUN_EXECUTION_FAILED` (not
  generic `INTERNAL_ERROR`) and context includes `plan_version_id`.
- Monkeypatch `compute_staleness` to raise in `_is_to_node_current`.
  Assert the run still dispatches (201) and a warning is logged (use
  `caplog` fixture).

### PR C — REM-3: Branch evidence silent baseline fallback (High)

**File:** `cardre/services/branch_evidence.py`

**Change:** In `_find_shared_evidence` (lines 254-302), when
`source_branch_id is not None` and the source-branch lookup fails but
the baseline (`branch_id=None`) lookup succeeds, record a diagnostic
on the `diagnostics` list before returning:

```python
if lookup_branch is not None:
    rs = store.get_latest_successful_run_step_for_step_across_plan(
        plan_id, step_id, branch_id=None,
    )
    if rs is not None:
        if diagnostics is not None:
            diagnostics.append(Diagnostic(
                code="INHERITED_BASELINE_EVIDENCE",
                message=(
                    f"Step {step_id}: source branch {source_branch_id} "
                    "has no evidence; fell back to baseline (branch_id=None)."
                ),
                source="BranchEvidenceResolver._find_shared_evidence",
                severity="warning",
                context={
                    "step_id": step_id,
                    "plan_id": plan_id,
                    "source_branch_id": source_branch_id,
                    "fallback_branch_id": None,
                },
            ))
        return rs
```

Also add `INHERITED_BASELINE_EVIDENCE` to
`LimitationCode.warning_codes()` in
`cardre/readiness/limitation_codes.py` so it can be surfaced as a
report limitation.

**Test** (`tests/test_executor_branch_execution.py` or new
`tests/test_branch_evidence_fallback.py`):

- Set up a parent/child branch map where shared upstream points to a
  source branch with no evidence, but baseline evidence exists.
- Assert `prepare_branch_run` succeeds (does not fail-hard — fallback
  is allowed) but `ctx.diagnostics` contains a diagnostic with code
  `INHERITED_BASELINE_EVIDENCE` and context including
  `source_branch_id`.

### PR D — REM-5 + REM-6: Collector required-evidence + annotation twin (High)

**File:** `cardre/reporting/collector.py`

**Changes:**

1. **REM-5** — Add limitation `else` branches to the 5 silent-omit
   collectors. For each, append a `Limitation` when the step exists but
   the artifact is missing:

   - `_collect_model` (line 401): `else` after `if model_art is not
     None:` →
     `Limitation(severity="blocker", code=LimitationCode.MISSING_MODEL_COEFFICIENTS,
     message=f"Model step {ref.step_id} produced no MODEL_ARTIFACT evidence.")`
   - `_collect_modelling_metadata` (line 432): `else` →
     `Limitation(severity="warning", code=LimitationCode.MISSING_MODELLING_METADATA,
     message=...)`. Add `MISSING_MODELLING_METADATA` to the enum +
     `warning_codes()`.
   - `_collect_score_scaling` (line 450): `else` →
     `Limitation(severity="blocker", code=LimitationCode.MISSING_SCORE_SCALING,
     message=...)` (reuse existing code).
   - `_collect_validation` (line 478): bare `return` →
     `Limitation(severity="blocker", code=LimitationCode.MISSING_TRAIN_VALIDATION_METRICS,
     message=...)` (reuse existing code).
   - `_collect_cutoff` (line 509): `else` →
     `Limitation(severity="warning", code=LimitationCode.NO_CUTOFF_ANALYSIS,
     message=...)` (reuse existing code).

2. **REM-6** — Replace `collector.py:736-737`
   `except Exception: return None` with the same `Result` pattern used
   in the service copy (Batch 4, `manual_binning_service.py:624-647`).
   Since the collector is not a service, return a `Degraded(None,
   [Diagnostic(code="REVIEW_ANNOTATION_UNREADABLE", ...)])` and have
   the caller (`_collect_manual_interventions` at line 549) append a
   `Limitation(severity="warning",
   code=LimitationCode.MISSING_MANUAL_INTERVENTION_REASON, message=...)`
   when the annotation is degraded. Reuse the existing
   `MISSING_MANUAL_INTERVENTION_REASON` code.

   Alternatively (simpler): extract a shared
   `read_latest_review_annotation(store, step_id, pv_id) -> Result` in
   `cardre/audit/annotations.py` and have both the service and
   collector call it. This eliminates the duplication entirely. Either
   approach is acceptable; the shared extraction is preferred.

**Tests** (`tests/test_reporting.py`):

- Build a successful run step for `logistic-regression` whose output
  artifact IDs do not include a `MODEL_ARTIFACT` evidence kind.
  Assert the report bundle `limitations` contains a blocker with code
  `MISSING_MODEL_COEFFICIENTS`.
- Repeat for score-scaling (assert `MISSING_SCORE_SCALING`) and
  validation (assert `MISSING_TRAIN_VALIDATION_METRICS`).
- Insert malformed `payload_json` into `step_annotations`. Assert the
  report bundle `limitations` contains
  `MISSING_MANUAL_INTERVENTION_REASON` (or
  `REVIEW_ANNOTATION_UNREADABLE` if not using the limitation path).

### PR E — REM-10 + REM-11 + REM-12: Health, export, fairness (High + High + Blocker)

**Files:** `sidecar/routes/health.py`,
`cardre/services/export_service.py`, `cardre/nodes/fairness.py`

**Changes:**

1. **REM-10** (`health.py:14-42`): Change the response to include
   `status="degraded"` and a `diagnostics` list when any load fails:

   ```python
   diagnostics = []
   try:
       load_registry()
       registry_accessible = True
   except Exception as exc:
       registry_accessible = False
       diagnostics.append({"code": "REGISTRY_UNREACHABLE",
           "message": str(exc)})
   # ... same pattern for nodes and governance ...
   status = "ok" if not diagnostics else "degraded"
   return HealthResponse(..., status=status, diagnostics=diagnostics)
   ```

   Add `diagnostics: list[dict] = []` to `HealthResponse` in
   `sidecar/models.py`. Regenerate `frontend/src/api/schema.d.ts` via
   `python3 scripts/generate-openapi-types.py` and commit the diff.

2. **REM-11** (`export_service.py:306-310`): Track whether any branch
   report failed and mark the export as partial:

   ```python
   except Exception as exc:
       diagnostics.append({
           "code": "REPORT_FAILED",
           "message": f"Report generation failed for branch {branch_id}: {exc}",
           "context": {"branch_id": branch_id, "run_id": latest_run_id},
       })
       partial = True
   ```

   At the end of the function, if `partial`, prepend a warning:
   `"Export is partial: one or more branch reports failed to generate."`
   The caller (route) should check this and include it in the response.
   Do not silently return success.

3. **REM-12** (`fairness.py:344-347` and `:478-482`): Replace
   `except Exception: df = None` / `pass` with a recorded warning on
   the node output:

   ```python
   except Exception as exc:
       warnings.append({
           "code": "TRAIN_DATA_READ_FAILED",
           "message": f"Could not read training data for fairness analysis: {exc}",
       })
       df = None
   ```

   Then, after the sensitive-columns loop, if `df is None` and
   `sensitive_columns` is non-empty, add a blocker-level warning:

   ```python
   if df is None and sensitive_columns:
       warnings.append({
           "code": "FAIRNESS_CHECK_INCOMPLETE",
           "message": "Fairness analysis is incomplete: training data could not be loaded.",
       })
   ```

   The `warnings` list is already written to `run_steps.warnings_json`
   by the executor, so no plumbing change is needed. The key change is
   that a false all-clear is no longer silent.

**Tests:**

- `tests/test_sidecar_api.py` or `tests/test_health.py`: Monkeypatch
  `load_registry` to raise. Assert `/health` returns `status="degraded"`
  and `diagnostics` contains `REGISTRY_UNREACHABLE`.
- `tests/test_reporting.py` or `tests/test_export_service.py`: Monkeypatch
  `ReportGenerationService.generate_and_write` to raise for one branch.
  Assert the export result includes a `partial` indicator and a
  `REPORT_FAILED` diagnostic.
- `tests/test_nodes.py` or new `tests/test_fairness_node.py`: Monkeypatch
  `pl.read_parquet` to raise. Assert the fairness node output
  `warnings` contains `TRAIN_DATA_READ_FAILED` and
  `FAIRNESS_CHECK_INCOMPLETE`.

### PR F — REM-8 + REM-9: Executor code + handler context (Low/Medium)

**Files:** `cardre/executor.py`, `sidecar/error_handling.py`

**Changes:**

1. **REM-8** (`executor.py:440-445`): Set `error_entry["code"]` from
   the classified category, falling back to `"STEP_FAILED"`:

   ```python
   _CODE_MAP: dict[str, str] = {
       "GraphValidationError": "GRAPH_VALIDATION_ERROR",
       "MissingInputArtifactError": "MISSING_INPUT_ARTIFACT",
       "ParameterValidationError": "PARAMETER_VALIDATION_ERROR",
       "ArtifactReadError": "ARTIFACT_READ_ERROR",
       "ArtifactWriteError": "ARTIFACT_WRITE_ERROR",
       "NodeExecutionError": "NODE_EXECUTION_ERROR",
       "ContractViolationError": "CONTRACT_VIOLATION_ERROR",
       "RoleAccessError": "ROLE_ACCESS_ERROR",
       "LeakageProtectionError": "LEAKAGE_PROTECTION_ERROR",
       "CardreError": "CARDRE_ERROR",
   }
   error_entry = {
       "code": _CODE_MAP.get(category, "STEP_FAILED"),
       "message": f"{exc_type.__name__ if exc_type else 'Unknown'}: {exc_value}",
       "traceback": tb,
       "category": category,
   }
   ```

2. **REM-9** (`error_handling.py:161-181`): Add method/path and
   exception message to the diagnostics. Use `str(exc)` (the message,
   not the traceback) which is safe for a local-first sidecar:

   ```python
   return _envelope(
       code="INTERNAL_ERROR",
       message="An internal error occurred.",
       status_code=500,
       diagnostics=[{
           "code": "INTERNAL_ERROR",
           "message": f"Unhandled {type(exc).__name__}: {exc}",
           "exception_type": type(exc).__name__,
           "method": request.method,
           "path": str(request.url.path),
       }],
       request_id=rid,
   )
   ```

   Do not include the traceback in the response. The `str(exc)` is the
   exception message (e.g. `"KeyError: 'woe_table'"`), which is
   actionable for a local user without leaking server internals beyond
   what a desktop sidecar already exposes.

**Tests:**

- `tests/test_executor.py`: Force a `ParameterValidationError` in a
  step. Assert the failed `RunStepRecord.errors[0]["code"]` is
  `"PARAMETER_VALIDATION_ERROR"` (not `"STEP_FAILED"`). Force a plain
  `RuntimeError` and assert code is `"STEP_FAILED"` (fallback).
- `tests/test_error_envelope.py` or `tests/test_sidecar_api.py`: Create
  a test route that raises `RuntimeError("disk full")`. Assert the 500
  response diagnostics include `method`, `path`, and
  `"Unhandled RuntimeError: disk full"` in `message`.

### PR G — TEST-1: Diagnostic characterization tests (cross-cutting)

**Files:** New `tests/test_run_diagnostics.py`

**Goal:** Cover the `append_run_diagnostic` mechanism and all new
diagnostic codes introduced by Batches 2-6. Currently zero tests
reference `append_run_diagnostic`, `RUN_DISPATCH_FAILED`,
`RUN_FINALISATION_FAILED`, `RUN_RECORD_MISSING`,
`REUSE_EVIDENCE_NOT_FOUND`, `BRANCH_VERSION_MISMATCH`, or
`BRANCH_PREPARATION_FAILED`.

**Tests:**

1. **Async dispatch failure** — Monkeypatch `execute_run` to raise
   before any step is created. Call `dispatch_run_async`. Assert
   `store.get_run_diagnostics(run_id)` contains a diagnostic with code
   `RUN_DISPATCH_FAILED`, `exception_type`, `run_id`,
   `plan_version_id`, and `traceback`. Assert the run is `failed`.

2. **Lifecycle finalisation failure** — Monkeypatch `write_manifest` to
   raise `OSError("disk full")`. Run `RunLifecycle.finalise`. Assert
   `store.get_run_diagnostics(run_id)` contains
   `RUN_FINALISATION_FAILED` with `traceback`. Assert run is `failed`.

3. **Missing run record** — Delete the run row before `write_manifest`.
   Assert `RunLifecycleError("RUN_RECORD_MISSING")` is raised.

4. **Branch version mismatch** — Create a branch whose
   `head_plan_version_id` differs from the requested version. Assert
   `BranchEvidenceError` with code `BRANCH_VERSION_MISMATCH` and
   context containing both `head_pv_id` and `requested_pv_id`.

5. **Reuse evidence not found** — Set up a shared upstream step with
   no evidence anywhere (no branch, no baseline, no plan run). Assert
   `ctx.diagnostics` contains `REUSE_EVIDENCE_NOT_FOUND` with
   `policies_tried` listing all three attempted policies.

6. **Stale-run recovery** — Create a run with `status="running"` and
   restart the store (triggering the stale-recovery path). Assert a
   `RUN_INTERRUPTED_RECOVERY` diagnostic (or equivalent) is written
   and the run is marked `interrupted`.

## Dependency graph and parallelism

```
PR A (REM-1 manual-binning gate)     ──┐
PR B (REM-2/4/7 run routes)          ──┤
PR C (REM-3 branch fallback)         ──┤── all independent, parallel
PR D (REM-5/6 collector)             ──┤
PR E (REM-10/11/12 health/export/fair)──┤
PR F (REM-8/9 executor/handler)      ──┤
PR G (TEST-1 characterization)       ──┘
```

No cross-PR dependencies. All 7 PRs can be opened concurrently. PR G
tests code from Batches 2-6 that is already merged, so it has no code
dependency on PRs A-F — but it should be merged before declaring the
sprint done.

## Definition of done

1. `compute_manual_binning_blockers` returns a blocker when
   `selected_variables` is non-empty and `variable_summaries` is empty.
2. POST `/runs` (async) returns 500 (not 201) with
   `RUN_DISPATCH_FAILED` when thread start fails.
3. POST `/runs?sync=true` returns `RUN_EXECUTION_FAILED` with context
   (not a context-free generic 500) when execution raises.
4. `_find_shared_evidence` records `INHERITED_BASELINE_EVIDENCE`
   diagnostic when falling back from source-branch to baseline.
5. Every collector `_collect_*` function appends a `Limitation` when
   the step exists but the artifact is missing.
6. `collector.py:_get_latest_review_annotation` no longer silently
   returns `None` on exception.
7. `_is_to_node_current` logs a structured warning on staleness
   failure (does not block).
8. Failed `RunStepRecord.errors[0]["code"]` reflects the classified
   category, not always `"STEP_FAILED"`.
9. `generic_exception_handler` diagnostics include `method`, `path`,
   and `str(exc)`.
10. `/health` returns `status="degraded"` with diagnostics when
    registry/nodes/governance fail to load.
11. `export_service` marks the export as partial when a branch report
    fails.
12. `fairness.py` records `TRAIN_DATA_READ_FAILED` and
    `FAIRNESS_CHECK_INCOMPLETE` warnings when train data cannot be
    read.
13. `tests/test_run_diagnostics.py` exists and covers all diagnostic
    codes listed in PR G.
14. `make lint && make typecheck && make test` all pass.
15. `frontend/src/api/schema.d.ts` regenerated if `HealthResponse`
    changed (PR E).

## Priority

Launch-blocker: REM-1 (governance gate bypass), REM-2 (misleading 201),
REM-5 (audit-pack silent omissions), REM-12 (fairness false all-clear).

Should-fix: REM-3, REM-4, REM-10, REM-11.

Nice-to-have: REM-7, REM-8, REM-9, TEST-1 (but TEST-1 is a DoD gate).