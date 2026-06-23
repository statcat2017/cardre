# Guided Workflow Sprint

Resolve the number-one weakness: the frontend/guided workflow trails the
backend. A modeller must be able to open Cardre, import a dataset, understand
the next required action, configure each launch step, run the pathway,
inspect evidence, fix blockers, manually edit bins, validate the scorecard,
and export a credible pack without needing to know backend internals.

## Design Principles

- **Do not rebuild the frontend from scratch.** Keep the current structure
  (left nav, central pathway/manual editor/artifacts/exports views, right
  step inspector, bottom diagnostics). Add a guided layer on top — never
  replace.
- **Reuse backend pieces, do not duplicate them.** Readiness comes from
  `check_report_readiness`; manual-binning readiness from
  `ManualBinningService.get_editor_state`; staleness from
  `compute_staleness`; plan status from `PlanService.get_plan_with_status`.
  The new `WorkflowGuidanceService` orchestrates; it does not re-implement.
- **Backend-for-frontend contract follows ADR 0006.** The
  `WorkflowGuidance` response is a Pydantic model in `sidecar/models.py`,
  reaches the frontend via `frontend/src/api/schema.d.ts`, and is consumed by
  a single one-liner in `client.ts`. No new inline TS types.
- **Phase vocabulary matches `CONTEXT.md` and ADR 0001.** Manual binning is
  part of the build stream; `phase` is `setup | build | validate | report |
  ready` (see ADR 0008). No new `manual_review` phase.
- **One run CTA, not two.** JourneyHeader and TopBar's "Run Pathway" button
  unify once `next_action.run_scope` exists. Retire the duplicate.
- **No DAG canvas yet.** A well-designed vertical journey beats a
  half-finished DAG. Do not invest in a canvas in this sprint.
- **No new model types.** Advanced modelling is not the bottleneck.
- **Evidence is step-attached, not a generic file explorer.** Keep
  `ArtifactBrowser` for non-step artifacts (notably the `__import__` plan
  outputs flagged by `TopBar`'s help tooltip) but never make it the evidence
  UX.

## Architectural Pre-Requisite

ADR 0008 fixes four contract decisions before they become silent bugs:
branch+run keying, the `WorkflowGuidanceService` seam, the phase vocabulary,
and evidence route boundaries. **Phase 0 implements ADR 0008's decision
points. No journey UI PR may start before Phase 0 is merged.**

See: `docs/adr/0008-workflow-guidance-seam-and-keys.md`.

## Phase Sequence

| Phase | Title                                                    | Depends on |
|-------|----------------------------------------------------------|------------|
| 0     | Foundations: ADR 0008 scaffolding + branch context UI   | —          |
| 1     | Workflow guidance backend endpoint                       | 0          |
| 2     | JourneyHeader (integrated into TopBar)                   | 1          |
| 3     | Guided PathwayView section states                        | 1, 2       |
| 4     | StepInspector Next action + Evidence tabs                | 1, 2       |
| 5     | Manual binning journey integration (5a UI, 5b review-complete marker) | 1, 2, 3 |
| 6     | Report readiness UI in Exports                           | 1, 2       |
| 7     | Frontend test infrastructure + journey acceptance tests  | 2, 3, 4, 6 |

Phases 3, 4, and 6 can be implemented in parallel after 2 lands. Phase 5
splits internally: 5a (journey integration + DTO enrichment) is mergeable
before 5b (review-complete marker with node-param schema + audit). Phase 7
starts late but its infra (vitest + RTL + msw dependency wiring, CI job)
can be added in Phase 2 as a one-commit prep step if it does not perturb
Phase 2 scope.

## Definition Of Done

A new user can complete the launch scorecard journey by following the UI's
prompts:

```
Import data
→ define target/sample
→ split/profile
→ bin/WOE
→ manually review bins
→ fit logistic scorecard
→ scale scorecard
→ validate
→ resolve warnings/blockers
→ export audit pack
```

At every point the UI explains where they are, what is complete, what is
missing, what to do next, what evidence exists, and whether the model or
report is defensible.

Mechanically, DoD requires:

- Endpoint `GET /plans/{plan_id}/workflow-guidance?branch_id=…&run_id=…`
  returns a populated `WorkflowGuidance` object for any plan, any branch,
  any run state.
- `WorkflowGuidanceService` unit tests assert it delegates exactly once per
  query to each readiness source (no duplicated logic).
- `ProjectView` carries `selectedBranchId`; PathwayView canonicalizes
  branch-owned step IDs.
- JourneyHeader (in TopBar) is the single run CTA.
- Every StepInspector tab is populated from a typed sidecar route, not raw
  artifact reads.
- Manual binning editor warns the modeller if they try to leave automated
  bins as final without a review-complete marker (Phase 5b) or an explicit
  accept-automated decision.
- ExportPanel auto-readiness + "Go to step" mapping join step IDs from
  `ReadinessBlocker` (not message parsing).
- `vitest run` is green in CI; six journey scenarios (per Phase 7) pass.

## Files Mapped To Phases

| Area              | Phase teasing                                                    |
|-------------------|------------------------------------------------------------------|
| ADR 0008          | Phase 0                                                          |
| `ProjectView`     | Phase 0 (branch state), 2 (JourneyHeader wiring), 5a            |
| `PathwayView`     | Phase 0 (canonicalization), 3 (section states)                  |
| `StepCard`        | Phase 3                                                          |
| `TopBar`          | Phase 2 (single CTA, phase/next-action ribbon)                  |
| `StepInspector`    | Phase 4 (tabs), 5a (manual-binning tab)                        |
| `ManualBinningEditor` | Phase 5a (warnings + IV/WOE/event-rate summary), 5b (review-complete) |
| `ExportPanel`     | Phase 6                                                          |
| `sidecar/routes/plans.py` | Phase 1 (`workflow-guidance`), Phase 4 (evidence routes) |
| `sidecar/routes/runs.py` | Phase 4 (`/runs/{id}/steps/{id}/evidence`, `/runs/{id}/evidence`) |
| `cardre/services/workflow_guidance_service.py` | Phase 1 (created) |
| `sidecar/models.py` | Phase 1 (`WorkflowGuidance` + nested DTOs), Phase 4 (evidence summary DTOs), Phase 5b (`reviewed` param), Phase 6 (`ReadinessBlocker.step_id`) |
| `frontend/src/api/schema.d.ts` | Regenerated at every backend-touching phase |
| `frontend/src/api/client.ts` | One-liner additions per ADR 0006 |
| `frontend/src/hooks/useWorkflowGuidance.ts` | Phase 2 |
| `frontend/src/hooks/useReportReadiness.ts` | Phase 6 (shared by ProjectView auto + ExportPanel manual) |
| `frontend/package.json` | Phase 7 (vitest, @testing-library/react, msw) |
| `.github/workflows/ci.yml` | Phase 7 (`test-frontend` job) |
| `docs/architecture/artifact-evidence-access.md` | Phase 4 augments with new routes |

## What This Sprint Must Not Do

- No DAG/canvas editor.
- No new model types or modelling extensions.
- No deprecation of `ArtifactBrowser` (still needed for `__import__` plan evidence).
- No report PDF styling investment until readiness/guidance ships.
- No second run CTA competing with JourneyHeader.
- No new inline TypeScript types for `WorkflowGuidance` (ADR 0006 compliance).