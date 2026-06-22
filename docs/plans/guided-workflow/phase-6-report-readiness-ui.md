# Phase 6 — Report readiness UI in Exports

You are implementing **Phase 6** of the Guided Workflow Sprint
(`docs/plans/guided-workflow-sprint.md`). Phases 1 and 2 are merged. Phase
4's `ReadinessItem.step_id` field (introduced in Phase 1) is the
prerequisite for the "Go to step" join this phase ships.

Read first:
- `frontend/src/components/ExportPanel.tsx` (already renders readiness)
- `cardre/reporting/readiness.py` (`check_report_readiness`)
- `cardre/reporting/limitation_codes.py` (`LimitationCode`)
- `docs/adr/0008-workflow-guidance-seam-and-keys.md`

## Goal

The export panel never feels like "try export and see if it fails." It
explains readiness before the user attempts export, auto-fetches readiness
on important state changes, and provides a "Go to step" action beside
blockers that map to a step.

Phase 1 already adds `step_id: str | None` to `ReadinessItem`. Phase 6 just
consumes it. No new backend work unless you discover a blocker code whose
canonical step mapping is missing — see "Blocker → step mapping" below.

## Behaviour Changes

### Auto-readiness (single shared hook)

`ExportPanel` currently triggers readiness via a manual `Check readiness`
button. Phase 6 replaces this with:

- **Auto-fetch on mount** when `latestRun` and `targetBranchId` are
  settled.
- **Auto-refetch** when `targetBranchId` or `reportMode` changes
  (existing `useEffect` resets the UI; just trigger the query there too).
- **Auto-refetch** when a run completes (`useRunProgress.onRunComplete`
  invalidates the shared query).
- The manual "Check readiness" button stays as a refresh affordance.

Move the readiness query out of `ExportPanel`'s local `useMutation` into a
shared hook used by both `ProjectView` (JourneyHeader's readiness badge,
Phase 2) and `ExportPanel`:

```ts
// frontend/src/hooks/useReportReadiness.ts
export function useReportReadiness(
  projectId: string | null,
  runId: string | null,
  targetBranchId: string | null,
  reportMode: "branch" | "champion" = "branch",
  opts?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: ["reportReadiness", projectId, runId, targetBranchId, reportMode],
    queryFn: () => api.getReportReadiness(projectId!, runId!, {
      target_branch_id: targetBranchId!,
      report_mode: reportMode,
    }),
    enabled: !!projectId && !!runId && !!targetBranchId && (opts?.enabled ?? true),
    staleTime: 5000,
  });
}
```

This hook is the single source of readiness for the entire UI. Phase 2's
report-readiness badge inside TopBar must use it — do not fetch twice.

The hook uses **branch mode** by default for a passive readiness pulse.
Champion mode is a manual switch inside `ExportPanel`.

### "Go to step" beside blockers

For each rendered `blocker` in readiness display:

- If `blocker.step_id` is non-null (Phase 1 added this), render a
  small **"Go to step"** button beside the blocker row.
- Click → `onStepSelect(blocker.step_id)` + `setActiveSection("pathway")`.
  `ProjectView` already owns `setActiveSection` and `setSelectedStepId`;
  thread callbacks through `ExportPanel`'s props.

### Blocker → step mapping

Phase 1 populates `ReadinessItem.step_id` for known blockers. If a
`LimitationCode` does **not** map to a step, `step_id` is `None` and the
"Go to step" button is hidden — nothing breaks.

Confirm coverage of the codes already documented in `readiness.py`:
`TARGET_BRANCH_NOT_FOUND` (no step), `MISSING_REQUIRED_CANONICAL_STEP`
(step in `message` — Phase 1 captures this into `step_id`),
`MISSING_WOE_IV_EVIDENCE_V1` (step), `MISSING_RUN_MANIFEST` (no step),
`CHAMPION_ASSIGNMENT_MISSING` (no step), `NO_CHAMPION_ASSIGNMENT` (no step,
warning), `NO_OOT_SAMPLE` (no step, warning).

If any legal `LimitationCode` that warrants a "Go to step" action is
unmapped, **add the mapping in `cardre/reporting/readiness.py`** (the
backend populates `step_id` directly). Do not add the mapping in the
frontend. The frontend only consumes.

### Readiness display polish

Keep the existing visual layout in `ExportPanel.tsx:294-320`. The only
additions:

- Auto-readiness fetch (no manual click needed on first visit).
- The small "Go to step" button per row.
- A new "Re-check" affordance next to the manual button, both wired to
  `queryClient.invalidateQueries({queryKey:["reportReadiness",...]})`.

### JourneyHeader integration

JourneyHeader's report-readiness badge (Phase 2) reads from the same
`useReportReadiness` hook. Confirm the hook's `enabled` logic works for
ProjectView (where `latestRun` may be derived from `projectRuns` query).
Trigger invalidation from `useRunProgress`'s `onRunComplete` callback.

If the readiness state disagrees between JourneyHeader and ExportPanel,
it's a query-key bug in the shared hook — mismatched `targetBranchId` is
the most likely cause (ExportPanel tracks its own local state; ProjectView
now tracks `selectedBranchId` from Phase 0). To avoid this, the
`ExportPanel`'s `targetBranchId` should default to the
`ProjectView.selectedBranchId` when available, falling back to its
existing auto-select behaviour only when not given. Make `targetBranchId`
an optional prop on `ExportPanel`.

## Files

| File                                              | Action | Content                                                                                          |
|---------------------------------------------------|--------|--------------------------------------------------------------------------------------------------|
| `frontend/src/hooks/useReportReadiness.ts`         | Create | Shared TanStack Query hook.                                                                      |
| `frontend/src/components/ExportPanel.tsx`         | Edit   | Replace `checkReadinessMutation` with `useReportReadiness`. Accept optional `targetBranchId`. Add "Go to step" buttons per blocker. |
| `frontend/src/components/ProjectView.tsx`         | Edit   | Pass `selectedBranchId` into `ExportPanel` as `targetBranchId` (optional). Pass `onStepSelect` and `setActiveSection` callbacks. |
| `frontend/src/components/TopBar.tsx`              | Edit   | Phase 2's report badge uses `useReportReadiness` (rename any local copy to use the hook). |
| `cardre/reporting/readiness.py`                   | Edit if needed | If audit finds an unmapped step-bearing blocker code, add the assignment. Do not refactor. |
| `tests/test_sidecar_api.py`                       | Edit if needed | If new backend code paths, add coverage. Most likely no backend change required. |

## Sequence

1. Create `useReportReadiness`.
2. Refactor `ExportPanel` to consume it; add `targetBranchId` optional
   prop + `onStepSelect` callback prop.
3. Wire `ProjectView` to pass the props.
4. Refactor any Phase 2 local readiness copy in `TopBar` to use the hook.
5. Add "Go to step" button per blocker row.
6. If a backend mapping is missing, patch `readiness.py` first.
7. `npx tsc --noEmit` clean.

## Acceptance Criteria

- The export panel shows readiness on first mount without a manual click
  when a target branch + run are settled.
- Every blocker with a `step_id` exposes a "Go to step" button that
  switches the central pane to `pathway` and selects the step.
- Readiness shown in JourneyHeader and in ExportPanel are identical queries
  — same query key, same TanStack cache entry. No double-fetch.
- Switching the branch selector (Phase 0) updates the readiness shown in
  both places.
- After a run completes, readiness auto-refreshes without page reload.
- No project with `report_readiness.ready === false` allows the
  "Generate audit pack" button to become enabled — the existing
  `uiState.value === "ready" || "ready_with_warnings"` guard is preserved.

## Non-Goals

- Removing the manual "Check readiness" button (keep as refresh).
- Champion-mode blocker code at journey level — champion blockers only
  matter inside `ExportPanel` when the user explicitly selects champion
  mode.
- New readiness codes (out of scope; if surfaced through Phase 5b's
  `MANUAL_BINNING_NOT_REVIEWED`, that phase handles the mapping).
- Report PDF styling.

## Drop-Dead Notes

- **Do not** mutate the readiness object shape returned to `ExportPanel`.
  The shared hook returns exactly what `api.getReportReadiness` returns.
- **Do not** fetch readiness when both `runId` and `targetBranchId` are
  null; the hook's `enabled` must default to false in that state to avoid
  400s.
- The "Go to step" button must use **canonical or branch-owned step_id**
  consistently with `ProjectView.setSelectedStepId`. Phase 0's
  `canonicalizeStepId` is acceptable if the IDs differ — but the user
  should land on the right card regardless.
- The readiness fetch path uses **branch mode** for the passive pulse
  (ADR 0008). A future Champion-mode CTA may switch the hook's
  `reportMode` param at the call site; the hook does not infer.