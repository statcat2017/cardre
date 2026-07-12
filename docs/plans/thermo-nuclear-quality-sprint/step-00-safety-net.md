# PR0 — Safety net before refactor

**Findings:** none (preparatory)
**Batch:** A (must be first)
**Depends on:** nothing
**Behaviour change:** No (tests + scripts only)

## Goal

Before any refactor PR, build the safety net that makes refactoring safe and
reviewable. This PR adds golden fixtures, a report-output diff check, a
build→validate→report smoke test, and grep/check scripts for forbidden
patterns. No production code changes.

## Tasks

### 1. Golden report bundle fixture

1. Run the existing end-to-end pathway test
   (`tests/test_api_scorecard_launch_pathway.py`) to produce a real report
   bundle from a synthetic 60-row binary-classification dataset.
2. Capture the serialized `ReportBundle` JSON output as a golden fixture at
   `tests/fixtures/golden_report_bundle.json`.
3. Add a test `tests/test_golden_report_bundle.py` that runs the pathway and
   asserts the report bundle JSON matches the golden fixture (with a
   `--update-golden` flag for regeneration).
4. This fixture is the diff baseline for all collector refactor PRs
   (PR3c, PR5). If a refactor changes the report output, the golden diff
   fails and the PR must either fix the regression or document the
   intended change.

### 2. Golden model artifact fixture

1. Capture a real `cardre.model_artifact.v1` JSON artifact from the same
   pathway run as `tests/fixtures/golden_model_artifact.json`.
2. Add a test that round-trips it through `ModelArtifactV1.from_dict()` /
   `.to_dict()` and asserts the round-trip is lossless.
3. This fixture is the baseline for PR2 (typed properties) and the
   model-artifact unification.

### 3. Golden bin definition / manual overrides fixture

1. Capture a real bin definition artifact and a manual-binning overrides
   artifact from the pathway run as
   `tests/fixtures/golden_bin_definition.json` and
   `tests/fixtures/golden_manual_binning_overrides.json`.
2. Add a round-trip test for each.
3. This fixture is the baseline for PR7 (binning type cleanup). The
   `apply_overrides` lossy round-trip (T7) will be caught here if the
   merged bins drop fields.

### 4. Build → validate → report smoke test

1. The existing `tests/test_launch_pathway.py` is the executor-level smoke
   test. `tests/test_api_scorecard_launch_pathway.py` is the API-level
   acceptance test. Verify both pass and are sufficient to catch behaviour
   regressions in the refactor PRs.
2. If either test does not cover the full build→validate→report flow, add
   the missing coverage. The smoke test must exercise: import → profile →
   binning → WOE/IV → variable selection → logistic regression → score
   scaling → validation → cutoff analysis → reporting → scorecard export.

### 5. Grep/check scripts

Create `scripts/audit_quality.py` (or extend an existing audit script) that
emits counts for:

- `_raw` accesses in `cardre/nodes/`, `cardre/reporting/`,
  `cardre/services/comparison_service.py` (target: 0 after PR3*)
- `class .*Adapter` in `cardre/_evidence/adapters/` (target: ≤3 after PR2)
- Duplicated step resolver definitions (`ResolvedStepRef` / `resolve_step_for_branch`
  definitions — target: 1 after PR1)
- `EvidenceResolver` / `BranchRunEvidence` / `prepare_branch_evidence`
  references (target: 0 after PR4 or wired with tests)
- Files over 1000 lines in `cardre/` (target: 0 after PR5/PR6)
- Bare string status literals (`"running"`, `"failed"`, etc.) in
  `cardre/services/`, `cardre/execution/` (target: 0 after PR8)

Output as JSON with `{check: count, target: N}` per metric. Include a
`--json` flag for machine-readable output. Include the current baseline
counts in the PR description.

### 6. Report-output diff check

1. Add a pytest fixture or helper that runs the pathway and produces a
   report bundle dict, then compares it to the golden fixture with a
   tolerance for non-deterministic fields (timestamps, run IDs, artifact
   hashes — compare structure + field names, not exact values).
2. This is the check that PR3c and PR5 use to prove no behaviour change.

## Acceptance criteria

- [ ] `tests/fixtures/golden_report_bundle.json` exists.
- [ ] `tests/fixtures/golden_model_artifact.json` exists.
- [ ] `tests/fixtures/golden_bin_definition.json` exists.
- [ ] `tests/fixtures/golden_manual_binning_overrides.json` exists.
- [ ] `tests/test_golden_report_bundle.py` passes.
- [ ] Round-trip tests for model artifact + bin definition + manual
  overrides pass.
- [ ] `scripts/audit_quality.py --json` emits baseline counts for all 6
  metrics.
- [ ] `tests/test_launch_pathway.py` and
  `tests/test_api_scorecard_launch_pathway.py` pass.
- [ ] No production code changed (only tests + scripts + fixtures).

## Do not

- Do not change any production code in this PR.
- Do not fix any findings — this is purely the safety net.