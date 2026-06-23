# Phase 2 — Guided Launch Journey Acceptance Test

## Goal

Replace the current thin TopBar smoke test with a meaningful journey-level
test that proves the UI wiring from project load through report readiness
and "Go to step" navigation. Fix the "Go to step" section-switch bug that
the test must assert against.

## Context you must read first

- `frontend/src/components/__tests__/journey.test.tsx` — the existing
  shallow test you are replacing. It renders `TopBar` in isolation with
  hardcoded props.
- `frontend/src/components/ProjectView.tsx` — the component under test.
  Trace the mount-time queries: `getProject` (31), `getProjectPlans` (36),
  `getPlan` (47), `listBranches` (60), `getProjectRuns` (via ExportPanel
  when exports section active), `getWorkflowGuidance` (72).
- `frontend/src/components/ProjectView.tsx:105-112` — `handleStepSelect`.
  This is the bug: it sets `selectedStepId` and clears `editingStepId` but
  does **not** `setActiveSection("pathway")`. "Go to step" from the exports
  tab updates `StepInspector` (always-mounted right panel) but leaves the
  center panel on exports.
- `frontend/src/components/ProjectView.tsx:123-163` — `handleJourneyAction`,
  which **does** switch sections for `configure_step`/`resolve_blocker`/
  `review_evidence`. This is the pattern to follow.
- `frontend/src/components/ProjectView.tsx:239-245` — ExportPanel only
  mounts when `activeSection === "exports"`. Tests that need readiness
  must first switch sections.
- `frontend/src/components/LeftNav.tsx` — the section switcher the test
  will click.
- `frontend/src/test/setup.ts` — `onUnhandledRequest: "error"`. Every
  endpoint ProjectView fires must be mocked or the test fails.
- `frontend/src/test/server.ts` — shared default handlers. Has a duplicate
  guidance handler that PR 1 should have consolidated; if not, consolidate
  here.
- `frontend/src/components/ExportPanel.tsx` — note the "Go to step" button
  at 274-285 calls `onStepSelect(b.step_id)`.
- `docs/plans/launch-journey-batch1/README.md` — batch-level validation
  context and cross-cutting rules.
- `docs/plans/launch-journey-batch1/phase-1-export-panel-branch-run-determinism.md`
  — PR 1 must land first. This phase depends on ExportPanel being
  controlled (so the test can assert branch wiring) and on
  `latestSuccessfulRun` living in `utils/runs.ts`.

## Fix: "Go to step" must switch the center panel to pathway

Before writing the tests, fix the wiring in `ProjectView.tsx`.

The current `handleStepSelect` (`:105-112`) is used by both `PathwayView`
(in-pathway clicks, where no section switch is needed) and `ExportPanel`'s
"Go to step" button (where the user is on the exports tab and needs to be
taken back to the pathway). One handler cannot serve both without a
section switch that would be wrong for in-pathway clicks.

Introduce a dedicated handler for the export-navigation case:

```ts
const handleGoToStep = useCallback((stepId: string) => {
  setSelectedStepId(stepId);
  setEditingStepId(null);
  setActiveSection("pathway");
}, []);
```

Wire `ExportPanel`'s `onStepSelect` prop to `handleGoToStep` (not
`handleStepSelect`). Leave `PathwayView`'s `onStepSelect` on
`handleStepSelect` so in-pathway toggle behavior (click selected step to
deselect) is unchanged.

Do **not** change `handleStepSelect` itself — the toggle-on-second-click
behavior is correct for pathway clicks and must not gain a section switch.

## MSW fixtures

Create `frontend/src/test/fixtures/launchJourney.ts` (new file) exporting
reusable fixture builders. Each builder returns an MSW `http` handler (or
a plain object the test composes into a handler). Names:

- `mockProject(projectId?)`
- `mockPlanWithLaunchSteps(planId?)` — returns a plan with at least
  `import` (succeeded), `target-definition` (not_run), and one
  build-phase step that the guidance will point at.
- `mockBaselineBranch(projectId?, branchId?)`
- `mockSucceededRun(projectId?, runId?)` — returns one succeeded run with
  a `finished_at` newer than its `started_at`.
- `mockWorkflowGuidanceBuildPhase(planId?, branchId?, stepId?)` — returns
  guidance with `phase: "build"` and a `configure_step` next action
  pointing at `stepId`.
- `mockWorkflowGuidanceExportPhase(planId?, branchId?, runId?)` — returns
  guidance with `phase: "report"` and an `export_report` next action, so
  the TopBar CTA drives the user to exports.
- `mockReportReadinessBlocked(runId?, stepId?)` — POST
  `/projects/:projectId/runs/:runId/report-readiness` returning
  `ready: false` with one blocker carrying `step_id`.
- `mockReportReadinessReady(runId?, branchId?)` — same POST returning
  `ready: true`, empty blockers/warnings.
- `mockListRunReportsEmpty(runId?)` — GET reports list returning `[]`.
- `mockGenerateReport(runId?, branchId?)` — POST reports returning a
  `GenerateReportResponse` with a fixed `report_id`.

The fixture file must be plain data/handler builders — no react, no
react-query. This keeps it reusable and keeps the test files small.

Required endpoints to mock for a `ProjectView` mount (because of
`onUnhandledRequest: "error"`):

| Endpoint | Triggered by |
|---|---|
| `GET /projects/:projectId` | `ProjectView` mount |
| `GET /projects/:projectId/plans` | `ProjectView` mount |
| `GET /plans/:planId` | `ProjectView` mount (after plan id resolves) |
| `GET /projects/:projectId/branches` | `ProjectView` mount (branch auto-select) |
| `GET /plans/:planId/workflow-guidance` | `ProjectView` mount (after branch resolves) |
| `GET /projects/:projectId/runs` | `ExportPanel` mount (exports section) |
| `POST /projects/:projectId/runs/:runId/report-readiness` | `ExportPanel` readiness query |
| `GET /projects/:projectId/runs/:runId/reports` | `ExportPanel` reports list query |
| `POST /projects/:projectId/runs/:runId/reports` | `ExportPanel` generate mutation |

`StepInspector` is always mounted but its only query is gated on
`!!step && isManualBinning` (`StepInspector.tsx:61`), so the pathway-phase
test does not need editor-state mocks unless it selects a manual-binning
step.

## Tests

Create `frontend/src/components/__tests__/journey.launch.test.tsx` (new
file). Render `ProjectView` inside a `QueryClientProvider` (retry disabled,
same helper as the existing journey test). Use `@testing-library/user-event`
for clicks so async state settles correctly.

### Test 1 — "loads guided project journey and shows pathway readiness"

Fixtures: `mockProject`, `mockPlanWithLaunchSteps`, `mockBaselineBranch`,
`mockWorkflowGuidanceBuildPhase`.

Asserts:
- Project loads (project name appears in the breadcrumb).
- TopBar shows the guidance CTA label from the build-phase next action.
- TopBar shows the `build` phase chip.
- PathwayView renders (assert at least one step from the plan is visible).
- The baseline branch is selected (assert the branch name appears in the
  context line added by PR 1, or assert the guidance handler was called
  with the baseline `branch_id`).

This test must fail if `ProjectView` stops wiring `guidance` into `TopBar`
or stops passing steps to `PathwayView`.

### Test 2 — "report blocker Go to step selects the blocked step and switches to pathway"

Fixtures: `mockProject`, `mockPlanWithLaunchSteps`, `mockBaselineBranch`,
`mockSucceededRun`, `mockWorkflowGuidanceExportPhase`,
`mockReportReadinessBlocked`, `mockListRunReportsEmpty`.

Steps:
1. Render `ProjectView`. Wait for the export-phase guidance CTA.
2. Click the TopBar CTA (or click the exports item in `LeftNav`) to switch
   to the exports section. Specify the trigger explicitly in the test —
   driving via the guidance `export_report` action is the most
   journey-faithful, but clicking `LeftNav` is also acceptable. Pick one
   and comment which.
3. Wait for `ExportPanel` to fetch report readiness.
4. Assert the blocker with `step_id` is shown.
5. Click "Go to step".
6. Assert **both**:
   - the center panel is now `PathwayView` (assert a pathway-only element
     is visible and an exports-only element is gone), **and**
   - the blocked step is selected (assert the step appears in
     `StepInspector`, or assert `StepInspector` shows the step id/name).

This test must fail if `handleGoToStep` does not set
`activeSection("pathway")`, and must fail if it does not set
`selectedStepId`. Asserting only `StepInspector` selection would pass
against the current buggy code — the pathway-visible assertion is the
real guard.

### Test 3 — "ready report enables generate and calls generate with the right branch/run"

Fixtures: `mockProject`, `mockPlanWithLaunchSteps`, `mockBaselineBranch`,
`mockSucceededRun`, `mockWorkflowGuidanceExportPhase`,
`mockReportReadinessReady`, `mockListRunReportsEmpty`,
`mockGenerateReport`.

Steps:
1. Render `ProjectView`, switch to exports.
2. Wait for readiness ready state to appear (assert the "Ready." copy or
   equivalent from PR 3, or assert the generate button is enabled).
3. Assert the generate button is enabled.
4. Click generate.
5. Assert the generate MSW handler was called with the expected
   `target_branch_id` (the selected baseline branch) and the expected
   `run_id` (the succeeded run from `mockSucceededRun`). Use a spy handler
   or assert on the captured request body.

This test must fail if ExportPanel uses a different branch from
`ProjectView` (the core PR 1 guarantee) or if it uses the wrong run.

## Acceptance criteria

- No placeholder tests. Every test renders `ProjectView` and asserts on
  real journey wiring.
- Test 2 fails if "Go to step" does not switch the center panel to
  pathway (the bug fix is guarded).
- Test 3 fails if ExportPanel uses the wrong branch or run.
- The fixture file is reusable and contains no react imports.
- `npx tsc --noEmit` passes in `frontend/`.
- `npm test` passes in `frontend/`.
- No backend changes. No `schema.d.ts` regen.

## Out of scope for this phase

- Do not change readiness UX copy (loading/error/blank states) — that is
  PR 3. Test 3 may assert on whatever ready indicator exists after PR 1;
  if PR 3's "Ready." copy is not yet present, assert on the generate
  button's enabled state instead.
- Do not add generate-safety branch/run echo guards — that is PR 3.
- Do not extract `ReadinessPanel` — that is PR 3.
