# Batch 5 — Report readiness and metadata hardening

## Goal

Make report metadata write failure fail generation, make corrupt metadata
distinguishable from a missing report, carry structured readiness blockers
through to the API, and fail hard on out-of-project report paths. After
this batch, a report cannot be generated without persisted metadata,
corrupt metadata is visible (not a 404), and report blockers are
actionable in the UI.

## Findings addressed

- **REP-1** — `_save_metadata` OSError fails report generation with
  `REPORT_METADATA_WRITE_FAILED`.
- **REP-2** — `_load_metadata` corruption returns
  `REPORT_METADATA_UNREADABLE`, not 404; list endpoint skips with a
  visible warning.
- **REP-3** — `ReportGenerationError` carries structured blockers
  (`code`/`message`/`step_id`), not `list[str]`; route preserves them.
- **REP-4** — report paths outside project root fail hard with
  `REPORT_PATH_OUTSIDE_PROJECT`.

## Context you must read first

- `sidecar/routes/reports.py:27-47` — `_metadata_path`,
  `_save_metadata` (swallows `OSError`), `_load_metadata` (returns
  `None` on `OSError`/`JSONDecodeError`).
- `sidecar/routes/reports.py:86-139` — `generate_report`; the
  `except ReportGenerationError` at 103; `_save_metadata` at 130 is
  **after** the try (Batch 1 moved it inside / wrapped it; this batch
  makes it fail generation).
- `sidecar/routes/reports.py:142-187` — `list_run_reports` and
  `get_report_metadata`; `_load_metadata` returning `None` becomes a 404
  for corrupt metadata.
- `sidecar/routes/reports.py:190-234` — `serve_report_file`; the
  `PATH_TRAVERSAL` guard at 214 already works; REP-4's real target is the
  `relative_to()` fallback in `report_generation_service.py:148-161`.
- `cardre/services/report_generation_service.py:26-30` —
  `ReportGenerationError.__init__(message, blockers: list[str])` — the
  single construction site is `generate_and_write` at line 90.
- `cardre/services/report_generation_service.py:89-93` —
  `blockers=[str(b.code) for b in readiness.blockers]` discards
  `message`/`step_id`.
- `cardre/services/report_generation_service.py:148-161` — three
  `try/except ValueError: <abs fallback>` blocks for `relative_to()`.
- `cardre/readiness/dto.py:10-31` — `ReadinessBlocker` has
  `code`/`message`/`step_id`.
- `sidecar/models.py` — `ReadinessItem`, `GenerateReportResponse`,
  `ReportReadinessResponse`.
- `docs/plans/error-handling-hardening-batch/README.md` — cross-cutting
  rules (fail hard on artifact read/write; diagnostics carry context).

## Changes

### 1. REP-1 — `_save_metadata` failure fails generation

`sidecar/routes/reports.py:31-37`:

```python
def _save_metadata(project_root, report_id, meta):
    path = _metadata_path(project_root, report_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(meta, indent=2, sort_keys=True))
    except OSError as e:
        raise CardreError(
            "REPORT_METADATA_WRITE_FAILED",
            message=f"Could not write report metadata: {e}",
            context={"report_id": report_id, "path": str(path), "run_id": meta.get("run_id")},
            status_code=500,
        ) from e
```

In `generate_report` (line 86-139), move `_save_metadata(store.root,
report_id, meta)` **inside** the `try` block (Batch 1 may have already
wrapped it; ensure it now raises `CardreError` rather than being
swallowed). The report bundle is already written at this point; the
metadata write failure means the report exists on disk but is
unlistable/untraceable. **Decision**: fail the generation request with
500 `REPORT_METADATA_WRITE_FAILED` and include `report_id` in
`context` so the user can locate the orphaned bundle manually. Do not
attempt to delete the orphaned bundle in this batch (cleanup tooling is
out of scope).

### 2. REP-2 — `_load_metadata` distinguishes corrupt from missing

`sidecar/routes/reports.py:40-47`:

```python
def _load_metadata(project_root, report_id) -> dict | None:
    """Return metadata dict, or None if absent.

    Raises CardreError(REPORT_METADATA_UNREADABLE) if the file exists
    but cannot be parsed.
    """
    path = _metadata_path(project_root, report_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise CardreError(
            "REPORT_METADATA_UNREADABLE",
            message=f"Report metadata for {report_id} is corrupt: {e}",
            context={"report_id": report_id, "path": str(path)},
            status_code=500,
        ) from e
```

`get_report_metadata` (line 171-187): the `if meta is None` 404 stays
for genuinely missing reports. The `REPORT_METADATA_UNREADABLE`
`CardreError` propagates to the Batch 0 handler and returns a 500 with
the diagnostic — corrupt metadata is no longer hidden as 404.

`list_run_reports` (line 142-168): a corrupt metadata file would now
raise and abort the whole list. Instead, catch
`CardreError` per-report and skip with a visible warning:

```python
reports = []
skipped = []
for report_dir in sorted(exports_dir.iterdir()):
    if not report_dir.is_dir() or not report_dir.name.startswith("report_"):
        continue
    rid = report_dir.name.removeprefix("report_")
    try:
        meta = _load_metadata(store.root, rid)
    except CardreError as e:
        skipped.append({"report_id": rid, "code": e.code, "message": e.message})
        continue
    if meta is None or meta.get("run_id") != run_id:
        continue
    reports.append(ReportMetadataResponse(...))
# Optional: return a list response with a warnings field, or log skipped.
```

**Decision**: `list_run_reports` returns `list[ReportMetadataResponse]`
unchanged, and `skipped` is logged server-side with `request_id`. Adding
a wrapper response model is a breaking change to a list endpoint; defer
it. Log the skipped reports so they are visible in dev logs.

### 3. REP-3 — `ReportGenerationError` carries structured blockers

`cardre/services/report_generation_service.py:26-30`:

```python
class ReportGenerationError(CardreError):
    code = "REPORT_BLOCKED"
    status_code = 400

    def __init__(self, message, blockers: list[ReadinessBlocker] | None = None):
        super().__init__(message)
        self.blockers = blockers or []
```

`generate_and_write` (line 89-93):

```python
if not readiness.ready:
    raise ReportGenerationError(
        "Report generation blocked by readiness checks.",
        blockers=readiness.blockers,   # pass objects, not str(b.code)
    )
```

`ReportGenerationError.to_envelope` (inherited from `CardreError`) must
include the blockers in `diagnostics`. Override or extend so each
blocker becomes a `Diagnostic(code=b.code, message=b.message,
context={"step_id": b.step_id})`. The route no longer needs to format
`f"Report generation blocked: {exc.blockers}"` (line 106); the envelope
carries them.

`sidecar/routes/reports.py:103-107`: simplify to let the
`ReportGenerationError` propagate to the Batch 0 handler (it is a
`CardreError`). Remove the local `except ReportGenerationError` once the
handler serialises blockers into `detail.diagnostics`. The response
becomes 400 with `detail.code="REPORT_BLOCKED"` and
`detail.diagnostics=[{code, message, context.step_id}, ...]`.

`GenerateReportResponse` gains an optional `blockers: list[ReadinessItem]
= []` so a blocked response (if the route still constructs one) carries
them; alternatively the frontend reads `detail.diagnostics`. **Decision**:
frontend reads `detail.diagnostics` from the `ApiError` (consistent with
Batch 1/4), so `GenerateReportResponse` is unchanged. Regenerate
`frontend/src/api/schema.d.ts` only if other models change.

### 4. REP-4 — out-of-project report paths fail hard

`cardre/services/report_generation_service.py:148-161` — three
`try/except ValueError` blocks fall back to absolute paths when
`relative_to(self.store.root)` raises. Replace each with a fail-hard
`CardreError`:

```python
def _relative_to_store(path: Path, store_root: Path, kind: str) -> str:
    try:
        return str(path.relative_to(store_root))
    except ValueError as e:
        raise CardreError(
            "REPORT_PATH_OUTSIDE_PROJECT",
            message=f"{kind} path {path} is outside the project store root {store_root}.",
            context={"kind": kind, "path": str(path), "store_root": str(store_root)},
            status_code=500,
        ) from e

bundle_rel = _relative_to_store(Path(result["bundle_path"]), self.store.root, "bundle")
html_rel = _relative_to_store(Path(result["html_path"]), self.store.root, "html")
export_rel = _relative_to_store(Path(result["report_dir"]), self.store.root, "report_dir")
```

This is the actual source of out-of-project paths (the `/reports/serve`
route already guards `PATH_TRAVERSAL`). A report whose output dir is
outside the store root is a misconfiguration that should surface
immediately, not silently produce an absolute path the frontend cannot
serve safely.

### 5. `sidecar/routes/reports.py:190-234` — `serve_report_file` unchanged

The `PATH_TRAVERSAL` guard at line 214 already returns a 403. Confirm it
still works after Batch 0's handler swap (it raises `HTTPException` with
a dict detail, which `http_exception_handler` normalises). No change
needed here; REP-4 is satisfied by step 4.

## Tests

- Monkeypatch `_save_metadata` to raise `OSError` → `POST /reports`
  returns 500 `REPORT_METADATA_WRITE_FAILED` with `context.report_id`
  and `context.run_id`; the report bundle exists on disk (verify in test
  fixture) but the response is an error, not 201.
- Corrupt `report_metadata.json` (invalid JSON) → `GET .../reports/{id}`
  returns 500 `REPORT_METADATA_UNREADABLE` with `context.report_id`,
  **not** 404.
- Missing `report_metadata.json` → `GET .../reports/{id}` returns 404
  `REPORT_NOT_FOUND` (unchanged).
- `list_run_reports` with one corrupt and one valid metadata returns
  the valid one only; the corrupt one is logged (assert via caplog).
- Blocked readiness → `POST /reports` returns 400
  `detail.code="REPORT_BLOCKED"` with `detail.diagnostics` containing
  each blocker's `code`, `message`, and `context.step_id`.
- `generate_report` with `output_dir` outside store root returns 500
  `REPORT_PATH_OUTSIDE_PROJECT` with `context.kind` and `context.path`.
- `serve_report_file` with a traversal path still returns 403
  `PATH_TRAVERSAL` (regression).

## Acceptance criteria

- A report cannot be generated without persisted metadata; metadata
  write failure fails the request with `REPORT_METADATA_WRITE_FAILED`.
- Corrupt report metadata returns `REPORT_METADATA_UNREADABLE` (500),
  not 404.
- `ReportGenerationError.blockers` is `list[ReadinessBlocker]`; the API
  envelope's `detail.diagnostics` carries `code`/`message`/
  `context.step_id` for each blocker.
- Out-of-project report paths raise `REPORT_PATH_OUTSIDE_PROJECT`; no
  silent absolute-path fallback.
- `serve_report_file` traversal guard still returns 403.
- `make lint && make typecheck && make test` pass.
- `frontend/src/api/schema.d.ts` regenerated if models changed.

## Out of scope

- Branch-evidence typed errors (Batch 6).
- A cleanup tool for orphaned report bundles (metadata write failed but
  bundle written) — out of scope; the `context.report_id` lets the user
  locate it manually.
- Changing `list_run_reports` to a wrapper response model with
  `warnings` — deferred to avoid a breaking change to a list endpoint.