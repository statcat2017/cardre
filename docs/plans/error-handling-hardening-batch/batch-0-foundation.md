# Batch 0 — Foundation: `CardreError` attributes, `Result`, envelope, request id

## Goal

Deliver the two architectural refactors that every subsequent batch
depends on, plus the request-id middleware and dead-table cleanup. After
this batch, every new error type inherits a standard envelope for free and
every "degrade gracefully" call site has a mechanical `Result` helper
instead of a hand-rolled `(value, error)` tuple or `try/except: pass`.

This is the **only** batch that touches error infrastructure broadly.
Batches 1-6 consume these primitives; they do not redefine them.

## Findings addressed

- **MAIN-1, MAIN-2** — request id middleware + unified exception envelope.
- **Foundation for**: WG-1…WG-7, RO-1…RO-3, RUN-1…RUN-4, FE-1…FE-4,
  EXE-1…EXE-3, LIFE-1…LIFE-3, PLAN-1, MB-2…MB-4, REP-1…REP-4, BR-1…BR-3,
  ST-1.

## Context you must read first

- `cardre/errors.py` — current 11 `CardreError` subclasses are bare
  `pass` classes with no attributes. This batch adds the attributes.
- `sidecar/main.py:39-65` — the five per-type exception handlers this
  batch replaces with one `CardreError` handler plus a generic fallback.
- `cardre/store/schema.py:87-101` — the unused `errors` and `warnings`
  tables. Confirm with `rg "INSERT INTO errors|INSERT INTO warnings|
  FROM errors|FROM warnings" cardre/ sidecar/ tests/` that there are no
  readers/writers before dropping.
- `cardre/services/manual_binning_service.py:506-547` —
  `_resolve_upstream_defs` returns `((None, None, None, None), error_msg)`,
  the canonical hand-rolled tuple this batch replaces with `Result`.
- `docs/adr/0004-single-run-lifecycle-atomic-finalisation.md` —
  finalisation ordering rationale; this batch's `Result` does not change
  it but must coexist.
- `docs/plans/error-handling-hardening-batch/README.md` — sprint-level
  validation context and cross-cutting rules.

## Architectural refactors

### Refactor 1 — `CardreError` with attributes

Make `CardreError` carry the envelope fields as instance attributes, so
a single FastAPI handler serialises **any** `CardreError` subclass
without per-type handlers.

New `cardre/errors.py` shape (sketch — final signatures are your
responsibility, keep them minimal and typed):

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Diagnostic:
    code: str
    message: str
    source: str | None = None
    exception_type: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

class CardreError(Exception):
    """Base for all typed Cardre errors.

    Subclasses set a default `code` and `status_code`; callers pass
    `message`, `context`, `recoverable`, `severity`, and `diagnostics`
    at construction. A single FastAPI handler serialises any subclass
    into the standard envelope.
    """
    code: str = "CARDRE_ERROR"
    status_code: int = 500
    severity: str = "error"
    recoverable: bool = False

    def __init__(
        self,
        message: str | None = None,
        *,
        context: dict[str, Any] | None = None,
        recoverable: bool | None = None,
        severity: str | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.context = context or {}
        if recoverable is not None: self.recoverable = recoverable
        if severity is not None: self.severity = severity
        self.diagnostics = diagnostics or []

    def to_envelope(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "severity": self.severity,
            "context": self.context,
            "diagnostics": [dataclasses.asdict(d) for d in self.diagnostics],
        }
```

Rules:
- Each existing subclass (`GraphValidationError`, `MissingInputArtifactError`,
  `ParameterValidationError`, `ArtifactReadError`, `ArtifactWriteError`,
  `NodeExecutionError`, `ContractViolationError`, `NodeNotAvailableForLaunch`,
  `GovernanceNotEnabled`, `ConcurrentRunError`, `SchemaVersionError`) gets
  a class-level `code` and `status_code` default. Do not give them
  per-instance `code` unless they already carry one.
- `PlanValidationError` (in `cardre/services/__init__.py` or wherever the
  import in `sidecar/main.py:18` resolves) becomes a `CardreError`
  subclass with `code="PLAN_VALIDATION_FAILED"` and `status_code=400`.
  Preserve its existing `extra` kwarg by mapping it into `context`.
- `RoleAccessError` (`cardre/executor.py:744`) changes base class from
  `ValueError` to `CardreError` with `code="ROLE_ACCESS_ERROR"`,
  `status_code=400`, `severity="error"`, `recoverable=False`. It must
  remain importable from `cardre.executor` for the existing import sites.
  Add `LeakageProtectionError(CardreError)` with
  `code="LEAKAGE_PROTECTION_ERROR"` and route the leakage branch of
  `validate_leakage_rules` (`executor.py:523`) to raise it; keep
  `RoleAccessError` for the role-mismatch branches.
- Add `BranchValidationError(CardreError)` (`code="BRANCH_VALIDATION_ERROR"`,
  `status_code=400`) and `BranchEvidenceError(CardreError)`
  (`code="BRANCH_EVIDENCE_ERROR"`, `status_code=409`) for Batch 6. Do
  not use them yet — only declare them.
- Add `RunLifecycleError(CardreError)` (`code="RUN_LIFECYCLE_ERROR"`,
  `status_code=500`) for Batch 6's `RUN_RECORD_MISSING`.
- Do **not** delete the existing subclass names; services and tests
  import them. Only widen their bases and add attributes.

### Refactor 2 — `Result[T, Diagnostic]`

Add a discriminated-union `Result` that makes the fail-hard-vs-degrade
rule mechanical. Every helper that can fail returns `Result`; the caller
declares policy via `.unwrap_or_raise()` (fail hard) or
`.unwrap_or_degrade(default, diagnostic)` (degrade visibly).

```python
from typing import Generic, TypeVar, Union
import dataclasses

T = TypeVar("T")

@dataclasses.dataclass
class Ok(Generic[T]):
    value: T
    diagnostics: list[Diagnostic] = dataclasses.field(default_factory=list)

@dataclasses.dataclass
class Degraded(Generic[T]):
    value: T                       # the degraded default
    diagnostics: list[Diagnostic]  # non-empty; explains the degradation

@dataclasses.dataclass
class Fail:
    diagnostics: list[Diagnostic]   # non-empty; the error(s)

Result = Union[Ok[T], Degraded[T], Fail]

def is_ok(r: Result) -> bool: return isinstance(r, Ok)
def is_degraded(r: Result) -> bool: return isinstance(r, Degraded)
def is_fail(r: Result) -> bool: return isinstance(r, Fail)

def unwrap_or_raise(r: Result) -> Any:
    """Fail-hard policy: raise the first diagnostic as a CardreError."""
    if isinstance(r, Ok): return r.value
    if isinstance(r, Degraded): return r.value   # degraded is still usable
    d = r.diagnostics[0]
    raise CardreError(d.message, code=d.code, context=d.context,
                      diagnostics=r.diagnostics)

def unwrap_or_degrade(r: Result, default: Any, diagnostic: Diagnostic | None = None) -> Any:
    """Degrade-gracefully policy: return default + diagnostic(s)."""
    if isinstance(r, Ok): return r.value
    if isinstance(r, Degraded): return r.value
    extra = [diagnostic] if diagnostic else []
    return default  # caller is responsible for collecting r.diagnostics + extra
```

Rules:
- `Result` is **opt-in**. Do not retro-fit every function in the
  codebase in this batch. Wire it only where subsequent batches need it:
  `_resolve_upstream_defs`, `compute_staleness` callers, readiness
  checks, manifest write. Other call sites migrate as their batch lands.
- `Degraded.value` is the degraded default (e.g. empty staleness map);
  callers must still surface `Degraded.diagnostics`.
- `Fail` carries no value — it must be raised or converted to a
  degraded value by an explicit decision.
- Do not introduce a `try/except` that converts `Fail` to `Degraded`
  silently; the conversion must be explicit via `unwrap_or_degrade`.

## Changes

### 1. `cardre/errors.py` — widen base + add `Result` + `Diagnostic`

Implement Refactor 1 and Refactor 2 above. Keep `__all__` updated.
Add `Diagnostic`, `Ok`, `Degraded`, `Fail`, `Result`, `unwrap_or_raise`,
`unwrap_or_degrade`, `is_ok`, `is_degraded`, `is_fail` to `__all__`.

### 2. `sidecar/error_handling.py` — new module

Create the single envelope normaliser. This module owns:

- `ApiErrorEnvelope` Pydantic model (the `detail` shape).
- `render_error(exc, request_id, error_id) -> JSONResponse` — the one
  function that maps any exception to the envelope.
- `cardre_error_handler(request, exc)` — serialises `CardreError` via
  `exc.to_envelope()`, adds `request_id` and `error_id`, returns
  `JSONResponse(status_code=exc.status_code, content={"detail": envelope})`.
- `http_exception_handler(request, exc)` — normalises `HTTPException`:
  if `exc.detail` is a dict with `code`+`message`, wrap it; if it is a
  string, map to `code="HTTP_ERROR"`, `message=detail`; add request id
  and error id; preserve the original status code.
- `request_validation_error_handler(request, exc)` — maps FastAPI's
  `RequestValidationError` to `code="VALIDATION_ERROR"`,
  `status_code=422`, `message="Request validation failed."`, with the
  pydantic errors in `diagnostics`. **This must not leak the default
  FastAPI shape** (array of `{loc, msg, type}`) as the top-level `detail`
  — wrap it inside `detail.diagnostics` so frontend `fetchJson`'s
  `ApiError` parsing still works.
- `generic_exception_handler(request, exc)` — maps any other
  `Exception` to `code="INTERNAL_ERROR"`, `status_code=500`,
  `message="An internal error occurred."`, with the exception type and
  a short message in `diagnostics` (not the full traceback — that goes
  to logs). Log the full traceback server-side with the request id.
- `RequestContextMiddleware` — generates `X-Cardre-Request-Id` (UUID4
  if the inbound `X-Cardre-Request-Id` header is absent, else echo it),
  stores it on `request.state.request_id`, sets the response header,
  and logs `method path status elapsed request_id`.

Envelopes:

```json
{
  "detail": {
    "code": "RUN_DISPATCH_FAILED",
    "message": "Run could not be started.",
    "recoverable": true,
    "severity": "error",
    "context": { "project_id": "...", "run_id": "..." },
    "diagnostics": [
      { "code": "THREAD_START_FAILED", "message": "...",
        "source": "sidecar.routes.runs", "exception_type": "RuntimeError" }
    ],
    "request_id": "...",
    "error_id": "..."
  }
}
```

Rules:
- `message` is user-readable; never include a raw traceback.
- `code` is stable and testable; snake-case UPPER.
- `context` contains ids needed to recover.
- `diagnostics` contains developer-facing structured detail; each entry
  has at least `code` and `message`.
- Every response (success and error) includes `X-Cardre-Request-Id`.

### 3. `sidecar/main.py` — wire the handlers and middleware

Replace the five per-type exception handlers (lines 48-65) with:

```python
from sidecar.error_handling import (
    RequestContextMiddleware, cardre_error_handler, http_exception_handler,
    request_validation_error_handler, generic_exception_handler,
)
from cardre.errors import CardreError
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException

app.add_middleware(RequestContextMiddleware)
app.add_exception_handler(CardreError, cardre_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_error_handler)
app.add_exception_handler(Exception, generic_exception_handler)
```

Remove the now-redundant `plan_validation_error_handler`,
`project_not_found_handler`, `project_path_missing_handler`,
`concurrent_run_handler`. They are subsumed because `PlanValidationError`,
`ProjectNotFoundError`, `ProjectPathMissingError`, `ConcurrentRunError`
are all `CardreError` subclasses after step 1.

Keep the `log_requests` middleware? No — `RequestContextMiddleware`
subsumes logging; remove `log_requests` to avoid double logging.

### 4. `sidecar/models.py` — add run-level diagnostic models (forward decl)

Add Pydantic models for run diagnostics that Batch 2 will populate:

```python
class RunDiagnostic(BaseModel):
    code: str
    message: str
    severity: str = "error"
    category: str | None = None
    exception_type: str | None = None
    run_id: str
    plan_version_id: str | None = None
    branch_id: str | None = None
    step_id: str | None = None
    traceback: str | None = None
    created_at: str

class RunResponse(BaseModel):
    # ... existing fields ...
    diagnostics: list[RunDiagnostic] = []
    latest_error: RunDiagnostic | None = None
```

Regenerate `frontend/src/api/schema.d.ts` and commit the diff.

### 5. `cardre/store/schema.py` — drop dead tables

Remove the `errors` and `warnings` table definitions (lines 87-101).
Add a migration entry to the store's migration mechanism (see
`cardre/store/schema.py` migration helpers / `store_meta` version bump)
that drops the tables if they exist:

```sql
DROP TABLE IF EXISTS errors;
DROP TABLE IF EXISTS warnings;
```

Bump `store_meta` schema version. Existing projects will auto-migrate on
open. Confirm no code references these tables (`rg` in README context).

### 6. `docs/adr/0009-typed-errors-and-result.md` — record the decision

New ADR recording:
- One `CardreError` hierarchy with attributes; one FastAPI handler.
- `Result[T, Diagnostic]` as the mechanical fail-hard/degrade tool.
- `runs.metadata_json.diagnostics` (Batch 2) as the diagnostic store —
  note this is the chosen path over a new table, for zero-migration
  consistency with `run_steps.errors_json`.
- Drop of unused `errors`/`warnings` tables.

## Tests

Add to `tests/test_api_contracts.py` (or a new `tests/test_error_envelope.py`):

- `CardreError` subclass serialises with its class-level `code`/`status_code`
  and per-instance `message`/`context`/`recoverable`/`severity`/`diagnostics`.
- `PlanValidationError(code="X", message="Y", status_code=400, extra={...})`
  maps to a 400 with `detail.code == "X"`, `detail.context` containing the
  `extra` payload, and a `request_id`.
- `HTTPException(status_code=404, detail={"code":"X","message":"Y"})`
  preserves status and shape, adds `request_id`/`error_id`.
- `HTTPException(status_code=400, detail="RUN_FAILED")` (string detail)
  maps to `detail.code="HTTP_ERROR"`, `detail.message="RUN_FAILED"`.
- `RequestValidationError` maps to 422 with `detail.code="VALIDATION_ERROR"`
  and pydantic errors inside `detail.diagnostics` (not top-level).
- A route raising a generic `RuntimeError` returns 500 with
  `detail.code="INTERNAL_ERROR"` and a non-empty `request_id`; the full
  traceback is logged, not in the body.
- Every response (success via a `GET /health` and error via a forced 500)
  has `X-Cardre-Request-Id`.
- Inbound `X-Cardre-Request-Id` header is echoed on the response.
- `Result` helpers: `unwrap_or_raise(Ok(1)) == 1`;
  `unwrap_or_raise(Fail([Diagnostic("X","y")]))` raises `CardreError`;
  `unwrap_or_degrade(Fail([...])), default=0)` returns `0`.
- Dropping `errors`/`warnings`: a fresh project store opens without those
  tables; an old store with them opens and drops them; both still
  read/write runs and run_steps.

Frontend (in `frontend/src/api/__tests__/`):
- `ApiError` is exported from `client.ts` (compile-time check via import).
- A typed `isApiError(e: unknown): e is ApiError` guard exists and narrows.

## Acceptance criteria

- `sidecar/main.py` has exactly four exception handlers:
  `CardreError`, `HTTPException`, `RequestValidationError`, `Exception`.
- No per-type handler remains; no `plan_validation_error_handler`,
  `project_not_found_handler`, `project_path_missing_handler`,
  `concurrent_run_handler`.
- `RequestContextMiddleware` runs for every request; `X-Cardre-Request-Id`
  is present on every response; inbound id is echoed.
- `cardre/errors.py` exports `Diagnostic`, `Ok`, `Degraded`, `Fail`,
  `Result`, `unwrap_or_raise`, `unwrap_or_degrade`, `is_ok`,
  `is_degraded`, `is_fail`, plus the widened `CardreError` hierarchy.
- `RoleAccessError` and `LeakageProtectionError` are `CardreError`
  subclasses importable from `cardre.executor` (existing import sites
  unchanged).
- `PlanValidationError` is a `CardreError` subclass; its `extra` kwarg
  maps into `context`.
- `errors` and `warnings` tables are dropped; schema version bumped;
  old stores migrate cleanly.
- `make lint && make typecheck && make test` pass.
- `frontend/src/api/schema.d.ts` regenerated and committed.
- ADR 0009 merged.
- No behaviour change for end users yet — this batch is plumbing. The
  existing `HTTPException`-raising routes still produce their current
  status codes; only the envelope shape is unified and gains
  `request_id`/`error_id`.

## Out of scope for this batch

- Migrating any specific call site to `Result` (done in Batches 3-6).
- Adding run-level diagnostic storage writes (Batch 2).
- Changing any `try/except: pass` (Batches 3-6).
- Frontend error display (Batch 1).
- Branch typed errors usage (Batch 6).

## Risks

- **Migration risk**: dropping tables requires a schema-version bump
  and a clean migration path for existing local projects. Test with an
  old fixture store if one exists in `tests/fixtures/`; otherwise
  construct one inline in the migration test.
- **`RoleAccessError` base-class change** could break `isinstance`
  checks in `executor.py:381-396` category map. The map checks
  `isinstance(exc_value, exc_cls)` for `CardreError` last; after this
  batch `RoleAccessError` would match `CardreError` and never reach a
  more specific category. **Fix**: add `RoleAccessError` and
  `LeakageProtectionError` to the `_CATEGORY_MAP` **before** the
  `CardreError` catch-all, and re-order so specific classes come first.
  This is a within-batch consistency fix, not a follow-up.
- **`PlanValidationError` `extra` → `context` mapping** must preserve the
  `STALE_VERSION` flow used by frontend `ParamsEditor.tsx:48` etc. Verify
  the frontend's `e?.detail?.code === "STALE_VERSION"` still resolves —
  `code` is unchanged, `extra` becomes `context`, so the frontend
  pattern-match on `code` is unaffected. Confirm with a journey test.