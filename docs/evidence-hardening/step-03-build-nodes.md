# Step 03 — Migrate Core Build Nodes

Files (assigned one per subagent in Batch B):
- `cardre/nodes/build/models.py`
- `cardre/nodes/build/selection.py`
- `cardre/nodes/build/freeze.py`
- `cardre/nodes/build/export.py`

## Goal

Remove every direct `json.loads(store.artifact_path(...).read_text())`
in these files and replace with `ArtifactEvidenceReader` calls. The
files must not appear in the audit script's `production_violation`
list after this step.

## Pre-req

S2 complete (typed models + reader convenience methods available).

## How to migrate a raw read

Given a pattern like:
```python
model_dict = json.loads(store.artifact_path(model_art).read_text())
```
replace with:
```python
reader = ArtifactEvidenceReader(store)
model_artifact = reader.read(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)
```
Then operate on the typed model (`ModelArtifact`) fields instead of the
raw dict. If the typed model is missing a field used downstream, ADD
the field to the model in `cardre/_evidence/models.py` (this is allowed
in this step — go back and extend S2 if needed, but do not bypass the
reader).

## Per-file guidance

### `cardre/nodes/build/models.py`

Known direct reads (from survey):
- L191 `pl.read_parquet(store.artifact_path(train_artifact))` — ALLOWED,
  this is WOE-transformed training data consumed for model fitting
  (spec §9 PR3 special case). Add suppression
  `# cardre-allow-artifact-read: dataset-frame-input` on the same line.
- L408 `model_dict = json.loads(store.artifact_path(model_art).read_text())`
  — reading a MODEL_ARTIFACT. Replace with
  `reader.read(model_art.artifact_id, EvidenceKind.MODEL_ARTIFACT)`.
- L520 `scorecard = json.loads(store.artifact_path(scorecard_artifact).read_text())`
  — likely FROZEN_SCORECARD_BUNDLE or a scorecard role. Check the
  artifact's metadata to pick the kind. If it's a scorecard bundle,
  this is the canonical FROZEN_SCORECARD_BUNDLE reader.
- L526 `model = json.loads(store.artifact_path(model_artifact).read_text())`
  — MODEL_ARTIFACT read; use `reader.read(...)`.
- L606 `pl.read_parquet(...)` for input data — dataset frame input,
  suppress with `dataset-frame-input`.

LogisticRegressionNode is explicitly allowed to keep its
`pl.read_parquet` for the WOE-transformed training Parquet (spec §9
PR3 special case). All other reads in this file must be typed.

### `cardre/nodes/build/selection.py`

- L209 `data = json.loads(store.artifact_path(a).read_text())` —
  likely reading a definition/report. Determine the kind by branch
  context (probably SELECTION_DEFINITION or a kind in the selection
  family). Replace with `reader.read(...)` of the right kind.
- Any `pl.read_parquet` reading candidate ranking tables is a
  dataset-frame-input and can be suppressed if it's tabular ranking
  data, NOT interpreted evidence. If the parquet *is* an evidence
  artifact (e.g. WOE_TABLE, IV_TABLE), it must go through the reader
  — the reader returns the parquet `LazyFrame`/dataclass, do not
  duplicate interpretation.

### `cardre/nodes/build/freeze.py`

- L42 `scorecard = json.loads(store.artifact_path(scorecard_artifact).read_text())`
  — FROZEN_SCORECARD_BUNDLE (or SCORE_SCALING; confirm from metadata).
- L69 `model_raw = json.loads(store.artifact_path(model_art).read_text())`
  — MODEL_ARTIFACT.

After migration `freeze.py` should read both via `reader.read(...)`.

### `cardre/nodes/build/export.py`

Seven direct reads at L92, L94, L97, L99, L101, L103, L105 reading
MODDELLING_METADATA, SELECTION_DEFINITION, MODEL_ARTIFACT (twice),
SCORE_SCALING/FROZEN_SCORECARD_BUNDLE, VALIDATION_METRICS, and
CUTOFF_ANALYSIS respectively. Each must become a typed read.

Important: the spec PR7 design says the technical manifest should
become a renderer/index of the canonical report bundle OR share the
same evidence collector. If this file *is* the TechnicalManifestExportNode
(spec §9 PR7 names `cardre/nodes/build/export.py`), collect all
evidence via `ArtifactEvidenceReader` and produce the index from the
typed models. Keep this node's interpretation identical to
`reporting/collector.py` — if you find duplicated interpretation logic
between the two, surface it for S7; do not silently diverge.

## Error handling

Wrap reader errors into node-level user-facing messages per spec §11.
Pattern:
```python
try:
    score_scaling = reader.read(score_artifact_id, EvidenceKind.SCORE_SCALING)
except EvidenceNotFoundError as exc:
    raise NodeInputError(
        f"Score scaling requires cardre.score_scaling.v1 evidence from the "
        f"score scaling step, but no matching artifact was found among inputs: "
        f"{[a.artifact_id for a in artifacts]}."
    ) from exc
```
Use the project's existing `NodeInputError`-style exception (look in
`cardre/executor.py` or `cardre/errors.py` for the canonical node error
type — do not invent a new one).

## Tests

- Existing node tests must still pass unchanged.
- Add or extend tests to assert the node *calls* the typed reader
  rather than reading raw artifacts. E.g. monkeypatch
  `ArtifactEvidenceReader.read` and assert call, or assert the
  downstream result equals the typed-model-derived value.

## Do NOT do

- Do not modify `reporting/collector.py` here (S7).
- Do not add new EvidenceKind enum members here (S2 owns that).
- Do not delete `_EXISTING_VIOLATORS` (S9 owns that).
- Do not add inline suppressions except `dataset-frame-input` for
  tabular training frames.

## Verify

```
python scripts/audit_artifact_reads.py --production --json | grep <this file>
pytest tests/test_scorecard_model.py tests/test_frozen_scorecard_bundle.py tests/test_binning.py tests/test_ml_scorecard_methods.py
```