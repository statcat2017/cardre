# UI Recovery Audit — Phase Plan

Automated execution of the UI recovery audit implementation plan. Each phase is a vertical TDD slice.

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Foundation | Widen `ApiError.detail` type, create `classifyError()` + test, create `useStaleVersionHandler` + test |
| 2 | RecoveryBanner | Create shared `<RecoveryBanner>` component + test; refactor `<QueryState>` to use it |
| 3 | Silent failures | Fix `ArtifactPreviewPane`, `ArtifactSummaryInline` to show RecoveryBanner instead of null + tests |
| 4 | More silent failures | Fix `RunHistoryTab`, `StepInspector` silent error swallowing + tests |
| 5 | Run lifecycle | `useRunProgress` handles `cancelled`, `interrupted`, `is_stale`, dispatcher failure + tests |
| 6 | Governance & plan validation | Gate Branch controls on `governance_enabled`, render PLAN_CONTAINS_UNAVAILABLE_NODES context + tests |

---

## Phase 1 — Foundation

### Files to modify
- `frontend/src/api/client.ts` — widen `ApiError.detail` type (add `recoverable`, `severity`)
- `frontend/src/utils/errors.ts` — add `classifyError()` with `RecoveryInfo` type and `CODE_COPY` map
- `frontend/src/hooks/useStaleVersionHandler.ts` — NEW: centralise STALE_VERSION handling
- `frontend/src/utils/__tests__/recovery.test.ts` — NEW: test classifyError for all error codes
- `frontend/src/hooks/__tests__/useStaleVersionHandler.test.ts` — NEW: test STALE_VERSION handling

### TDD execution
1. Write `recovery.test.ts` — test `classifyError` for each canonical code → correct `kind`, `retryable`, copy
2. Write `useStaleVersionHandler.test.ts` — test 409 STALE_VERSION → calls onPlanRefreshed; non-stale → rethrows
3. Implement `classifyError` + `CODE_COPY` map in `utils/errors.ts`
4. Widen `ApiError.detail` in `client.ts`
5. Implement `useStaleVersionHandler` in new hook file
6. Run `npm run test` — all pass
7. Run `npm run lint` — no errors

---

## Phase 2 — RecoveryBanner component

### Files to modify
- `frontend/src/components/RecoveryBanner.tsx` — NEW: render `RecoveryInfo` with severity colour, retry button, collapsible diagnostics, request/error id footer
- `frontend/src/components/__tests__/RecoveryBanner.test.tsx` — NEW: test all severity colours, retry callback, diagnostics toggle, request_id display

### TDD execution
1. Write `RecoveryBanner.test.tsx` — test renders error, info, success severity; retry button fires; diagnostics collapsible; request_id shown
2. Implement `RecoveryBanner.tsx`
3. Run `npm run test` — all pass
4. Run `npm run lint` — no errors

---

## Phase 3 — Fix silent failures (ArtifactPreviewPane + ArtifactSummaryInline)

### Files to modify
- `frontend/src/components/ArtifactPreviewPane.tsx` — add `isError` check, render `<RecoveryBanner>` with retry
- `frontend/src/components/ArtifactSummaryInline.tsx` — add `isError` check, render `<RecoveryBanner>` with retry
- `frontend/src/components/__tests__/ArtifactPreviewPane.recovery.test.tsx` — NEW: test API reject → RecoveryBanner, not null
- `frontend/src/components/__tests__/ArtifactSummaryInline.recovery.test.tsx` — NEW: test API reject → RecoveryBanner, not null
- Extend existing test files: `ArtifactSummaryInline.test.tsx`, no existing ArtifactPreviewPane test

### TDD execution
1. Write recovery test files: preview rejects → RecoveryBanner with Retry; summary rejects → RecoveryBanner
2. Implement `isError` checks in both components, rendering `<RecoveryBanner>` instead of `null`
3. Run all tests — existing happy-path tests still pass, new recovery tests pass
4. Run lint

---

## Phase 4 — Fix RunHistoryTab + StepInspector

### Files to modify
- `frontend/src/components/inspector/RunHistoryTab.tsx` — add `isError` check, render RecoveryBanner; separate from "not executed" state
- `frontend/src/components/StepInspector.tsx` — surface `editorStateQuery` error to `NextActionTab`
- `frontend/src/components/__tests__/RunHistoryTab.recovery.test.tsx` — NEW: test API reject → RecoveryBanner, NOT "not executed"
- `frontend/src/components/__tests__/StepInspector.test.tsx` — extend: test error shows recovery state

### TDD execution
1. Write new test files
2. Implement changes in both components
3. Run all tests
4. Run lint

---

## Phase 5 — Run lifecycle recovery

### Files to modify
- `frontend/src/hooks/useRunProgress.ts` — handle `status:"cancelled"`, `status:"interrupted"`, `run.is_stale`, read `RUN_SHORT_CIRCUITED` diagnostic, render all step errors (not just first), distinguish `RUN_DISPATCH_FAILED` from `RUN_EXECUTION_FAILED`
- `frontend/src/hooks/__tests__/useRunProgress.test.tsx` — extend: test `cancelled`, `interrupted`, `RUN_SHORT_CIRCUITED`, `RUN_DISPATCH_FAILED`, multi-step errors

### TDD execution
1. Extend `useRunProgress.test.tsx` with new test cases
2. Implement lifecycle changes in `useRunProgress.ts`
3. Run all tests
4. Run lint

---

## Phase 6 — Governance gates + plan validation

### Files to modify
- `frontend/src/components/ProjectView.tsx` — gate Branch controls when `!governance_enabled`; render PLAN_CONTAINS_UNAVAILABLE_NODES context per-step
- `frontend/src/hooks/useRunProgress.ts` — extend `startRun` catch to render per-step issues for `PLAN_CONTAINS_UNAVAILABLE_NODES`, install hint copy for `OPTIONAL_DEPENDENCY_NOT_INSTALLED`
- `frontend/src/components/__tests__/ProjectView.governance.test.tsx` — NEW: test controls disabled when governance off
- `frontend/src/hooks/__tests__/useRunProgress.test.tsx` — extend: test `PLAN_CONTAINS_UNAVAILABLE_NODES` context, `OPTIONAL_DEPENDENCY_NOT_INSTALLED` install hint

### TDD execution
1. Write new test files / extend existing
2. Implement gates and recovery copy
3. Run all tests
4. Run lint
