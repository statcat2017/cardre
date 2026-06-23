# Phase 1 — ExportPanel Branch/Run Determinism

## Goal

Make `ExportPanel` and the wider guided journey unambiguous about which
branch and run are being evaluated. Start the subcomponent extraction
needed to stay under the CI 600-line `.tsx` ceiling.

## Context you must read first

- `frontend/src/components/ExportPanel.tsx` — the file you are editing.
  Note the local branch state at line 40, the local `<select>` at
  199-213, and `successfulRuns[0]` at 52-53.
- `frontend/src/components/ProjectView.tsx` — the branch owner.
  `selectedBranchId` is state at line 29, auto-selected at 65-70, passed
  to ExportPanel at 242 and to workflow guidance at 72-76.
- `frontend/src/hooks/useReportReadiness.ts` — the readiness hook; note
  it is keyed on `(projectId, runId, targetBranchId, reportMode)`.
- `frontend/src/types.ts` — type aliases. `RunListItem` comes from the
  generated schema; do not redefine it.
- `docs/adr/0006-generated-api-contract-as-frontend-boundary.md` and
  `docs/adr/0008-workflow-guidance-seam-and-keys.md` — the contract
  boundary and branch/run-keying rationale.
- `docs/plans/launch-journey-batch1/README.md` — batch-level validation
  context and cross-cutting rules.

## Changes

### 1. Make ExportPanel branch mode controlled by ProjectView

ExportPanel must stop owning branch state. ProjectView already owns
`selectedBranchId` and already feeds it to workflow guidance; ExportPanel
must evaluate the same branch.

New props on `ExportPanel`:

```ts
targetBranchId: string | null;
onBranchSelect?: (branchId: string) => void;
```

Rules:
- `targetBranchId` is now **required** (not optional). ProjectView passes
  `selectedBranchId` directly (not `?? undefined`).
- If `onBranchSelect` is present, the branch control remains an interactive
  `<select>` and calls `onBranchSelect` on change. ProjectView wires this to
  `setSelectedBranchId`.
- If `onBranchSelect` is absent, render the selected branch as read-only
  text (no `<select>`). This is the controlled-component contract.
- Remove `targetBranchIdLocal` state and the auto-select effect at
  `ExportPanel.tsx:115-119`. The local fallback is gone.
- `resolvedBranchId` becomes simply `targetBranchId`.
- Handle the "no branch yet" case in the read-only render: during the brief
  window before ProjectView's baseline auto-select effect runs
  (`ProjectView.tsx:65-70`), `targetBranchId` is null. Show "Select a
  branch." in that state (this overlaps with PR 3's empty-state copy; keep
  the copy consistent).

### 2. Sort successful runs explicitly

Do not rely on `successfulRuns[0]`.

Create `frontend/src/utils/runs.ts` (new file) with:

```ts
import type { RunListItem } from "../types";

export function latestSuccessfulRun(runs: RunListItem[]): RunListItem | null {
  return [...runs]
    .filter((r) => r.status === "succeeded")
    .sort((a, b) => {
      const aTime = Date.parse(a.finished_at ?? a.started_at ?? "");
      const bTime = Date.parse(b.finished_at ?? b.started_at ?? "");
      return bTime - aTime;
    })[0] ?? null;
}
```

Rationale for `finished_at ?? started_at`: a succeeded run always has a
`finished_at` (`cardre/store/run_repo.py` sets it on finalize), but falling
back to `started_at` keeps the helper safe for in-flight edge cases. The
backend already returns runs `ORDER BY started_at DESC`, so this sort is
for explicitness and `finished_at` correctness, not to fix a live bug.

ExportPanel imports `latestSuccessfulRun` and replaces lines 52-53:

```ts
const successfulRuns: RunListItem[] = projectRuns?.runs?.filter((r) => r.status === "succeeded") ?? [];
const latestRun = latestSuccessfulRun(projectRuns?.runs ?? []);
```

Keep `successfulRuns` only if the "no runs" fallback at line 363 still uses
it; otherwise drop it and use `latestRun === null` for that fallback.

Place the helper in `utils/runs.ts` (not inline) so PR 2's journey tests and
`RunHistoryPanel` can import it, and so the unit tests below can target it
directly.

### 3. Extract a BranchSelector subcomponent (start the line-budget work)

Create `frontend/src/components/BranchSelector.tsx` (new file) that
encapsulates the controlled-vs-read-only branch control from change 1. It
receives:

```ts
interface BranchSelectorProps {
  branches: BranchListItem[];
  selectedBranchId: string | null;
  onSelect?: (branchId: string) => void;
  disabled?: boolean;
}
```

If `onSelect` is present, render the `<select>`. If absent, render read-only
text. ExportPanel composes it. This is the first extraction toward staying
under the 600-line ceiling; PR 3 will extract `ReadinessPanel` next.

### 4. Show the selected readiness context

In ExportPanel, above the readiness result, render a compact context line:

- selected branch name/id;
- latest run id (or "No successful run");
- report mode;
- readiness state last checked for branch/run.

This matters because export readiness is meaningless unless the user knows
what it applies to. PR 3 will expand the freshness copy; here just add the
static context line so PR 2's tests have something to assert against.

## Tests

Add `frontend/src/utils/__tests__/runs.test.ts` (new file):

- `latestSuccessfulRun` returns the run with the greatest `finished_at`.
- `latestSuccessfulRun` falls back to `started_at` when `finished_at` is
  null.
- `latestSuccessfulRun` returns null when no runs succeeded.
- `latestSuccessfulRun` returns null for an empty list.
- `latestSuccessfulRun` does not mutate the input array.
- `latestSuccessfulRun` is deterministic when two runs share the same
  timestamp (stable on input order is acceptable; assert it does not
  throw).

Add `frontend/src/components/__tests__/ExportPanel.branch.test.tsx` (new
file) using MSW for the project-runs and branches endpoints:

- When `onBranchSelect` is provided, changing the `<select>` calls
  `onBranchSelect` with the new branch id and does **not** mutate any local
  state.
- When `onBranchSelect` is absent, the branch is rendered as read-only text
  and there is no `<select>` with the branch role.
- When `targetBranchId` is null, "Select a branch." copy is shown and the
  readiness query is not enabled (assert via MSW handler call count or via
  the "Re-check" button being disabled).
- When there are no successful runs, the readiness/generate controls are
  disabled and the "No successful run" copy is shown.
- When the branch changes (ProjectView re-renders with a new
  `targetBranchId`), ExportPanel re-evaluates readiness against the new
  branch. Assert the readiness MSW handler is called with the new
  `target_branch_id`.

Use the existing `server` from `frontend/src/test/server.ts`. Add per-test
handlers with `server.use(...)`; do not mutate the shared default handlers
except to fix the duplicate `/plans/:planId/workflow-guidance` handler (see
Housekeeping below).

## Housekeeping

- Remove the duplicate `/plans/:planId/workflow-guidance` handler in
  `frontend/src/test/server.ts` (lines 5-22 and 55-68; keep one). MSW uses
  the first match, so the second is dead. Consolidate into a single
  handler with the richer `step_guidance` payload.
- Do not change `ProjectView.tsx`'s auto-select effect
  (`:65-70`). ProjectView remains the branch owner; it just stops passing
  `?? undefined` and starts passing `selectedBranchId` (nullable) plus
  `onBranchSelect={setSelectedBranchId}`.

## Acceptance criteria

- ExportPanel cannot silently use a different branch from ProjectView.
  The local branch state is gone.
- `latestSuccessfulRun` is deterministic and shared in `utils/runs.ts`.
- Branch/run/report mode are visible in the export panel.
- `ExportPanel.tsx` is smaller than before (the branch control moved to
  `BranchSelector.tsx`) and well under the 600-line ceiling.
- New files (`utils/runs.ts`, `BranchSelector.tsx`, tests) are each well
  under 600 lines.
- `npx tsc --noEmit` passes in `frontend/`.
- `npm test` passes in `frontend/`.
- No backend changes in this PR. No `schema.d.ts` regen needed.

## Out of scope for this phase

- Do not change readiness UX states (loading/error/blank) — that is PR 3.
- Do not add the journey acceptance test — that is PR 2.
- Do not fix "Go to step" section switching — that is PR 2.
- Do not add generate-safety guards beyond the existing
  `!readinessData?.ready` check — that is PR 3.
