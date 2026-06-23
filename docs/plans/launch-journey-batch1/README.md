# Launch Journey Proof and Branch/Run Correctness — Batch 1

## Purpose

Prove that the guided launch journey works as a product flow, not just as
individual components. Cover weaknesses:

1. no true frontend launch acceptance test;
2. ambiguous branch/run ownership;
3. non-deterministic report/export readiness flow;
4. frontend tests still too shallow.

Target outcome: a user can follow the guided UI from project load to report
readiness/export, and the tests prove branch/run/report state is consistent.

## Scope boundary

This batch does **not** add new modelling nodes, new backend evidence types,
or new scorecard functionality.

Allowed backend touches are limited to:
- Echo fields on an existing response (PR 3, optional) — not a new evidence
  type.
- Regenerating `frontend/src/api/schema.d.ts` when backend models change.

Focus areas:
- branch selection ownership;
- latest successful run selection;
- report-readiness state clarity;
- Go to step blocker navigation (including section switch);
- MSW-backed journey tests.

## Validation context (read before starting)

The plan was validated against the repo on 2026-06-23. Confirmed facts that
shape the work:

- `ExportPanel.tsx` keeps local `targetBranchIdLocal` state and renders a
  local branch `<select>` that bypasses `ProjectView.selectedBranchId`
  (`frontend/src/components/ExportPanel.tsx:40,62,199-213`). Live
  inconsistency: `ProjectView` feeds `selectedBranchId` to workflow
  guidance but ExportPanel can silently evaluate a different branch.
- `successfulRuns[0]` is unsorted in the frontend
  (`ExportPanel.tsx:52-53`). The backend already returns runs `ORDER BY
  started_at DESC` (`cardre/store/run_repo.py:75`), so it happens to work
  today. PR 1's sort is for explicitness, `finished_at` correctness for
  succeeded runs, and defense against backend changes — not a live breakage.
- `journey.test.tsx` renders `TopBar` in isolation with hardcoded props, not
  `ProjectView`. It does not exercise `PathwayView`, `StepInspector`, or
  `ExportPanel`.
- "Go to step" today calls `ProjectView.handleStepSelect`
  (`ProjectView.tsx:243,105-112`), which only sets `selectedStepId` and
  clears `editingStepId`. It does **not** `setActiveSection("pathway")`. So
  from the exports tab, "Go to step" updates `StepInspector` (always-mounted
  right panel) but the center panel stays on exports — the user never sees
  `PathwayView`. Compare `handleJourneyAction` (`:130-137`) which does
  switch sections. **This is a real UX bug and must be fixed in this
  batch.**
- `ReportReadinessResponse` (`sidecar/models.py:570-574`) contains only
  `ready/status/blockers/warnings` — no `target_branch_id` or `run_id`.
  Combined with the stale-`readinessData` behavior (see below), a user can
  fetch readiness for branch A, switch to branch B (stale `ready=true`
  still shown), and click Generate → generates for B from A's readiness.
  This is the actual safety gap PR 3 must close.
- Readiness transient states are worse than the original plan described:
  - The readiness panel only renders when `readinessData` is truthy
    (`ExportPanel.tsx:263`), so during initial load it is blank — not
    "Checking…".
  - The clear effect (`:121-125`) resets local `blockers/warnings/errorMsg`
    but `readinessData` (react-query cache) is not cleared, and the sync
    effect (`:71-76`) immediately re-populates from stale data. Stale
    blockers for branch A can flash for branch B.
  - Error only shows when `errorMsg && !readinessData` (`:303`). A failed
    re-check after a prior success is hidden.
- Two readiness surfaces can diverge: `guidance.report_readiness`
  (`WorkflowGuidance.report_readiness`, `sidecar/models.py:811`) shown as
  the TopBar badge (`TopBar.tsx:154-177`), and `useReportReadiness`
  (separate POST) in ExportPanel. Different `staleTime`, different
  triggers. The user can see "Report ready" in TopBar and "Blocked" in
  ExportPanel. This batch only touches ExportPanel's readiness; PR 3's
  freshness copy must make clear which readiness is being shown.
- CI enforces a **600-line limit per `.tsx` file**
  (`scripts/check-line-counts.py`, job `check-line-counts`). `ExportPanel.tsx`
  is already 370 lines. PRs 1 and 3 together will approach/exceed 600 unless
  subcomponents/hooks are extracted. This is a hard CI gate, not optional.
- `frontend/src/test/setup.ts` uses `onUnhandledRequest: "error"`. Any
  unmocked network call fails the test. Journey fixtures must cover every
  endpoint `ProjectView` fires on mount and on section switch.
- `frontend/src/test/server.ts` has a duplicate
  `/plans/:planId/workflow-guidance` handler (lines 5-22 and 55-68). MSW
  uses the first match; the second is dead. Consolidate when adding
  fixtures.
- `check-api-contracts` CI job regenerates
  `frontend/src/api/schema.d.ts` and fails on uncommitted diff. Any backend
  model change must commit the regenerated types in the same PR.

## PR sequence

| PR | Title | Main outcome |
|----|-------|--------------|
| PR 1 | ExportPanel branch/run determinism | Controlled branch selection, deterministic latest run, subcomponent extraction started |
| PR 2 | Guided launch journey acceptance test | Real ProjectView-level MSW journey tests + Go-to-step section-switch fix |
| PR 3 | Report readiness UX states | Clear disabled/loading/error/ready states, generate safety, freshness copy |

Detailed LLM instructions live in:
- `phase-1-export-panel-branch-run-determinism.md`
- `phase-2-guided-launch-journey-acceptance-test.md`
- `phase-3-report-readiness-ux-states.md`

## Cross-cutting rules for all three PRs

1. **No new modelling/evidence/scorecard scope.** If a change tempts you into
   `cardre/nodes/`, `cardre/executor.py`, or `cardre/reporting/collector.py`,
   stop and re-scope.
2. **Stay under the 600-line `.tsx` ceiling.** Extract before approaching
   it. Reusable helpers go in `frontend/src/utils/` or
   `frontend/src/hooks/`, not inline.
3. **No new handwritten TS types for API shapes.** Per ADR 0006, API
   response shapes come from `frontend/src/api/schema.d.ts`. If the backend
   model changes, regenerate types with
   `python3 scripts/generate-openapi-types.py` and commit the diff in the
   same PR.
4. **Every new test uses MSW.** Do not mock `api` modules directly. The
   `server` in `frontend/src/test/server.ts` is the only network seam.
5. **Do not leave TODOs that gate safety.** If a guard cannot be
   implemented, either implement the prerequisite or remove the guard — do
   not ship a TODO that implies safety the code does not provide.

## Definition of done for the batch

1. ExportPanel has one clear branch owner (`ProjectView`).
2. Latest successful run selection is deterministic and shared.
3. Report readiness visibly applies to a specific branch/run/mode.
4. "Go to step" from ExportPanel switches the center panel to `pathway`
   **and** selects the blocked step. Tests assert both.
5. The frontend has a real ProjectView-level guided journey test using MSW.
6. CI runs frontend tests and fails on broken journey wiring.
7. No new modelling scope is introduced.
8. `ExportPanel.tsx` and every new file stay under the 600-line CI ceiling.

## Priority

Do this before evidence UI polish or manual-binning redesign. This batch
provides the safety net needed to keep improving Cardre without repeatedly
breaking the core launch journey.
