# Phase 4 — Readiness/evidence consistency tests

## Goal

Prove readiness and evidence cannot silently diverge. PR 0 collapsed
the two readiness producers; PR 4closes the loop by adding the
assertions that prevent regression of (a) readiness-vs-evidence state,
(b) readiness-vs-collector limitation emission, and (c) blocker-to-
evidence navigation.

This PR is mostly test hardening — but PR 0 has done the producer
consolidation; this PR is the verification, not the refactor.

## Context you must read first

- `cardre/readiness/check.py` (post-PR-0) — single producer; called by
  both `sidecar/routes/reports.py` and
  `cardre/services/workflow_guidance_service.py`.
- `cardre/reporting/collector.py:321` and
  `cardre/readiness/check.py:~213` (line numbers shift after PR 0) —
  both emit `MISSING_WOE_IV_EVIDENCE_V1`. A report can
  succeed-with-limitation while readiness blocks. This PR asserts that
  this **cannot** cause divergence: collector blocker-level limitations
  ⊆ readiness blockers for the same branch/run/mode.
- `cardre/readiness/limitation_codes.py` (post-PR-0 path) — code set.
- `cardre/reporting/evidence_contract.py:18-49` — the lists PR 2 uses
  for "partial"; the same lists determine which steps must have
  evidence for a branch to be ready.
- `cardre/services/manual_binning_service.py:243-258` — the
  `VARIABLE_SUMMARY_UNAVAILABLE` editor warning. PR 4 confirms this
  editor-level warning is consistent with (not contradictory to) the
  readiness blocker on `final-woe-iv`.
- `frontend/src/components/ReadinessPanel.tsx:114-116` — the
  disclaimer that admits TopBar-vs-ExportPanel divergence. **Remove
  this disclaimer** once the PR 0 consolidation is verified.
- `frontend/src/components/__tests__/journey.test.tsx` and
  `journey.launch.test.tsx` — the existing MSW-driven journey tests.
  PR 4 adds a journey-with-blocker test alongside these.
- `tests/test_reporting_acceptance.py:98-110` — `_review_manual_binning`
  helper to reuse.
- `tests/test_reporting.py:526-645` — the regression class PR 4
  extends.

## Changes

### 1. Backend: assert single-producer invariant

In `tests/test_readiness_package.py` (created in PR 0), extend
`test_single_producer_shape` with:

- A full-blocker scenario (manual-binning unreviewed + WOE/IV missing
  + no champion assignment).
- Assert `check_report_readiness(...).to_dict()` (the readiness route's
  source) and the `report_readiness` dict embedded in
  `WorkflowGuidance` (from the workflow-guidance route) are **deep-equal**
  for the same `branch_id` / `run_id` / `report_mode="branch"`.
- The only allowed difference: context echo fields
  (`project_id`, `run_id`, etc.) live only on
  `ReportReadinessResponse`, not on `WorkflowReportReadiness`; assert
  `blockers` and `warnings` arrays match exactly.

This test is the regression prevention for PR 0's consolidation.

### 2. Backend: assert collector limitations ⊆ readiness blockers

In `tests/test_reporting_acceptance.py` (or a new
`tests/test_collector_readiness_consistency.py`), add:

**`test_collector_blocker_limitations_are_readiness_blockers`**:

- Drive a scenario where the report builds *with* a limitation
  (collector emits a code in
  `LimitationCode.blocker_codes()`).
- Run `check_report_readiness` against the same branch/run.
- Assert: every collector-emitted blocker-level limitation code is also
  present in `result.blockers` (matched by code and resolved
  `step_id`).
- Document the inverse is **not** required: readiness may have blockers
  the collector does not (e.g. champion assignment) — those gate *the
  export* not *the build*. The test only asserts collector ⊆ readiness,
  not the reverse.

If the assertion fails because the collector emits a blocker-level
limitation code that readiness doesn't, **this is a real divergence**
and ~~do not relax the test~~ file the inconsistency as a defect in this
PR by extending `cardre/reporting/collector.py` to consult
`cardre.readiness.limitation_codes` and refuse to emit a blocker-level
limitation code unless readiness would too. (This is the small collector
reconciliation PR 4 calls out; it should be a one-method guard, not a
re-implementation.)

### 3. Backend: scenario tests for readiness and evidence agreeing

New file `tests/test_readiness_evidence_consistency.py`. Three
scenarios:

**`test_final_woe_iv_missing`**:
- Branch has run steps for `model-fit`, `score-scaling`,
  `validation-metrics` but **not** `final-woe-iv`.
- Call `check_report_readiness(target_branch_id, report_mode="branch")`.
  Assert: `blockers` contains `MISSING_WOE_IV_EVIDENCE_V1` with
  `step_id` resolving to (or absent because of) the missing step.
- Call the evidence route
  `GET /runs/{run_id}/steps/{step_id}/evidence` against the manual
  binning step's `step_id` (where the user would land from a blocker).
  Assert: response `status=MISSING` or `PARTIAL`, and at least one
  per-item `status=MISSING` for `final-woe-iv`.

**`test_manual_binning_unreviewed`**:
- Manual-binning step present but `reviewed=False`,
  `accept_automated=False`.
- `check_report_readiness` → blocker with
  `code=MANUAL_BINNING_NOT_REVIEWED`, `step_id` = manual-binning step
  on this branch.
- Workflow guidance (`/workflow-guidance`): the `step_guidance` entry
  for `manual-binning` marks readiness incomplete.
- Assert workflow-guidance step_incomplete step_id ==
  readiness blocker step_id.

**`test_stale_upstream_consistency`**:
- Run a successful `final-woe-iv`, then mutate a parent step's params
  so `staleness.py` reports `step_is_stale=True` for `final-woe-iv`.
- `check_report_readiness`: assert either a blocker or a warning
  carries `MISSING_WOE_IV_EVIDENCE_V1` (or a new `STALE_WOE_IV_EVIDENCE_`
  warning if PR 1 added one). The point is consistency, not the code.
- Evidence route for `final-woe-iv`'s step: assert response
  `status=STALE` (per PR 2's routing of `staleness_detail`).
- Assert the workflow guidance `step_guidance` field `is_stale=True`
  for the same step.

Each scenario uses pytest fixtures; do **not** mock the readiness check
or the evidence route at the unit level. Use the same store + run
fixtures as `tests/test_reporting_acceptance.py`.

### 4. Frontend: journey test for blocker → evidence navigation

Add `frontend/src/components/__tests__/journey.blocker-evidence.test.tsx`
modeled on `journey.launch.test.tsx`. Steps:

1. MSW returns guidance with a blocker carrying `step_id` for
   manual-binning unreviewed and report-mode `branch`.
2. ExportPanel (or ReadinessPanel) shows the blocker with the "Go to
   step" button.
3. User clicks "Go to step". Assert:
   - ProjectView switches the center panel to `pathway`
     (`setActiveSection("pathway")`).
   - `selectedStepId` is set to the blocker's `step_id`.
4. `EvidenceTab` mounts for that step. MSW returns a step-evidence
   response (PR 2 shape) with `status=MISSING` (manual-binning has not
   produced WOE/IV evidence yet, or WOE/IV step evidence is absent).
   Assert:
   - EvidenceTab renders the "No evidence found" or "Partial evidence"
     copy.
   - The blocker's `step_id` matches the request the EvidenceTab hook
     fired.
5. Readiness context line (`ReadinessPanel`'s freshness copy from
   Batch 1 PR 3) shows `target_branch_id`, `run_id`, `report_mode`
   matching the echo fields from PR 1.

Reuse the MSW infrastructure already present in
`frontend/src/test/server.ts`. The handler set the
journey tests use covers `/workflow-guidance`, `/report-readiness`,
`/runs/{run_id}/steps/{step_id}/evidence`, and the basic run/branch
endpoints. Every network call must have a handler —
`onUnhandledRequest: "error"` will otherwise fail the test.

### 5. Remove the disclaimer

Once the backend single-producer test (#1) passes, remove:
- `frontend/src/components/ReadinessPanel.tsx:114-116` (the
  "Export readiness is checked separately from the TopBar readiness
  badge" copy).
- Any duplicate test assertion that tolerated the divergence.

Removing the disclaimer before tests prove no divergence
is a regression risk. Gate the removal on the
`test_single_producer_shape` test passing locally; do not remove it
speculatively.

## Tests

This PR's primary deliverable is tests. The new tests are described
above. No production code changes except:

1. The small collector guard (§2, ~one method) if needed to satisfy
   the collector ⊆ readiness assertion.
2. Removing the `ReadinessPanel.tsx:114-116` disclaimer (§5).
3. Optionally, if PR 1 didn't add a staleness-specific readiness code,
   this PR may add a small readiness warning for the stale-upstream
   case (§3's third scenario expects one exists). If adding it: a
   single new entry in `cardre/readiness/limitation_codes.py` and one
   `warnings.append(...)` in `check_report_readiness`. Do **not** add
   new blocker codes — staleness is a warning, not a launch blocker.

## Acceptance criteria

- Backend: `test_single_producer_shape` proves readiness route and
  workflow-guidance route return deep-equal blockers/warnings for the
  same inputs (modulo context echo fields).
- Backend: `test_collector_blocker_limitations_are_readiness_blockers`
  proves collector-emitted blocker-level codes ⊆ readiness blockers
  for the same branch/run/mode.
- Backend: the three consistency scenarios
  (final-woe-iv missing, manual-binning unreviewed, stale upstream)
  pass and prove readiness state ↔ evidence state ↔ workflow guidance
  state agree.
- Frontend: `journey.blocker-evidence.test.tsx` proves the blocker →
  "Go to step" → EvidenceTab flow end-to-end with MSW, asserting the
  context line matches the echo fields.
- `ReadinessPanel.tsx:114-116` disclaimer is removed.
- All existing acceptance tests
  (`tests/test_reporting_acceptance.py`, `journey.launch.test.tsx`)
  still pass.
- No new modelling scope, no new report sections.
- Every new test uses MSW (frontend) or fixtures (backend) — no
  module-level mocking of `api` or `check_report_readiness`.

## Out of scope for this phase

- Adding new readiness blocker codes beyond the one optional
  staleness warning in §3.
- Adding new evidence kinds.
- Touching `cardre/reporting/collector.py` beyond the one-method guard
  in §2.
- Redesigning the manual-binning UI.
- Desktop packaging smoke tests.