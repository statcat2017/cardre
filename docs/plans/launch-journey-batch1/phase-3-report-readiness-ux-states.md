# Phase 3 — Report Readiness UX States

## Goal

Make the export panel trustworthy and non-confusing during readiness
checks. Close the real safety gap: a user can today fetch readiness for
branch A, switch to branch B, and click Generate while stale `ready=true`
from branch A is still shown.

## Context you must read first

- `frontend/src/components/ExportPanel.tsx` — the file you are editing.
  Read lines 64-100 (readiness query + reports query), 121-125 (the
  broken clear effect), 263-300 (readiness panel render gate), 303-307
  (error gate), 247-258 (generate button).
- `frontend/src/hooks/useReportReadiness.ts` — note `staleTime: 5000` and
  `retry: false`. The hook keys on `(projectId, runId, targetBranchId,
  reportMode)`, so switching branch/run/mode produces a fresh query key
  — but the *cached* data for the old key is not cleared, and
  ExportPanel's local state sync effect re-populates from it.
- `frontend/src/components/TopBar.tsx:154-177` — the **other** readiness
  surface (`guidance.report_readiness` badge). This batch does not touch
  it, but the freshness copy you add must make clear which readiness is
  being shown (ExportPanel's POST-based readiness, not the guidance
  badge).
- `sidecar/models.py:570-574` — `ReportReadinessResponse` has only
  `ready/status/blockers/warnings`. No `target_branch_id` or `run_id`.
  This drives the generate-safety decision below.
- `frontend/src/types.ts` and `frontend/src/api/schema.d.ts` — if you
  extend the backend model, regenerate types per ADR 0006.
- `docs/plans/launch-journey-batch1/README.md` — batch-level validation
  context and cross-cutting rules.
- `docs/plans/launch-journey-batch1/phase-1-export-panel-branch-run-determinism.md`
  — PR 1 must land first. ExportPanel is now controlled (no local branch
  state) and shows a context line; this phase expands that into full
  freshness copy.
- `scripts/check-line-counts.py` — the 600-line `.tsx` ceiling. PR 1
  started extraction with `BranchSelector`; this phase must extract
  `ReadinessPanel` to keep `ExportPanel.tsx` under budget.

## Decision: generate-safety approach

The original plan proposed a guard asserting "readiness branch matches
selected branch / run matches latest run." That guard is **not
implementable** today because `ReportReadinessResponse` carries no
branch/run identifiers.

There is a real mismatch this guard was meant to prevent: stale
`readinessData` for branch A can still show `ready=true` after the user
switches to branch B, because the clear effect at `ExportPanel.tsx:121-125`
resets local `blockers/warnings/errorMsg` but the react-query cache is not
cleared, and the sync effect at `:71-76` immediately re-populates from the
stale cache.

**Chosen approach: stale-state prevention + explicit freshness copy.** Do
not ship a TODO-based echo guard. Instead:

1. Drive the entire readiness UI from the query state
   (`isLoading`/`error`/`data`), not from local `blockers`/`warnings`/
   `errorMsg` state that mirrors the cache. This eliminates the
   re-populate-from-stale-cache path.
2. Disable Generate unless `readinessData?.ready === true` **and** the
   query is not loading and not erroring and not refetching.
3. Show explicit freshness copy naming the branch/run/mode the readiness
   applies to (using the values ExportPanel already has — it does not
   need them from the response).

This closes the safety gap without a backend change. The mismatch cannot
occur because stale data is never shown as current: a branch switch changes
the query key, the query goes into loading state, and the UI shows
"Checking readiness…" instead of the old result.

**Optional backend extension (allowed but not required):** if you want
defense-in-depth, add `target_branch_id` and `run_id` echo fields to
`ReportReadinessResponse` in `sidecar/models.py` and have
`check_report_readiness` populate them from its arguments. If you do this,
regenerate `frontend/src/api/schema.d.ts` with
`python3 scripts/generate-openapi-types.py` and commit the diff in this
PR. The frontend can then assert the echo matches before generating. This
is within scope (not a new evidence type) but is not necessary if the
stale-state prevention is solid. Do not leave it as a TODO — either do it
or rely on the frontend approach.

## Changes

### 1. Extract ReadinessPanel (line-budget work)

Create `frontend/src/components/ReadinessPanel.tsx` (new file) that owns
the readiness result rendering. It receives:

```ts
interface ReadinessPanelProps {
  readinessData: ReportReadinessResponse | undefined;
  readinessLoading: boolean;
  readinessError: Error | null;
  readinessIsFetching: boolean;
  branchName: string | null;
  branchId: string | null;
  runId: string | null;
  reportMode: ReportMode;
  onStepSelect?: (stepId: string) => void;
  onRecheck: () => void;
  recheckLoading: boolean;
}
```

`ExportPanel` composes `ReadinessPanel` and passes the query state
directly. `ReadinessPanel` renders the seven states below. This moves
~100 lines out of `ExportPanel.tsx` and keeps both files well under the
600-line ceiling.

### 2. Replace blank/transient states with explicit ones

`ReadinessPanel` renders exactly one of these states, in priority order:

1. `targetBranchId` is null → "Select a branch."
2. `runId` is null (no successful run) → "No successful run yet."
3. `readinessLoading` or `readinessIsFetching` (initial load or
   refetch/branch switch) → "Checking readiness…". This is the state
   that replaces the blank panel today (`ExportPanel.tsx:263` only
   renders when `readinessData` is truthy).
4. `readinessError` → "Readiness check failed." plus the error message.
   This replaces the `errorMsg && !readinessData` gate at `:303` that
   hides errors after a prior success.
5. `readinessData` and `!ready` and blockers → "Blocked." plus blocker
   rows (with "Go to step" buttons, same as today).
6. `readinessData` and `ready` and warnings → "Ready with warnings."
   plus warning rows.
7. `readinessData` and `ready` and no warnings → "Ready."

Do not briefly show empty content while the query is in flight. The
"Checking readiness…" state covers both initial load and branch/mode
switch refetches.

### 3. Remove the broken local-state sync

Delete from `ExportPanel.tsx`:
- The `blockers`/`warnings`/`errorMsg` local state (lines 41-43).
- The sync effect that copies `readinessData` into local state
  (`:71-76`).
- The error sync effect (`:78-82`).
- The clear effect (`:121-125`).

`ReadinessPanel` reads blockers/warnings directly from `readinessData` and
the error from `readinessError`. This is the stale-cache fix: there is no
local mirror to repopulate from stale data.

### 4. Add explicit freshness copy

When `readinessData` is present (states 5-7), `ReadinessPanel` shows above
the result:

> Readiness checked for branch {branchName || branchId} using run {runId
> (first 8 chars)} · {reportMode} mode.

This makes clear which branch/run the readiness applies to. It uses the
values ExportPanel already holds (selected branch, latest run, mode), not
response fields — so it works whether or not the optional backend echo
extension is done. Add a short note when the two readiness surfaces could
diverge: a one-line caption under the freshness copy such as "Export
readiness is checked separately from the TopBar readiness badge." This
keeps the user from assuming the TopBar badge and the ExportPanel result
are the same check.

### 5. Add generate safety

The generate button is enabled only when **all** hold:

- `readinessData?.ready === true`;
- `!readinessLoading && !readinessIsFetching`;
- `!readinessError`;
- `runId !== null`;
- `targetBranchId !== null`.

Replace the current `disabled={!readinessData?.ready}` at
`ExportPanel.tsx:249` with this compound condition. This prevents
generation while stale data is being replaced, while a recheck is in
flight, or after an error.

If you did the optional backend echo extension, additionally assert
`readinessData.target_branch_id === targetBranchId` and
`readinessData.run_id === runId` before enabling generate. If you did not,
the stale-state prevention above is the safety mechanism — do not add a
TODO.

### 6. Make "Re-check" clearer

The recheck button label:
- "Checking…" while `readinessLoading || readinessIsFetching`;
- "Re-check readiness" otherwise.

(Replaces the current "Checking..." / "Re-check" at `:244`.)

## Tests

Add `frontend/src/components/__tests__/ReadinessPanel.test.tsx` (new file)
that renders `ReadinessPanel` directly with each set of props. This is a
pure component test — no MSW needed, just pass props.

States to cover:
- `targetBranchId` null → "Select a branch." and no generate button
  enabled.
- `runId` null → "No successful run yet." and generate disabled.
- `readinessLoading` true → "Checking readiness…" and generate disabled
  and no blocker/warning rows shown (assert the previous result is not
  rendered).
- `readinessError` set → "Readiness check failed." plus the message and
  generate disabled.
- `readinessData` blocked → "Blocked." plus blocker row, and "Go to
  step" button calls `onStepSelect` with the blocker's `step_id`, and
  generate disabled.
- `readinessData` ready with warnings → "Ready with warnings." and
  generate enabled.
- `readinessData` ready, no warnings → "Ready." and generate enabled.
- Freshness copy shows the branch name, run id prefix, and mode in states
  5-7.
- Recheck button label flips between "Checking…" and "Re-check readiness"
  with `recheckLoading`.

Add `frontend/src/components/__tests__/ExportPanel.generate-safety.test.tsx`
(new file) using MSW to assert the end-to-end generate gate:
- Render ExportPanel (inside `QueryClientProvider`) with a successful run
  and ready readiness. Assert generate is enabled and clicking it calls
  the generate handler with the right branch/run.
- Render ExportPanel, let readiness resolve ready, then switch the branch
  (re-render with a new `targetBranchId`). Assert that during the
  refetch the generate button is disabled and "Checking readiness…" is
  shown — not the stale "Ready." state. This is the core safety
  regression test.
- Render ExportPanel with readiness erroring. Assert generate is disabled
  and the error state is shown.

## Acceptance criteria

- Users can tell exactly why export is disabled (one of the seven states
  is always rendered, never blank).
- Users can tell exactly what branch/run/mode readiness applies to
  (freshness copy in states 5-7).
- Report generation cannot be triggered before readiness succeeds and
  while a refetch is in flight.
- The stale-cache repopulate path is gone (local blockers/warnings/errorMsg
  state removed).
- `ExportPanel.tsx` is smaller than after PR 1 (readiness rendering moved
  to `ReadinessPanel.tsx`) and well under the 600-line ceiling.
- `ReadinessPanel.tsx` and both new test files are each well under 600
  lines.
- `npx tsc --noEmit` passes in `frontend/`.
- `npm test` passes in `frontend/`.
- If the backend echo extension is done, `schema.d.ts` is regenerated and
  the diff is committed in this PR; `check-api-contracts` passes.
- No new modelling/evidence/scorecard scope. The only backend touch (if
  any) is adding echo fields to an existing response.

## Out of scope for this phase

- Do not unify the two readiness surfaces (TopBar badge vs ExportPanel).
  The freshness copy acknowledges they differ; full unification is a
  later batch.
- Do not change the TopBar badge logic.
- Do not add new report modes or readiness blocker codes.
- Do not touch `cardre/reporting/readiness.py` logic beyond optionally
  populating echo fields from existing arguments.
