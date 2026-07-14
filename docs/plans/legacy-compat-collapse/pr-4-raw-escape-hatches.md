# PR 4 — Remove `_raw` escape hatches and dual-key parsing in evidence models

**Sprint:** `docs/plans/legacy-compat-collapse.md`
**Depends on:** PR 3
**Risk:** High
**Authority:** ADR 0003; task sections 5 and 11.

## Goal

Every evidence model parses only the canonical structure. No `_raw` fields, no `data.get(a, data.get(b))` fallbacks, no inferred required fields. One model-artifact parser (collapse `ModelArtifact` reader into `ModelArtifactV1` or vice versa).

## Files to read first (do not edit)

- `cardre/modeling/schema.py` — `ModelArtifactV1` (:190-317), `_raw` (:222, comment "PR3a/3b/3c" at :220-221), `_raw`-backed properties `coefficients_dict`/`intercept`/`features`/`base_odds`/`bad_class_label`/`feature_strategy` (:228-265).
- `cardre/_evidence/models/model.py` — `ModelArtifact` (:27-131): `_raw` (:37), dual-structure `coefficients` parsing (dict at :54-62, list at :63-74), inferred `features` (:76-78), inferred `model_family` (:79-81), `_raw`-backed properties `feature_contract`/`source_variables`/`calibration`/`has_explicit_intercept`/`to_dict` (:110-130). `ScoreScaling._raw` (:144), `_raw`-backed properties `base_odds_text`/`intercept`/`has_explicit_intercept`/`base_points`/`target_column`/`attributes`/`to_dict` (:186-212). (Note: PR3 already canonicalized `points_to_double_odds` and `score_direction` — this PR removes the remaining `_raw` field and its accessors.)
- `cardre/_evidence/models/validation.py` — `ValidationMetrics._raw` (:26), dual-key parsing (`roles`/`metrics` at :32, top-level `train`/`test`/`oot` fallback at :34-36, `stability`/`psi` at :52), `CutoffRow` dual `score_cutoff`/`score` (:89), `CutoffAnalysis._raw` (:78), dual `cutoff_tables`/`tables` (:83).
- `cardre/_evidence/models/apply.py` — `ScoredDataset._raw` (:64).
- `cardre/_evidence/adapters/__init__.py` — `MODEL_ARTIFACT` adapter parse lambda (uses `ModelArtifact.from_json`).
- `cardre/nodes/validate/analyse.py` — writer emits dual keys (`roles`+`metrics` at :468-469, `stability`+`psi` at :470-471).

## Code instructions

### Step 1 — Tighten the validation-metrics writer

In `cardre/nodes/validate/analyse.py`:
- Line 468: keep `"roles": roles_metrics,`.
- Line 469: delete `"metrics": roles_metrics,`.
- Line 470: keep `"stability": stability,`.
- Line 471: delete `"psi": stability,`.
- Line 907: keep `"cutoff_tables": cutoff_tables,`. Verify no duplicate `"tables"` key is written (search the file).

The cutoff row writer (line 897) already uses `"score_cutoff"` — keep.

### Step 2 — Tighten `ValidationMetrics.from_json`

In `cardre/_evidence/models/validation.py`:
- Line 32: `raw_metrics = data.get("roles", data.get("metrics", {}))` → `raw_metrics = data.get("roles", {})`.
- Lines 33-36: delete the top-level `train`/`test`/`oot` fallback block:
  ```python
  # DELETE:
  if not raw_metrics:
      for key in ("train", "test", "oot"):
          if key in data and isinstance(data[key], dict):
              raw_metrics[key] = data[key]
  ```
- Line 52: `raw_psi = data.get("stability", data.get("psi", {}))` → `raw_psi = data.get("stability", {})`.
- Remove the `_raw` field (line 26) and its assignment in the constructor (line 62: `_raw=data,`).
- `CutoffAnalysis.from_json` (line 83): `raw_tables = data.get("cutoff_tables", data.get("tables", {}))` → `raw_tables = data.get("cutoff_tables", {})`.
- Line 89: `r.get("score_cutoff", r.get("score", 0))` → `r.get("score_cutoff", 0)`.
- Remove `CutoffAnalysis._raw` field (line 78) and its assignment (line 96: `_raw=data,`).

### Step 3 — Tighten `ModelArtifact.from_json`

In `cardre/_evidence/models/model.py` (`ModelArtifact.from_json`, lines 46-99):

- Lines 54-77: accept **only** the dict form of `coefficients`. Replace the `if isinstance(raw_coeffs, dict): ... elif isinstance(raw_coeffs, list): ...` block with:
  ```python
  if isinstance(raw_coeffs, dict):
      coefficients_dict = {
          k: v for k, v in raw_coeffs.items()
          if isinstance(v, (int, float))
      }
      coefficients = [
          Coefficient(variable_name=k, coefficient=v)
          for k, v in coefficients_dict.items()
      ]
  elif isinstance(raw_coeffs, list):
      raise ValueError(
          "ModelArtifact coefficients must be a dict {variable: coefficient}; "
          "list-of-dicts form is not supported."
      )
  else:
      raise ValueError("ModelArtifact requires a 'coefficients' dict.")
  ```
- Lines 76-82: `features` and `model_family` are **required**:
  ```python
  features = data.get("features")
  if not features:
      raise ValueError("ModelArtifact requires a non-empty 'features' list.")
  if not model_family:
      raise ValueError("ModelArtifact requires a non-empty 'model_family'.")
  ```
  (Remove the inference of `features` from `coefficients_dict` and `model_family` from coefficients.)

### Step 4 — Collapse the two model-artifact classes

Decide: make the evidence adapter parse callable construct `ModelArtifactV1.from_dict` and return it; delete `ModelArtifact`.

In `cardre/_evidence/adapters/__init__.py`, find the `MODEL_ARTIFACT` adapter entry and change its `parse` lambda:
```python
# was: parse=lambda path, art, store: ModelArtifact.from_json(read_json_payload(path), artifact_id=art.artifact_id),
parse=lambda path, art, store: ModelArtifactV1.from_dict(read_json_payload(path)),
```
Add the import: `from cardre.modeling.schema import ModelArtifactV1`.

Then find every consumer that imported `ModelArtifact` from `cardre._evidence.models.model`:
```bash
rg -n "from cardre._evidence.models.model import ModelArtifact|from cardre._evidence.models import ModelArtifact" cardre/ tests/
```
For each consumer, switch to `ModelArtifactV1` (from `cardre.modeling.schema`) and update property accesses:
- `ModelArtifact.coefficients_dict` → `ModelArtifactV1.coefficients_dict` (exists).
- `ModelArtifact.intercept` → `ModelArtifactV1.intercept` (exists).
- `ModelArtifact.features` → `ModelArtifactV1.features` (exists).
- `ModelArtifact.target_column` → `ModelArtifactV1.target_column` (exists as a field).
- `ModelArtifact.training` → `ModelArtifactV1.training` (exists; it's a `TrainingMetadata` object, not a dict — consumers that did `model.training.get("converged")` must use `model.training.converged`; `model.training.get("row_count")` → `model.training.row_count`). Grep for `model.training.get` and `model.training[` and update.
- `ModelArtifact.warnings` → `ModelArtifactV1.warnings` (exists).
- `ModelArtifact.ensemble_type`, `.base_models`, `.weights`, `.voting`, `.threshold` — these came from `model_payload`. Add accessors to `ModelArtifactV1` if consumers use them, or read from `model_payload`. Grep: `rg -n "\.ensemble_type|\.base_models|\.weights|\.voting|\.threshold" cardre/ tests/`. If unused outside ensemble adapters, skip.
- `ModelArtifact.feature_contract`, `.source_variables`, `.calibration`, `.has_explicit_intercept` — `ModelArtifactV1` has `feature_contract` as a field. `source_variables`/`calibration`/`has_explicit_intercept` may not exist; grep for consumers and add accessors or read from the artifact fields.

Delete the `ModelArtifact` class from `cardre/_evidence/models/model.py` (lines 27-131). Remove it from `cardre/_evidence/models/__init__.py` exports.

### Step 5 — Remove `_raw` from `ModelArtifactV1`

In `cardre/modeling/schema.py`:
- Delete lines 220-222 (the comment + `_raw` field):
  ```python
  # Raw payload for backward compatibility — populated by from_dict.
  # Consumers migrate off _raw in PR3a/3b/3c.
  _raw: dict[str, Any] = field(default_factory=dict, repr=False)
  ```
- Delete the `_raw`-backed properties `base_odds` (lines 248-257), `bad_class_label` (lines 260-261), `feature_strategy` (lines 264-265). Before deleting, grep for consumers:
  ```bash
  rg -n "\.base_odds|\.bad_class_label|\.feature_strategy" cardre/ tests/
  ```
  If consumers exist, add explicit fields to `ModelArtifactV1` (e.g. `base_odds: float = 50.0`, `bad_class_label: str = ""`, `feature_strategy: str = ""`) and populate them in `from_dict` from the corresponding keys. If `base_odds` is only read by score-scaling consumers, check whether `ModelArtifactV1` should carry it — likely it belongs on the scorecard, not the model artifact; if so, remove the consumers' use.
- Delete `_raw=data` in `from_dict` (line 316).

### Step 6 — Remove `_raw` from `ScoreScaling`

In `cardre/_evidence/models/model.py` (`ScoreScaling`, lines 133-212):
- Remove the `_raw` field (line 144) and its assignment (line 174: `_raw=data,`).
- Promote the `_raw`-backed properties to explicit typed fields populated in `from_json`:
  ```python
  @dataclass(frozen=True)
  class ScoreScaling:
      base_score: int = 600
      base_odds: float = 50.0
      points_to_double_odds: int = 20
      factor: float = 0.0
      offset: float = 0.0
      score_direction: str = "higher_is_lower_risk"
      rounding: str = "nearest_integer"
      min_score: int = 0
      max_score: int = 0
      source_artifact_id: str = ""
      base_odds_text: str = "50:1"
      intercept: float = 0.0
      has_explicit_intercept: bool = False
      base_points: float | int | None = None
      target_column: str = ""
      attributes: list = field(default_factory=list)
  ```
  In `from_json`, populate all from explicit keys:
  - `base_odds_text = str(data.get("base_odds", "50:1"))`
  - `intercept = float(data.get("intercept", 0.0))`
  - `has_explicit_intercept = "intercept" in data`
  - `base_points = data.get("base_points")`
  - `target_column = str(data.get("target_column", ""))`
  - `attributes = [dict(v) for v in data.get("attributes", []) if isinstance(v, dict)]`
- Replace the `_raw`-backed properties (lines 186-209) with direct field access (the fields now exist). Delete the `@property` blocks for `base_odds_text`, `intercept`, `has_explicit_intercept`, `base_points`, `target_column`, `attributes`.
- Replace `to_dict` (line 211) to rebuild from typed fields (or delete it if no consumer uses it — grep first).

### Step 7 — Remove `_raw` from `ScoredDataset`

In `cardre/_evidence/models/apply.py`:
- Remove the `_raw` field (line 64) and its assignment.
- Grep for `_raw`-backed accessors on `ScoredDataset`; promote to explicit fields or delete if unused.

### Step 8 — Update tests

- `tests/test_evidence_adapters.py` parity tests: any fixture that supplies list-form `coefficients` or legacy keys (`metrics`, `psi`, `tables`, `score`) must be updated to the canonical form.
- `tests/test_validation_metrics_node.py`, `tests/test_validation_failure_evidence.py`: update fixtures/payloads to canonical keys (`roles`, `stability`, `cutoff_tables`, `score_cutoff`).
- `tests/test_model_apply_boundary.py`, `tests/test_logistic_regression_known_input.py`, `tests/test_logistic_regression_validation.py`: update model-artifact fixtures to dict-form coefficients, required `features`/`model_family`.
- `tests/test_golden_fixtures_roundtrip.py`: update golden fixtures if they carry list-form coefficients or `_raw`-dependent fields.
- `tests/test_build_summary_node.py` / `test_build_summary_report.py`: if they access `model.training.get(...)`, switch to `model.training.<field>` (the `TrainingMetadata` dataclass).

### Step 9 — Add guard tests

Add to `tests/test_canonical_contract.py`:
```python
def test_model_artifact_rejects_list_coefficients():
    from cardre.modeling.schema import ModelArtifactV1
    with pytest.raises((TypeError, ValueError)):
        ModelArtifactV1.from_dict({
            "coefficients": [{"variable_name": "x", "coefficient": 1.0}],
            "features": ["x"], "model_family": "logistic_regression",
            "target_column": "y", "target_event_value": "bad",
            "class_mapping": {"0": "good", "1": "bad"},
            "feature_contract": {"features": ["x"]}, "training": {"row_count": 10},
        })

def test_validation_metrics_rejects_legacy_keys():
    from cardre._evidence.models.validation import ValidationMetrics
    with pytest.raises((KeyError, TypeError)):
        # legacy 'metrics' key must not be accepted
        ValidationMetrics.from_json({"metrics": {"train": {}}})
```

## Verification

```bash
. .venv/bin/activate
rg -n "_raw" cardre/_evidence/models/ cardre/modeling/schema.py
# Zero matches (no _raw fields remain in evidence/modeling models).
rg -n "data\.get\(\"[a-z_]+\", data\.get\(" cardre/
# Zero dual-key fallbacks.
rg -n "from cardre._evidence.models.model import ModelArtifact|from cardre._evidence.models import ModelArtifact" cardre/ tests/
# Zero matches (ModelArtifact class deleted).
ruff check --fix
pytest tests/test_evidence_adapters.py tests/test_validation_metrics_node.py \
       tests/test_validation_failure_evidence.py tests/test_model_apply_boundary.py \
       tests/test_logistic_regression_known_input.py tests/test_logistic_regression_validation.py \
       tests/test_golden_fixtures_roundtrip.py tests/test_build_summary_node.py \
       tests/test_canonical_contract.py -q
make preflight
scripts/pr-gate.sh
```

## Definition of done

- [ ] No `_raw` fields in `cardre/_evidence/models/` or `cardre/modeling/schema.py`.
- [ ] No `data.get(a, data.get(b))` dual-key fallbacks in `cardre/`.
- [ ] Validation writer emits only `roles`, `stability`, `cutoff_tables`, `score_cutoff`.
- [ ] `ModelArtifact` class deleted; `ModelArtifactV1` is the single parser.
- [ ] `ModelArtifactV1.from_dict` rejects list-form coefficients.
- [ ] `ModelArtifactV1` requires `features` and `model_family`.
- [ ] `ScoreScaling` has explicit typed fields; no `_raw`.
- [ ] Guard tests added.
- [ ] `ruff check` clean; `make preflight` green; PR gate green.

## Failure mode

- **`model.training.get(...)` AttributeError:** `TrainingMetadata` is a dataclass, not a dict. Update consumers to `model.training.row_count`, `model.training.converged`, etc.
- **`ModelArtifact` import error:** a consumer still imports the deleted class. Switch the import to `ModelArtifactV1` from `cardre.modeling.schema`.
- **Adapter parity test fails:** the test fixture supplied list-form coefficients. Update the fixture to dict form.
- **`has_explicit_intercept` consumer breaks:** the property now reads from a typed field. Ensure `from_json` populates it from `"intercept" in data` before the property is removed.