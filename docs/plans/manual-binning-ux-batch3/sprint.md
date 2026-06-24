# Manual-Binning UX Polish Sprint

Resolve the next weakness: manual binning feels like a parameter screen,
not a governed modelling workflow. A modeller must be able to open the
manual-binning step, see which variables need review and why, inspect
bin-level WOE/IV/bad-rate evidence, make or accept binning decisions
with clear audit reasons, mark review complete only when the
branch-specific state is valid, and see the result reflected in
readiness, evidence, and the exported report — without rebuilding the
manual-binning backend.

This sprint covers Batch 3 of the launch-journey work. Batch 2
(evidence and readiness hardening) is a hard prerequisite: its
branch-scoped readiness, seven-state `EvidenceTab`, and consolidated
readiness producer are the foundations Phases 1 and 4 build on.

## Design principles

- **Do not build a parallel manual-binning state model.** The
  persisted contract is `reviewed` / `accept_automated` in
  `plan_steps.params_json` plus the `manual_binning_review`
  annotation. `review_status`, `blockers`, and `warnings` are
  **computed at the DTO boundary** from those, never persisted as a
  third representation. Every phase that needs blocker logic calls the
  single `compute_blockers(state)` helper introduced in Phase 1.
- **Augment the existing contract in place.** `ManualBinningService`,
  `ManualBinningEditorStateResponse`, the sidecar models, and the
  frontend editor already exist and are wired into readiness. Widen
  them; do not create parallel DTOs, services, or endpoints.
- **Reuse existing resolution modules.** Branch / canonical resolution
  is `cardre/step_id.py`; staleness is `cardre/staleness.py`; bin-def /
  selection-def reading is `ArtifactEvidenceReader`; readiness is
  `cardre/readiness/check.py`. No phase reimplements these.
- **The override schema is the action vocabulary.** `VALID_ACTIONS` on
  `ManualBinningNode` (`merge_bins`, `group_categories`,
  `reject_variable`, `reorder_missing_bin`, `reorder_special_bin`) is
  the complete set. "Isolate missing/special" maps to
  `reorder_missing_bin` / `reorder_special_bin`. No phase adds a new
  binning action. Adjacency for numeric merges is already enforced at
  `cardre/engine/binning/definition.py:428`.
- **No new evidence kind.** Manual binning is audited via the
  `manual_binning_review` annotation (Phase 1 widens its payload).
  Evidence and report integration derive a summary from the annotation
  + editor state; they do not invent an artifact kind.
- **Frontend types come from OpenAPI (ADR 0006).** Every
  backend-touching phase regenerates `frontend/src/api/schema.d.ts` and
  commits the diff. No hand-written TS types for API shapes.
- **`selected_variable_id` is frontend-only.** The backend never
  tracks the modeller's current cursor. It lives in React state and
  resets on reload.
- **`in_progress` is not persisted.** It is a transient frontend badge
  for "has unsaved draft overrides". The backend contract has three
  states: unreviewed, reviewed, accepted-automated.
- **Atomic review write.** The annotation insert and the plan-version
  commit are one transaction (Phase 1 fixes the current non-atomic
  split).
- **Stay under the 600-line ceiling** for `.tsx` and non-test `.py`
  (per `scripts/check-line-counts.py`). Split before approaching it.

## Phase sequence

| Phase | Title                                                | Depends on | Net new backend |
|-------|------------------------------------------------------|------------|-----------------|
| 1     | State contract consolidation + audit widening       | —          | Yes (widen DTO, atomic write, `compute_blockers`) |
| 2     | Variable review list and governed editor layout      | 1          | Minimal (fill DTO gaps only) |
| 3     | Bin detail, safe edits, and review-completion gate   | 1, 2       | Yes (gate, reopen, per-variable accept/reset audit) |
| 4     | Readiness / evidence / report integration            | 3          | Yes (evidence summary, report section) |

Phases 1 and 2 may be developed in parallel after Phase 1's contract is
code-complete (the frontend can develop against a stub DTO), but
**Phase 2 must not merge until Phase 1 lands** — otherwise the frontend
renders fields the backend does not yet produce. Phase 3 depends on
both: the bin table from Phase 2 hosts the edit actions, and the gate
uses Phase 1's `compute_blockers`. Phase 4 depends on Phase 3 because
evidence and report integration surface the review-completion state.

Detailed LLM instructions live in:

- `phase-1-state-contract.md`
- `phase-2-variable-review-list.md`
- `phase-3-bin-detail-safe-edits-gate.md`
- `phase-4-readiness-evidence-report.md`

## Definition of done

A modeller can complete the manual-binning review as a governed
workflow:

```
Open manual-binning step
→ see which variables need review (left column badges)
→ understand why (right column warnings + recommended action)
→ inspect bin-level WOE/IV/bad-rate (bin table)
→ edit or accept bins with reason code + free-text (edit dialog + preview)
→ mark review complete (gated by backend validation)
→ see review reflected in readiness, EvidenceTab, and the report bundle
```

Mechanically, DoD requires:

1. `ManualBinningEditorStateResponse` carries `project_id`,
   `branch_id`, `run_id`, computed `review_status`, `reviewed`,
   `accept_automated`, `reviewed_at`, `reviewed_by`, `review_reason`,
   `review_reason_code`, `blocking_issues`, and the widened
   per-variable fields — all computed or read from the annotation,
   none persisted as a parallel state.
2. `review_status` is derived from `reviewed` / `accept_automated`
   and cannot drift.
3. `save_with_review` writes `reviewed_by`, `reason_code`,
   `review_reason` into the annotation and is atomic with the plan
   version creation.
4. `_validate_manual_binning_review_params` requires `review_reason` +
   `reason_code` when `reviewed=True`.
5. Sparse / monotonicity checks live in
   `cardre/engine/binning/diagnostics.py`; the duplicated helpers in
   `manual_binning_service.py` are deleted.
6. `compute_blockers(state)` exists as a single function shared by the
   editor state, the review gate, and the evidence/report integration.
7. Variables needing review are visible without opening each variable:
   the two-column layout renders IV, bin count, missing/special,
   monotonicity, warning count, and review-required badges from the
   backend DTO.
8. Bin-level WOE / IV / bad-rate evidence is visible in the bin table.
9. Manual edits require a `reason_code` and free-text rationale; the
   override schema enforces both; preview precedes save.
10. Review completion is gated by backend validation: unreviewed
    required variables, edits without reasons, unresolved zero-cell /
    sparse-bin blockers, unresolved missing/special handling, and
    branch mismatch all block `reviewed=True`.
11. `reviewed` and `accept_automated` remain distinct states throughout
    readiness, evidence, and report.
12. Reopen review is an explicit, reasoned action that flips
    `reviewed=False` and returns the editor to its editable state.
13. Readiness blockers link to the branch-owned manual-binning step
    (regression-asserted).
14. `EvidenceTab` shows a manual-binning review summary card.
15. The report bundle contains a manual-binning review section: review
    status, variables edited, reasons, unresolved warnings, and
    whether automated bins were accepted.
16. Tests cover state, edit, review-completion, readiness, evidence,
    and report integration.
17. No `.tsx` or non-test `.py` file exceeds the 600-line ceiling.
18. No new modelling scope is introduced.

## Files mapped to phases

| Area | Phase touch |
|---|---|
| `cardre/services/manual_binning_service.py` | 1 (widen DTO population, atomic `save_with_review`, read annotation), 3 (gate, reopen, per-variable accept/reset) |
| `cardre/services/plan_dto.py` | 1 (widen `ManualBinningEditorStateResponse` + `ManualBinningVariableSummary`) |
| `sidecar/models.py` | 1 (mirror DTO widening), 3 (gate error shape) |
| `cardre/services/plan_service.py` | 1 (widen `_validate_manual_binning_review_params`, atomic annotation path), 3 (reopen mode) |
| `cardre/nodes/build/bins.py` | 1 (`REASON_CODES`, `reason_code` acceptance in `validate_params`) |
| `cardre/engine/binning/definition.py` | 1 (pass through `reason_code`) — no new actions |
| `cardre/engine/binning/diagnostics.py` | 1 (fold sparse/monotonicity checks; `compute_blockers` host or sibling module) |
| `cardre/readiness/check.py` | 4 (warning-on-reviewed-with-unresolved-warnings; regression assert) |
| `cardre/readiness/manual_binning.py` (new, if needed) | 1 (`compute_blockers`) |
| `cardre/_evidence/summaries.py` | 4 (manual-binning summary builder) |
| `cardre/services/branch_evidence.py` | 4 (wire manual-binning summary) |
| `cardre/reporting/collector.py` | 4 (extend manual-binning bundle section) |
| `sidecar/routes/plans.py` | 1 (unchanged — DTO widening flows through), 3 (gate error surfaces `blocking_issues`) |
| `frontend/src/api/schema.d.ts` | Regenerated at every backend-touching phase |
| `frontend/src/hooks/useManualBinningState.ts` | 1 (new) |
| `frontend/src/components/ManualBinningEditor.tsx` | 2 (split into orchestrator + columns), 3 (edit dialog wiring) |
| `frontend/src/components/ManualBinningVariableList.tsx` | 2 (new) |
| `frontend/src/components/ManualBinningReviewPanel.tsx` | 2 (new) |
| `frontend/src/components/ManualBinningReviewActions.tsx` | 2 (new), 3 (reopen) |
| `frontend/src/components/ManualBinningBinTable.tsx` | 2 (new, read-only), 3 (edit actions) |
| `frontend/src/components/ManualBinningEditDialog.tsx` | 3 (new) |
| `frontend/src/components/inspector/EvidenceTab.tsx` / `ManualBinningEvidenceCard.tsx` | 4 (new card) |
| `frontend/src/components/__tests__/ReadinessPanel.test.tsx` | 4 (extend) |
| `tests/test_manual_binning_service.py` | 1, 3, 4 |
| `tests/test_reporting.py` | 4 (regression + new) |

## What this sprint must not do

- Persist a `review_status` enum that duplicates `reviewed` /
  `accept_automated`.
- Persist `selected_variable_id` on the backend.
- Persist `in_progress` as a backend state.
- Invent a new manual-binning evidence kind / artifact. Reuse the
  `manual_binning_review` annotation.
- Add a new binning action (`isolate_missing`, `rename_bin`, etc.).
  The existing `VALID_ACTIONS` cover the launch surface; UI labels map
  to them.
- Hand-sync `ManualBinningVariableSummary` across the three layers.
  Regenerate the frontend types.
- Introduce a second readiness producer. Batch 2 consolidated it; this
  sprint extends in place.
- Add new modelling scope (new nodes, new ML methods, reject inference,
  fairness, challenger modelling, report redesign beyond the
  manual-binning section).
- Grow any `.tsx` or non-test `.py` file past the 600-line ceiling.

## Priority

This sprint sits after Batch 2 (evidence and readiness hardening). Do
not start Phase 1 until Batch 2's branch-scoped readiness and
consolidated readiness producer are merged — Phase 4 depends on that
consolidation holding, and Phase 1's `compute_blockers` leans on the
same resolution primitives Batch 2 verified.