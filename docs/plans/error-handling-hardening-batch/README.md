# Error Handling Hardening — Sprint Plan

A batched delivery plan to eliminate hidden failures across the Cardre
backend, sidecar, and frontend. Builds on the original error-handling
review (WG-1 … ST-1) and incorporates the two architectural refactors
recommended during validation:

1. A **typed `CardreError` hierarchy with attributes** carrying `code`,
   `message`, `context`, `recoverable`, `severity`, serialized into one
   standard API envelope by a single FastAPI handler — replacing the
   per-type handler sprawl in `sidecar/main.py`.

2. A **`Result[T, Diagnostic]` type** in `cardre/errors.py` that
   mechanically enforces the fail-hard-vs-degrade-gracefully rule at
   call sites, removing the class of "forgot to attach a diagnostic"
   bugs that per-site fixes would otherwise re-introduce.

These two refactors are delivered first, in **Batch 0 (Foundation)**,
because every subsequent batch depends on them. Batches 1-6 then
sequentially address the per-finding fixes in dependency order, with
each batch producing one PR.

## Scope boundary

This batch is **only** about error handling, diagnostics visibility, and
the plumbing needed to support them. It does **not** add new modelling
nodes, new evidence kinds, new scorecard functionality, or new reporting
sections.

Allowed backend touches:
- `cardre/errors.py` — new `CardreError` attributes and `Result` type.
- `cardre/services/*.py`, `cardre/executor.py`, `cardre/run_lifecycle.py`,
  `cardre/staleness.py`, `cardre/topology.py`, `cardre/store/project_store.py`
  — narrow refactor to use `CardreError` / `Result` and to stop swallowing
  failures.
- `sidecar/error_handling.py` (new), `sidecar/main.py`, `sidecar/models.py`,
  `sidecar/routes/*.py` — single envelope, request id middleware, route
  error normalization.
- `frontend/src/api/client.ts`, `frontend/src/hooks/useRunProgress.ts`,
  `frontend/src/components/{ManualBinning*,Params*,StepInspector}*` —
  structured error consumption and display.
- `docs/adr/0009-*.md` — record the error-envelope and Result decisions.

Out of scope: any change inside `cardre/nodes/**` (except adding
`RoleAccessError` to the category map), any change to scoring/binning
maths, any change to report content, any new endpoint.

## Validation context (read before starting)

The original plan and this sprint plan were validated against the repo on
2026-06-25. Confirmed facts that shape the work:

- `cardre/errors.py` already defines `GraphValidationError` and ten other
  `CardreError` subclasses, but **carries no attributes** (no `code`,
  `context`, `recoverable`, `severity`). They are bare `pass` classes.
- `cardre/topology.py:12 validate_topology` raises **plain `ValueError`**,
  not `GraphValidationError`. `staleness.py:128 _find_spec` raises plain
  `KeyError`. These are the real missing-parent paths the original ST-1
  finding refers to — not a missing exception class.
- `cardre/executor.py:744 RoleAccessError(ValueError)` is a `ValueError`
  subclass, **not** a `CardreError`, so it escapes the executor's
  category map and the future envelope handler.
- `cardre/store/schema.py:50-57` defines `runs.metadata_json TEXT NOT NULL
  DEFAULT '{}'` that is **never written** by `create_run`/`finish_run`.
  This is the zero-migration home for run-level diagnostics.
- `cardre/store/schema.py:87-101` defines `errors` and `warnings` tables
  with `run_step_id` FKs, but **no code reads or writes them** — step
  errors/warnings live in `run_steps.errors_json`/`warnings_json`. These
  are dead tables and a trap for the implementer; Batch 0 removes them.
- `sidecar/main.py:39-65` registers five exception handlers
  (`PlanValidationError`, `ProjectNotFoundError`, `ProjectPathMissingError`,
  `ConcurrentRunError`, `HTTPException` implicit) plus the implicit
  `RequestValidationError`/generic-`Exception` defaults. No request id, no
  unified envelope, no `error_id`.
- `sidecar/routes/*.py` raise `HTTPException` with **inconsistent detail
  shapes**: some `detail={"code":..., "message":...}` (dict), some
  `detail="RUN_FAILED"` (string). The envelope normaliser must handle
  both until a sweep converts the string variants.
- `frontend/src/api/client.ts:50` declares `class ApiError` **without
  `export`**, yet four components pattern-match `e?.detail?.code` on the
  thrown object structurally (`ManualBinningEditDialog.tsx:103`,
  `ManualBinningReviewActions.tsx:69`, `SchemaDrivenParamsEditor.tsx:253`,
  `RawJsonParamsFallback.tsx:46`, `ParamsEditor.tsx:48`). This is fragile
  and untyped; Batch 1 exports `ApiError` and a typed `isApiError` guard.
- `frontend/src/api/client.ts:66` does `await res.json()` on every non-OK
  response. A non-JSON 500 (sidecar crash, HTML error page) throws
  `SyntaxError` and the HTTP status, URL, and body are lost.
- `frontend/src/hooks/useRunProgress.ts:122` is `catch {}` with **no
  error binding** — the `ApiError` is discarded. FE-2 must capture `e`.
- `frontend/src` never reads `RunStepItem.errors` anywhere (rg finds zero
  references) — FE-3's "show failed step errors" is greenfield.
- `cardre/services/workflow_guidance_service.py:163-321` `build()` is a
  158-line method with four scattered `try/except: pass` blocks. Batch 3
  decomposes it into `gather_evidence / derive_status / derive_phase /
  derive_next_action`, each returning a `Result` with an explicit
  fail-hard-vs-degrade policy.
- `cardre/services/workflow_guidance_service.py:297` and `:448` call
  `check_report_readiness` twice per `build()`. Batch 3 consolidates to
  one call.
- `cardre/services/manual_binning_service.py:200` calls
  `_get_latest_review_annotation` (line 580, which itself swallows all
  exceptions and returns `None`) **before** the editor-state `try` block
  at line 230. A corrupt annotation DB row silently nulls
  `reviewed_at`/`reviewed_by`/`review_reason` in a ready editor.
- `cardre/services/report_generation_service.py:90` constructs
  `ReportGenerationError(blockers=[str(b.code) for b in readiness.blockers])`
  — `blockers` is `list[str]`, not `list[ReadinessBlocker]`. REP-3 requires
  widening this to carry structured blockers; the single construction site
  is `generate_and_write` at line 90.
- `cardre/services/report_generation_service.py:148-161` falls back to
  absolute paths when `relative_to(self.store.root)` raises. This is the
  actual source of out-of-project report paths (REP-4), not the
  `/reports/serve` route which already guards `PATH_TRAVERSAL`.
- `sidecar/routes/runs.py:28 except (ValueError, Exception): pass` in
  `_is_branch_current` swallows preflight errors. A
  `SHARED_UPSTREAM_STALE` raised during preflight returns `None`, the
  route creates a new run, and the same error re-raises inside the
  background thread → run marked failed with no diagnostic. This is a
  missed case in the same family as RUN-1/RO-2; Batch 2 covers it.
- `sidecar/routes/runs.py:101-122` sync execution calls
  `execute_run(..., run_id=None)`; the run is created inside
  `RunLifecycle.start`, then on exception the route raises
  `HTTPException` and `RunLifecycle.__exit__` finalises the run as
  failed — leaving a failed run in the DB with no diagnostic and no
  run_id in the HTTP response. RUN-1's fix is about persisting
  diagnostics and returning the run_id, not "creating a separate run".
- `cardre/run_lifecycle.py:325-327` `finalise` catches `Exception`, marks
  failed, and re-raises the **manifest-write** exception, which masks
  the original body exception when both fail. LIFE-2 and LIFE-3 must be
  fixed together with explicit `raise ... from original` chaining.
- `cardre/executor.py:376-427` `_execute_step`'s failure path can itself
  raise if `store.save_run_step` fails (store unavailable). The original
  node error is then lost. The recording path needs its own best-effort
  guard. Batch 6 covers this together with EXE-1/EXE-2/EXE-3.
- `cardre/store/project_store.py:191` stale-run recovery on startup
  silently transitions runs to `interrupted` with no diagnostic and no
  manifest. This will violate PR 2's acceptance ("no failed run has zero
  step errors and zero run diagnostics unless explicitly cancelled")
  unless recovery writes a `RUN_INTERRUPTED_RECOVERY` diagnostic. Batch 2
  covers it.
- CI enforces a **600-line limit per `.tsx` file**
  (`scripts/check-line-counts.py`). `useRunProgress.ts` and
  `ManualBinningEditDialog.tsx` are near the budget; Batch 1/2 frontend
  work must extract subhooks/components before approaching the ceiling.
- `check-api-contracts` CI job regenerates `frontend/src/api/schema.d.ts`
  and fails on uncommitted diff. Any backend model change must commit the
  regenerated types in the same PR.

## Batch sequence

| Batch | PR | Title | Main outcome | Depends on |
|-------|----|-------|--------------|------------|
| 0 | PR 0 | Foundation: `CardreError` attributes, `Result`, envelope, request id, dead-table cleanup | One typed error hierarchy, one FastAPI handler, one envelope shape, `X-Cardre-Request-Id` on every response, `errors`/`warnings` tables dropped | — |
| 1 | PR 1 | API envelope adoption + frontend parsing | All routes emit the envelope; `ApiError` exported; `fetchJson` survives non-JSON/HTML/empty; `useRunProgress` captures poll errors | 0 |
| 2 | PR 2 | Run diagnostics + polling display | `runs.metadata_json.diagnostics` written for async/thread-start/lifecycle/stale-recovery/preflight failures; `RunResponse.latest_error`; frontend shows run + step errors | 1 |
| 3 | PR 3 | Workflow guidance degraded-state diagnostics | `build()` decomposed into `Result`-returning helpers; no `except: pass`; staleness failure blocks; readiness failure degrades visibly; phase no longer maps readiness failure to `"validate"` | 0, 1 |
| 4 | PR 4 | Manual-binning evidence and annotation diagnostics | Structured preview/editor diagnostics; `MANUAL_BINNING_UPSTREAM_EVIDENCE_UNREADABLE`; `REVIEW_ANNOTATION_UNREADABLE`; `NODE_TYPE_NOT_REGISTERED` (narrowed `try`); all four `updateStepParams` callers show structured errors | 0, 1 |
| 5 | PR 5 | Report readiness and metadata hardening | `_save_metadata` failure fails generation; corrupt metadata returns `REPORT_METADATA_UNREADABLE` (not 404); `ReportGenerationError` carries structured blockers; out-of-project paths fail hard | 0, 1 |
| 6 | PR 6 | Branch errors + executor/lifecycle classification | Typed branch errors replace `ValueError("CODE: ...")`; branch pre-run failures write diagnostics in both sync and async paths; `RoleAccessError` joins category map; reuse-miss diagnostic; `write_manifest` fails hard on missing run record; finalise chains exceptions; `_execute_step` recording-failure guard | 0, 2 |

Detailed LLM-aimed implementation plans live in:
- `batch-0-foundation.md`
- `batch-1-api-envelope-and-frontend-parsing.md`
- `batch-2-run-diagnostics-and-polling.md`
- `batch-3-workflow-guidance-degraded-state.md`
- `batch-4-manual-binning-evidence-and-annotations.md`
- `batch-5-report-readiness-and-metadata.md`
- `batch-6-branch-and-lifecycle-classification.md`

## Cross-cutting rules for every batch

1. **No new modelling/evidence/scorecard scope.** If a change tempts you
   into `cardre/nodes/**` (except the executor category map), `cardre/
   reporting/collector.py`, or new endpoints, stop and re-scope.
2. **One envelope, one handler.** No new per-type FastAPI exception
   handlers after Batch 0. New error types subclass `CardreError` and
   inherit the envelope for free.
3. **Fail hard or degrade visibly — never silently.** Every `except` that
   previously swallowed must now either re-raise, return a `Result` with
   a `Diagnostic`, or attach a diagnostic to an existing result. Use the
   `Result` helpers; do not hand-roll `(value, error)` tuples.
4. **No `except Exception: pass` and no `except: pass`.** If you cannot
   remove the `except`, replace it with a `Result.degrade(...)` or a
   `raise ... from original`.
5. **No bare `except KeyError`, `except ValueError`, `except Exception`
   around broad blocks.** Narrow `try` blocks to the single call that
   can actually raise the caught type. The PLAN-1 fix in Batch 4 is the
   canonical example.
6. **Diagnostics carry context.** Every diagnostic includes the ids
   needed to recover: `run_id`, `plan_version_id`, `branch_id`,
   `step_id`, `artifact_id` as applicable. Free-text messages alone are
   not acceptable.
7. **Raw tracebacks stay in run diagnostics or dev logs, not in API
   messages.** The `message` field is user-readable; `traceback` is
   developer-only and lives in `run_steps.errors_json` or
   `runs.metadata_json.diagnostics`.
8. **Stay under the 600-line `.tsx` and `.ts` ceiling.** Extract before
   approaching it. Reusable helpers go in `frontend/src/utils/` or
   `frontend/src/hooks/`, not inline.
9. **No new handwritten TS types for API shapes.** Per ADR 0006, API
   response shapes come from `frontend/src/api/schema.d.ts`. If a
   backend model changes, regenerate types with
   `python3 scripts/generate-openapi-types.py` and commit the diff in
   the same PR.
10. **Every new test uses MSW for frontend, pytest for backend.** Do not
    mock `api` modules directly in frontend tests; the `server` in
    `frontend/src/test/server.ts` is the only network seam.
11. **No TODOs that gate safety.** If a guard cannot be implemented,
    implement the prerequisite or remove the guard — do not ship a TODO
    that implies safety the code does not provide.
12. **Run `make lint` and `make typecheck` before declaring a batch
    done.** Both must pass. `make test` must pass. New tests must
    accompany every behaviour change.

## Definition of done for the sprint

1. No `except Exception: pass` and no `except: pass` remains in
   `cardre/services/`, `cardre/executor.py`, `cardre/run_lifecycle.py`,
   `cardre/staleness.py`, `cardre/topology.py`, or `sidecar/routes/`.
2. Every API failure reaches the frontend as a typed `ApiError` with
   `code`, `message`, `request_id`, `status`, and (when applicable)
   `context`/`diagnostics`. No `SyntaxError` from `await res.json()`.
3. No failed run has zero step errors and zero run diagnostics unless it
   was explicitly cancelled by the user.
4. Workflow guidance never reports a pathway as fresh when staleness
   computation failed; it degrades with a visible blocker.
5. Manual-binning review audit fields cannot silently disappear; corrupt
   annotations surface a `REVIEW_ANNOTATION_UNREADABLE` warning.
6. A report cannot be generated without persisted metadata; corrupt
   metadata is distinguishable from a missing report.
7. Branch creation and branch execution never fail with an unstructured
   `ValueError`; async branch failures are visible from `/runs/{run_id}`.
8. The dead `errors` and `warnings` tables are removed.
9. `X-Cardre-Request-Id` is present on every response (success and
   error) and echoed in the error body.
10. `make lint && make typecheck && make test` all pass; the frontend
    journey tests still pass; the OpenAPI/schema diff is committed.

## Priority

This sprint is a **launch blocker**. Do it before further feature work on
evidence UI polish, manual-binning redesign, or new modelling nodes. It
provides the safety net and observability needed to keep improving Cardre
without repeatedly hiding failures from users and developers.

## Original findings reference

The original review findings (WG-1 … ST-1, RO-1 … RO-3, RUN-1 … RUN-4,
MAIN-1/2, FE-1 … FE-4, EXE-1 … EXE-3, LIFE-1 … LIFE-3, PLAN-1/2, MB-1 …
MB-5, REP-1 … REP-4, BR-1 … BR-3, ST-1) are mapped to batches in the
per-batch files. The two architectural refactors (typed `CardreError` with
attributes; `Result[T, Diagnostic]`) are delivered in Batch 0 and consumed
throughout.