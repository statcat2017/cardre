# Phase 2 Technical Specification

This specification defines the implementation contracts for Cardre Phase 2:
Minimum Viable Scorecard Engine. The immediate implementation target is Phase 2A,
the binning/WOE spine. Phase 2B and Phase 2C remain explicit follow-up slices.

Follow the existing architecture:

- SQLite stores metadata only.
- Parquet stores tabular artifacts.
- JSON stores definitions, reports, model artifacts, and manifests.
- The executor owns role enforcement and run-step evidence.
- Historical runs and artifacts are immutable.
- `is_stale` remains computed, not stored.

## Non-Goals

- Do not build a full GUI editor in Phase 2.
- Do not add freeform DAG editing.
- Do not export raw datasets by default.
- Do not allow fitting nodes to read `test` or `oot` artifacts.
- Do not store tabular data or blobs in SQLite.
- Do not implement model fitting, score scaling, role-based scoring, validation
  metrics, or cutoff analysis in Phase 2A.

## Phase 2A Green Path

Phase 2A must produce a complete auditable run through final WOE/IV, but it does
not need a model or scorecard.

Minimum green path:

```text
German Credit import
-> Define Modelling Metadata
-> Apply Exclusions
-> Profile Dataset
-> Validate Binary Target
-> Development Sample Definition
-> Train/Test/OOT Split with recorded strategy
-> Explicit Missing/Outlier Treatment, or pass-through
-> Automatic Fine Classing on train only
-> Initial WOE/IV Diagnostics
-> Variable Clustering
-> Variable Selection
-> Manual Binning pass-through plus JSON overrides
-> Final WOE/IV Calculation
-> Technical Manifest Stub
```

Phase 2B adds WOE transform, logistic regression, score scaling, and a build
summary report. Phase 2C adds apply-to-role scoring, validation metrics, cutoff
analysis, and final manifest export.

## Dependencies

Required Phase 2 dependency additions:

- `scikit-learn` for logistic regression and AUC if accepted.
- Optional: `numpy` if not already pulled transitively and direct numeric arrays
  are needed.

Existing dependencies remain:

- `polars`
- `pyarrow`
- `pydantic`
- `fastapi`
- `uvicorn`
- `pytest`

Avoid `pandas` unless a specific importer requires it. Core transforms should use
Polars.

## Module Layout

The current `cardre/nodes.py` can host the first implementation, but Phase 2 will
add enough code that splitting by domain is preferred once the first helper layer
exists.

Recommended layout:

```text
cardre/
  artifacts.py          # shared artifact writing/loading helpers
  scorecard/
    __init__.py
    binning.py          # bin definition structures and bin assignment helpers
    woe.py              # WOE/IV calculations and zero-cell policy
    selection.py        # clustering and variable selection helpers
    model.py            # logistic regression helpers
    scaling.py          # score scaling helpers
    metrics.py          # AUC/Gini/KS/calibration/cutoff helpers
  nodes.py              # registered NodeType wrappers, or thin imports from nodes/*
```

Keep public node identifiers stable even if implementation files move.

## Shared Artifact Helpers

Add helpers that create and register artifacts consistently.

### JSON Artifact Helper

Suggested signature:

```python
def write_json_artifact(
    store: ProjectStore,
    *,
    artifact_type: str,
    role: str,
    stem: str,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    directory: str = "artifacts",
) -> ArtifactRef:
    ...
```

Requirements:

- Serialize with sorted keys and stable separators.
- Compute `logical_hash` using canonical JSON.
- Compute `physical_hash` from written bytes.
- Write under `artifacts/` unless the caller explicitly uses `exports/`.
- Register the artifact in SQLite.
- Return `ArtifactRef`.

### Parquet Artifact Helper

Suggested signature:

```python
def write_parquet_artifact(
    store: ProjectStore,
    *,
    artifact_type: str,
    role: str,
    stem: str,
    frame: pl.DataFrame,
    metadata: dict[str, Any] | None = None,
    directory: str = "datasets",
) -> ArtifactRef:
    ...
```

Requirements:

- Use `table_logical_hash` for logical hash.
- Write deterministic Parquet as far as Polars/Arrow allows.
- Include row count, column count, and schema in metadata.
- Register the artifact in SQLite.

## Node Contract Requirements

Every new node type must define:

- `node_type`
- `version`
- `category`
- `input_roles`
- `output_roles`
- deterministic `run(context)` implementation

Node-level input contracts are mandatory. Do not rely on category-only filtering
for Phase 2 nodes.

Each node must declare the exact artifact roles it accepts and whether each role
is tabular data or non-tabular evidence. The executor must use those declarations
to select node inputs, then apply separate leakage rules.

Hard leakage rule:

- Any node that fits, learns, selects, ranks, clusters, refines fitted modelling
  definitions, or computes WOE/IV must not consume `test` or `oot` tabular
  artifacts.
- Such nodes may consume non-tabular `definition` and `report` artifacts produced
  upstream, as long as those artifacts were themselves produced without test/OOT
  leakage.
- Apply nodes may consume `train`, `test`, and `oot` tabular artifacts plus fitted
  definitions, but must not update fitted definitions.
- Transform nodes must not be used as a workaround for leakage-sensitive learning.
  If a node learns parameters, it is a `fit` node.

Recommended optional fields:

- `display_name`
- `description`
- `params_schema`
- `output_summary_schema`

Every node output fingerprint must include or be completed by the executor with:

- `plan_version_id`
- `step_id`
- `node_type`
- `node_version`
- `params_hash`
- `parent_run_step_ids`
- `input_artifact_logical_hashes`
- `output_artifact_logical_hashes`
- runtime metadata already required by Phase 1

## Artifact Roles And Types

Use these roles consistently:

- `input`: imported source dataset.
- `train`: training dataset artifact.
- `test`: test dataset artifact.
- `oot`: out-of-time dataset artifact.
- `definition`: reusable fitted/configured definition.
- `report`: diagnostic or governance report.
- `model`: model coefficients/metadata.
- `scorecard`: finalized scorecard definition.
- `manifest`: technical export manifest.

Role names identify artifacts, not whether a node may use them. Permission is the
combination of node-level input contract plus leakage rules.

Use these artifact types consistently:

- `dataset`
- `definition`
- `report`
- `model`
- `scorecard`
- `manifest`

## Fixed Phase 2A Pathway

Register this pathway as the default scorecard plan for new projects during the
Phase 2A implementation.

| Position | Step ID | Node Type | Category | Parents |
|---:|---|---|---|---|
| 0 | `import` | `cardre.import_dataset` | `transform` | none |
| 1 | `define-metadata` | `cardre.define_modelling_metadata` | `transform` | `import` |
| 2 | `apply-exclusions` | `cardre.apply_exclusions` | `transform` | `import`, `define-metadata` |
| 3 | `profile` | `cardre.profile_dataset` | `transform` | `apply-exclusions` |
| 4 | `validate-target` | `cardre.validate_binary_target` | `transform` | `apply-exclusions`, `define-metadata` |
| 5 | `sample-definition` | `cardre.development_sample_definition` | `transform` | `apply-exclusions`, `define-metadata` |
| 6 | `split` | `cardre.split_train_test_oot` | `transform` | `apply-exclusions`, `sample-definition` |
| 7 | `explicit-missing-outlier-treatment` | `cardre.explicit_missing_outlier_treatment` | `apply` | `split` |
| 8 | `fine-classing` | `cardre.fine_classing` | `fit` | `explicit-missing-outlier-treatment`, `define-metadata` |
| 9 | `initial-woe-iv` | `cardre.calculate_woe_iv` | `selection` | `explicit-missing-outlier-treatment`, `fine-classing`, `define-metadata` |
| 10 | `variable-clustering` | `cardre.variable_clustering` | `selection` | `explicit-missing-outlier-treatment`, `initial-woe-iv` |
| 11 | `variable-selection` | `cardre.variable_selection` | `selection` | `initial-woe-iv`, `variable-clustering` |
| 12 | `manual-binning` | `cardre.manual_binning` | `refinement` | `fine-classing`, `variable-selection` |
| 13 | `final-woe-iv` | `cardre.calculate_woe_iv` | `selection` | `explicit-missing-outlier-treatment`, `manual-binning`, `define-metadata` |
| 14 | `technical-manifest-stub` | `cardre.technical_manifest_export` | `transform` | `define-metadata`, `sample-definition`, `split`, `explicit-missing-outlier-treatment`, `fine-classing`, `variable-selection`, `manual-binning`, `final-woe-iv` |

Phase 2B pathway extension:

- `woe-transform-train`: `cardre.woe_transform_train`, `fit`.
- `logistic-regression`: `cardre.logistic_regression`, `fit`.
- `score-scaling`: `cardre.score_scaling`, `fit`.
- `build-summary-report`: `cardre.build_summary_report`, `fit`.

Phase 2C pathway extension:

- `apply-woe`: `cardre.apply_woe_mapping`, `apply`.
- `apply-model`: `cardre.apply_model`, `apply`.
- `validation-metrics`: `cardre.validation_metrics`, `apply`.
- `cutoff-analysis`: `cardre.cutoff_analysis`, `apply`.
- `technical-manifest`: extended `cardre.technical_manifest_export`.

Implementation blocker: before adding the Phase 2A pathway, replace category-only
role filtering with explicit node-level input contracts. The current category map
cannot safely support mixed inputs such as train datasets plus definition/report
artifacts.

## Node Specifications

### `cardre.define_modelling_metadata`

Category: `transform`

Inputs:

- Imported or filtered dataset artifact.

Params:

```json
{
  "target_column": "credit_risk_class",
  "good_values": ["1"],
  "bad_values": ["2"],
  "indeterminate_values": [],
  "population": "",
  "product": "",
  "segment": "",
  "observation_window": null,
  "performance_window": null
}
```

Outputs:

- JSON `definition` artifact with role `definition`.

Validation:

- `target_column` must exist in the input dataset.
- Good and bad value sets must be non-empty and disjoint.

### `cardre.apply_exclusions`

Category: `transform`

Inputs:

- Dataset artifact.
- Optional modelling metadata definition.

Params:

```json
{
  "rules": [
    {
      "column": "age_years",
      "operator": ">=",
      "value": 18,
      "reason": "Adult lending population"
    }
  ]
}
```

Supported operators:

- `==`
- `!=`
- `<`
- `<=`
- `>`
- `>=`
- `in`
- `not_in`
- `is_null`
- `is_not_null`

Outputs:

- Filtered Parquet dataset with inherited role.
- JSON report with row counts and per-rule exclusion counts.

Validation:

- Every rule requires a non-empty reason.
- Unknown columns or unsupported operators fail the step.

### `cardre.development_sample_definition`

Category: `transform`

Inputs:

- Dataset artifact.
- Modelling metadata definition.

Params:

```json
{
  "sample_method": "full_population",
  "weight_column": null,
  "population_bad_rate": null,
  "prior_probability_adjustment": null
}
```

Outputs:

- JSON `definition` artifact.

Validation:

- If `weight_column` is set, it must exist and be numeric.

### `cardre.split_train_test_oot`

Category: `transform`

Inputs:

- Filtered input dataset artifact.
- Optional modelling metadata definition.
- Optional development sample definition. In Phase 2A, split must at least record
  this evidence in its report even if advanced sample weighting is not applied.

Params:

```json
{
  "strategy": "random_stratified",
  "train_fraction": 0.6,
  "test_fraction": 0.2,
  "oot_fraction": 0.2,
  "target_column": "credit_risk_class",
  "role_column": null,
  "random_seed": 42
}
```

Supported Phase 2A strategies:

- `random_stratified`: deterministic random assignment stratified by target.
- `preassigned_role_column`: consumes an existing role column with values that
  map to `train`, `test`, and `oot`.

Deferred strategy:

- `date_based_oot`: required for production credit-risk projects with real time
  windows, but optional until a fixture with a usable date column is available.

Outputs:

- Parquet dataset artifact with role `train`.
- Parquet dataset artifact with role `test`.
- Parquet dataset artifact with role `oot`.
- JSON split report with exact strategy, seed, fractions, role counts, target
  rates by role, and, for preassigned roles, source role mappings.

Validation:

- Role assignments must be deterministic for identical input and params.
- `random_stratified` requires a binary target column.
- `preassigned_role_column` requires every row to map to exactly one valid role.
- Output artifact role metadata is immutable after registration.

### `cardre.explicit_missing_outlier_treatment`

Category: `apply`

Inputs:

- Role-tagged split datasets.

Params:

```json
{
  "imputations": {
    "column_name": {"value": 0, "reason": "Explicit analyst-defined fill"}
  },
  "caps": {
    "column_name": {"value": 99999, "reason": "Known operational maximum"}
  },
  "floors": {
    "column_name": {"value": 0, "reason": "Known non-negative quantity"}
  }
}
```

Outputs:

- Treated Parquet artifacts preserving input roles.
- In the normal Phase 2A pathway, this means one treated `train` artifact, one
  treated `test` artifact, and one treated `oot` artifact.
- JSON treatment definition/report artifact.

Validation:

- Explicit imputation and cap/floor configs must reference existing columns.
- Numeric operations on non-numeric columns fail.
- Every configured treatment requires a reason.
- Phase 2A treatments are explicit-only. The node must not learn means, medians,
  modes, quantiles, or caps from the combined train/test/OOT inputs.

Future learned treatment must be split into:

- `cardre.fit_missing_outlier_treatment`, category `fit`, consumes `train` only
  and produces a treatment definition.
- `cardre.apply_missing_outlier_treatment`, category `apply`, consumes
  train/test/OOT plus the treatment definition.

### `cardre.fine_classing`

Category: `fit`

Inputs:

- `train` dataset.
- Modelling metadata definition.

Params:

```json
{
  "max_bins": 20,
  "min_bin_fraction": 0.05,
  "missing_policy": "separate_bin",
  "max_categorical_levels": 50,
  "exclude_columns": []
}
```

Outputs:

- JSON bin-definition artifact with role `definition`.

Bin definition shape:

```json
{
  "variables": [
    {
      "variable": "duration_months",
      "kind": "numeric",
      "bins": [
        {
          "bin_id": "duration_months_bin_001",
          "label": "(-inf, 12]",
          "lower": null,
          "upper": 12,
          "lower_inclusive": false,
          "upper_inclusive": true,
          "categories": null,
          "is_missing_bin": false,
          "row_count": 100,
          "good_count": 80,
          "bad_count": 20
        }
      ]
    }
  ],
  "warnings": []
}
```

Validation:

- Target column is excluded from candidates.
- `max_bins >= 2`.
- `0 < min_bin_fraction < 1`.

### `cardre.calculate_woe_iv`

Category: `selection`

Inputs:

- `train` dataset.
- Bin-definition artifact.
- Modelling metadata definition.

Params:

```json
{
  "zero_cell_policy": "block",
  "smoothing": null,
  "purpose": "initial"
}
```

Event convention and formulas:

- `event = bad`.
- `non_event = good`.
- `event_distribution = bad_count / total_bad_count`.
- `non_event_distribution = good_count / total_good_count`.
- `woe = ln(non_event_distribution / event_distribution)`.
- `iv_component = (non_event_distribution - event_distribution) * woe`.
- `iv = sum(iv_component)` per variable.

Smoothing policy:

- Default `zero_cell_policy` is `block`.
- If smoothing is enabled, use additive smoothing consistently:
  `smoothed_good_count = good_count + alpha` and
  `smoothed_bad_count = bad_count + alpha`.
- Smoothing config must include `method = "additive"`, `alpha > 0`, affected
  bins in the output report, and a user rationale.

Outputs:

- Parquet bin-level WOE table with role `report`.
- Parquet IV ranking table with role `report`.
- Optional JSON summary report.

WOE table columns:

- `variable`
- `bin_id`
- `label`
- `row_count`
- `good_count`
- `bad_count`
- `good_distribution`
- `bad_distribution`
- `woe`
- `iv_component`

IV table columns:

- `variable`
- `iv`
- `bin_count`
- `zero_cell_count`
- `warning_count`

Validation:

- If `zero_cell_policy == "block"`, zero good/bad bins fail final WOE use.
- If smoothing is configured, method, value, and rationale are required.
- The WOE sign convention must be recorded in the output summary so downstream
  model and scorecard artifacts are interpretable.

### `cardre.variable_clustering`

Category: `selection`

Inputs:

- `train` dataset.
- IV ranking report.

Params:

```json
{
  "correlation_threshold": 0.7,
  "candidate_limit": 50
}
```

Outputs:

- JSON or Parquet clustering report with role `report`.
- If a robust correlation basis is not available in Phase 2A, emit singleton
  clusters for all IV candidates and record a warning that clustering was
  pass-through.

Validation:

- Correlation threshold must be between 0 and 1.

### `cardre.variable_selection`

Category: `selection`

Inputs:

- IV ranking report.
- Clustering report.

Params:

```json
{
  "min_iv": 0.02,
  "max_variables": 15,
  "manual_includes": [],
  "manual_excludes": []
}
```

Outputs:

- JSON selected-variable definition with role `definition`.

Selection shape:

```json
{
  "selected": [
    {
      "variable": "duration_months",
      "reason": "IV above threshold and strongest in cluster"
    }
  ],
  "rejected": [
    {
      "variable": "credit_amount",
      "reason": "Lower IV than selected correlated variable"
    }
  ]
}
```

Validation:

- Manual includes/excludes require reasons if exposed in params.
- Output must include a reason for every included and excluded candidate.

### `cardre.manual_binning`

Category: `refinement`

Inputs:

- Automatic bin-definition artifact.
- Selected-variable definition.

Params:

```json
{
  "overrides": [
    {
      "variable": "duration_months",
      "action": "merge_bins",
      "source_bin_ids": ["duration_months_bin_003", "duration_months_bin_004"],
      "new_label": "Medium duration",
      "reason": "Merged sparse adjacent bins"
    }
  ]
}
```

Supported actions:

- `merge_bins`
- `group_categories`
- `isolate_missing`
- `isolate_special_value`

Outputs:

- Refined bin-definition artifact with role `definition`.

Validation:

- Every override requires a reason.
- Numeric merges must use adjacent source bins.
- All source bin IDs must exist.

### `cardre.woe_transform_train`

Category: `fit`

Inputs:

- `train` dataset.
- Refined bin definitions.
- Final WOE table/report.

Outputs:

- WOE-transformed train Parquet dataset with role `train`.
- Optional JSON transform report.

Dataset columns:

- target column.
- selected variable WOE columns named `{variable}_woe`.
- optional source row ID if available.

Validation:

- All selected variables must have final WOE mappings.

### `cardre.apply_woe_mapping`

Category: `apply`

Inputs:

- Role-tagged train/test/OOT datasets.
- Refined bin definitions.
- Final WOE table/report.

Outputs:

- WOE-transformed Parquet datasets preserving role.
- JSON fallback usage report.

Validation:

- No WOE values are recalculated from validation roles.
- Unseen category fallback policy is recorded.

### `cardre.logistic_regression`

Category: `fit`

Inputs:

- WOE-transformed train dataset.
- Modelling metadata definition.

Params:

```json
{
  "penalty": null,
  "C": 1.0,
  "max_iter": 1000,
  "solver": "lbfgs",
  "random_seed": 42
}
```

Outputs:

- JSON model artifact with role `model`.

Model shape:

```json
{
  "target_column": "credit_risk_class",
  "features": ["duration_months_woe"],
  "intercept": -0.12,
  "coefficients": {"duration_months_woe": 0.45},
  "class_mapping": {"good": "1", "bad": "2"},
  "training": {
    "row_count": 600,
    "converged": true,
    "iterations": 12
  },
  "warnings": []
}
```

Validation:

- At least one selected feature is required.
- Convergence failure is recorded and may fail the step depending on severity.

### `cardre.score_scaling`

Category: `fit`

Inputs:

- Model artifact.
- Refined bin definitions.
- Final WOE table/report.

Params:

```json
{
  "base_score": 600,
  "base_odds": 50.0,
  "points_to_double_odds": 20,
  "higher_score_is_lower_risk": true
}
```

Outputs:

- JSON scorecard artifact with role `scorecard`.
- Optional CSV scorecard artifact.

Validation:

- `base_odds > 0`.
- `points_to_double_odds > 0`.

### `cardre.build_summary_report`

Category: `fit`

Inputs:

- Scorecard artifact.
- Model artifact.
- Final WOE/IV reports.

Outputs:

- JSON build summary report for model, scorecard, and characteristic evidence.

Do not call this a gains report unless it consumes scored observations. Gains,
lift, and cutoff reports belong after `apply_model` in Phase 2C.

### `cardre.apply_model`

Category: `apply`

Inputs:

- WOE-transformed role-tagged datasets.
- Model artifact.
- Scorecard artifact.

Outputs:

- Prediction/score Parquet datasets preserving role.

Prediction columns:

- target column.
- `predicted_bad_probability`.
- `score`.
- optional row ID.

Probability orientation:

- `predicted_bad_probability` is always the probability of the configured bad
  class from modelling metadata.
- The implementation must not rely on scikit-learn class ordering implicitly.
- The model artifact must store the bad-class label and the coefficient/intercept
  orientation used to calculate bad probability.
- A parity test must assert that persisted coefficients, intercept, and feature
  order reproduce node output `predicted_bad_probability` and `score` for a tiny
  fixture.

Validation:

- Feature order must match the model artifact.
- Missing scorecard/model features fail clearly.

### `cardre.validation_metrics`

Category: `apply`

Inputs:

- Prediction/score artifacts by role.
- Modelling metadata definition.

Outputs:

- JSON metrics report with role `report`.
- Optional Parquet metric tables.

Required metrics:

- AUC.
- Gini.
- KS.
- Calibration summary.
- Score distribution by role.

Optional Phase 2 metric:

- PSI train-vs-test and train-vs-OOT.

### `cardre.cutoff_analysis`

Category: `apply`

Inputs:

- Prediction/score artifacts.
- Validation metrics report.

Params:

```json
{
  "cutoffs": [],
  "band_count": 20
}
```

Outputs:

- JSON or Parquet cutoff report with approval rate, bad rate, and capture rate by
  role.

### `cardre.technical_manifest_export`

Category: `transform`

Inputs:

- Build summary reports when Phase 2B is implemented.
- Validation/cutoff reports.
- In Phase 2A, final WOE/IV and variable-selection reports.
- The node may query the store for complete run-step and artifact evidence only
  for `context.run_id` and `context.plan_version_id`.

Outputs:

- JSON manifest artifact with role `manifest`.

Manifest shape:

```json
{
  "project": {"project_id": "...", "name": "..."},
  "run": {"run_id": "...", "plan_version_id": "..."},
  "steps": [],
  "artifacts": [],
  "modelling_metadata": {},
  "selected_variables": [],
  "model": {},
  "scorecard": {},
  "validation_metrics": {},
  "warnings": [],
  "errors": []
}
```

Requirements:

- Include physical and logical hashes for referenced artifacts.
- Include node versions and params hashes.
- Do not include raw row-level data by default.
- Use `context.run_id`, `context.plan_version_id`, parent run-step evidence, and
  immutable artifact IDs.
- Do not infer from the latest run, latest plan version, latest artifact, or any
  mutable project-level state.
- Phase 2A manifest stub includes evidence through final WOE/IV and selected
  variables. Phase 2C extends the same manifest with model, scorecard,
  validation, and cutoff evidence.

## Executor Input Contract Requirement

The current category role filtering is intentionally conservative but
insufficient for Phase 2. Phase 2 nodes need mixed inputs such as train datasets
plus definition/report artifacts. This must be solved before implementing the
Phase 2A pathway.

Required approach:

- Implement node-level input role filtering.
- Each node declares exact accepted roles and whether each accepted role is
  tabular or non-tabular evidence.
- The executor selects inputs using the node contract.
- The executor then applies separate leakage validation.
- Fit, selection, and refinement nodes must reject `test` and `oot` tabular
  inputs unless a future node explicitly proves it is non-learning and safe.
- Apply nodes may consume `train`, `test`, and `oot` tabular inputs plus fitted
  definitions, but must not update definitions.

Forbidden shortcut:

- Do not mark learning nodes as `transform` to bypass role filtering.

Do not make transform nodes a backdoor for leakage-sensitive fitting work. If a
node learns parameters, classify it as `fit`.

## Sidecar API Requirements

Existing endpoints should remain compatible:

- `POST /projects`
- `GET /projects/{project_id}`
- `POST /datasets/import`
- `GET /plans/{plan_id}`
- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/steps`
- artifact endpoints already present in `sidecar/routes/artifacts.py`

Phase 2 additions should be minimal:

- Ensure project creation registers the Phase 2A scorecard pathway.
- Ensure dataset import updates the Phase 2A pathway import params.
- Add report/artifact content retrieval only if current artifact endpoints cannot
  inspect JSON reports and summaries.

No background run queue is required unless synchronous full-pathway runs become
too slow for the local API tests.

## Acceptance Test Matrix

### Unit Tests

- Node-level input contracts select mixed inputs correctly.
- Fit, selection, and refinement nodes reject `test` and `oot` tabular artifacts.
- Split creates deterministic `train`, `test`, and `oot` artifacts and records the
  strategy used.
- Explicit missing/outlier treatment does not learn from combined role data.
- Fine classing creates deterministic numeric bins.
- Fine classing creates categorical bins and handles high cardinality.
- WOE/IV calculation matches hand-calculated small fixtures.
- WOE/IV uses event = bad, non-event = good, and the documented WOE formula.
- Zero-cell WOE blocks final use by default.
- Smoothing requires explicit method, parameter, and rationale.
- Variable selection includes/rejects candidates with reasons.
- Manual bin overrides merge by `bin_id` and reject invalid merges.

Phase 2B/2C unit tests:

- WOE transform maps bins to expected WOE values.
- Score scaling produces deterministic points.
- Persisted model coefficients reproduce `predicted_bad_probability` and score
  for a tiny fixture.
- Validation metrics match small hand-checkable fixtures.

### Executor Integration Tests

- Fit, selection, and refinement nodes cannot consume `test` or `oot` datasets.
- Apply nodes consume definitions plus role-tagged datasets without fitting.
- Changing fine-classing params makes downstream steps stale.
- Re-running preserves old run records and artifacts.
- Failed scorecard node records a failed run step with structured errors.
- Manifest generation uses `context.run_id` and does not read latest-run state.

### End-To-End API Tests

- Create project.
- Import German Credit.
- Run the Phase 2A scorecard pathway.
- Assert run succeeds.
- Assert final WOE/IV artifacts exist.
- Assert selected-variable artifact exists with inclusion/exclusion reasons.
- Assert manifest stub exists and references run/step/artifact hashes through
  final WOE/IV.

Phase 2B/2C end-to-end tests add final scorecard artifacts, scored
train/test/OOT outputs, validation metrics by role, cutoff analysis, and the final
manifest.

## Definition Of Done

Phase 2A is complete when:

- A fresh project gets the fixed Phase 2A scorecard pathway.
- German Credit can be imported and run through final WOE/IV.
- Node-level input contracts are implemented and leakage tests pass.
- Fitting, selection, and refinement steps operate only on train tabular data plus
  non-tabular upstream evidence.
- The run produces split artifacts, fine-classing definitions, initial WOE/IV,
  variable clustering, selected variables, refined/manual bins, final WOE/IV, and
  a manifest stub.
- The Phase 2A run is reproducible from persisted plan params, input artifact hashes,
  node versions, and run-step evidence.
- Tests cover node behavior, role enforcement, staleness, and the end-to-end API
  flow.

Full Phase 2 is complete after Phase 2B/2C add the logistic model, scorecard,
scored train/test/OOT outputs, validation metrics, cutoff analysis, and final
technical manifest.
