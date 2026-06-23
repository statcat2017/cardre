# Workflow Guidance Seam, Branch/Run Keys, And Phase Vocabulary

## Status

Proposed

## Context

The frontend/guided workflow is the top weakness. The proposed remedy is a
backend "workflow guidance" endpoint that returns a single
frontend-friendly object describing phase, next action, blockers, per-step
readiness, and report readiness, plus a series of UI layers that consume it.

Before that endpoint is implemented, four contract-level decisions are
undefined and each will silently produce wrong UI state if left implicit:

1. **No branch context in the UI.** `ProjectView` only holds `plan_id` and
   `latest_version_id`. `PlanService.get_plan_with_status`
   (`cardre/services/plan_service.py:62`) returns the latest plan version's
   steps flat and ignores `branch_step_map`. `compute_staleness` is called
   without `branch_id`. The guidance aggregator cannot answer "Is manual
   binning ready?" or "Which step is blocking launch?" for any branched plan
   because branch-owned step IDs (`manual-binning__br_xxx`) are not joined
   against `branch_step_map` and not resolved to canonical IDs.

2. **Readiness is run-keyed, not plan-keyed.** `check_report_readiness`
   (`cardre/reporting/readiness.py:102`) requires `(run_id, target_branch_id,
   report_mode)`. A plan-keyed guidance URL (`/plans/{plan_id}/workflow-guidance`)
   hides both; the aggregator would need to invent a "representative run"
   resolution that does not exist today. `PlanService` uses
   `list_runs(latest_pv_id)[0]`, which is wrong for branches whose runs
   reference the branch head version, not necessarily the plan's
   `latest_version_id`.

3. **The proposed `phase` enum reinvents existing vocabulary.** The plan
   proposed `setup | build | manual_review | validate | report | ready`.
   `CONTEXT.md` defines the build stream as including manual binning (under
   "Refinement nodes"), and ADR 0001 fixes the boundary at score scaling.
   Splitting `manual_review` out of `build` contradicts both. The frontend
   already groups steps via `STEP_DISPLAY_METADATA.sections` and
   `SECTION_ORDER` (see `frontend/src/config/stepDisplayMetadata.ts`),
   further fragmenting the vocabulary.

4. **No declared service seam for the aggregator.** Readiness logic lives in
   `cardre/reporting/readiness.py`, manual-binning readiness in
   `cardre/services/manual_binning_service.py`, staleness in
   `cardre/staleness.py`, plan status in `cardre/services/plan_service.py`.
   Without a declared seam, the next contributor will scatter readiness-derived
   logic across `plan_service.py`, `report_generation_service.py`, and a
   sidecar route, recreating the bifurcation ADRs 0002 and 0004 were written
   to prevent.

## Decision

1. **A dedicated `WorkflowGuidanceService` owns the aggregator.** It lives in
   `cardre/services/workflow_guidance_service.py`, is constructed with a
   `ProjectStore`, and delegates — never duplicates — to
   `check_report_readiness`, `ManualBinningService.get_editor_state`,
   `staleness.compute_staleness`, and `PlanService.get_plan_with_status`.
   No readiness logic is reimplemented inside it.

2. **The guidance endpoint is run-keyed and branch-keyed, not plan-keyed.**

   ```
   GET /plans/{plan_id}/workflow-guidance?branch_id=…&run_id=…
   ```

   At least one of `branch_id` or `run_id` is required. The service resolves
   the missing key from the other:
   - `run_id` only → `branch_id` resolved from `run.plan_version_id` via
     `get_branch_step_map` against the head version of the branch whose
     `head_plan_version_id == run.plan_version_id`. If none, no branch
     context (single-branch/fallback projects).
   - `branch_id` only → `run_id` resolved from the most recent successful run
     attached to `branch.head_plan_version_id`. If none, phase is `setup` or
     `build`.
   - Both supplied → must be consistent (`run.plan_version_id == branch.head_plan_version_id`
     or a known ancestor); 400 otherwise.

   This matches `getPlan`'s `?project_id=` convention and avoids introducing
   the first `/projects/.../plans/...` route.

3. **Phase vocabulary is derived from the existing two-stream model.** The
   `phase` field is one of:

   - `setup` — no imported dataset artifact with a `train` role is associated
     with the project yet (extension of the
     `_check_oot_exists` pattern in `readiness.py`).
   - `build` — build-stream steps (population, target, sample, split, profile,
     binning, WOE/IV, selection, manual binning, WOE transform, LR, score
     scaling) include incomplete or stale steps. Manual binning is part of
     `build`, not a separate phase.
   - `validate` — build stream is fully successful and not stale; validate
     steps (apply WOE, apply model, validation metrics, cutoff/strategy) are
     incomplete or stale.
   - `report` — all required canonical steps have non-stale successful run
     steps; report readiness may still report warnings/blockers.
   - `ready` — `report` phase plus `check_report_readiness.ready == true`.

   The enum is backend-derived from `STEP_DISPLAY_METADATA.sections` +
   `SECTION_ORDER` mirrored in a backend constant (not the frontend file),
   so backend and frontend agree without one importing the other.

4. **Branch context is introduced into the frontend before journey UI.**
   `ProjectView` gains `selectedBranchId` state and a small branch selector
   component. `PathwayView`'s step lookup canonicalizes branch-owned step IDs
   (strip `__br_xxx` suffix or resolve via `branch_step_map`) before hitting
   `STEP_DISPLAY_METADATA`. Without this, every journey UI test will be
   single-branch-only and break the day branches are used.

5. **`next_action` carries a suggested `run_scope`.** Alongside `kind` and
   `label`, the field exposes `"run_scope": "full_plan" | "branch" | "to_node"
   | null`. The JourneyHeader CTA and the existing TopBar "Run Pathway"
   button are unified — one CTA, driven by guidance — to avoid two competing
   run triggers.

6. **Evidence is surfaced only through sidecar summary routes.** PR 4's
   "Evidence" tab uses `ArtifactEvidenceReader.summarise_artifact`,
   `summarise_step_outputs`, and `summarise_run_artifacts`. The frontend never
   imports the reader; new routes `GET /runs/{run_id}/steps/{step_id}/evidence`
   and `GET /runs/{run_id}/evidence` return summary DTOs.

7. **No new handwritten inline TS types.** The `WorkflowGuidance` response
   shape is defined as a Pydantic model in `sidecar/models.py` and reaches the
   frontend only through `frontend/src/api/schema.d.ts` (regenerated). The
   handwritten `client.ts` method is a single one-liner typed from the
   generated operation. This brings the workflow-guidance endpoint into
   compliance with ADR 0006 from day one.

## Consequences

- **Easier:** the journey UI cannot silently produce wrong answers for
  branched plans; branch-keyed and run-keyed state are explicit.
- **Easier:** readiness reuses the single `check_report_readiness` source of
  truth; the service composition is auditable.
- **Easier:** phase vocabulary matches `CONTEXT.md`, the existing frontend
  section config, and ADR 0001. No follow-up ADR is needed to reconcile.
- **Harder:** `ProjectView` must gain a branch selector and branch state
  before journey UI work. This is a prerequisite gate, not a parallel PR.
- **Harder:** the evidence tab requires new sidecar routes, not just frontend
  wiring. Phase 4 cannot be a pure-frontend PR.
- **Risk:** if the `WorkflowGuidanceService` aggregator accidentally
  re-computes readiness instead of delegating, it will drift. Mitigated by a
  unit test asserting the service calls each delegate exactly once per query.