# Phase 5 — Manual binning journey integration

You are implementing **Phase 5** of the Guided Workflow Sprint
(`docs/plans/guided-workflow-sprint.md`). Phases 1, 2, and 3 are merged.
Phase 4 is **not** a hard dependency, but Phase 5a's StepInspector tab edits
expect Phase 4's tab scaffold to be in place — land Phase 4 first or
coordinate merges.

This phase is split internally:
- **Phase 5a (mergeable on its own):** journey integration + manual-binning
  DTO enrichment.
- **Phase 5b:** review-complete marker with node-param schema + audit
  annotation.

Submit **two sequential PRs**, 5a then 5b. Do not batch.

Read first:
- `frontend/src/components/ManualBinningEditor.tsx`
- `frontend/src/components/StepInspector.tsx` (manual-binning readiness
  block)
- `cardre/services/manual_binning_service.py` (`get_editor_state`,
  `validate_overrides`)
- `sidecar/models.py` (`ManualBinningEditorStateResponse`)
- `frontend/src/components/ProjectView.tsx` (`handleEditManualBinning`)
- `CONTEXT.md` §"Refinement nodes" — confirms manual binning is build-stream.

## Phase 5a — Journey integration + DTO enrichment

### Goal

- Manual binning is surfaced as a journey step everywhere it matters:
  - JourneyHeader CTA shows "Edit bins" when `step_guidance["manual-binning"].readiness == "ready"`.
  - Pathway card shows the count of selected variables ("Ready to edit N selected variables").
  - StepInspector's Next-action tab shows manual-binning readiness as a
    feature card (the legacy block is reworked into the assistant flow).
- `ManualBinningEditorStateResponse` gains the per-variable summary fields
  the editor needs to surface judgement, not just override wiring.

### Backend DTO Enrichment

Extend `ManualBinningEditorStateResponse` additively:

```python
class ManualBinningVariableSummary(BaseModel):
    variable: str
    iv: float | None
    woe_by_bin: dict[str, float] | None
    event_rate_by_bin: dict[str, float] | None
    missing_count: int | None
    special_bin_count: int | None
    sparse_bin_warning: bool
    non_monotonic_warning: bool

class ManualBinningEditorStateResponse(BaseModel):
    # ...existing fields...
    variable_summaries: list[ManualBinningVariableSummary]  # new; aligned with selected_variables
```

`ManualBinningService.get_editor_state` populates the new field. Compute WOE/IV
per variable from the upstream WOE/IV evidence artifact (locate via the
`cardre.woe_iv_evidence.v1` artifact for this branch's most recent run).
Sparse-bin threshold = a node param or service constant (start at 5% of
total rows per bin). Non-monotonic = WoE trend not monotone in the bin
order. Doc-annotate the constant threshold; do not expose as a node param in
this phase.

⚠ **Read** WOE values through `ArtifactEvidenceReader.find(...)` on the
`EvidenceKind.WOE_IV` evidence — never `pl.read_parquet` of raw artifact
paths or `json.loads` of artifact bodies. The artifact-read guardrail will
flag it.

### Frontend

`ManualBinningEditor.tsx` (current 292 lines) extends to render a new
top-of-editor panel:

- Variable list with IV, WOE-by-bin sparkline (text only is fine for 5a — no
  chart library; chartless bars suffice), event-rate-by-bin, missing count,
  special-bin count, sparse-bin warning tag, non-monotonic warning tag.
- Existing override form stays below.

`StepInspector` Next-Action tab gets a feature card for manual-binning
readiness that mirrors the journey flow:

- "Ready to edit N selected variables" + "Edit Bins" button (calls
  `onEditManualBinning`). This is the legacy block, restyled.
- Or "Not ready: {blocked_reason}" + the prerequisite step chips.

The card copy uses the **canonical** "Edit bins" label from guidance. No
second CTA.

`PathwayView` StepCard for `manual-binning` (canonical ID) gains the
"Ready to edit N selected variables" hint sourced from
`guidance.step_guidance["manual-binning"]`. Phase 3 already added `primary_action`
text; Phase 5a adds the variable count. The guidance backend (Phase 1)
**must** include the variable count in `step_guidance["manual-binning"].primary_action`
or a new `step_guidance["manual-binning"].action_target` (the cleaner option:

Phase 5a may extend `WorkflowStepGuidance` additively with:

```python
class WorkflowStepGuidance(BaseModel):
    # ...existing fields...
    action_target: str | None  # new, generic; for manual binning: "manual_binning:N_selected=12"
```

This additive change is small and does not break Phase 1 contract. Update
Phase 1 tests to assert the new field exists but is optional.

### Files (5a)

| File                                              | Action | Content                                                                                          |
|---------------------------------------------------|--------|--------------------------------------------------------------------------------------------------|
| `sidecar/models.py`                               | Edit   | Add `ManualBinningVariableSummary`. Add `WorkflowStepGuidance.action_target: str \| None`. Extend `ManualBinningEditorStateResponse.variable_summaries`. |
| `cardre/services/manual_binning_service.py`       | Edit   | `get_editor_state` populates `variable_summaries`. Reads WOE/IV via `ArtifactEvidenceReader`. |
| `cardre/services/workflow_guidance_service.py`    | Edit   | Populate `step_guidance["manual-binning"].action_target = f"manual_binning:N_selected={len(state.selected_variables)}"`. |
| `frontend/src/components/ManualBinningEditor.tsx` | Edit   | Render the variable summary panel. Existing override form unchanged.                          |
| `frontend/src/components/StepInspector.tsx`        | Edit   | Rework the manual-binning readiness block in the Next-action tab (per Phase 4's tab scaffold, or inline if Phase 4 not yet landed — coordinate). |
| `tests/test_manual_binning_source.py`             | Edit   | Add coverage for `variable_summaries` population, sparse-bin warning, non-monotonic warning. |
| `frontend/src/api/schema.d.ts`                    | Regen  | After the sidecar model change. |

### Acceptance (5a)

- Backend: `get_editor_state` returns `variable_summaries` for every entry in
  `selected_variables`. Sparse/non-monotonic flags are computed from evidence,
  not from a re-fit.
- Manual binning cannot be edited without first seeing the variable summary
  panel (the existing "Save Overrides" button sits below the new panel).
- Pathway card shows "Ready to edit N selected variables" when the readiness
  is `ready`.
- JourneyHeader (Phase 2) CTA becomes "Edit bins" in `build` phase when
  manual binning is the next step.
- Guardrail test passes (no new direct file reads).

### Non-Goals (5a)
- Review-complete marker (5b).
- Charts / sparklines library.
- Persisting per-override accept-automated state.

---

## Phase 5b — Review-complete marker

### Goal

A modeller cannot accidentally treat automated bins as final without
either (a) marking manual binning reviewed, or (b) explicitly accepting
automated bins. Suggested copy: "Mark bin review complete" + "Accept
automated bins (overrides will be discarded)".

### Backend

1. Manual-binning node param schema gains `reviewed: bool = False` and
   `accept_automated: bool = False` (mutually exclusive — validation in
   `node.validate_params` rejects both true).
2. `ManualBinningService.save_overrides` (or `PlanService.update_params`
   for the manual-binning step) writes `reviewed=True` atomically with the
   override list when the user clicks "Mark bin review complete". If
   `accept_automated=True`, the existing overrides list is replaced with
   `[]` and `reviewed=True` is persisted.
3. **Audit annotation**: a `step_annotation` row (use existing audit row kind
   if available, otherwise add an audit table for step annotations) records:
   `kind: "manual_binning_review"`, `step_id`, `actor: "user"`,
   `timestamp`, `payload: {reviewed: true, accepted_automated: false,
   override_count: N}`. This evidence is what auditors look for.

### Staleness interaction

Per `CONTEXT.md §"Step Status: Stored vs Computed"`, staleness is computed.
Any upstream change to fine-classing or WOE/IV **must** reset
`reviewed=False` for the dependent manual-binning step. Implement in
`PlanService.update_params` for any step upstream of
`manual-binning`: after computing stale_step_ids, also reset the downstream
manual-binning step's `reviewed` param to `False` in the same transaction.
This is a small targeted write; a unit test asserts the reset.

### Guidance surfacing

`WorkflowGuidanceService._step_guidance_for("manual-binning")` reads
`reviewed` from current params:

- `reviewed == True` → readiness `complete` (assuming non-stale).
- Otherwise if upstream complete and `accept_automated == False` → readiness
  `ready` with `primary_action` "Mark bin review complete".
- If overrides present but `reviewed == False` → readiness `ready` with
  `primary_action` "Review saved overrides and mark complete".

### Files (5b)

| File                                              | Action | Content                                                                                          |
|---------------------------------------------------|--------|--------------------------------------------------------------------------------------------------|
| `cardre/nodes/manual_binning.py` (or equivalent)  | Edit   | Add `reviewed` and `accept_automated` to `parameter_schema`; enforce mutual exclusion in `validate_params`. |
| `cardre/services/manual_binning_service.py`       | Edit   | `save_with_review(plan_id, plan_version_id, step_id, overrides, reviewed, accept_automated)` writes the params + annotation. |
| `cardre/services/plan_service.py`                 | Edit   | After stale computation, reset downstream manual-binning `reviewed` to False in same transaction. |
| `sidecar/routes/plans.py`                         | Edit   | New endpoint `POST /plans/{plan_id}/steps/{step_id}/manual-binning/review` accepting `{reviewed, accept_automated, overrides?}`. |
| `sidecar/models.py`                               | Edit   | `ManualBinningReviewRequest`, `ManualBinningReviewResponse`.                                    |
| `cardre/services/workflow_guidance_service.py`    | Edit   | Read `reviewed`/`accept_automated` from current manual-binning step params; set readiness accordingly. |
| `cardre/audit.py` (or `cardre/store_schema.py`)   | Edit   | Step-annotation row kind; storage helper. Keep SQLite metadata-only. |
| `frontend/src/components/ManualBinningEditor.tsx` | Edit   | Add the two buttons. Wire the new endpoint via a one-liner `client.ts` method. |
| `frontend/src/components/StepInspector.tsx`       | Edit   | Surface reviewed/accept-automated state in the Next-action tab. |
| `frontend/src/api/schema.d.ts`                    | Regen  | After sidecar models. |
| `tests/test_manual_binning_source.py`             | Edit   | Cover mutual exclusion, stale reset, guidance-derived readiness. |

### Acceptance (5b)

- With automated bins, the modeller **cannot** reach "report ready" without
  `reviewed == True` on `manual-binning` (or `accept_automated == True`).
  Enforce via `check_report_readiness` adding a blocker
  `MANUAL_BINNING_NOT_REVIEWED` (new `LimitationCode`).
- Any upstream parameter change resets `reviewed` to False; a stale pill
  appears on the manual-binning card (Phase 3).
- Annotation audit row written on every review/accept action.
- `python3 -m pytest tests/ -q` green; new test asserts stale reset.
- `npx tsc --noEmit` clean.

### Non-Goals (5b)
- Per-override timestamps (single annotation at review time is sufficient).
- Multi-actor review workflows.

## Drop-Dead Notes (Both 5a and 5b)

- Manual binning is part of the **build** stream (CONTEXT.md, ADR 0001).
  Do not add a `manual_review` phase. Readiness surface is per-step.
- The `reviewed` param is a **node param**, not a separate store table.
  Persist in `plan_steps.params` JSON; this is the existing pattern.
- Reset of `reviewed` on upstream change must be transactional with the new
  plan-version write in `PlanService.update_params` — do this inside the
  same `with self._store.transaction() as conn:` block that already exists.
- 5a is *required before 5b*. 5b touches node schema and adds a readiness
  blocker; without 5a's DTO, the modeller has no warnings to look at.