# Manual-Binning UX Polish — Batch 3

## Purpose

Make manual binning feel like a governed modelling workflow rather than a
parameter-editing screen.

By the end of Batch 3, a modeller should be able to:

1. See which variables need binning review.
2. Understand why a variable needs attention.
3. Inspect bins, WOE, IV, missing/special handling, and warnings.
4. Make or accept binning decisions with clear audit reasons.
5. Mark manual binning as reviewed only when the branch-specific review
   state is valid.
6. See the result reflected in readiness, evidence, and report export.

## Non-goals

Batch 3 does **not** add new binning algorithms, new ML methods, reject
inference, fairness, challenger modelling, or report redesign. It also
does **not** rewrite the manual-binning backend beyond the small
contract widening called out in Phase 1.

## Why this batch exists as four phases, not five PRs

The original draft plan proposed five PRs that each "add or harden"
parallel structures alongside the substantial manual-binning stack that
already ships. A pre-batch validation pass against the repo on
2026-06-24 found that most of the proposed surface already exists, and
that the draft would have introduced a second, parallel state model
fighting the one that already drives readiness, staleness reset, and
audit. The amended plan collapses the work into four phases that
**augment the existing contract in place** rather than building
alongside it.

## Validation context (read before starting)

Validated against the repo on 2026-06-24. Confirmed facts that shape the
work:

- `ManualBinningService` (`cardre/services/manual_binning_service.py:86`)
  already assembles branch-scoped editor state, walks
  `branch_step_map`, resolves upstream bin / variable-selection defs,
  and computes per-variable WOE / IV / event-rate plus sparse / missing
  / special / non-monotonic warnings. `get_editor_state` already
  branches via `mb_spec.branch_id` and `find_nearest_binning_source`.
- `ManualBinningEditorStateResponse`
  (`cardre/services/plan_dto.py:72`) already carries `plan_id`,
  `plan_version_id`, `step_id`, `ready`, `blocked_reason`,
  `required_steps`, `source`, `selected_variables`,
  `source_bins_by_variable`, `current_overrides`, `warnings`, and
  `variable_summaries`. The sidecar model at `sidecar/models.py:296`
  mirrors it. **Augment these in place — do not add a parallel DTO.**
- Sidecar endpoints already exist: `GET editor-state`,
  `POST …/preview`, `POST …/review` (`sidecar/routes/plans.py:67-108`),
  plus Pydantic models `ManualBinningReviewRequest` / `Response`
  (`sidecar/models.py:332-345`).
- `save_with_review` (`manual_binning_service.py:356`) already writes a
  `step_annotations` row of kind `"manual_binning_review"` for audit.
  The annotation payload today carries `reviewed`, `accept_automated`,
  `override_count`, `base_plan_version_id`, `new_plan_version_id`. It
  does **not** carry `reviewed_by`, `reason_code`, or `review_reason` —
  Phase 1 adds those.
- Readiness already blocks on `MANUAL_BINNING_NOT_REVIEWED`
  branch-scoped via `resolve_step_for_branch` and the step map
  (`cardre/readiness/check.py:190-216`). The blocker already carries
  `step_id`. The readiness check reads `params.get("reviewed")` /
  `params.get("accept_automated")` — keep those as the persisted
  contract.
- The staleness-reset block in `PlanService.update_params`
  (`cardre/services/plan_service.py:272-294`) resets
  `reviewed` / `accept_automated` to `False` when an upstream step
  changes. Any new persisted review field added by Phase 1 must be
  added to this reset path too.
- The override schema is generic and validated by
  `LifecycleBinDefinition.validate_overrides`
  (`cardre/engine/binning/definition.py:372`). Valid actions are
  `merge_bins`, `group_categories`, `reject_variable`,
  `reorder_missing_bin`, `reorder_special_bin` (see
  `cardre/nodes/build/bins.py:431`). **Adjacency for numeric merges is
  already enforced** at `definition.py:428`. "Isolate missing" and
  "isolate special" are **not** first-class actions — see Phase 2 for
  how they are expressed.
- The override schema already requires `reason` free-text per override
  (`bins.py:492-493`) and persists overrides as-is in
  `params.overrides`. Phase 1 adds a structured `reason_code` enum
  alongside the existing free-text.
- `ManualBinningVariableSummary` lives in **three** places:
  `cardre/services/plan_dto.py`, `sidecar/models.py`, and the frontend
  via `frontend/src/api/schema.d.ts` (regenerated from OpenAPI per ADR
  0006). All three must widen identically; do not hand-sync.
- `_check_sparse_bins` and `_check_non_monotonic`
  (`manual_binning_service.py:67-83`) duplicate logic that belongs in
  `cardre/engine/binning/diagnostics.py`. Phase 1 folds these into the
  diagnostics module so Phase 2's warning counts and Phase 3's blocker
  computation share one implementation.
- `save_with_review` opens its own `transaction()` and inserts an
  annotation **after** `PlanService.update_params` has already
  committed (`manual_binning_service.py:392`). That is two writes, not
  atomic — if the annotation insert fails, the step is marked reviewed
  with no audit row. Phase 1 wraps both in one transaction (or moves
  annotation writing into `update_params` behind a flag).
- Frontend `ManualBinningEditor.tsx` (411 lines) already has the summary
  table, override form requiring a reason, preview/review actions, and
  the "Accept automated bins" path. Phase 2 replaces the ad-hoc
  table-and-form with the governed two-column layout; it does not
  introduce a second editor.
- Evidence summaries live in `cardre/_evidence/summaries.py`
  (dispatch by `schema_version`). There is **no** manual-binning
  evidence kind today — manual binning is reported via the
  `cardre.manual_binning_review` annotation. Phase 4 reuses the
  annotation, it does not invent a new evidence kind.

## Phase sequence

| Phase | Title                                                  | Depends on |
|-------|--------------------------------------------------------|------------|
| 1     | State contract consolidation + audit widening          | —          |
| 2     | Variable review list and governed editor layout       | 1          |
| 3     | Bin detail, safe edits, and review-completion gate     | 1, 2       |
| 4     | Readiness / evidence / report integration              | 3          |

Phases 1 and 2 may be implemented in parallel after Phase 1's contract
widening is code-complete (the frontend can develop against a stub),
but Phase 2 must not merge until Phase 1 lands the DTO and annotation
changes. Phase 3 depends on both. Phase 4 depends on Phase 3 because
evidence and report integration surface the review-completion state.

Detailed LLM instructions live in:

- `phase-1-state-contract.md`
- `phase-2-variable-review-list.md`
- `phase-3-bin-detail-safe-edits-gate.md`
- `phase-4-readiness-evidence-report.md`

## Cross-cutting rules for all phases

1. **No parallel manual-binning state model.** `reviewed` /
   `accept_automated` in `plan_steps.params_json` plus the
   `manual_binning_review` annotation are the canonical contract.
   `review_status`, `blockers`, and `warnings` are **computed at the
   DTO boundary**, never persisted as a third representation.
2. **Reuse existing resolution modules.** Branch / canonical
   resolution is `cardre/step_id.py:resolve_required_steps` /
   `resolve_step_for_branch`. Staleness is `cardre/staleness.py`.
   Bin-def / selection-def reading is `ArtifactEvidenceReader`. Do not
   reimplement these in the editor route or service.
3. **No handwritten TS types for API shapes.** Regenerate
   `frontend/src/api/schema.d.ts` via
   `python3 scripts/generate-openapi-types.py` and commit the diff in
   the same PR. `check-api-contracts` CI job enforces this.
4. **Every new frontend test uses MSW.** The `server` in
   `frontend/src/test/server.ts` is the only network seam; unhandled
   requests fail tests.
5. **Stay under the 600-line `.tsx` and `.py` ceiling** except for test
   files (per `scripts/check-line-counts.py`). Extract before
   approaching it. Reusable backend helpers go in
   `cardre/engine/binning/diagnostics.py` or `cardre/_evidence/`;
   reusable frontend helpers go in `frontend/src/utils/` or
   `frontend/src/hooks/`.
6. **`selected_variable_id` is frontend-only.** It does not belong on
   the backend response — putting it there forces the backend to track
   a per-user cursor with no audit meaning.
7. **`in_progress` is not persisted.** It is a transient frontend badge
   meaning "has unsaved draft overrides". The backend contract has
   only three real states: unreviewed (`reviewed=False`,
   `accept_automated=False`), reviewed (`reviewed=True`), and
   accepted-automated (`accept_automated=True`). The `review_status`
   string on the DTO is a computed view over these.
8. **Every manual edit persists a reason.** The override already
   requires `reason` free-text. Phase 1 adds a `reason_code` enum
   alongside it; Phase 3 enforces both are present on save.
9. **Atomic review write.** The annotation insert and the
   `update_params` commit must be one transaction. Phase 1 fixes the
   current non-atomic split.

## Definition of done for the batch

1. Manual-binning state is branch-scoped and self-describing: the DTO
   carries `branch_id`, `run_id`, computed `review_status`, and the
   per-variable fields a governed review needs.
2. `reviewed` and `accept_automated` remain the persisted contract;
   `review_status` is computed and cannot drift from them.
3. The `manual_binning_review` annotation carries `reviewed_by`,
   `reason_code`, and `review_reason`; the write is atomic with
   `update_params`.
4. Variables needing review are visible without opening each variable:
   the two-column layout renders IV, bin count, missing / special,
   monotonicity, warning count, and review-required badges from the
   backend DTO.
5. Bin-level WOE / IV / bad-rate evidence is visible in a bin table.
6. Manual edits require a `reason_code` and free-text rationale; the
   override schema enforces both; preview precedes save.
7. Review completion is gated by backend validation: unreviewed
   required variables, edits without reasons, unresolved zero-cell /
   sparse-bin blockers, unresolved missing / special handling, and
   branch mismatch all block completion.
8. `reviewed` and `accept_automated` remain distinct states throughout
   readiness, evidence, and report.
9. Readiness blockers link to the branch-owned manual-binning step
   (already true; Phase 4 asserts it survives the new DTO shape).
10. `EvidenceTab` shows a manual-binning review summary card.
11. The report bundle contains a manual-binning review evidence
    section: review status, variables edited, reasons, unresolved
    warnings, and whether automated bins were accepted.
12. Tests cover state, edit, review-completion, readiness, evidence,
    and report integration.
13. No `.tsx` or non-test `.py` file exceeds the 600-line ceiling.
14. No new modelling scope is introduced.

## What this batch must not do

- Introduce a persisted `review_status` enum that duplicates
  `reviewed` / `accept_automated`.
- Persist `selected_variable_id` on the backend.
- Persist `in_progress` as a backend state.
- Invent a new manual-binning evidence kind. Reuse the
  `manual_binning_review` annotation.
- Add "isolate missing" / "isolate special" as new node actions. They
  are encoded as `reorder_missing_bin` / `reorder_special_bin` in the
  existing override schema; Phase 2 surfaces that mapping in the UI.
- Hand-sync `ManualBinningVariableSummary` across the three layers.
  Regenerate the frontend types.
- Grow `ManualBinningEditor.tsx` past the 600-line ceiling. Phase 2
  splits it into focused components.