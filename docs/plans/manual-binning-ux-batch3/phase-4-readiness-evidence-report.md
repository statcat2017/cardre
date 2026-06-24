# Phase 4 — Readiness, evidence, and report integration

## Goal

Make the manual-binning review state visible across the rest of the
launch journey: readiness, the `EvidenceTab` card, and the exported
report bundle. This phase wires the Phase 1–3 contract into the
existing readiness, evidence, and reporting seams without duplicating
them.

## Context you must read first

- `cardre/readiness/check.py:190-216` — the existing branch-scoped
  manual-binning blocker. Already uses
  `resolve_step_for_branch` and reads `reviewed` /
  `accept_automated` from params. Phase 4 asserts this still works
  after Phases 1–3 and that the blocker links to the branch-owned
  step.
- `cardre/reporting/collector.py:232-249` — the manual-binning
  reference resolution in the report collector. Already resolves
  `manual-binning` via the step map.
- `cardre/_evidence/summaries.py:20-21` — the dispatch table. There
  is **no manual-binning evidence kind** today; manual binning is
  audited via the `manual_binning_review` annotation (Phase 1 widened
  its payload). Phase 4 reuses the annotation, it does **not** invent
  a new evidence kind.
- `cardre/services/branch_evidence.py` — the branch-evidence
  aggregation used by `EvidenceTab`. Phase 4 adds a manual-binning
  summary derived from the annotation + the editor state, not a new
  artifact.
- `frontend/src/components/inspector/EvidenceTab.tsx` (post-Batch-2
  seven-state version) — the evidence card host. Phase 4 adds a
  manual-binning card following the same conventions as the other
  evidence cards.
- `frontend/src/components/inspector/EvidenceCard.tsx` — the card
  component. Reuse it; do not build a parallel card.
- `frontend/src/hooks/useReportReadiness.ts` — the readiness hook
  shared by `ProjectView` auto-readiness and `ExportPanel`. Phase 4
  asserts the manual-binning blocker flows through it unchanged.
- `cardre/services/report_generation_service.py:171` — the report
  generation entry point. Phase 4 extends the bundle's manual-binning
  section, it does not rewrite generation.
- `sidecar/routes/reports.py` — the report readiness route. Already
  echoes context (Batch 2). Phase 4 ensures the manual-binning blocker
  still carries `step_id`.
- `tests/test_reporting.py` — readiness regression tests. Extend, do
  not replace.
- `tests/test_reporting_acceptance.py:98-110` —
  `_review_manual_binning` helper. Reuse in Phase 4's acceptance
  tests.

## Changes

### 1. Readiness integration

The existing readiness blocker at `readiness/check.py:210-216` already
fires on `not reviewed and not accept_automated`. Phase 4 leaves that
logic intact and adds:

- An assertion (test-level, not code) that the blocker's `step_id`
  resolves to the branch-owned manual-binning step — this was Batch 2's
  work; Phase 4 confirms it survived the Phase 1–3 contract widening.
- A **warning** (not a blocker) when the step is reviewed but
  `compute_blockers(state)` returns non-empty warnings (non-monotonic
  accepted, low IV accepted). Surface these as `ReadinessWarning`s
  with the manual-binning `step_id` so they link back. Use the shared
  `compute_blockers` helper from Phase 1; do not re-derive.

Do **not** add a second readiness producer. Batch 2 consolidated
readiness into `cardre/readiness/`; this phase extends the existing
function in place.

### 2. Evidence summary for manual binning

Add a manual-binning evidence summary that reads the latest
`manual_binning_review` annotation and the editor state, and produces:

- `review_status` — computed (Phase 1).
- `accepted_automated` — bool.
- `edited_variable_count` — count of variables with at least one
  override in `current_overrides`.
- `reviewed_variable_count` — count of variables covered by an
  override with a valid reason code (or the step is `reviewed`).
- `unresolved_warning_count` — from `compute_blockers` (warnings only,
  not blockers).
- `review_timestamp` — `reviewed_at` from the annotation.
- `reviewer_reason` — `review_reason` from the annotation.
- `top_warning_codes` — the codes of the top N warnings by frequency.

Put this in `cardre/_evidence/summaries.py` as a new builder keyed on a
synthetic `schema_version` (e.g. `cardre.manual_binning_review_summary.v1`)
or, cleaner, as a dedicated function called from the
branch-evidence aggregation in `cardre/services/branch_evidence.py`.
Prefer the dedicated function — manual binning is not an artifact
evidence kind; it is an annotation + editor-state summary. Do not
invent a new `EvidenceKind` enum value.

### 3. Report bundle section

In `cardre/reporting/collector.py`, extend the manual-binning section
(at `:232` onwards) to include:

- `review_status`
- `variables_edited` (list or count — prefer count for the bundle
  summary, with the per-variable detail available in the annotation
  audit trail)
- `reasons` (the distinct `reason_code` values used across overrides)
- `unresolved_warnings` (the warning list from `compute_blockers`)
- `accepted_automated` (bool)
- `reviewed_at`, `reviewed_by`, `review_reason`

The bundle section is **read-only** — it reflects the review state at
report-generation time. It does not modify the review state. Keep the
collector under the 600-line ceiling; if the section pushes it over,
extract a `manual_binning_section(bundle, store, plan_version_id,
step_id)` helper into a new small module or into
`cardre/_evidence/summaries.py`.

### 4. EvidenceTab manual-binning card

In `frontend/src/components/inspector/EvidenceTab.tsx` (or a new
`ManualBinningEvidenceCard.tsx` extracted from it to stay under the
ceiling), render a card when the step is manual-binning:

```
Manual binning reviewed · 8 variables reviewed · 3 edited · 2 warnings
Reviewer: alice · 2026-06-24T10:03Z · Reason: business_interpretability
```

Distinct rendering for `accepted_automated`:

```
Automated bins accepted · 8 variables · 0 edited · 2 warnings
```

Reuse `EvidenceCard.tsx`; pass a summary payload built from the
Phase 4 evidence summary. Do not build a parallel card component.

### 5. ReadinessPanel link

`ReadinessPanel.tsx` already renders a "Go to step" button when
`step_id` is non-null (Batch 2). Phase 4 asserts the manual-binning
blocker still carries the branch-owned `step_id` and that selecting it
opens the manual-binning step in the pathway. No new frontend
component; extend the existing test.

### 6. Wire the report readiness change after review completion

After a successful "Mark review complete" (Phase 3) or "Accept
automated bins", the frontend must invalidate the `reportReadiness` and
`workflowGuidance` queries so the readiness panel and evidence tab
refresh. This is already partially done in
`ManualBinningEditor.tsx:205-207` (Phase 2); Phase 4 ensures
`useReportReadiness` is also invalidated. Add the invalidation to the
review action's `onSuccess` if it is missing.

## Tests

### Backend

1. `test_readiness_blocker_links_to_branch_owned_manual_binning_step` —
   create a branch, leave manual-binning unreviewed; assert
   `check_report_readiness` returns `MANUAL_BINNING_NOT_REVIEWED` with
   the branch-owned `step_id` (e.g. `manual-binning__br_xxx`), not the
   baseline step id.
2. `test_evidence_summary_reports_reviewed_edited_counts` — after
   `save_with_review(reviewed=True, …)` with 3 edited variables;
   assert the evidence summary returns `review_status="reviewed"`,
   `edited_variable_count=3`, `reviewed_variable_count` ≥ 3,
   `review_timestamp` set, `reviewer_reason` present.
3. `test_evidence_summary_reports_accepted_automated_distinctly` —
   `accept_automated=True`; assert the summary returns
   `accepted_automated=True`, `edited_variable_count=0`, and a
   distinct `review_status`.
4. `test_report_bundle_includes_manual_binning_review_details` —
   generate a report after review; assert the bundle's
   manual-binning section carries `review_status`, `variables_edited`,
   `reasons`, `unresolved_warnings`, `accepted_automated`,
   `reviewed_at`, `reviewed_by`, `review_reason`.
5. `test_report_bundle_accepted_automated_distinct_from_manual` —
   generate a report after `accept_automated=True`; assert the bundle
   section differs from the `reviewed=True` case (no `reasons` list,
   `accepted_automated=True`).
6. `test_readiness_warning_when_reviewed_with_unresolved_warnings` —
   reviewed step with non-monotonic accepted (warning, not blocker);
   assert readiness returns a warning with the manual-binning
   `step_id`, not a blocker.
7. `test_blocker_step_id_survives_contract_widening` — regression:
   after all Phase 1–3 changes, the existing Batch 2 readiness
   assertions still pass.

### Frontend (MSW)

8. `EvidenceTab.test.tsx` (or `ManualBinningEvidenceCard.test.tsx`) —
   mock the evidence summary; assert the card renders
   `review_status`, the counts, and the reviewer line; assert the
   accepted-automated rendering differs from reviewed.
9. `ReadinessPanel.test.tsx` — extend the existing test: a
   manual-binning blocker with `step_id="manual-binning__br_xxx"`
   renders a "Go to step" button that selects the manual-binning step.
10. `ManualBinningReviewActions.test.tsx` — after a successful review,
    `reportReadiness` and `workflowGuidance` queries are invalidated
    (assert via a spy on `queryClient.invalidateQueries`).

## Acceptance criteria

- Readiness blockers link to the branch-owned manual-binning step
  (regression-asserted; no new code, just a guard).
- `EvidenceTab` shows a manual-binning evidence card with review
  status, edited/reviewed counts, warning count, reviewer, and
  reason.
- The report bundle contains a manual-binning review section with
  review status, variables edited, reasons, unresolved warnings, and
  whether automated bins were accepted.
- `accepted_automated` is reported distinctly from `reviewed` in both
  evidence and the report bundle.
- Readiness warns (does not block) when a reviewed step has
  unresolved non-blocking warnings; the warning links to the
  manual-binning step.
- A successful review-completion or accept-automated action invalidates
  the readiness and workflow-guidance queries so the UI refreshes.
- `pytest` backend tests pass; `npx tsc --noEmit` and `npm test` pass
  in `frontend/`; no `.tsx` or non-test `.py` file exceeds the 600-line
  ceiling.
- No new `EvidenceKind` enum value was added; manual-binning evidence
  is an annotation + editor-state summary.

## Out of scope for this phase

- A new manual-binning evidence kind / artifact. Reuse the annotation.
- Report redesign beyond the manual-binning section.
- New modelling, fairness, challenger, or reject-inference scope.
- Replacing the readiness producer. Batch 2 consolidated it; this
  phase extends in place.