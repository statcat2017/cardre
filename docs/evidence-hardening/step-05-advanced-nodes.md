# Step 05 — Migrate Advanced Modelling Nodes

Files:
- `cardre/nodes/ensembles.py`
- `cardre/nodes/explainability.py`
- `cardre/nodes/fairness.py`
- `cardre/nodes/feature_selection.py`

## Pre-req: S2 complete.

## Direct reads (from survey)

### `ensembles.py`
- L56 `json.loads(store.artifact_path(art).read_text())` — most likely
  ENSEMBLE_MODEL_ARTIFACT or a base model read. Use
  `reader.read(art.artifact_id, EvidenceKind.ENSEMBLE_MODEL_ARTIFACT)`
  if it's an ensemble; if it's a base MODEL_ARTIFACT, use that.
- L185, L390, L427 `pl.read_parquet(store.artifact_path(train_art/val_art))`
  — training/validation data frames. Dataset-frame-input, suppress.

### `explainability.py`
- L152 `model = json.loads(store.artifact_path(model_art).read_text())`
  — MODEL_ARTIFACT.
- L303, L413, L469, L719 `pl.read_parquet(...)` — data frames.
  Dataset-frame-input, suppress.
- L311 `meta = json.loads(store.artifact_path(a).read_text())` —
  likely EXPLAINABILITY_REPORT or MODELLING_METADATA. Determine kind.
- L594 `model = json.loads(store.artifact_path(model_art).read_text())`
  — MODEL_ARTIFACT.

### `fairness.py`
- L94 `pl.read_parquet(store.artifact_path(data_art))` — data frame.
- L315 `model = json.loads(store.artifact_path(model_art).read_text())`
  — MODEL_ARTIFACT.
- L323, L458 `pl.read_parquet(store.artifact_path(train_art))` — data
  frame.

### `feature_selection.py`
- L99, L344, L540, L708 `pl.read_parquet(store.artifact_path(train_art))`
  — training frame, dataset-frame-input, suppress.
- L259, L439 `existing = json.loads(store.artifact_path(def_art).read_text())`
  — FEATURE_SELECTION_EVIDENCE (added in S2 as experimental) or a
  selection family definition. Use the experimental/evidence reader
  path; do not parse raw JSON.

## Required behaviour (spec §9 PR5)

- Experimental nodes may remain feature-gated (LaunchMode /
  CARDRE_GOVERNANCE env flags). They MUST NOT bypass the reader.
- Use the experimental evidence kinds added in S2
  (`FEATURE_SELECTION_EVIDENCE`, `ENSEMBLE_MODEL_ARTIFACT`,
  `EXPLAINABILITY_REPORT`, `FAIRNESS_REPORT`, `RESAMPLING_EVIDENCE`,
  `HYPERPARAMETER_TUNING_EVIDENCE`, `PROXY_RISK_REPORT`).
- Where the typed model is not yet launch-grade, return an
  `ExperimentalEvidence` placeholder model from the reader; product
  nodes accept the placeholder as best-effort. Do NOT introduce a
  second raw-JSON path "just for now".

## Tests

- Existing tests under `tests/test_ml_ensembles.py`,
  `test_boosting_fairness.py`, `test_explainability_limitations.py`,
  `test_feature_selection_resampling.py` continue to pass.
- Tests pass under both launch mode (no env flags) and
  governance/experimental mode (`CARDRE_GOVERNANCE=1`).
- No file from this step appears in audit `production_violation`
  (after dataset-frame-input suppressions).

## Do NOT do

- Do not promote experimental evidence to a launch contract in this
  step. Mark models as experimental (comment + simple validation) and
  leave deeper schema work for later.
- Do not modify the guardrail test or audit script.

## Verify

```
python scripts/audit_artifact_reads.py --production --json
CARDRE_GOVERNANCE=1 pytest tests/test_ml_ensembles.py tests/test_boosting_fairness.py tests/test_explainability_limitations.py tests/test_feature_selection_resampling.py
pytest tests/test_ml_ensembles.py tests/test_boosting_fairness.py
```