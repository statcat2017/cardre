# Phase 1 — State contract consolidation + audit widening

## Goal

Make the manual-binning state response explicit enough for the governed
review UI without introducing a parallel state model. Widen the existing
`ManualBinningEditorStateResponse` in place, fold duplicated diagnostics
into `engine/binning/diagnostics.py`, add the audit fields the review
workflow needs, and make the review write atomic.

This phase is **contract and plumbing only**. It deliberately does not
redesign the editor screen — that is Phase 2. The frontend hook this
phase adds exists only to make the new contract observable; the layout
that consumes it lands in Phase 2.

## Context you must read first

- `cardre/services/manual_binning_service.py:86-260` —
  `get_editor_state`. Note how it resolves `branch_id` from
  `mb_spec.branch_id` (`:138`), builds `branch_step_map`, walks upstream
  via `find_nearest_binning_source`, computes staleness, and assembles
  `variable_summaries` by reading `final-woe-iv` evidence.
- `cardre/services/plan_dto.py:44-91` — the existing DTOs. **Augment
  these in place.** Do not create a second response class.
- `sidecar/models.py:277-345` — the Pydantic mirrors. Must widen
  identically.
- `cardre/services/manual_binning_service.py:356-411` — `save_with_review`.
  Note the non-atomic two-write pattern at `:381` (calls
  `PlanService.update_params` which commits) and `:392` (opens its own
  `transaction()` and inserts the annotation). Phase 1 fixes this.
- `cardre/services/plan_service.py:272-294` — the staleness-reset block
  that resets `reviewed` / `accept_automated` when an upstream step
  changes. Any new persisted review field added here must be added to
  this reset path too. (Phase 1 adds no new *persisted* field to
  `plan_steps.params_json`, but the annotation is the audit record —
  confirm the reset still emits a fresh annotation if needed.)
- `cardre/services/plan_service.py:303-314` —
  `_validate_manual_binning_review_params`. Phase 1 widens this to
  require `reason_code` + `review_reason` when `reviewed=True`.
- `cardre/nodes/build/bins.py:431-503` — `VALID_ACTIONS` and
  `validate_params`. The override already requires `reason` free-text
  (`:492`). Phase 1 adds a `reason_code` enum alongside it.
- `cardre/engine/binning/definition.py:372-438` —
  `LifecycleBinDefinition.validate_overrides`. Adjacency for numeric
  merges is already enforced at `:428`. **Do not re-add this.**
- `cardre/readiness/check.py:190-216` — the existing branch-scoped
  manual-binning blocker. Reads `reviewed` / `accept_automated` from
  params. Must keep working unchanged after Phase 1.
- `cardre/store/schema.py:160-168` — the `step_annotations` table. No
  schema migration is needed; the new audit fields ride inside
  `payload_json`.
- `cardre/_evidence/summaries.py` — the dispatch table at `:20-21` and
  the per-kind summary builders. Phase 1 does **not** add a
  manual-binning evidence kind; it reuses the annotation.

## Changes

### 1. Fold sparse / non-monotonic checks into diagnostics

Move `_check_sparse_bins` (`manual_binning_service.py:67`) and
`_check_non_monotonic` (`:77`) into
`cardre/engine/binning/diagnostics.py` as pure functions, e.g.
`sparse_bin_warning(bin_data: dict, threshold: float = 0.05) -> bool`
and `monotonicity_status(woe_by_bin: dict) -> MonotonicStatus` where
`MonotonicStatus` is a small enum (`monotonic`, `non_monotonic`,
`insufficient_bins`). Expose both from the module. Delete the
duplicated helpers from `manual_binning_service.py` and import the
new ones.

Phase 2 will reuse the same functions for the per-variable warning
counts; Phase 3 will reuse them for blocker computation. One
implementation, three callers.

### 2. Widen the variable summary

Extend `ManualBinningVariableSummary` (in `plan_dto.py:60`, mirrored in
`sidecar/models.py:285`) with:

- `variable_type: str | None` — `"numeric" | "categorical"`, read from
  the source bin definition.
- `bin_count: int | None` — `len(bin_data["bins"])`.
- `missing_rate: float | None` — `missing_count / total` if total > 0.
- `special_rate: float | None` — same shape.
- `zero_cell_warning_count: int` — count of bins with `bad_count == 0`
  or `good_count == 0`. Compute in diagnostics.py.
- `sparse_bin_warning_count: int` — count of bins below the threshold,
  not just a bool. (Keeps the existing `sparse_bin_warning: bool` field
  for back-compat as `sparse_bin_warning_count > 0`.)
- `monotonicity_status: str` — the enum value from diagnostics.
- `edited: bool` — `True` if any override in `current_overrides` targets
  this variable.
- `review_required: bool` — derived: `True` when the variable has
  warnings (sparse / zero-cell / non-monotonic) or missing/special
  handling and is not yet covered by an override with a valid reason
  code. See the derivation table below.

Populate these in `get_editor_state` from the same source-bin and WOE
data already loaded. No new artifact reads.

`review_required` derivation:

| Condition | `review_required` |
|---|---|
| Variable has zero-cell or sparse warning and no override | `True` |
| Variable is non-monotonic and no override records a `monotonicity` reason code | `True` |
| Variable has missing/special bins and no override records a `missing_value_treatment` / `special_value_treatment` reason code | `True` |
| Otherwise | `False` |

This is a **computed field**, not persisted. Recompute on every
`get_editor_state` call.

### 3. Widen the editor state response

Extend `ManualBinningEditorStateResponse` (in `plan_dto.py:72`,
`sidecar/models.py:296`) with:

- `project_id: str = ""` — already known in the route; surface it.
- `branch_id: str | None = None` — from `mb_spec.branch_id`.
- `run_id: str | None = None` — the run the WOE/IV evidence came from.
- `review_status: str = "not_started"` — **computed** from
  `reviewed` / `accept_automated`: `"not_started"` |
  `"reviewed"` | `"accepted_automated"`. Do **not** add
  `"in_progress"` to the backend enum; that is a frontend-only badge
  (see README rule 7).
- `reviewed: bool = False` — already implicitly in params; surface it.
- `accept_automated: bool = False` — same.
- `reviewed_at: str | None = None` — read from the latest
  `manual_binning_review` annotation's `created_at`.
- `reviewed_by: str | None = None` — read from the annotation's actor
  or a new `reviewed_by` payload field (Phase 1 adds it to the payload).
- `review_reason: str | None = None` — read from the annotation's new
  `review_reason` payload field.
- `review_reason_code: str | None = None` — read from the annotation's
  new `reason_code` payload field.
- `blocking_issues: list[dict] = []` — **computed** via the shared
  `compute_blockers(state)` helper (added in this phase, used by
  Phase 3's gate and Phase 4's evidence). Lives in
  `cardre/engine/binning/diagnostics.py` or a new small
  `cardre/readiness/manual_binning.py`. Each item is
  `{code, message, variable?, step_id}`. Empty list when there are no
  blockers.
- `selected_variable_id: str | None = None` — **do not add.** This is
  frontend-only (README rule 6).

Populate `reviewed_at` / `reviewed_by` / `review_reason` /
`review_reason_code` by reading the most recent
`manual_binning_review` annotation for this step + plan version. Add a
small helper `get_latest_review_annotation(store, step_id,
plan_version_id)` in `manual_binning_service.py` (or reuse whatever
annotation-read helper already exists — check
`cardre/store/plan_repo.py` first).

### 4. Widen the override schema with a reason code

In `cardre/nodes/build/bins.py`:

- Add `REASON_CODES` as a frozenset on `ManualBinningNode`:
  `{"business_interpretability", "monotonicity", "sparse_bin",
  "zero_cell", "missing_value_treatment", "special_value_treatment",
  "regulatory_or_policy", "other"}`.
- In `validate_params` (`:482`), after the existing `reason` check at
  `:492`, add: if `reason_code` is present it must be in `REASON_CODES`
  (warn, don't error, for back-compat with existing overrides that lack
  it). Do **not** require `reason_code` at the node-param level yet —
  Phase 3's review-completion gate is where "every manual edit must
  have a reason code" is enforced. The node stays permissive; the gate
  is strict.
- Update the `parameter_schema` help_text at `:456` to mention
  `reason_code`.

In `cardre/engine/binning/definition.py:validate_overrides` (`:372`),
accept and pass through `reason_code` without semantic change — it is
metadata on the override, not a binning operation.

### 5. Widen `save_with_review` and make it atomic

In `manual_binning_service.py:356`:

- Add `reviewed_by: str | None = None`, `reason_code: str | None =
  None`, `review_reason: str | None = None` parameters.
- Write all three into the annotation payload alongside the existing
  fields. `reviewed_by` should also go into the `actor` column if it is
  more specific than the current hard-coded `"user"`.
- **Fix the non-atomic write.** Today `update_params` commits, then
  `save_with_review` opens a separate `transaction()` for the
  annotation. Collapse them into one transaction. The cleanest path:
  add an optional `annotation` parameter to `PlanService.update_params`
  that, if provided, inserts the annotation inside the same
  transaction that creates the new plan version. `save_with_review`
  then calls `update_params(..., annotation={...})` and does not open
  its own transaction. If that coupling is undesirable, the
  alternative is a new `PlanService.update_params_with_annotation`
  method that wraps both — but prefer extending `update_params` with a
  defaulted optional so there is one entry point.

### 6. Widen `_validate_manual_binning_review_params`

In `plan_service.py:303`: when `reviewed=True`, require a non-empty
`review_reason` and a `reason_code` in `ManualBinningNode.REASON_CODES`.
When `accept_automated=True`, neither is required (accepting automated
  bins is a "no manual change" decision; the audit captures who/when).
  Keep the existing mutual-exclusion and
  accept-automated-incompatible-with-overrides checks.

### 7. Add `compute_blockers(state)` helper

Add a pure function that takes the assembled editor state (or the raw
inputs it needs) and returns the `blocking_issues` list. This is the
single source of truth used by:

- `get_editor_state` (to populate `blocking_issues` on the response).
- Phase 3's review-completion gate.
- Phase 4's evidence summary and report section.

Put it in `cardre/readiness/manual_binning.py` (new small module) or
`cardre/engine/binning/diagnostics.py` — whichever stays under the
600-line ceiling. Blockers it emits:

| Code | Condition |
|---|---|
| `UNREVIEWED_REQUIRED_VARIABLE` | A variable with `review_required=True` has no override with a valid reason code. |
| `EDIT_WITHOUT_REASON_CODE` | An override in `current_overrides` lacks `reason_code` or `reason`. |
| `UNRESOLVED_ZERO_CELL` | A variable has `zero_cell_warning_count > 0` and no override isolating or merging the offending bin. |
| `UNRESOLVED_SPARSE_BIN` | Same shape for sparse bins. |
| `UNRESOLVED_MISSING_HANDLING` | Variable has a missing bin and no override with reason code `missing_value_treatment`. |
| `UNRESOLVED_SPECIAL_HANDLING` | Same for special. |
| `BRANCH_MISMATCH` | The `step_id` in the request does not belong to the resolved branch. (Caught earlier, but emit as a blocker for the gate too.) |

### 8. Frontend hook (contract observability only)

Add `frontend/src/hooks/useManualBinningState.ts` — a thin React Query
hook wrapping the existing `api.getManualBinningEditorState` call. Its
only job in Phase 1 is to make the new contract observable and typed;
Phase 2 consumes it for the governed layout.

```ts
export function useManualBinningState(
  projectId: string,
  planId: string,
  stepId: string,
  enabled = true,
) {
  return useQuery({
    queryKey: ["manualBinningState", projectId, planId, stepId],
    queryFn: () => api.getManualBinningEditorState(planId, projectId, stepId),
    enabled: enabled && !!planId && !!projectId && !!stepId,
  });
}
```

Do **not** redesign `ManualBinningEditor.tsx` in this phase. Leave it
calling the hook where straightforward, but the existing inline query
is acceptable for now — Phase 2 does the layout work.

### 9. Regenerate frontend types

Run `python3 scripts/generate-openapi-types.py`, then `cd frontend &&
npx tsc --noEmit`. Commit the regenerated `schema.d.ts`.

## Tests

### Backend (`tests/test_manual_binning_service.py` or equivalent)

1. `test_get_editor_state_returns_branch_scoped_context` — assert
   `branch_id`, `run_id`, `review_status` are populated and
   `review_status` matches `reviewed` / `accept_automated`.
2. `test_review_status_computed_not_persisted` — set `reviewed=True`
   via `save_with_review`, assert the response shows
   `review_status="reviewed"`; flip back to `reviewed=False` and assert
   `not_started`. Confirm no `review_status` column exists in
   `plan_steps`.
3. `test_reviewed_at_by_reason_read_from_annotation` — after
   `save_with_review(reviewed=True, reviewed_by="alice",
   reason_code="business_interpretability", review_reason="…")`, the
   next `get_editor_state` call returns those values.
4. `test_blockers_computed_from_state` — drive a scenario with an
   unreviewed zero-cell variable and assert `blocking_issues` contains
   `UNRESOLVED_ZERO_CELL`.
5. `test_save_with_review_is_atomic` — make the annotation insert fail
   (e.g. malformed payload that violates a NOT NULL) and assert the
   plan version was **not** created either. (May require a temp
   monkeypatch; if impractical, assert via a transaction-rollback
   fixture.)
6. `test_validate_review_params_requires_reason_when_reviewed` —
   `reviewed=True` without `review_reason` raises
   `PlanValidationError`; `accept_automated=True` does not require it.
7. `test_override_reason_code_validated_when_present` — an override
   with `reason_code="bogus"` is rejected; one with a valid code passes.
8. `test_diagnostics_module_is_single_source` — import
   `sparse_bin_warning` / `monotonicity_status` from diagnostics and
   assert `manual_binning_service` no longer defines them.

### Frontend

9. `useManualBinningState.test.ts` — MSW-mock `editor-state`; assert the
   hook returns the widened fields (`review_status`, `blockers`,
   `reviewed_at`). Assert it does not fetch when IDs are missing.

### Readiness regression

10. Extend `tests/test_reporting.py` readiness cases to assert the
    blocker still fires with the unchanged `reviewed` /
    `accept_automated` params contract after the DTO widening.

## Acceptance criteria

- `ManualBinningEditorStateResponse` carries `project_id`, `branch_id`,
  `run_id`, computed `review_status`, `reviewed`, `accept_automated`,
  `reviewed_at`, `reviewed_by`, `review_reason`, `review_reason_code`,
  `blocking_issues`, and the widened per-variable fields — all computed
  or read from the annotation, none persisted as a parallel state.
- `review_status` is derived from `reviewed` / `accept_automated` and
  cannot drift.
- `save_with_review` writes `reviewed_by`, `reason_code`,
  `review_reason` into the annotation and is atomic with the plan
  version creation.
- `_validate_manual_binning_review_params` requires `review_reason` +
  `reason_code` when `reviewed=True`.
- Sparse / monotonicity checks live in `cardre/engine/binning/diagnostics.py`
  and are imported by `manual_binning_service.py`; the duplicated
  helpers are deleted.
- `compute_blockers` exists as a single function shared by the editor
  state, the review gate (Phase 3), and evidence/report (Phase 4).
- `useManualBinningState` exists and is tested.
- `frontend/src/api/schema.d.ts` regenerated and committed.
- `pytest tests/test_manual_binning_service.py tests/test_reporting.py`
  passes; `npx tsc --noEmit` and `npm test` pass in `frontend/`.
- No `.tsx` or non-test `.py` file exceeds the 600-line ceiling.

## Out of scope for this phase

- The governed two-column editor layout — Phase 2.
- Enforcing reason codes on every save (the gate) — Phase 3.
- Evidence / report integration — Phase 4.
- A new manual-binning evidence kind. Reuse the annotation.
- Any new binning action (`isolate_missing` etc.) — the existing
  `reorder_missing_bin` / `reorder_special_bin` actions cover it; Phase 2
  surfaces them in the UI.