# Step 04 — Migrate Validation/Apply Node

File: `cardre/nodes/validate/apply.py`

## Pre-req: S2 complete.

## Direct reads (from survey)

- L149 `pl.read_parquet(store.artifact_path(data_art))` — APPLY data
  stream (test/oot tabular data). Dataset-frame-input — suppress with
  `# cardre-allow-artifact-read: dataset-frame-input`.
- L305 `model = json.loads(store.artifact_path(model_art).read_text())`
  — MODEL_ARTIFACT. Replace with
  `reader.read(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)`.
- L315 `scorecard_parsed = json.loads(store.artifact_path(scorecard_art).read_text())`
  — FROZEN_SCORECARD_BUNDLE or SCORE_SCALING; confirm from metadata.
- L330 `base_parsed.append(json.loads(store.artifact_path(bm_art).read_text()))`
  — comparison base models. These are MODEL_ARTIFACT reads for
  comparison; if the kind is COMPARISON_ARTIFACT (added in S2), use
  that, else MODEL_ARTIFACT.
- L368 `pl.read_parquet(store.artifact_path(data_art))` — validation
  apply data; dataset-frame-input, suppress.

## Required behaviour changes (spec §9 PR4)

1. Apply WOE must consume typed `BinDefinition` and
   `SelectionDefinition` evidence — not parse definition JSON.
2. Apply model must consume typed `ModelArtifact` and `ScoreScaling`
   evidence.
3. Validation metrics must consume typed `ScoredDataset` and
   `ModellingMetadata` evidence.
4. Any legacy artifact fallback must move into `cardre/_evidence/`
   (extend S2 legacy matchers), not live in `apply.py`.

If a legacy fallback *must* be added inside `_evidence`, do it in
`reader._legacy_match` or a dedicated `_evidence/legacy.py` module.
Never inline legacy detection in `apply.py`.

## Error handling

Apply failures must be clear when model/score scaling/binning evidence
is missing or ambiguous. Wrap `EvidenceNotFoundError` /
`AmbiguousEvidenceError` into a user-facing message naming the step the
evidence was expected from (use spec §11 example).

## Tests

- Existing tests continue to pass.
- Add tests for: missing model evidence → typed error; ambiguous
  score scaling → typed error; legacy-compatible evidence (older schema
  version) → still parses through reader and node succeeds.

## Do NOT do

- Do not modify `nodes/validate/analyse.py` here (it reads parquet
  dataset frames; if its parquet reads are dataset-frame-input, suppress
  them in the same batch as S5, not here — out of scope for S4).
- Do not touch the guardrail test.

## Verify

```
python scripts/audit_artifact_reads.py --production --json
pytest tests/test_scorecard_model.py tests/test_ml_scorecard_methods.py tests/test_safety_rails.py
```