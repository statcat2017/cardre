# Phase 3 — Bin detail, safe edits, and review-completion gate

## Goal

Make bin-level inspection and editing auditable and hard to misuse, and
make "review complete" a backend-validated gate rather than a flag.
This phase lands the edit actions on top of the Phase 2 bin table and
adds the backend validation that turns "Mark review complete" into a
governed decision.

## Context you must read first

- `cardre/engine/binning/definition.py:372-540` —
  `validate_overrides` and `apply_overrides`. Adjacency for numeric
  merges is already enforced at `:428`. The supported actions are
  `merge_bins`, `group_categories`, `reject_variable`,
  `reorder_missing_bin`, `reorder_special_bin` (see `bins.py:431`).
  **Do not add new actions.** "Isolate missing" / "isolate special" map
  to `reorder_missing_bin` / `reorder_special_bin`.
- `cardre/nodes/build/bins.py:482-503` — `validate_params`. Already
  requires `reason` free-text per override and rejects `merge_bins`
  with fewer than 2 source bins. Phase 1 added `reason_code`
  acceptance; this phase enforces `reason_code` presence at the
  review gate (not at the node-param level — the node stays
  permissive for back-compat with existing overrides).
- `cardre/services/manual_binning_service.py:262-327` —
  `preview_overrides`. Already validates and applies overrides to
  produce refined bins. Phase 3 reuses this for the edit preview; it
  does not add a new preview path.
- `cardre/services/manual_binning_service.py:329-354` —
  `validate_overrides`. Phase 3's gate calls this plus
  `compute_blockers` (from Phase 1).
- `cardre/services/manual_binning_service.py:356-411` —
  `save_with_review`. Phase 1 made it atomic and widened its payload.
  Phase 3 adds the gate check before it commits.
- `cardre/services/plan_service.py:303-314` —
  `_validate_manual_binning_review_params`. Phase 1 widened it to
  require `review_reason` + `reason_code` when `reviewed=True`. Phase 3
  adds the *content* gate (blockers / reasons / branch) on top.
- The Phase 1 `compute_blockers(state)` helper and the Phase 2 bin
  table. The gate is `compute_blockers` returning an empty list; the
  frontend already disables the button when it is non-empty.
- `cardre/staleness.py` — the staleness-reset block in
  `plan_service.py:272-294` resets `reviewed` / `accept_automated` when
  upstream changes. After Phase 3, reopening review must also clear
  those flags via the same path (or via a dedicated reopen annotation
  that flips them). Understand which path the existing reset uses.

## Changes

### 1. Bin table edit actions

`ManualBinningBinTable.tsx` (from Phase 2) gains an "Actions" column
or a per-row action menu. Actions are scoped per the existing
`VALID_ACTIONS`:

| UI label | Override action | Notes |
|---|---|---|
| Merge adjacent bins | `merge_bins` | Picker pre-filters to adjacent numeric bins; backend rejects non-adjacent regardless (`definition.py:428`). |
| Rename / edit bin label | `group_categories` with `new_label`, or a new `rename_bin` action? **Check first.** The existing schema has `new_label` on `group_categories`. For a pure rename of one bin without grouping, the cleanest path is `group_categories` with a single category and `new_label`. Do **not** add a new `rename_bin` action without confirming the existing one cannot express it. |
| Isolate missing | `reorder_missing_bin` | The existing action reorders; "isolate" is a UI label for placing the missing bin as its own bin. |
| Isolate special | `reorder_special_bin` | Same. |
| Reject variable | `reject_variable` | Already supported. |
| Accept automated bins for this variable | (not an override) | Removes this variable's overrides from the draft and saves with a `business_interpretability` reason code on the variable's removal. Emits an annotation entry. |
| Reset variable to automated bins | (not an override) | Same as accept-automated-for-variable but with an audit annotation recording the reset. |

Each action opens an edit dialog (`ManualBinningEditDialog.tsx`,
new). The dialog requires:

- **Reason code** (dropdown from `ManualBinningNode.REASON_CODES`,
  surfaced via node-types or a mirrored constant — prefer the
  endpoint to avoid drift).
- **Reason free-text** (textarea, non-empty).
- **Preview** — calls `api.previewManualBinning` with the proposed
  override appended to the current `current_overrides` for this
  variable. Renders the refined bins side-by-side with the source bins
  (bad rate, WOE, IV contribution per bin). The save button is
  disabled until the preview succeeds and reason code + text are
  present.
- **Save** — calls `api.updateStepParams` with the new
  `params.overrides` list (or `api.reviewManualBinning` if the action
  is "accept automated for this variable" / "reset"). On success,
  invalidate `manualBinningState` and `plan`.

The dialog reuses the existing `PreviewResults.tsx` rendering. Do not
build a second preview component.

### 2. Per-variable "accept automated" and "reset"

These are not overrides in the schema sense; they modify the
`overrides` list for that variable:

- **Accept automated for this variable**: remove every override in
  `current_overrides` whose `variable` matches, then save. The audit
  is a new annotation kind `manual_binning_variable_accept` (or a
  `manual_binning_review` annotation with a `variable` and
  `action="accept_automated_variable"` payload field). Phase 3 picks
  one and documents it. Prefer reusing `manual_binning_review` with a
  discriminating payload field to avoid a second annotation kind.
- **Reset variable to automated bins**: same removal, plus an
  annotation recording the reset with reason code + text. Distinct
  from accept-automated-for-variable only in the audit narrative
  (reset implies a prior manual edit existed); the resulting
  `overrides` list is identical. Decide whether the UI needs both or
  whether one action ("Revert to automated") with a reason suffices.
  Lean: one action, "Revert to automated bins", with required reason —
  the audit distinguishes "had prior overrides" from "had none".

### 3. Backend: review-completion gate

Add `complete_review` (or harden `save_with_review`) so that
`reviewed=True` is rejected when `compute_blockers(state)` is
non-empty. Concretely, in `manual_binning_service.py`:

```python
def save_with_review(self, ..., reviewed=False, accept_automated=False, ...):
    if reviewed:
        state = self.get_editor_state(plan_id, step_id=step_id)
        blockers = compute_blockers(state)  # Phase 1 helper
        if blockers:
            raise PlanValidationError(
                "REVIEW_COMPLETION_BLOCKED",
                "Cannot complete review: " + "; ".join(b["message"] for b in blockers),
                status_code=409,
            )
    # ... existing atomic write
```

The gate uses the **same** `compute_blockers` Phase 1 introduced and
Phase 2 rendered. One implementation, one source of truth.

Blockers the gate enforces (from Phase 1 §7):

- `UNREVIEWED_REQUIRED_VARIABLE` — a `review_required` variable with no
  covering override.
- `EDIT_WITHOUT_REASON_CODE` — an override missing `reason_code` or
  `reason`.
- `UNRESOLVED_ZERO_CELL` / `UNRESOLVED_SPARSE_BIN` — unresolved
  warnings with no covering override.
- `UNRESOLVED_MISSING_HANDLING` / `UNRESOLVED_SPECIAL_HANDLING`.
- `BRANCH_MISMATCH` — `step_id` does not belong to the resolved
  branch.

Warnings that **do not block** (already in Phase 1's design, restated
for the gate):

- Non-monotonic WOE accepted with a `monotonicity` reason code — warn,
  not block.
- Low IV variable accepted — warn, not block.
- No OOT sample — warn, not block (this is a readiness concern, not a
  manual-binning gate concern; keep it out of `compute_blocklers`
  entirely — it lives in `readiness/check.py`).

### 4. Reopen review

Add a `reopen_review` operation that flips `reviewed=False` (and
leaves `accept_automated=False`) with a reason. It:

- Emits a `manual_binning_review` annotation with `action="reopen"`,
  `reviewed=False`, `reason_code`, `review_reason`.
- Is atomic (reuses the Phase 1 atomic path).
- After reopen, `get_editor_state` returns `review_status="not_started"`
  and the frontend shows the editable layout again.

The reopen reason is required; reopening without a reason is
rejected by `_validate_manual_binning_review_params` (extend it to
accept a `reopen=True` mode that requires reason + code but does not
require blockers to be empty).

Frontend: the read-only reviewed state (Phase 2) gains a "Reopen
review" button that opens the same reason dialog as the edit actions,
then calls `api.reviewManualBinning` (or a dedicated
`api.reopenManualBinningReview` if the sidecar gains one — prefer
extending the existing endpoint with an `action` field to avoid a
proliferation of routes).

### 5. Sidecar: gate the review endpoint

`sidecar/routes/plans.py:82-108` already calls `save_with_review`.
Phase 3 ensures the 409 `REVIEW_COMPLETION_BLOCKED` error surfaces to
the frontend with the blocker list so the UI can render *why* the gate
failed, not just that it failed. Extend `ManualBinningReviewResponse`
(or the error shape) to carry `blocking_issues` on failure.

## Tests

### Backend

1. `test_merge_adjacent_bins_persists_reason` — save an override with
   `action=merge_bins`, `reason_code="monotonicity"`, reason text;
   assert the new plan version's `params.overrides` carries both and
   the annotation records them.
2. `test_isolate_missing_persists_reason` — `reorder_missing_bin`
   override with `missing_value_treatment` reason code; assert
   persistence.
3. `test_reset_to_automated_clears_manual_edit_records_action` — save
   overrides, then reset; assert `overrides` no longer contains the
   variable's entries and an annotation records the reset with reason.
4. `test_invalid_non_adjacent_merge_rejected` — `merge_bins` with
   non-adjacent numeric bins returns a validation error (already
   enforced at `definition.py:428`; this test asserts the gate
   surfaces it).
5. `test_cannot_complete_with_unreviewed_required_variable` — leave a
   `review_required` variable without a covering override; assert
   `save_with_review(reviewed=True)` raises
   `REVIEW_COMPLETION_BLOCKED` and lists the blocker.
6. `test_cannot_complete_if_edit_reasons_missing` — an override
   missing `reason_code`; assert the gate blocks.
7. `test_can_complete_with_warnings_if_reasons_present` — non-monotonic
   variable with a `monotonicity` reason-code override; assert the
   gate allows completion (non-monotonic is a warning, not a blocker).
8. `test_branch_mismatch_blocks_completion` — call
   `save_with_review` with a `step_id` from a different branch;
   assert `BRANCH_MISMATCH`.
9. `test_accepted_automated_path_distinct_from_reviewed` —
   `accept_automated=True` does not invoke the blocker gate (it is a
   "no manual change" decision) and produces a distinct annotation.
10. `test_reopen_review_requires_reason` — reopen without reason is
    rejected; reopen with reason flips `reviewed=False` and emits the
    annotation.
11. `test_gate_rejects_zero_cell_unresolved` — a variable with a
    zero-cell bin and no covering override blocks completion.

### Frontend (MSW)

12. `ManualBinningEditDialog.test.tsx` — save disabled until reason
    code + text present; preview renders before save; successful edit
    updates the bin table; failed edit (gate 409) shows the blocker
    list.
13. `ManualBinningReviewActions.test.tsx` — "Mark review complete"
    success path updates status; the accepted-automated path updates
    status distinctly; the 409 path renders `blocking_issues`.
14. `ManualBinningReopenReview.test.tsx` — the reviewed read-only state
    has a "Reopen review" button; reopening requires reason + code;
    success returns to the editable layout.
15. `ManualBinningBinTable.test.tsx` — the per-row action menu offers
    the right actions for the variable type (numeric vs categorical);
    "Revert to automated bins" removes the variable's overrides.

## Acceptance criteria

- Bin-level edits are explicit, reasoned, reversible, and auditable:
  every save carries a `reason_code` and free-text; preview precedes
  save.
- The edit actions map 1:1 to the existing `VALID_ACTIONS`; no new
  binning action is added. "Isolate missing/special" use
  `reorder_missing_bin` / `reorder_special_bin`.
- "Accept automated bins for this variable" and "Reset variable to
  automated bins" modify the `overrides` list and emit an annotation;
  they do not introduce a new node action.
- The review-completion gate is enforced by the backend: unreviewed
  required variables, edits without reasons, unresolved zero-cell /
  sparse-bin blockers, unresolved missing/special handling, and
  branch mismatch all block `reviewed=True`. The gate reuses
  `compute_blockers` from Phase 1.
- `reviewed` and `accept_automated` remain distinct paths: the gate
  applies to `reviewed=True` only; `accept_automated=True` bypasses
  the gate and produces a distinct annotation.
- Reopen review is an explicit, reasoned action that flips
  `reviewed=False` and returns the editor to its editable state.
- The 409 `REVIEW_COMPLETION_BLOCKED` response carries `blocking_issues`
  so the frontend can render the reasons.
- `pytest` backend tests pass; `npx tsc --noEmit` and `npm test` pass
  in `frontend/`; no `.tsx` or non-test `.py` file exceeds the 600-line
  ceiling.

## Out of scope for this phase

- New binning algorithms or new node actions.
- Changing the override schema beyond the `reason_code` addition
  from Phase 1.
- Evidence / report integration — Phase 4.
- Fairness / challenger / reject-inference scope.