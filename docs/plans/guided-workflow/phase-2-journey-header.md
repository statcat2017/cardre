# Phase 2 — JourneyHeader (integrated into TopBar)

You are implementing **Phase 2** of the Guided Workflow Sprint
(`docs/plans/guided-workflow-sprint.md`). Phase 0 and Phase 1 are merged.

Read first:
- `frontend/src/components/TopBar.tsx`
- `frontend/src/components/ProjectView.tsx`
- `frontend/src/hooks/useRunProgress.ts`
- `docs/adr/0008-workflow-guidance-seam-and-keys.md` (especially decision 5:
  one run CTA, not two)

## Goal

A user landing on `ProjectView` immediately sees the current phase, the next
required action, whether the project is blocked, and a single primary
button to continue. The Header uses `workflowGuidance` from Phase 1.

This phase **collapses TopBar's "Run Pathway" button into the JourneyHeader
CTA** so there is exactly one run trigger in the UI. Do not ship two CTAs.

The Header is integrated **into TopBar**, not as a separate ribbon above
ProjectView. TopBar already owns the prime horizontal real-estate; a second
ribbon is vertically expensive and competes with the existing run count and
project breadcrumb.

## Wire

```
ProjectView
  └─ useWorkflowGuidance(projectId, planId, selectedBranchId)
  ...
  <TopBar
     ...existing props...
     guidance={guidance}
     onAction={handleJourneyAction}
  />
```

`useWorkflowGuidance` is a thin TanStack Query wrapper:

```ts
// frontend/src/hooks/useWorkflowGuidance.ts
export function useWorkflowGuidance(
  planId: string | null,
  projectId: string | null,
  branchId: string | null,
  runId?: string | null,
) {
  return useQuery({
    queryKey: ["workflowGuidance", planId, branchId, runId],
    queryFn: () => api.getWorkflowGuidance(planId!, { project_id: projectId!, branch_id: branchId!, run_id: runId }),
    enabled: !!planId && !!projectId && !!branchId,
    staleTime: 2000,  // matches App.tsx default
  });
}
```

Refetch triggers:
- After `useRunProgress` finishes a run (call `queryClient.invalidateQueries({queryKey:["workflowGuidance"]})`).
- After params save (already handled by `handlePlanRefreshed`).
- After import (`handleImported`).

## TopBar Changes

TopBar extends to a two-row layout **only when `guidance` is loaded**, otherwise one row as today:

Row 1 (existing): Cardre / project / plan breadcrumb, project counts, **single
run CTA — now `guidance.next_action.label` instead of "Run Pathway"**.

Row 2 (new, only when guidance present): phase chip + blockers summary +
report readiness badge.

Row 2 layout (sketch, not pixel-perfect):

```
[Phase: Build]  ⚠ 2 blockers  ✓  WOE/IV evidence present   [Continue]
                Continue = next_action's primary button
```

- `phase` chip: small label with `theme.blueBg`/`theme.blueText`.
- Blockers count: if `blockers.length > 0`, show `theme.redText` pill with
  count; click expands a small popover listing `code: message`.
- Report readiness badge:
  - `report_readiness.ready === true` → `greenText "Report ready"`.
  - `report_readiness.blockers.length > 0` → `redText "Report blocked
    (N)"`.
  - `report_readiness.status === "ready_with_warnings"` → `yellowText "Report
    ready with N warnings"`.
  - `report_readiness === null` (no run) → omitted.

## Single Run CTA

TopBar's existing `onRun` prop is **replaced** by `onAction`. The CTA label
and disabled state derive from `guidance.next_action`:

- If `next_action.kind == "run_pathway"`: label =
  `next_action.label`, disabled = `running` (existing state from
  `useRunProgress`).
- If `next_action.kind == "import_dataset"`: label = "Import dataset" →
  `onSectionChange("dataset")`.
- If `next_action.kind == "configure_step"`: label = "Configure step" →
  `onStepSelect(next_action.step_id)` then expand StepInspector params
  editor.
- If `next_action.kind == "edit_bins"`: label = "Edit bins" →
  `onEditManualBinning(next_action.step_id)`.
- If `next_action.kind == "resolve_blocker"`: label = "View blockers" →
  `onStepSelect(next_action.step_id)`.
- If `next_action.kind == "review_evidence"`: label = "Review evidence" →
  `onStepSelect(next_action.step_id)`.
- If `next_action.kind == "export_report"`: label = "Open exports" →
  `onSectionChange("exports")`.

`ProjectView.handleJourneyAction` dispatches based on
`guidance.next_action.kind` (and `action_target` if present). The existing
`handleRun` still exists for `kind == "run_pathway"`: reuse it.

`onAction` receives `WorkflowGuidance` so `handleJourneyAction` does not need
to thread other props; pass `stepProgress` separately still.

## Action → Run Scope

When `next_action.kind == "run_pathway"` and `next_action.run_scope !=
"full_plan"`, `handleRun` must pass the suggested scope:

```ts
// useRunProgress.startRun signature must accept run_scope
startRun(planVersionId, { run_scope: guidance.next_action.run_scope ?? "full_plan" });
```

Edit `useRunProgress.ts` to accept an options object
`{ run_scope, target_step_id, branch_id }` and forward to `api.runPlan`. The
existing default (`"full_plan"`) is preserved when no options given.

## Files

| File                                             | Action | Content                                                                                                          |
|--------------------------------------------------|--------|------------------------------------------------------------------------------------------------------------------|
| `frontend/src/hooks/useWorkflowGuidance.ts`      | Create | TanStack Query wrapper for `api.getWorkflowGuidance`.                                                            |
| `frontend/src/components/TopBar.tsx`             | Edit   | Two-row layout when `guidance` present. Replace `onRun` with `onAction`. Render phase chip + blockers pill + report readiness badge. Run CTA label and disabled state follow `guidance.next_action`. |
| `frontend/src/components/ProjectView.tsx`        | Edit   | Call `useWorkflowGuidance`. Add `handleJourneyAction(guidance)`. Pass `guidance` and `onAction` to `TopBar`. Invalidate `workflowGuidance` in `handleImported`, `handlePlanRefreshed`, and on run completion (extend the `useRunProgress` `onRunComplete` callback). Pass `selectedBranchId` from Phase 0 into the hook. |
| `frontend/src/hooks/useRunProgress.ts`           | Edit   | `startRun(planVersionId, options?)` accepts `run_scope`/`target_step_id`/`branch_id`. The `api.runPlan` body now forwards these. Keep default `"full_plan"`. |
| `frontend/src/api/client.ts`                     | Edit   | `getWorkflowGuidance(planId, {project_id, branch_id, run_id?})` — already added in Phase 1's client.ts edit. Confirm here. |

## Sequence

1. Add `useWorkflowGuidance` hook.
2. Extend `useRunProgress.startRun` to accept scope options.
3. Refactor `TopBar` into the new two-row shape. Add a Storybook-free
   visual stub via local component state if needed for development.
4. Wire `ProjectView.handleJourneyAction` and pass `guidance` to `TopBar`.
5. Add invalidation calls in the three refetch trigger paths.
6. `npx tsc --noEmit` clean.

## Acceptance Criteria

Manually (dev mode is acceptable until Phase 7):

1. Project with no dataset shows phase **setup**, CTA **Import dataset**, click
   takes central pane to the dataset section.
2. Imported dataset with unconfigured target step shows phase **build**, CTA
   **Configure step**, click selects that step in the pathway and expands
   StepInspector params editor (Phase 4 will make this visible; here the step
   is just selected).
3. After a run that left a step stale, phase is **build** or **validate** per
   ADR 0008 derivation; blockers pill reflects the count; CTA suggests
   **Run pathway** with the correct `run_scope`.
4. With `report_readiness.ready === false`, the badge shows "Report blocked
   (N)".
5. Report ready → phase **ready**, CTA **Open exports**.
6. Only one run button exists anywhere in `ProjectView`. The old "Run
   Pathway" string does not appear after merge.

## Non-Goals

- PathwayCard or section state changes (Phase 3).
- StepInspector tab refactor (Phase 4).
- Evidence route work (Phase 4).
- Wiring the run-CTA scope into `useRunProgress`'s *execution backend* — that
  is already supported by `RunRequest.run_scope`; this phase just plumbs the
  suggestion through. Do **not** add any new backend run path.

## Drop-Dead Notes

- **Do not** create a separate `<JourneyHeader>` component that sits above
  TopBar. Integrate into TopBar. This is a deliberate deviation from the
  original plan (avoiding duplicate ribbons).
- **Do not** fetch guidance when `selectedBranchId` is null — wait until
  Phase 0's `BranchSelector` settles.
- `guidance.next_action.label` from the backend is the canonical CTA copy.
  Do not re-label in the frontend.
- CTA disabled logic: if `running` from `useRunProgress` is true, CTA shows
  progress text (`stepProgress.completed/total`) exactly like today;
  next-action label is restored when `running` returns to false.
- Deviating `phase` or `next_action` between renders causes flicker. Pin
  the guidance object within a `useMemo` keyed by stable query result identity
  (TanStack default). Avoid derived re-renders unless the data changes.