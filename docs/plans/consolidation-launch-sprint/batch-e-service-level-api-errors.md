# Batch E — Service-Level API Errors

## Goal

Make the frontend receive actionable domain error codes
(`BRANCH_NOT_FOUND`, `BASELINE_BRANCH_NOT_FOUND`, `REPORT_BLOCKED`) instead
of flattened wrappers (`EXPORT_FAILED`, `COMPARISON_FAILED`,
`READINESS_FAILED`). The central `CardreError` envelope already exists;
services just need to raise `CardreError` subclasses and routes need to stop
catching `ValueError`.

## Context you must read first

- `sidecar/error_handling.py:98` — `cardre_error_handler`. The envelope is
  good. `CardreError.to_envelope()` carries `code`, `message`, `context`,
  `diagnostics`, `status_code`.
- `cardre/errors.py` — `CardreError` base and existing subclasses
  (`BranchEvidenceError`, `GovernanceNotEnabled`, `ReportGenerationError`).
- `cardre/services/comparison_service.py:333` — `create_comparison` raises
  `ValueError(f"BASELINE_BRANCH_NOT_FOUND: {baseline_branch_id}")`.
- `sidecar/routes/comparisons.py:33` — catches `ValueError` and returns
  `code="COMPARISON_FAILED"`, discarding `BASELINE_BRANCH_NOT_FOUND`.
- `sidecar/routes/comparisons.py:91` — `REFRESH_FAILED`, same flattening.
- `cardre/services/export_service.py:51` — `raise ValueError(f"BRANCH_NOT_FOUND: ...")`.
- `sidecar/routes/exports.py:36` — catches `ValueError` as `EXPORT_FAILED`.
- `sidecar/routes/reports.py:73` — catches readiness `ValueError` as
  `READINESS_FAILED`.
- `sidecar/routes/champion.py:29` — `CHAMPION_FAILED` flattening.
- `sidecar/routes/projects.py:42` — parses colon-prefixed `ValueError` from
  `validate_project_path` into a code/status.
- `cardre/services/manual_binning_service.py` — raises
  `PlanValidationError` (subclass of `CardreError`? check) for
  `VERSION_NOT_IN_PLAN`, `PARAMS_VALIDATION_FAILED`, `REVIEW_COMPLETION_BLOCKED`.
- `docs/plans/consolidation-launch-sprint/README.md` — cross-cutting rules,
  especially rule 2: extend, do not reinvent, the error framework.

## Prerequisite

No hard dependency on Batches A-D, but coordinate with Batch C: both touch
`comparison_service.py`, `export_service.py`, and
`report_generation_service.py`. Land Batch C first, then Batch E, or split
Batch E by service so the two batches do not conflict on the same files.

## Changes

### 1. Add error subclasses

In `cardre/errors.py`, add (or confirm existing):

```python
class NotFound(CardreError):
    status_code = 404

class Conflict(CardreError):
    status_code = 409

class ValidationFailed(CardreError):
    status_code = 400
```

Keep `ReportGenerationError` as-is (`code="REPORT_BLOCKED"`,
`status_code=400`). Keep `BranchEvidenceError` as-is — it already carries
domain codes (`BRANCH_NOT_FOUND`, `BRANCH_INACTIVE`, `BRANCH_VERSION_MISMATCH`,
`SHARED_UPSTREAM_STALE`, `BRANCH_NO_OP_FAILED`).

Do not add a second envelope or a new handler. The existing
`cardre_error_handler` serializes any `CardreError` subclass automatically.

### 2. Convert comparison service

In `comparison_service.py`:

- `create_comparison:333` — replace
  `raise ValueError(f"BASELINE_BRANCH_NOT_FOUND: ...")` with
  `raise NotFound("Baseline branch not found.", code="BASELINE_BRANCH_NOT_FOUND",
  context={"branch_id": baseline_branch_id})`.
- Same for `CHALLENGER_BRANCH_NOT_FOUND:349`.
- `refresh_comparison:401` — `COMPARISON_NOT_FOUND` → `NotFound`.
- `:409` — `BASELINE_BRANCH_NOT_FOUND` → `NotFound`.

In `sidecar/routes/comparisons.py`, delete the `except ValueError` blocks at
`:33-34` and `:91-92`. Let `CardreError` propagate to the central handler.

### 3. Convert export service

In `export_service.py`:

- `:51` — `raise ValueError(f"BRANCH_NOT_FOUND: ...")` →
  `raise NotFound(..., code="BRANCH_NOT_FOUND", ...)`.
- `:57` — `PROJECT_NOT_FOUND` → `NotFound`.

In `sidecar/routes/exports.py`, delete the `except ValueError` block at
`:36-37`. Keep the `HTTPException` for `EXPORT_PATH_TRAVERSAL` at `:22` —
that is a direct HTTP concern.

### 4. Convert report readiness

In `sidecar/routes/reports.py:73`, delete the `except ValueError` block. If
`check_report_readiness` can raise `ValueError` today (it shouldn't after
Batch C), convert the source to `CardreError`. `ReportGenerationError` is
already a `CardreError`, so `generate_report` failures at `:100-154` already
flow through the central handler.

### 5. Convert champion service

In `sidecar/routes/champion.py:29`, delete the `except ValueError` block.
Convert `assign_champion` in `champion_service.py` to raise
`CardreError` subclasses (e.g. `BRANCH_NOT_FOUND` → `NotFound`,
`COMPARISON_NOT_READY` → `Conflict`).

### 6. Convert project path validation

In `sidecar/routes/projects.py:42-46`, the route parses the colon-prefixed
`ValueError` from `validate_project_path`. Move that parsing into
`validate_project_path` itself and have it raise `CardreError` subclasses
(`PROJECT_EXISTS` → `Conflict`, `DIR_EXISTS` → `Conflict`, invalid path →
`ValidationFailed`). The route becomes a straight call.

### 7. Convert manual-binning service (if not already done)

Check `ManualBinningService`. `PlanValidationError` should already be a
`CardreError` subclass; if not, make it one. Ensure
`VERSION_NOT_IN_PLAN`, `PARAMS_VALIDATION_FAILED`, `REVIEW_COMPLETION_BLOCKED`
flow through the central handler with their original codes.

The route at `sidecar/routes/plans.py` should not need `ValueError` catches
after this. Audit and remove any.

### 8. Audit all remaining `except ValueError` in routes

Grep `sidecar/routes/` for `except ValueError`. Each one should either:

- Be deleted because the service now raises `CardreError`.
- Be replaced with `except CardreError: raise` (no-op, just explicit) if the
  route adds context like `project_id`.
- Remain only for genuine legacy boundaries with a comment explaining why.

## Tests

### New: `tests/test_api_error_codes.py`

Regression tests against `detail.code` in the response body, not just status
code. Use FastAPI `TestClient`:

- Export missing branch → 404, `detail.code == "BRANCH_NOT_FOUND"`.
- Export missing project → 404, `detail.code == "PROJECT_NOT_FOUND"`.
- Comparison missing baseline → 404,
  `detail.code == "BASELINE_BRANCH_NOT_FOUND"`.
- Comparison missing challenger → 404,
  `detail.code == "CHALLENGER_BRANCH_NOT_FOUND"`.
- Refresh missing comparison → 404, `detail.code == "COMPARISON_NOT_FOUND"`.
- Report blocked by readiness → 400,
  `detail.code == "REPORT_BLOCKED"`, `detail.diagnostics` includes blocker
  codes.
- Champion missing branch → 404, `detail.code == "BRANCH_NOT_FOUND"`.
- Project path traversal → 403, `detail.code == "EXPORT_PATH_TRAVERSAL"` (this
  one stays `HTTPException` — verify it still envelopes correctly).
- Unexpected internal exception → 500,
  `detail.code == "INTERNAL_ERROR"`, `detail.request_id` present.
- Every error response has a non-empty `detail.request_id`.

### Update existing route tests

Any test that asserts `COMPARISON_FAILED`, `REFRESH_FAILED`,
`EXPORT_FAILED`, `READINESS_FAILED`, or `CHAMPION_FAILED` must be updated to
assert the new domain code. If a test was asserting the flattened code
because the service genuinely has no more specific code, keep the flattened
code but document why.

## Verification

```bash
pytest tests/test_api_error_codes.py
pytest tests/  # full suite to catch regressions
```

## Definition of done

1. `NotFound`, `Conflict`, `ValidationFailed` (or confirmed existing)
   `CardreError` subclasses exist.
2. Comparison, export, report, champion, and project-path services raise
   `CardreError` subclasses with domain codes.
3. Route-local `except ValueError` blocks are removed (or documented as
   legacy boundaries).
4. `detail.code` regression tests pass for all converted paths.
5. No error response loses its `request_id`.
6. Full test suite is green.

## Files touched

- `cardre/errors.py`
- `cardre/services/comparison_service.py`
- `cardre/services/export_service.py`
- `cardre/services/champion_service.py`
- `cardre/services/manual_binning_service.py` (if needed)
- `cardre/services/project_registry.py` (validate_project_path)
- `sidecar/routes/comparisons.py`
- `sidecar/routes/exports.py`
- `sidecar/routes/reports.py`
- `sidecar/routes/champion.py`
- `sidecar/routes/projects.py`
- `sidecar/routes/plans.py` (audit only)
- `tests/test_api_error_codes.py` (new)
- affected route tests (updated)

## Depends on

Coordinate with Batch C (shared files). No hard prerequisite on A-D.

## Unblocks

Batch H (parity tests assert domain codes).