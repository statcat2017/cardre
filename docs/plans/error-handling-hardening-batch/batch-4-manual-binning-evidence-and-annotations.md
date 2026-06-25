# Batch 4 — Manual-binning evidence and annotation diagnostics

## Goal

Replace free-text manual-binning preview/editor diagnostics with
structured codes, surface corrupt upstream evidence and review
annotations as visible warnings, narrow the `PLAN-1` `except KeyError:
pass` to the single call that can actually raise it, and render
structured errors in all four `updateStepParams` caller components.

## Findings addressed

- **PLAN-1** — unknown node type during parameter validation raises
  `NODE_TYPE_NOT_REGISTERED` with a narrowed `try`; no validation skip.
- **MB-1** — editor-state blockers gain structured `code`,
  `required_steps`, and context (graceful state kept, free text
  machine-actionable).
- **MB-2** — variable-summary failures include artifact id, step id,
  exception category, and branch/run context.
- **MB-3** — `EvidenceError` becomes
  `MANUAL_BINNING_UPSTREAM_EVIDENCE_UNREADABLE` with artifact id and
  schema context.
- **MB-4** — `_get_latest_review_annotation` stops hiding
  read/JSON errors; returns editor state with
  `REVIEW_ANNOTATION_UNREADABLE` warning.
- **MB-5** — preview diagnostics become structured
  `{code, message, step_id, artifact_id}`.
- **FE-4** (completion) — all four `updateStepParams` callers
  (`ManualBinningEditDialog`, `SchemaDrivenParamsEditor`,
  `RawJsonParamsFallback`, `ParamsEditor`) render structured `ApiError`
  detail (code/context/diagnostics), not just `err?.message`.

## Context you must read first

- `cardre/services/plan_service.py:226-244` — the `try/except KeyError:
  pass` around schema validation + `validate_params` + the
  `PlanValidationError` raises. This is the PLAN-1 site.
- `cardre/services/manual_binning_service.py:86-307` —
  `get_editor_state`; the `_get_latest_review_annotation` call at line
  200 runs **before** the editor-state `try` at 230.
- `cardre/services/manual_binning_service.py:580-597` —
  `_get_latest_review_annotation` catches all exceptions and returns
  `None`.
- `cardre/services/manual_binning_service.py:506-547` —
  `_resolve_upstream_defs` returns `((None,None,None,None), error_msg)`
  tuple; the `EvidenceError` catch at 546 produces a generic string.
- `cardre/services/manual_binning_service.py:309-374` —
  `preview_overrides` returns `PreviewDiagnostics(warnings=[str, ...])`
  with free-text strings.
- `frontend/src/components/ManualBinningEditDialog.tsx:103,134` —
  `err?.status === 409 && err?.detail?.code === "STALE_VERSION"`,
  fallback `err?.message || "Save failed"`.
- `frontend/src/components/SchemaDrivenParamsEditor.tsx:253-262`,
  `RawJsonParamsFallback.tsx:46-55`, `ParamsEditor.tsx:48-57` — the other
  three `updateStepParams` callers.
- `cardre/errors.py` — `Result`, `Diagnostic`, `CardreError`,
  `ArtifactReadError` (from Batch 0).
- `sidecar/models.py` — `ManualBinningEditorStateResponse`,
  `ManualBinningPreviewResponse`, `PreviewDiagnostics`.
- `docs/plans/error-handling-hardening-batch/README.md` — cross-cutting
  rules (narrow `try`; diagnostics carry context; 600-line ceiling).

## Changes

### 1. PLAN-1 — narrow the `try` and raise `NODE_TYPE_NOT_REGISTERED`

`plan_service.py:226-244` currently wraps schema validation, custom
`validate_params`, **and** the `PlanValidationError` raises in one
`try/except KeyError: pass`. The `KeyError` can come from
`registry.instantiate(target_step.node_type)` (unknown node type) **or**
from inside `validate_against_schema`/`node.validate_params` (node
looking up a registry key) **or** while constructing the
`PlanValidationError` message.

Narrow to:

```python
try:
    node = self._registry.instantiate(target_step.node_type)
except KeyError:
    raise PlanValidationError(
        "NODE_TYPE_NOT_REGISTERED",
        f"Node type {target_step.node_type!r} is not registered; cannot validate params.",
        status_code=400,
        context={"step_id": step_id, "node_type": target_step.node_type},
    )
schema = node.parameter_schema()
new_params = merge_defaults(schema, new_params)
schema_errors = validate_against_schema(schema, new_params)
if schema_errors:
    raise PlanValidationError("PARAMS_VALIDATION_FAILED", "; ".join(schema_errors))
custom_errors = node.validate_params(new_params)
if custom_errors:
    raise PlanValidationError("PARAMS_VALIDATION_FAILED", "; ".join(custom_errors))
```

The `try` covers **only** `instantiate`. A `KeyError` from
`validate_against_schema` or `validate_params` now propagates as an
unexpected error (correct — it indicates a node bug, not user input).

### 2. MB-3 — `_resolve_upstream_defs` returns `Result` with structured context

Convert `_resolve_upstream_defs` to return `Result[tuple[bin_def, vs_def,
bin_artifact_id, vs_artifact_id]]`:

```python
def _resolve_upstream_defs(self, plan_version_id, plan_id, *, bin_step_id,
                           vs_step_id, branch_id=None) -> Result[tuple]:
    # ... _find_run_step unchanged ...
    if bin_rs is None or vs_rs is None:
        return Fail([Diagnostic(
            code="MANUAL_BINNING_UPSTREAM_NOT_RUN",
            message="Run binning and variable-selection before editing manual bins.",
            context={"bin_step_id": bin_step_id, "vs_step_id": vs_step_id, "branch_id": branch_id},
        )])
    bin_artifact_id = bin_rs.output_artifact_ids[0] if bin_rs.output_artifact_ids else None
    vs_artifact_id = vs_rs.output_artifact_ids[0] if vs_rs.output_artifact_ids else None
    if bin_artifact_id is None or vs_artifact_id is None:
        return Fail([Diagnostic(
            code="MANUAL_BINNING_UPSTREAM_NO_OUTPUT",
            message="Binning or variable-selection produced no output artifacts.",
            context={"bin_run_step_id": bin_rs.run_step_id, "vs_run_step_id": vs_rs.run_step_id},
        )])
    try:
        reader = ArtifactEvidenceReader(self._store)
        bin_def = reader.read(bin_artifact_id, EvidenceKind.BIN_DEFINITION)
        vs_def = reader.read(vs_artifact_id, EvidenceKind.SELECTION_DEFINITION)
        return Ok((bin_def.to_dict(), vs_def.to_dict(), bin_artifact_id, vs_artifact_id))
    except EvidenceError as e:
        return Fail([Diagnostic(
            code="MANUAL_BINNING_UPSTREAM_EVIDENCE_UNREADABLE",
            message=f"Could not read binning or variable-selection artifact: {e}",
            source="manual_binning_service._resolve_upstream_defs",
            exception_type=e.__class__.__name__,
            context={"bin_artifact_id": bin_artifact_id, "vs_artifact_id": vs_artifact_id,
                     "bin_step_id": bin_step_id, "vs_step_id": vs_step_id, "branch_id": branch_id},
        )])
```

Update callers (`get_editor_state` line 163, `preview_overrides` line 349,
`validate_overrides` line 390) to consume the `Result`:

- `get_editor_state`: on `Fail`, return
  `ManualBinningEditorStateResponse(ready=False, blocked_code=diag.code,
  blocked_reason=diag.message, required_steps=[...], diagnostics=[diag])`.
- `preview_overrides`: on `Fail`, return `ManualBinningPreviewResponse(
  valid=False, diagnostics=PreviewDiagnostics(override_count=0,
  warnings=[], structured=[diag]))`.
- `validate_overrides`: on `Fail`, raise `PlanValidationError(
  diag.code, diag.message, context=diag.context)`.

### 3. MB-1 — editor-state blockers are structured

`ManualBinningEditorStateResponse` gains:

```python
blocked_code: str | None = None        # e.g. "MANUAL_BINNING_UPSTREAM_NOT_RUN"
required_steps: list[str] = []
context: dict[str, Any] = {}
```

Each `return ManualBinningEditorStateResponse(ready=False, ...)` site in
`get_editor_state` (lines 96, 103, 117, 123, 141, 157, 167) sets
`blocked_code` (e.g. `PLAN_NOT_FOUND`, `PLAN_NO_VERSIONS`,
`MANUAL_BINNING_STEP_NOT_FOUND`, `STEP_NOT_MANUAL_BINNING`,
`BINNING_NOT_ANCESTOR`, `UPSTREAM_STALE`,
`MANUAL_BINNING_UPSTREAM_EVIDENCE_UNREADABLE`) and `context`.

Keep `blocked_reason` as the human-readable string for backward compat,
but `blocked_code` is now the machine-actionable field the UI switches
on.

### 4. MB-4 — `_get_latest_review_annotation` surfaces errors

`_get_latest_review_annotation` (line 580) currently returns `None` on
any exception. Change to return a `Result[dict | None]`:

```python
def _get_latest_review_annotation(store, step_id, plan_version_id) -> Result[dict | None]:
    try:
        with store.transaction() as conn:
            rows = conn.execute(...).fetchall()
        if not rows: return Ok(None)
        payload = json.loads(rows[0]["payload_json"])
        payload["created_at"] = rows[0]["created_at"]
        return Ok(payload)
    except Exception as e:
        return Degraded(None, [Diagnostic(
            code="REVIEW_ANNOTATION_UNREADABLE",
            message=f"Corrupt review annotation for step {step_id}: {e}",
            severity="warning",
            context={"step_id": step_id, "plan_version_id": plan_version_id},
        )])
```

`get_editor_state` (line 200) consumes the result:

```python
annotation_r = _get_latest_review_annotation(self._store, step_id, latest_pv_id)
annotation = annotation_r.value if is_ok(annotation_r) else None
# attach annotation_r.diagnostics to result.warnings when Degraded
```

A corrupt annotation no longer silently nulls `reviewed_at`/
`reviewed_by`/`review_reason`; the editor loads as `ready=True` but with
a `REVIEW_ANNOTATION_UNREADABLE` warning in `warnings`, and the audit
fields are `None` with the warning explaining why.

### 5. MB-2 — variable-summary failure context

`get_editor_state` lines 281-286 catch all exceptions and append a
`VARIABLE_SUMMARY_UNAVAILABLE` warning with a generic message. Widen the
warning to include context:

```python
except Exception as e:
    warnings.append({
        "code": "VARIABLE_SUMMARY_UNAVAILABLE",
        "message": "Variable summary could not be loaded — WOE/IV evidence may be missing or stale.",
        "context": {
            "step_id": step_id,
            "plan_version_id": latest_pv_id,
            "branch_id": branch_id,
            "exception_type": e.__class__.__name__,
        },
    })
```

If the WOE/IV artifact id is known at the catch site, include it in
`context.artifact_id`.

### 6. MB-5 — preview diagnostics structured

`PreviewDiagnostics` gains:

```python
structured: list[dict] = []   # list of {code, message, step_id, artifact_id}
```

`preview_overrides` populates `structured` for each failure path:

- `STEP_NOT_FOUND` → `{"code":"MANUAL_BINNING_STEP_NOT_FOUND",
  "message":..., "step_id": step_id}`.
- Upstream `Fail` → forward the `Diagnostic` as a structured entry with
  `artifact_id` from the diagnostic context.
- `validate_manual_binning_overrides` warnings → each string becomes a
  structured entry with `code="OVERRIDE_VALIDATION_WARNING"` and
  `step_id`.

Keep `warnings` (strings) for backward compat; `structured` is the new
canonical field.

### 7. `sidecar/routes/plans.py` — propagate diagnostics

`get_manual_binning_editor_state` (line 67-71),
`preview_manual_binning_overrides` (74-79),
`review_manual_binning` (82-110): let `PlanValidationError` propagate
to the Batch 0 handler (it serialises `code`/`context`/`diagnostics`).
Do not catch it locally.

### 8. FE-4 — frontend structured error rendering

Add a shared `renderApiError(err: unknown): { code, message, context,
diagnostics } | null` helper in `frontend/src/utils/errors.ts` (new
file, under the 600-line ceiling). It uses `isApiError(e)` from Batch 1
and returns a structured object or `null`.

Update the four `updateStepParams` callers:

- `ManualBinningEditDialog.tsx:103,134` — replace
  `setError(err?.message || "Save failed")` with:
  ```ts
  const apiErr = renderApiError(err);
  setError(apiErr ? `${apiErr.code}: ${apiErr.message}` : "Save failed");
  if (apiErr?.context) setErrContext(apiErr.context);  // optional: show context
  if (apiErr?.diagnostics?.length) setErrDiagnostics(apiErr.diagnostics);
  ```
- `SchemaDrivenParamsEditor.tsx:253-262` — same pattern.
- `RawJsonParamsFallback.tsx:46-55` — same pattern.
- `ParamsEditor.tsx:48-57` — same pattern.

Add a small `ErrorDetail` component (new file) that renders
`code`/`message`/`context`/expandable `diagnostics` and is reused by all
four callers. Keep it under 100 lines.

The existing `STALE_VERSION` special-case at `e?.status === 409 && ...
=== "STALE_VERSION"` is preserved; it runs before the generic
`renderApiError` fallback so the "refreshing…" UX is unchanged.

## Tests

Backend (`tests/test_manual_binning_phase*.py`):
- Unknown node type in `PlanService.update_params` raises
  `PlanValidationError("NODE_TYPE_NOT_REGISTERED")` with `context.node_type`;
  no validation skip.
- Corrupt bin-definition artifact → `get_editor_state` returns
  `ready=False`, `blocked_code="MANUAL_BINNING_UPSTREAM_EVIDENCE_UNREADABLE"`,
  `context.bin_artifact_id` set.
- Corrupt review annotation row → `get_editor_state` returns `ready=True`
  with a `REVIEW_ANNOTATION_UNREADABLE` warning; `reviewed_at`/`reviewed_by`
  are `None`.
- `preview_overrides` with a missing step returns `valid=False` with a
  structured `MANUAL_BINNING_STEP_NOT_FOUND` entry in
  `diagnostics.structured` (not just a string in `warnings`).
- Variable-summary failure (monkeypatch `reader.read` to raise) →
  warning has `context.step_id`, `context.plan_version_id`,
  `context.exception_type`.
- `validate_overrides` with a `Fail` upstream result raises
  `PlanValidationError` with the diagnostic's `code` and `context`.

Frontend:
- `renderApiError(new ApiError(400, {code:"PARAMS_VALIDATION_FAILED",
  message:"X", context:{step_id:"y"}}))` returns the structured object.
- `renderApiError(new Error("x"))` returns `null`.
- `ErrorDetail` renders `code`, `message`, and an expandable
  `diagnostics` section; snapshot test.
- `ManualBinningEditDialog` journey: a save that fails with
  `PARAMS_VALIDATION_FAILED` shows `PARAMS_VALIDATION_FAILED: <message>`,
  not just `err.message`.

## Acceptance criteria

- `rg "except KeyError:\s*pass" cardre/services/plan_service.py` returns
  zero matches.
- `ManualBinningEditorStateResponse` has `blocked_code`, `required_steps`,
  `context` fields; frontend types regenerated.
- `PreviewDiagnostics` has `structured` field; frontend types regenerated.
- `_get_latest_review_annotation` no longer silently returns `None` on
  corruption; a `REVIEW_ANNOTATION_UNREADABLE` warning is attached.
- `_resolve_upstream_defs` returns `Result`; callers consume it via
  `is_ok`/`is_fail`/`is_degraded`.
- All four `updateStepParams` callers use `renderApiError` and show
  structured errors.
- `make lint && make typecheck && make test` pass.
- `frontend/src/api/schema.d.ts` regenerated and committed.

## Out of scope

- Report metadata corruption vs missing (Batch 5).
- Branch-evidence typed errors (Batch 6).
- Workflow guidance degraded-state UI rendering beyond what Batch 3
  already emits.