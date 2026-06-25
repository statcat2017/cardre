# Batch 1 — API envelope adoption + frontend parsing

## Goal

Make every sidecar route emit the unified envelope from Batch 0 and make
the frontend robust to non-JSON, malformed, empty, and HTML error
responses. After this batch, no API failure reaches the frontend as a raw
`SyntaxError`, and every component that consumes `ApiError` does so via a
typed guard.

## Findings addressed

- **MAIN-1, MAIN-2** (completion) — every route normalised.
- **RUN-1** (partial) — sync execution exception now returns a
  structured error with `run_id` in context; full run diagnostics land in
  Batch 2.
- **RUN-4** — manifest read/parse failures map to
  `RUN_MANIFEST_UNREADABLE`.
- **FE-1** — `fetchJson` survives non-JSON/HTML/empty responses.
- **FE-2** (partial) — `useRunProgress` captures the poll `ApiError`; full
  display lands in Batch 2.
- **FE-4** (partial) — all four `updateStepParams` callers export and use
  the typed `ApiError`; structured message rendering lands in Batch 4.

## Context you must read first

- `sidecar/routes/runs.py` — sync path at 101-122, async path at 139-158,
  `get_run_manifest` at 208-225.
- `sidecar/routes/reports.py` — `generate_report` at 86-139 catches only
  `ReportGenerationError`; an `OSError` from `_save_metadata` (line 130,
  after the try) currently produces a raw 500.
- `sidecar/routes/branches.py` — `create_branch` at 110-139 does not
  catch `ValueError`; it bubbles to the generic handler.
- `sidecar/routes/plans.py` — `update_step_params` at 59-64,
  `preview_manual_binning_overrides` at 74-79, `review_manual_binning`
  at 82-110 rely on `main.py`'s handler.
- `frontend/src/api/client.ts:50-68` — `ApiError` (unexported),
  `fetchJson` (calls `await res.json()` on every non-OK).
- `frontend/src/hooks/useRunProgress.ts:122` — `catch {}` with no
  binding; `consecutiveErrors++` discards the `ApiError`.
- `frontend/src/components/ManualBinningEditDialog.tsx:103`,
  `ManualBinningReviewActions.tsx:69`,
  `SchemaDrivenParamsEditor.tsx:253`,
  `RawJsonParamsFallback.tsx:46`,
  `ParamsEditor.tsx:48` — the five `e?.detail?.code` pattern-match sites.
- `docs/plans/error-handling-hardening-batch/README.md` — cross-cutting
  rules (no new TS types for API shapes; MSW for frontend tests; 600-line
  ceiling).

## Changes

### 1. Route error sweep — convert string-detail `HTTPException`s

Audit `sidecar/routes/*.py` for `HTTPException(detail="string")` and
convert each to `HTTPException(status_code=..., detail={"code": "...",
"message": "..."})`. The `http_exception_handler` from Batch 0 handles
both shapes, but the string form loses the `code` field that frontend
relies on. This is a mechanical sweep; do not change status codes or
messages, only the detail shape.

Specific sites to verify (non-exhaustive — `rg "HTTPException\(status_code"
sidecar/routes/`):
- `runs.py:117` — already dict-shaped; confirm.
- `runs.py:78, 84, 92, 119, 172, 205, 224` — audit each.
- `reports.py:61, 107, 176, 205, 215, 221, 229` — audit each.
- `branches.py:39, 66, 79` — audit each.
- `plans.py:52, 118, 120, 145, 158` — audit each.

Acceptance: `rg 'HTTPException\(status_code=\d+, detail="' sidecar/`
returns zero matches.

### 2. `sidecar/routes/runs.py` — sync execution structured error

The sync path (`runs.py:101-122`) currently returns a 400/500 with no
`run_id`. The run **is** created by `execute_run` → `RunLifecycle.start`
and finalised as failed by `__exit__`. Fix:

- Catch `CardreError` separately and re-raise it (the handler from Batch
  0 serialises it). Add `context={"run_id": <resolved>, "project_id":
  body.project_id, "plan_version_id": body.plan_version_id}` if the run
  was created. Because the run is created inside `execute_run`, you
  cannot easily get the `run_id` from the route. **Acceptable**: leave
  the `run_id` out of the route-level error context for the sync path
  and rely on Batch 2's run-level diagnostic for the failure. The route
  error context carries `project_id` + `plan_version_id` + `run_scope`.
- Catch `ValueError` and map to `PlanValidationError`-equivalent (or the
  typed branch errors from Batch 6 if present); for now, map
  `ValueError("CODE: msg")` to a 400 with `code` parsed from the message
  prefix before the colon, `message` after. If no `CODE:` prefix,
  `code="RUN_VALIDATION_FAILED"`.
- Catch `Exception` last and let the generic handler produce
  `INTERNAL_ERROR`.

Note: the existing `except ValueError ... FULL_RUN_FAILED` mapping at
`runs.py:114-117` is preserved in shape but the `detail_code` derivation
stays; just ensure it is emitted as a dict.

### 3. `sidecar/routes/runs.py` — async thread-start diagnostic (forward)

In the async path (`runs.py:141-158`), the `except Exception` at 156
marks the run failed but writes no diagnostic. This batch adds the
**diagnostic write** here only if Batch 0's `RunDiagnostic` storage is
available; otherwise, record a `RUN_DISPATCH_FAILED` `CardreError`
context and re-raise so the generic handler surfaces it. **Full
diagnostic persistence lands in Batch 2.** For this batch, at minimum:
- Log the thread-start exception with `run_id` and `request_id`.
- Return a structured 500 (via the generic handler) with `context.run_id`
  set, instead of a silent `store.finish_run(run_id, "failed")` followed
  by a 200 `_build_run_response` that reports `status="failed"` with no
  reason.

Decision required: should the async-create endpoint return 201 with the
failed run, or 500 with the run_id? **Recommendation**: return 201 with
the failed run **plus** a `RUN_DISPATCH_FAILED` entry in
`RunResponse.diagnostics` (populated by Batch 2). For this batch, return
201 with the failed run and log the cause; the diagnostic field is
populated in Batch 2. Do not change the status code — the frontend polls
on 201.

### 4. `sidecar/routes/runs.py` — manifest read structured error

`get_run_manifest` (`runs.py:208-225`): the manifest read can fail with
`EvidenceError`/`JSONDecodeError`/`OSError` from
`reader.read_run_manifest(art.artifact_id)`. Currently these would bubble
to the generic handler as a 500 `INTERNAL_ERROR`. Map them to a
`ArtifactReadError` (`CardreError` subclass from Batch 0) with
`code="RUN_MANIFEST_UNREADABLE"`, `context={"run_id": run_id,
"artifact_id": art.artifact_id}`, `status_code=500`. This satisfies
RUN-4.

### 5. `sidecar/routes/reports.py` — metadata save inside try

`generate_report` (`reports.py:86-139`): move the `_save_metadata` call
(line 130) **inside** the `try` block, or wrap it in its own
`try/except OSError as e: raise CardreError("REPORT_METADATA_WRITE_FAILED",
context={...}, status_code=500) from e`. This satisfies the structural
part of REP-1; the full "fail generation" semantics land in Batch 5.
For this batch, the OSError becomes a structured 500 rather than a raw
one.

### 6. `frontend/src/api/client.ts` — export `ApiError`, harden `fetchJson`

Export `ApiError` and add a typed guard:

```ts
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: {
    code: string;
    message: string;
    context?: Record<string, unknown>;
    diagnostics?: Array<{ code: string; message: string }>;
    request_id?: string;
    error_id?: string;
  };
  readonly requestId?: string;
  readonly rawBodyPreview?: string;
  constructor(status: number, detail: ApiError["detail"], opts?: { requestId?: string; rawBodyPreview?: string }) { ... }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}
```

Rewrite `fetchJson` to never throw `SyntaxError`:

```ts
async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${getBaseUrl()}${path}`;
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  } catch (e) {
    throw new ApiError(0, { code: "SIDECAR_UNREACHABLE", message: "Could not reach the Cardre sidecar." }, { rawBodyPreview: String(e) });
  }
  const text = await res.text();
  const requestId = res.headers.get("X-Cardre-Request-Id") ?? undefined;
  if (!res.ok) {
    if (text.length === 0) {
      throw new ApiError(res.status, { code: "EMPTY_ERROR_RESPONSE", message: `HTTP ${res.status} with empty body.` }, { requestId, rawBodyPreview: "" });
    }
    let detail: ApiError["detail"] | undefined;
    try { detail = JSON.parse(text)?.detail; } catch { /* not JSON */ }
    if (!detail || typeof detail.code !== "string" || typeof detail.message !== "string") {
      const preview = text.slice(0, 500);
      const code = text.trimStart().startsWith("<") ? "HTML_ERROR_RESPONSE" : "NON_JSON_ERROR_RESPONSE";
      throw new ApiError(res.status, { code, message: `HTTP ${res.status} returned a non-JSON body.` }, { requestId, rawBodyPreview: preview });
    }
    throw new ApiError(res.status, detail, { requestId });
  }
  if (text.length === 0) return undefined as unknown as T;  // 204
  try { return JSON.parse(text) as T; }
  catch {
    throw new ApiError(res.status, { code: "MALFORMED_JSON_RESPONSE", message: "OK response was not valid JSON." }, { requestId, rawBodyPreview: text.slice(0, 500) });
  }
}
```

Rules:
- Network failure → `SIDECAR_UNREACHABLE`, `status=0`.
- Empty non-OK → `EMPTY_ERROR_RESPONSE`.
- Non-JSON non-OK → `NON_JSON_ERROR_RESPONSE` (or `HTML_ERROR_RESPONSE`
  if body starts with `<`).
- OK non-JSON → `MALFORMED_JSON_RESPONSE`.
- OK empty → return `undefined` (204).
- Always set `requestId` from `X-Cardre-Request-Id` when present.
- `rawBodyPreview` is truncated to 500 chars.

### 7. `frontend/src/hooks/useRunProgress.ts` — capture poll errors

Change `catch {}` at line 122 to `catch (e: unknown)` and store the last
poll error:

```ts
const [lastPollError, setLastPollError] = useState<ApiError | null>(null);
...
} catch (e: unknown) {
  consecutiveErrors++;
  const apiErr = isApiError(e) ? e : null;
  setLastPollError(apiErr);
  if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
    ...
    setError(
      apiErr
        ? `${apiErr.code}: ${apiErr.detail.message}`
        : "Run polling failed after multiple retries."
    );
    addDiagnostic(`Polling failed (${apiErr?.code ?? "unknown"}): ${apiErr?.detail.message ?? "no message"}`);
  }
}
```

Expose `lastPollError` on the hook return for Batch 2 to render. Clear it
on each successful poll (`consecutiveErrors = 0`).

### 8. Frontend component sweep — typed `ApiError` consumption

Update the five pattern-match sites to use `isApiError(e)` and read
`e.detail.code` / `e.detail.message` / `e.detail.context` typed. The
behaviour (STALE_VERSION handling) is unchanged; only the narrowing
becomes typed. Do not change copy in this batch — Batch 4 improves
messages.

Files:
- `ManualBinningEditDialog.tsx:103,134`
- `ManualBinningReviewActions.tsx:69`
- `SchemaDrivenParamsEditor.tsx:253`
- `RawJsonParamsFallback.tsx:46`
- `ParamsEditor.tsx:48`

## Tests

Backend (`tests/test_api_contracts.py` or `tests/test_error_envelope.py`):
- A route that raises `HTTPException(detail="string")` still returns a
  400/500 with `detail.code == "HTTP_ERROR"` (until the sweep removes
  the last one; then assert no string-detail route remains).
- `POST /runs?sync=true` with an invalid plan_version_id returns a 400
  with `detail.code` set and `detail.context.plan_version_id` present.
- `GET /runs/{run_id}/manifest` with a corrupted manifest artifact
  returns 500 `RUN_MANIFEST_UNREADABLE` with `context.run_id` and
  `context.artifact_id`.
- `POST /reports` with `_save_metadata` patched to raise `OSError`
  returns 500 `REPORT_METADATA_WRITE_FAILED` (Batch 5 will refine the
  status semantics).

Frontend (`frontend/src/api/__tests__/client.test.ts`):
- Mock `fetch` to return a 500 with HTML body → `ApiError.code ===
  "HTML_ERROR_RESPONSE"`, `rawBodyPreview` set, `requestId` set from
  header.
- Mock `fetch` to return a 500 with empty body → `EMPTY_ERROR_RESPONSE`.
- Mock `fetch` to return a 200 with empty body → resolves `undefined`.
- Mock `fetch` to reject (network) → `SIDECAR_UNREACHABLE`, `status=0`.
- Mock `fetch` to return a 400 with valid `{"detail":{"code":"X","message":"Y"}}`
  → `ApiError.code === "X"`, `detail.message === "Y"`.
- `isApiError(new ApiError(...)) === true`; `isApiError(new Error("x")) === false`.

`useRunProgress` (`frontend/src/hooks/__tests__/useRunProgress.test.ts`):
- Mock `api.getRun` to reject with `ApiError(0, {code:"SIDECAR_UNREACHABLE",
  message:"x"})` five times → `error` contains `SIDECAR_UNREACHABLE`;
  `lastPollError.code === "SIDECAR_UNREACHABLE"`.

Journey (`frontend/src/components/__tests__/journey.test.tsx`):
- Existing STALE_VERSION flow still works after the typed-`ApiError`
  sweep.

## Acceptance criteria

- `rg 'HTTPException\(status_code=\d+, detail="' sidecar/` returns zero
  matches.
- Every API failure response has `detail.code`, `detail.message`,
  `detail.request_id`, `detail.error_id`.
- No frontend test asserts on a thrown `SyntaxError` from `fetchJson`.
- `ApiError` is exported and used via `isApiError` in all five
  pattern-match sites.
- `useRunProgress` exposes `lastPollError` and the test covers the
  `SIDECAR_UNREACHABLE` path.
- `X-Cardre-Request-Id` is present on every error response tested.
- `frontend/src/api/schema.d.ts` regenerated and committed (if models
  changed).
- `make lint && make typecheck && make test` pass.

## Out of scope

- Run-level diagnostic persistence and `RunResponse.diagnostics`
  population (Batch 2).
- Frontend rendering of failed-run step errors (Batch 2).
- Manual-binning structured message rendering (Batch 4).
- Report metadata corruption vs missing semantics (Batch 5).
- Branch `ValueError` → typed error conversion (Batch 6).