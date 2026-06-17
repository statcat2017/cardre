# Platt/Holdout Calibration Node — Implementation Plan

> Derived from: Platt (1999), Niculescu-Mizil & Caruana (2005), Zadrozny & Elkan (2002).
> Aligned with Cardre's two-stream pathway: calibrated in build stream, applied in validate stream.

## 1. Problem

The algo-risk-credit skill states:
> "Calibration: predicted PD matches actual default rates. A model with AUC=0.85 but predicted PD 2x actual default rate will cause systematic over/under-pricing. Need BOTH properties."

Currently `LogisticRegressionNode` outputs raw sklearn probabilities. These are reasonably calibrated for logistic regression but not guaranteed — especially with:
- Class imbalance (2-5% default rate, common in credit)
- Regularization (L1/L2 penalties shift probability scales)
- SMOTE/resampling (artificially balanced training sets shift priors)
- Non-linear models (GBDT/RF probabilities are notoriously uncalibrated)

## 2. Pipeline Position

Placed between `logistic-regression` and `score-scaling` in the build stream.

Calibration must happen **before** score scaling because score scaling converts log-odds to points — if the log-odds are miscalibrated, the score-point mapping is wrong.

```
Build stream:
  ... → logistic-regression → calibrate-probabilities → score-scaling → ...
                                    ^ NEW
Validate stream:
  ... → apply-model → ...   (no change — ApplyModelNode already uses calibrated model)
```

## 3. Node Specification

### `CalibrateProbabilitiesNode`

| Attribute | Value |
|-----------|-------|
| `node_type` | `cardre.calibrate_probabilities` |
| `version` | `1` |
| `category` | `fit` (fits calibrator on holdout) |
| `input_roles` | `["train", "test", "definition", "model"]` |
| `output_roles` | `["model"]` |

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `method` | str | `"platt"` | `"platt"` (logistic sigmoid) or `"isotonic"` (non-parametric step) |
| `calibration_sample` | str | `"test"` | Which role to calibrate on: `"test"` (recommended), `"train"` (fallback, risks overfitting) |
| `cross_validation` | bool | `True` | Use 5-fold CV on the calibration sample to avoid overfitting the calibrator |
| `cv_folds` | int | `5` | Number of CV folds when `cross_validation=True` |
| `min_probability` | float | `0.001` | Floor for calibrated probabilities (avoid zero) |
| `max_probability` | float | `0.999` | Ceiling for calibrated probabilities (avoid one) |

**Behavior:**

1. Read `MODELLING_METADATA` for target definition
2. Read scored dataset for the `calibration_sample` role (must contain `predicted_bad_probability` column and target)
3. If `cross_validation=True`: fit calibrator on each fold's out-of-fold predictions, ensemble by averaging
4. If `method="platt"`: fit `sklearn.isotonic.SigmoidCalibration` (logistic regression on log-odds)
5. If `method="isotonic"`: fit `sklearn.isotonic.IsotonicRegression` with `out_of_bounds="clip"`
6. Validate calibration quality:
   - Compute 10-bin calibration error: `mean(|avg_predicted - actual_bad_rate|)`
   - Compute max per-bin deviation
   - Compute Hosmer-Lemeshow chi-squared statistic (p-value < 0.05 warns of poor fit)
7. Wrap the calibrator + original model into a new model artifact:
   - Preserve all original `ModelArtifactV1` fields
   - Add `calibration` block with method, params, calibrator reference, calibration metrics
8. Write updated `cardre.model_artifact.v1` artifact (role: `"model"`)
9. Write calibration diagnostics report artifact (role: `"report"`)

**Calibration metrics in diagnostics report:**

```json
{
  "schema_version": "cardre.calibration_report.v1",
  "method": "platt",
  "calibrated_on": "test",
  "cross_validated": true,
  "cv_folds": 5,
  "calibration_error": 0.012,
  "max_bin_deviation": 0.038,
  "hosmer_lemeshow": {"chi2": 12.4, "p_value": 0.19, "df": 8, "passed": true},
  "bins": [
    {"bin": 0, "count": 200, "avg_predicted": 0.02, "actual_bad_rate": 0.025},
    {"bin": 1, "count": 200, "avg_predicted": 0.06, "actual_bad_rate": 0.055},
    ...
  ],
  "pre_calibration_bins": [
    {"bin": 0, "count": 200, "avg_predicted": 0.015, "actual_bad_rate": 0.03},
    ...
  ],
  "warnings": []
}
```

**Validation errors:**
- If `calibration_sample` role not found: raise
- If `predicted_bad_probability` missing from scored data: raise
- If fewer than 100 rows in calibration sample: raise (too small for reliable calibration)

**Warnings:**
- Calibration error > 0.05: warn "high calibration error"
- Hosmer-Lemeshow p < 0.05: warn "significant calibration deviation"
- Isotonic regression on < 1000 rows: warn "small sample for non-parametric calibration"

## 4. Model Artifact Changes

The `cardre.model_artifact.v1` JSON gains an optional `calibration` block:

```json
{
  "schema_version": "cardre.model_artifact.v1",
  "model_family": "logistic_regression",
  "calibration": {
    "method": "platt",
    "cross_validated": true,
    "params": {},
    "calibrator_artifact_id": "art_xxxx",
    "calibration_report_artifact_id": "art_yyyy",
    "calibration_error": 0.012,
    "max_bin_deviation": 0.038,
    "calibrator_format": "joblib"
  },
  "estimator": {
    "artifact_id": "art_zzzz",
    "estimator_format": "joblib"
  },
  ...
}
```

**Estimator reference** in the model artifact now points to the calibrator (joblib-serialized) rather than the raw model. The `ApplyModelNode` must detect the `calibration` block and:

- If present: load the calibrator, apply `predict_proba` from the raw estimator, then transform through the calibrator
- If absent: use `predict_proba` directly (current behavior, unchanged)

## 5. `ApplyModelNode` Changes

In `validate/apply.py`, the `ApplyModelNode.run()` method needs a new path:

```python
# After loading estimator and computing raw probabilities:
if model_calibration := model_artifact.get("calibration"):
    calibrator_id = model_calibration["calibrator_artifact_id"]
    calibrator_bytes = store.read_artifact_bytes(calibrator_id)
    calibrator = joblib.load(BytesIO(calibrator_bytes))
    y_prob_raw = np.array([[1 - p, p] for p in y_prob])  # shape (n, 2)
    y_prob_calibrated = calibrator.predict_proba(y_prob_raw)
    y_prob = [p[1] for p in y_prob_calibrated]  # bad probability
```

This ensures all downstream nodes (validation metrics, cutoff analysis, threshold optimization) receive calibrated probabilities transparently.

## 6. Evidence Kinds

### New `EvidenceKind` entry

```python
CALIBRATION_REPORT = "calibration_report"
```

### New schema constant

```python
SCHEMA_CALIBRATION_REPORT = "cardre.calibration_report.v1"
```

### Evidence profile

```python
EvidenceKind.CALIBRATION_REPORT: _Profile(
    expected_roles={"report"},
    expected_artifact_types={"report"},
    schema_version=SCHEMA_CALIBRATION_REPORT,
    required_keys={"method", "calibration_error", "bins"},
),
```

## 7. Files to Create or Modify

| File | Action | Notes |
|------|--------|-------|
| `cardre/nodes/calibrate.py` | **CREATE** | `CalibrateProbabilitiesNode` (~250 lines) |
| `cardre/nodes/__init__.py` | **MODIFY** | Import + re-export `CalibrateProbabilitiesNode` |
| `cardre/registry.py` | **MODIFY** | Register node in `_register_proof_nodes()` |
| `cardre/evidence.py` | **MODIFY** | +1 `EvidenceKind`, +1 schema constant, +1 profile entry |
| `cardre/nodes/validate/apply.py` | **MODIFY** | `ApplyModelNode`: detect calibration block, apply calibrator |
| `cardre/modeling/builders.py` | **MODIFY** | `build_model_artifact()`: accept optional calibration metadata |
| `sidecar/proof_pathway.py` | **MODIFY** | Insert `calibrate-probabilities` step between `logistic-regression` and `score-scaling` |
| `tests/test_calibrate.py` | **CREATE** | Unit + integration tests |

## 8. Testing Strategy

### Unit tests (6 tests)

1. `test_platt_calibration_improves_calibration_error`: Synthetic miscalibrated data -> calibration error decreases
2. `test_isotonic_calibration_non_decreasing`: Isotonic fit is monotonic
3. `test_platt_vs_isotonic_consistency`: Both methods accept same input format
4. `test_calibration_validation_errors`: Missing columns, too-few rows
5. `test_cross_validation_ensemble`: CV produces different calibrator than non-CV
6. `test_calibration_does_not_change_auc`: AUC is rank-order metric, calibration does not change rank order (verify within tolerance)

### Integration tests (4 tests)

7. `test_calibrated_model_apply`: `CalibrateProbabilitiesNode` -> `ApplyModelNode` pipeline produces calibrated probabilities
8. `test_full_pipeline_with_calibration`: Full scorecard pathway with calibration step
9. `test_uncalibrated_fallback`: Model artifact without calibration block -> ApplyModelNode behaves as before
10. `test_calibration_metrics_report`: Calibration report artifact has expected schema and values

## 9. Implementation Sequence

| Phase | What | Effort | Depends on |
|-------|------|--------|------------|
| 1 | Evidence types + schema constant | Tiny | — |
| 2 | `CalibrateProbabilitiesNode` core (Platt method) | Medium | Phase 1 |
| 3 | Isotonic method + cross-validation | Small | Phase 2 |
| 4 | `ApplyModelNode` calibration detection | Small | Phase 2 |
| 5 | Pathway registration | Tiny | Phase 2 |
| 6 | Tests | Medium | Phase 2-5 |

**MVP:** Platt calibration, no CV, pathway insert. Ships as optional step.
