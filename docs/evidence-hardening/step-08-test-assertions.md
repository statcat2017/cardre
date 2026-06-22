# Step 08 — Convert Tests to Evidence Assertions

Create `tests/helpers/evidence_assertions.py` and migrate high-value
tests.

## Pre-req: S2, S3, S4, S5 done. (Tests can't use types that don't
exist yet.)

## File: `tests/helpers/evidence_assertions.py`

Provide:
- `assert_model_artifact(evidence, *, expected_kind="logistic_regression", **fields)`
- `assert_bin_definition(evidence, *, expected_variables=None, **fields)`
- `assert_selection_definition(evidence, *, expected_selected=None, **fields)`
- `assert_woe_iv_evidence(evidence, *, **fields)`
- `assert_score_scaling(evidence, *, **fields)`
- `assert_scorecard_bundle(evidence, *, **fields)`
- `assert_validation_evidence(evidence, *, **fields)`
- `assert_report_bundle(evidence, *, **fields)`

Each helper:
- Asserts the right typed-evidence class was returned (instance-of or
  duck-shape).
- Asserts the `source_artifact_id` is populated.
- Compares user-supplied expected field values against the typed model
  fields.
- On mismatch, raises AssertionError with a diff-style message that
  points to the model field, NOT to the raw artifact file.
- Does NOT read any artifact file — works off the typed evidence
  object the test was handed.

## Migrate tests in priority order

1. `tests/test_scorecard_model.py`
2. `tests/test_frozen_scorecard_bundle.py`
3. `tests/test_reporting_acceptance.py`
4. `tests/test_woe.py`
5. `tests/test_binning.py`
6. `tests/golden_scorecard/` — golden-output tests; assert against the
   evidence model the golden bundle produces, not raw JSON.
7. `tests/test_sidecar_api.py`
8. `tests/test_ml_ensembles.py`
9. `tests/test_boosting_fairness.py`

For each test file:
- Replace `json.loads(store.artifact_path(art).read_text())` +
  dict-key assertions with `reader.read(art.artifact_id, EvidenceKind.X)`
  + an `assert_<model>` helper invocation.
- Replace `pl.read_parquet(store.artifact_path(...))` for evidentiary
  parquets (WOE_TABLE, IV_TABLE, SCORED_DATASET) with the typed reader.
- Tabular dataset reads for actual modelling data can stay as
  `pl.read_parquet(store.artifact_path(...))` in tests (tests are
  allowed dataset-frame-input; audit classifies as `test_violation`
  only when asserting raw layout, not when consuming data). To be
  safe and reduce noise, prefer routing through the reader where a
  typed `ScoredDataset` / `WoeTable` / `IvTable` exists.

## Raw layout tests — isolate

Raw artifact-shape assertions remain allowed ONLY in:
- `tests/test_artifact_serialization.py`
- `tests/test_evidence_reader.py`
- `tests/test_legacy_artifact_compatibility.py` (add if missing —
  this is the home for any "the on-disk JSON shape is still X" test,
  e.g. for backward compatibility; uses suppression
  `# cardre-allow-artifact-read: serialization-compatibility-test`).

Any other test module that genuinely needs to read raw bytes must
either:
- move the relevant test to one of the three files above, OR
- get the evidence via the reader and lose the raw layer.

## Acceptance criteria

- `tests/test_artifact_serialization.py` is the only test module
  with raw artifact layout assertions (plus the two compatibility
  files).
- Audit script `--tests --json` shows materially reduced
  `test_violation` count compared to Batch B exit state.
- All migrated tests still pass.

## Do NOT do

- Do not make tests rely on internal `reader._parse_*` methods; use
  public `read`/`find`.
- Do not lower assertions to `assert isinstance(...)` only — use the
  helper signature so regressions surface as named field mismatches.
- Do not modify production code in this step; if a test reveals a
  production bug, raise it to the orchestrator.

## Verify

```
python scripts/audit_artifact_reads.py --tests --json
pytest tests/test_scorecard_model.py tests/test_frozen_scorecard_bundle.py tests/test_reporting_acceptance.py tests/test_woe.py tests/test_binning.py tests/test_sidecar_api.py tests/test_ml_ensembles.py tests/test_boosting_fairness.py
```