# Phase 0 — Foundations: ADR 0008 scaffolding + branch context UI

You are implementing **Phase 0** of the Guided Workflow Sprint
(`docs/plans/guided-workflow-sprint.md`). This phase is the hard
prerequisite gate. **Do not start Phase 1 until this is merged.**

Read first:
- `docs/adr/0008-workflow-guidance-seam-and-keys.md` (this phase implements its
  decision points).
- `CONTEXT.md` (build vs validate stream).
- `frontend/src/components/ProjectView.tsx`, `frontend/src/components/PathwayView.tsx`,
  `frontend/src/config/stepDisplayMetadata.ts`.

## Goal

Land the four contract decisions ADR 0008 fixes, with no user-visible
journey UI yet. By the end of this phase:
1. `ProjectView` carries a branch selector and a `selectedBranchId` state.
2. `PathwayView` canonicalizes branch-owned step IDs (`manual-binning__br_xxx`)
   before hitting `STEP_DISPLAY_METADATA`, so branch steps land in the right
   section.
3. The future-phase `WorkflowGuidanceService` seam is reserved (empty
   scaffold file with docstring + module path declared), preventing future
   contributors from scattering guidance logic across `plan_service.py` or
   `report_generation_service.py`.
4. The future-phase evidence route module is reserved (empty scaffold at
   `sidecar/routes/evidence.py`).

No HTTP routes, no DTOs, no Pydantic models, no frontend journey chrome.
Just the scaffolding + branch context.

## Files

| File                                                         | Action                | Content                                                                                                       |
|--------------------------------------------------------------|-----------------------|---------------------------------------------------------------------------------------------------------------|
| `docs/adr/0008-workflow-guidance-seam-and-keys.md`           | Already exists        | Reference only.                                                                                               |
| `cardre/services/workflow_guidance_service.py`                | Create (scaffold only) | `class WorkflowGuidanceService: """Reserved by ADR 0008. Phase 1 implements methods."""` — no logic, no body that hints at behaviour. |
| `sidecar/routes/evidence.py`                                 | Create (scaffold only) | Empty router with docstring citing ADR 0008 §6 and `docs/architecture/artifact-evidence-access.md`. Not registered in `main.py` yet. |
| `frontend/src/components/BranchSelector.tsx`                 | Create                | Compact `<select>` over active branches. Calls `api.listBranches(projectId, {status:"active"})`. Auto-selects first if none chosen. |
| `frontend/src/components/ProjectView.tsx`                     | Edit                  | Add `selectedBranchId` state. Render `<BranchSelector>` between `LeftNav` and the central pane. Pass `selectedBranchId` to all central subviews (PathwayView, RunHistoryPanel etc.). |
| `frontend/src/components/PathwayView.tsx`                    | Edit                  | When looking up `STEP_DISPLAY_METADATA[step.step_id]`, canonicalize the ID first. Accept the suffix pattern `__br_…`. Cache canonicalization locally; do not modify the step object. |
| `frontend/src/config/stepDisplayMetadata.ts`                 | Edit (additive)       | Export `canonicalizeStepId(stepId: string): string` that strips `__br_*` suffixes. `PathwayView` and any future consumer import this. |
| `frontend/src/types.ts`                                      | Edit (additive)       | Re-export `BranchListResponse`, `BranchListItem` types already in `schema.d.ts`. No inline shapes. |
| `tests/test_workflow_guidance_scaffold.py`                   | Create                | Assert `WorkflowGuidanceService` exists, accepts a `ProjectStore`, and has zero behaviour (no methods doing work). Locks the seam in place. |
| `frontend/src/components/__tests__/PathwayView.canonicalization.test.tsx` | Create (skipped unless Phase 7 test infra is already in) | Skip if vitest is not yet configured. Otherwise assert branch-owned step IDs render under their canonical section. |

## Contracts

- **`canonicalizeStepId`** is the only new public frontend API in this phase.
  Signature: `(stepId: string) => string`. Strips a trailing `__br_*` suffix.
  Pure function.
- **`WorkflowGuidanceService` scaffold contract** (Python):

  ```python
  class WorkflowGuidanceService:
      """Reserved by ADR 0008. Phase 1 populates methods."""

      def __init__(self, store: ProjectStore) -> None: ...
  ```

  No methods. No imports beyond `cardre.store.ProjectStore`.

## Sequence

1. Land ADR check: confirm `docs/adr/0008-*.md` exists and is referenced by
   `docs/plans/guided-workflow-sprint.md`. (Done at sprint creation.)
2. Create `WorkflowGuidanceService` Python scaffold + scaffold test.
3. Create `sidecar/routes/evidence.py` empty scaffold with docstring only.
4. Add `canonicalizeStepId` to `stepDisplayMetadata.ts` (pure function).
5. Update `PathwayView.tsx` to use `canonicalizeStepId` for section lookup.
6. Create `BranchSelector.tsx`.
7. Wire `selectedBranchId` into `ProjectView.tsx`. The Default branch
   selection rule: first active branch from `api.listBranches`. Persist
   selection across renders via component state (no URL routing yet).
8. Run `npx tsc --noEmit` in `frontend/` and `python3 -m pytest tests/test_workflow_guidance_scaffold.py -q`.

## Acceptance Criteria

- `npx tsc --noEmit` clean.
- `python3 -m pytest tests/test_workflow_guidance_scaffold.py -q` green.
- A plan with a branch that owns `manual-binning__br_xxx` renders that step
  under the **same** section as the canonical `manual-binning` step. Manual
  check via dev mode is acceptable until Phase 7 lands automated coverage.
- `ProjectView` shows the `BranchSelector`. Switching branches does not
  crash the view; downstream Phase 1+ consumes the value.
- No existing frontend or backend test regresses (`python3 -m pytest tests/ -q`).

## Non-Goals

- Implementing the guidance endpoint (Phase 1).
- Implementing evidence routes (Phase 4).
- Auto-detecting the "default" branch (the *baseline* branch is
  `branch_type == "baseline"`; Phase 1 will hard-pin this if possible).
- URL routing for branches (out of scope; selector only).
- Any new Pydantic model.

## Drop-Dead Notes

- Do **not** call `compute_staleness` with a branch in this phase. The
  staleness call signature already supports `branch_id=` (see
  `cardre/services/plan_service.py:263`). Wiring that into
  `PlanService.get_plan_with_status` is **Phase 1's** call because it is
  observable. This phase does not change any plan-status behaviour.
- Do **not** deprecate the `Latest run` display anywhere. The branch selector
  co-exists with run state.
- Do **not** add `openapi-fetch` or any new npm dependency in this phase.
  Phase 7 may add `vitest` etc.; this phase touches dependencies only via
  regeneration of `schema.d.ts` if needed (it should not be needed).