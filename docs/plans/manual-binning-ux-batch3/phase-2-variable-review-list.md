# Phase 2 — Variable review list and governed editor layout

## Goal

Replace the ad-hoc summary table and override form in
`ManualBinningEditor.tsx` with a governed two-column review layout. The
modeller must be able to tell, without opening each variable, which
variables require attention and why. This phase is **frontend-led**; the
only backend work is filling any DTO gap Phase 1 left.

## Context you must read first

- `frontend/src/components/ManualBinningEditor.tsx` (411 lines) — the
  current editor. It mixes the variable summary table (`:257-293`),
  review action buttons (`:186-247`), `SourceBinsChips`,
  `BinDetailsAccordion`, `OverridesList`, and `AddOverrideForm` in one
  file. Phase 2 splits it.
- The widened DTO contract from Phase 1 — `review_status`,
  `blocking_issues`, `variable_summaries[*]` with `review_required`,
  `edited`, `zero_cell_warning_count`, `monotonicity_status`,
  `missing_rate`, `special_rate`, `bin_count`, `variable_type`. The
  layout renders from these; do not re-derive them in the frontend.
- `frontend/src/hooks/useManualBinningState.ts` — the hook from Phase 1.
  The new layout consumes it.
- `frontend/src/api/schema.d.ts` — the regenerated types. Do not
  hand-write TS shapes for the new fields.
- `frontend/src/test/server.ts` — the MSW server; every endpoint a
  test mounts must be mocked (`onUnhandledRequest: "error"`).
- `frontend/src/components/__tests__/ReadinessPanel.test.tsx` — the
  seven-state pattern the evidence batch established. The
  reviewed / unreviewed visual distinction in this phase follows the
  same badge conventions.
- `cardre/nodes/build/bins.py:431` — `VALID_ACTIONS`:
  `merge_bins`, `group_categories`, `reject_variable`,
  `reorder_missing_bin`, `reorder_special_bin`. **There is no
  `isolate_missing` action.** The UI exposes the existing actions; the
  labels in the action dropdown map to these strings:
  - "Merge adjacent bins" → `merge_bins`
  - "Group categories" → `group_categories`
  - "Reject variable" → `reject_variable`
  - "Isolate missing" → `reorder_missing_bin` (with the missing bin as
    the target — the existing action already reorders it; the "isolate"
    framing is a UI label, not a new action)
  - "Isolate special" → `reorder_special_bin`
  - "Accept automated bins for this variable" → not an override; it is
    "remove this variable's overrides and save" — see Phase 3.
  - "Reset variable to automated bins" → same as above with an audit
    annotation; see Phase 3.
- `cardre/engine/binning/definition.py:428` — adjacency for numeric
  merges is already validated. The UI should pre-filter the
  `source_bin_ids` picker to adjacent bins when `action="merge_bins"`
  on a numeric variable, but the backend will reject non-adjacent
  selections regardless.

## Changes

### 1. Split `ManualBinningEditor.tsx`

The file is 411 lines and will grow past the ceiling. Split into:

- `ManualBinningEditor.tsx` — the orchestrator; holds layout, the
  selected-variable state, and renders the two columns. Stays small
  (composition only).
- `ManualBinningVariableList.tsx` — left column: the variable
  table / search / filter / sortable columns.
- `ManualBinningReviewPanel.tsx` — right column: selected variable
  overview, warnings, recommended action, evidence summary, review
  status.
- `ManualBinningReviewActions.tsx` — the "Mark review complete" /
  "Accept automated bins" panel. (Carved out of the current inline
  block at `ManualBinningEditor.tsx:186-247`.)
- `ManualBinningBinTable.tsx` — the bin table for the selected
  variable. Rendered inside the right column when a variable is
  selected. (This is the Phase 3 bin detail view's host; Phase 3 adds
  edit actions on top of it.)
- Keep `SourceBinsChips.tsx`, `BinDetailsAccordion.tsx`,
  `OverridesList.tsx`, `AddOverrideForm.tsx`, `PreviewResults.tsx` as
  they are for now — Phase 3 will fold them into the bin table / edit
  dialog. Do not delete them in Phase 2.

Each new component stays well under the 600-line ceiling. If any
exceeds it, extract subcomponents further.

### 2. Left column — variable review list

`ManualBinningVariableList.tsx` renders a table with one row per
`variable_summaries[*]`. Columns:

- Variable name
- IV (sortable, numeric)
- Bin count (sortable)
- Missing rate (sortable, formatted as %)
- Special rate (sortable, formatted as %)
- Monotonicity status (badge: `monotonic` / `non_monotonic` /
  `insufficient_bins`)
- Warning count (sortable; sum of `zero_cell_warning_count` +
  `sparse_bin_warning_count` + missing/special unresolved flags)
- Review status (badge): `Needs review` (when `review_required`),
  `Edited` (when `edited`), `Accepted` (when the step-level
  `accept_automated` is true), `Reviewed` (when the variable is covered
  by an override with a valid reason code, or step-level `reviewed` is
  true). Use the badge conventions from `ReadinessPanel.tsx`.

Above the table:

- A search input (client-side filter on variable name).
- Filter chips: `Needs review`, `Edited`, `Warnings only`.
- A summary line: "N variables · M need review · K edited · J
  warnings".

Selecting a row updates the right column. The selected variable id
lives in `ManualBinningEditor.tsx` state (React `useState`) — it is
**not** sent to the backend (README rule 6). It persists only for the
session; a page reload resets selection to the first variable.

### 3. Right column — review panel

`ManualBinningReviewPanel.tsx` renders, for the selected variable:

- **Overview**: variable name, type, IV, bin count, missing / special
  rate, monotonicity status — same fields as the row, expanded.
- **Current warnings**: list of warnings for this variable (from the
  `warnings` already on the response, filtered to this variable, plus
  the per-variable warning counts). Each warning shows code + message.
- **Recommended action**: derived client-side from the warnings:
  - `non_monotonic` → "Review monotonicity; merge adjacent bins or
    accept with a `monotonicity` reason code."
  - `zero_cell` → "Address zero-cell bin: merge, isolate, or accept
    with a `zero_cell` reason code."
  - `sparse_bin` → "Merge sparse bin with a neighbour, or accept with
    a `sparse_bin` reason code."
  - missing/special unresolved → "Confirm missing / special handling
    with the matching reason code."
  - no warnings → "No action required; optionally accept automated
    bins."
  This is a **hint**, not a hard requirement. It reads from the same
  `review_required` derivation as the backend (Phase 1 §2).
- **Evidence summary**: a short line — "N bins · bad rate range X–Y ·
  WOE range A–B · IV Z" — computed from `source_bins_by_variable[var]`
  and `variable_summaries[var]`.
- **Review status**: the per-variable badge plus the step-level
  `review_status`, `reviewed_at`, `reviewed_by`, `review_reason`. When
  the step is reviewed, show the read-only reviewed state (Phase 3
  governs reopening).

When no variable is selected, render an empty-state prompt: "Select a
variable to review."

### 4. Review actions panel

`ManualBinningReviewActions.tsx` replaces the inline block at
`ManualBinningEditor.tsx:186-247`. It shows:

- The step-level summary: "M of N variables reviewed · K edited · J
  unresolved warnings".
- The list of `blocking_issues` (from the Phase 1 DTO) with their
  codes and messages. If any are present, the "Mark review complete"
  button is disabled and the issues are the explanation.
- "Mark review complete" button — calls
  `api.reviewManualBinning` with `reviewed=True`, `reason_code`, and
  `review_reason`. Disabled when `blocking_issues` is non-empty (Phase
  1's `compute_blockers` is the source of truth; the frontend does not
  re-derive the gate). On success, invalidate the
  `manualBinningState` and `plan` queries.
- "Accept automated bins" button — calls `reviewManualBinning` with
  `accept_automated=True`. Distinct path, distinct audit (README rule
  8; Phase 1's validation already enforces mutual exclusion).
- After completion, render a read-only reviewed banner with
  `reviewed_at` / `reviewed_by` / `review_reason`. A "Reopen review"
  button is Phase 3 (it requires a reason and emits a new annotation).

The "needs reason code + free-text" prompt for "Mark review complete"
lives here. The reason-code dropdown uses `ManualBinningNode.REASON_CODES`
surfaced via the node-types endpoint (or a constant mirrored from the
backend — check whether `GET /node-types` already exposes it; if so,
prefer that over a hand-mirrored constant).

### 5. Bin table (read-only in Phase 2)

`ManualBinningBinTable.tsx` renders the selected variable's bins from
`source_bins_by_variable[var]`:

- Bin label
- Lower/upper bound (numeric) or category group (categorical)
- Count
- Good count
- Bad count
- Bad rate
- WOE (from `variable_summaries[var].woe_by_bin[bin_id]`)
- IV contribution (derived: `bad_rate * woe` summed appropriately, or
  read from the WOE/IV evidence if available — prefer reading over
  re-deriving)
- Missing/special flag
- Warnings (zero-cell, sparse) per bin

Phase 2 renders this table read-only. Phase 3 adds the edit actions
(merge, rename, isolate, accept, reset) on top of it.

### 6. Wiring in `ManualBinningEditor.tsx`

The orchestrator:

```tsx
export function ManualBinningEditor({ planId, projectId, basePlanVersionId, stepId, onBack, onPlanRefreshed }: Props) {
  const state = useManualBinningState(projectId, planId, stepId);
  const [selectedVar, setSelectedVar] = useState<string | null>(null);

  if (state.isLoading) return <LoadingState />;
  if (!state.data) return <ErrorState onBack={onBack} />;
  if (!state.data.ready) return <NotReadyState data={state.data} onBack={onBack} />;

  const firstVar = selectedVar ?? state.data.selected_variables[0] ?? null;
  return (
    <div style={{ display: "flex", gap: 16, padding: 24, flex: 1 }}>
      <ManualBinningVariableList
        summaries={state.data.variable_summaries}
        stepStatus={state.data.review_status}
        selected={firstVar}
        onSelect={setSelectedVar}
      />
      <div style={{ flex: 2 }}>
        <ManualBinningReviewPanel
          variable={firstVar}
          state={state.data}
        />
        {firstVar && (
          <ManualBinningBinTable
            variable={firstVar}
            sourceBins={state.data.source_bins_by_variable[firstVar]}
            summary={state.data.variable_summaries.find(v => v.variable === firstVar)}
          />
        )}
        <ManualBinningReviewActions
          state={state.data}
          planId={planId}
          stepId={stepId}
          basePlanVersionId={basePlanVersionId}
          onPlanRefreshed={onPlanRefreshed}
        />
      </div>
    </div>
  );
}
```

Replace the inline query at `ManualBinningEditor.tsx:34-38` with
`useManualBinningState`. Keep the existing preview/save mutations in
`ManualBinningEditor.tsx` for now; Phase 3 moves them into the bin table
edit dialog.

### 7. Backend follow-ups

Phase 1 should have surfaced every field the layout needs. If a gap
appears during Phase 2 implementation (e.g. `iv_contribution` per bin
isn't on the WOE/IV evidence model), add it to the evidence reader /
summaries — do **not** re-derive it in the frontend. Keep such
additions small and gated behind "Phase 2 needs this field"; do not
widen the contract opportunistically.

## Tests

### Frontend (MSW for every endpoint)

1. `ManualBinningVariableList.test.tsx` — render from a fixture DTO;
   assert the badges appear for `Needs review`, `Edited`,
   `non_monotonic`, `zero_cell`; assert sorting works; assert the
   search filter narrows rows.
2. `ManualBinningReviewPanel.test.tsx` — selecting a variable changes
   the detail panel; the recommended action reflects the variable's
   warnings; the evidence summary line is present.
3. `ManualBinningReviewActions.test.tsx` — the "Mark review complete"
   button is disabled when `blocking_issues` is non-empty; enabling
   requires reason code + free-text; success updates the status
   badge; the accepted-automated path updates status distinctly from
   the reviewed path.
4. `ManualBinningBinTable.test.tsx` — renders bin label, bounds /
   categories, count, good/bad, bad rate, WOE, IV contribution,
   missing/special flag, per-bin warnings.
5. `ManualBinningEditor.test.tsx` — integration: the two-column layout
   renders; selecting a row updates the right column; the read-only
   reviewed state shows `reviewed_at` / `reviewed_by` / `review_reason`
   when `review_status === "reviewed"`.
6. Journey test extension — `journey.launch.test.tsx` (or equivalent)
   exercises the manual-binning step end-to-end through the new layout.

### Backend

7. If Phase 2 added any DTO field, extend the relevant
   `test_manual_binning_service.py` case to assert it is populated.

## Acceptance criteria

- A modeller can tell, without opening each variable, which variables
  require attention and why — the left-column badges and the summary
  line answer this.
- Selecting a variable updates the right column without a backend
  round-trip (`selected_variable_id` is frontend-only).
- The reviewed / accepted-automated states are visually distinct and
  backed by the computed `review_status`.
- The "Mark review complete" button is disabled when `blocking_issues`
  is non-empty — the gate logic lives in the backend (Phase 1's
  `compute_blockers`), the frontend only renders the result.
- `ManualBinningEditor.tsx` is well under the 600-line ceiling; every
  split component is under the ceiling.
- `frontend/src/api/schema.d.ts` is unchanged from Phase 1 (no new
  backend fields in this phase) unless a documented gap was filled.
- `npx tsc --noEmit` and `npm test` pass in `frontend/`.

## Out of scope for this phase

- Bin-level edit actions (merge, rename, isolate, accept, reset) —
  Phase 3.
- The backend review-completion gate validation — Phase 3.
- Reopening review — Phase 3.
- Evidence / report integration — Phase 4.
- Any new binning action. The existing `VALID_ACTIONS` cover the
  launch surface; Phase 2 only relabels them.