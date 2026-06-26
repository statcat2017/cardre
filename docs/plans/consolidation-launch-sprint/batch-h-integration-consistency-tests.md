# Batch H — Integration Consistency Tests

## Goal

Prove the consolidated primitives from Batches A-G are actually used
everywhere. This batch does not add new features — it adds cross-service
parity tests that fail if any consumer reverts to a local resolution path,
and it deletes the `evidence_locator.py` compatibility shim once all call
sites have migrated.

## Context you must read first

- `cardre/evidence_locator.py` — the compatibility shim from Batch A. All
  public functions now delegate to `EvidenceResolver`.
- `cardre/services/evidence_resolver.py` — the consolidated resolver.
- `cardre/services/step_resolution_service.py` — the consolidated step
  resolver.
- `cardre/services/run_currentness_service.py` — currentness evaluation.
- `cardre/reporting/report_evidence_plan.py` — shared readiness/collector
  plan.
- `cardre/services/manual_binning_context.py` — manual-binning context.
- `cardre/services/artifact_presentation_service.py` — artifact presentation.
- `cardre/services/resource_locator.py` — cross-project lookup.
- `docs/plans/consolidation-launch-sprint/README.md` — definition of done.
- All batch docs A-G.

## Prerequisite

Batches A-G must land first. This batch runs in Wave 4, after all backend
and frontend migrations.

## Changes

### 1. Cross-service evidence parity tests

New file `tests/test_evidence_resolution_parity.py`.

One fixture set, reused across every consumer. Each fixture constructs a
project with a known evidence layout (branch-owned, full-plan fallback,
inherited source-branch, stale fingerprint, non-first artifact, legacy
alias). Then each test asserts that every consumer resolves the same
`run_step_id` for the same branch/step.

Consumers covered:

- branch execution (`BranchEvidenceResolver.prepare_branch_run`)
- comparison readiness (`comparison_service._check_branch_readiness`)
- comparison content (`_build_comparison_content`)
- export (`export_service._populate_export`)
- report readiness (`check_report_readiness`)
- report collector (`ReportCollector.collect`)
- manual-binning editor (`ManualBinningService.get_editor_state`)
- manual-binning validation (`ManualBinningService.validate_overrides`)
- method-summary (`method_summary.get_branch_method_summary`)
- workflow guidance (`workflow_guidance_service.build`)
- run evidence route (`evidence.get_step_evidence`)

Assert for each fixture:

```python
def test_inherited_source_branch_evidence_parity(inherited_fixture):
    store = inherited_fixture.store
    branch_id = inherited_fixture.branch_id
    step_id = "final-woe-iv"

    # All consumers must resolve the same run_step_id
    expected = inherited_fixture.across_plan_run_step_id

    assert branch_execution_run_step(store, branch_id, step_id).run_step_id == expected
    assert comparison_readiness_run_step(store, branch_id, step_id).run_step_id == expected
    assert comparison_content_run_step(store, branch_id, step_id).run_step_id == expected
    assert export_run_step(store, branch_id, step_id).run_step_id == expected
    assert report_readiness_run_step(store, branch_id, step_id).run_step_id == expected
    assert report_collector_run_step(store, branch_id, step_id).run_step_id == expected
    assert manual_binning_editor_run_step(store, branch_id, step_id).run_step_id == expected
    assert method_summary_run_step(store, branch_id, step_id).run_step_id == expected
    assert workflow_guidance_run_step(store, branch_id, step_id).run_step_id == expected
```

This is the test that fails if any consumer later reintroduces a local
lookup.

### 2. Currentness consistency tests

New file `tests/test_currentness_consistency.py`.

Assert that `RunCurrentnessService`, `staleness_detail`, `compute_staleness`,
and the route preflight (now via `submit_run`) agree:

- `reason_by_step` from `CurrentnessResult` matches
  `staleness_detail` reasons for the same branch/version.
- `evidence_sources` matches the source `step_is_stale` actually used (not
  the collected map).
- `submit_run` branch no-op returns the same run as
  `RunCurrentnessService.evaluate_currentness` reports.
- To-node currentness does not return an unrelated full run (the Batch D
  regression test, now cross-checked against staleness).

### 3. Report evidence plan agreement tests

New file `tests/test_report_evidence_plan_agreement.py`.

- `check_report_readiness` and `ReportCollector.collect` consume the same
  `ReportEvidencePlan`; assert every `resolved_run_steps[canonical].run_step.run_step_id`
  matches between the two.
- `export_service` with `include_report=True` uses the same run as
  `ReportGenerationService.latest_reportable_run`.
- Method-summary selects the same model artifact as the report collector
  for a branch with inherited evidence.

### 4. Manual-binning context agreement tests

New file `tests/test_manual_binning_context_agreement.py`.

- `get_editor_state`, `preview_overrides`, and `validate_overrides` all
  report the same `binning_artifact_id` for the same branch/version/step.
- `save_with_review(reviewed=True)` against the context's
  `binning_artifact_id` succeeds; against a different (stale) artifact, it
  raises `REVIEW_COMPLETION_BLOCKED`.
- Preview carries a staleness warning when `binning_stale=True`.

### 5. API error code agreement tests

Extend `tests/test_api_error_codes.py` (from Batch E) with cross-route
assertions:

- The same missing-branch error returns `BRANCH_NOT_FOUND` from export,
  report, and comparison routes (not `EXPORT_FAILED` / `READINESS_FAILED` /
  `COMPARISON_FAILED`).
- Every error response carries a non-empty `detail.request_id`.
- `INTERNAL_ERROR` responses do not leak tracebacks in `detail.message`.

### 6. Frontend parity tests

Extend `frontend/src/components/__tests__/` with:

- `ArtifactSummaryInline` renders `ErrorNotice` with the API code on a 500,
  not `null`.
- `ArtifactPreviewPane` renders `PREVIEW_FAILED` from the backend code.
- `ManualBinningEditor` renders the editor-state error code.
- All API calls with optional params use `withQuery` (assert no manual `?`
  interpolation in the requested URL via MSW handler call assertions).

### 7. Delete `evidence_locator.py` compatibility shim

After every consumer is confirmed migrated by the parity tests above:

- Grep for `from cardre.evidence_locator import` and
  `from cardre import evidence_locator`. Every hit must be gone or point to
  the new `evidence_resolver.py`.
- Delete `cardre/evidence_locator.py`.
- Delete `tests/test_evidence_locator.py` (its coverage is now in
  `test_evidence_resolver.py` and the parity tests).
- If any import remains, either migrate that consumer or document why it
  cannot move and keep the shim with a deprecation comment — but the
  definition of done requires deletion unless there is a documented
  exception.

### 8. Final verification gate

Run the full suite:

```bash
pytest tests/
npm run test -- src/api src/hooks src/components/__tests__/ProjectView
npm run typecheck
npm run lint
python3 scripts/generate-openapi-types.py  # must produce no diff
```

All must be green on the integration branch before the sprint is declared
done.

## Verification

This batch's tests are the verification. They must pass and remain green on
the integration branch. Any future PR that reintroduces a local resolution
path will fail one of the parity tests.

## Definition of done

1. Cross-service evidence parity tests pass for all consumers listed above.
2. Currentness consistency tests pass.
3. Report evidence plan agreement tests pass.
4. Manual-binning context agreement tests pass.
5. API error code agreement tests pass.
6. Frontend parity tests pass.
7. `evidence_locator.py` is deleted (or retained with a documented
   exception).
8. Full `pytest tests/` and frontend test/typecheck/lint suites are green.
9. `schema.d.ts` regeneration produces no diff.

## Files touched

- `tests/test_evidence_resolution_parity.py` (new)
- `tests/test_currentness_consistency.py` (new)
- `tests/test_report_evidence_plan_agreement.py` (new)
- `tests/test_manual_binning_context_agreement.py` (new)
- `tests/test_api_error_codes.py` (extended)
- `frontend/src/components/__tests__/` (extended)
- `cardre/evidence_locator.py` (deleted)
- `tests/test_evidence_locator.py` (deleted)

## Depends on

Batches A-G

## Unblocks

Launch (this batch is the launch gate).