# Phase 2 Implementation Plan

Phase 2 turns the Phase 1 proof pathway into the first real scorecard engine.
The full Phase 2 target is a deterministic local run that imports a binary-target
credit dataset, fits scorecard definitions on train data only, applies the
finalized scorecard to train/test/OOT, writes auditable artifacts, and exports a
technical manifest.

Phase 2 is engine-first. The desktop shell should be able to trigger and inspect
the run through existing sidecar APIs, but the full node editor, manual binning
table UI, and rich audit export UI belong to Phase 3+.

## Baseline

Phase 1 already provides:

- `cardre/store.py`: SQLite metadata store and filesystem artifact registration.
- `cardre/executor.py`: topological execution, run-step evidence, role filtering,
  computed staleness, and replay semantics.
- `cardre/nodes.py`: proof nodes for import, profiling, target validation, split,
  dummy fit, and dummy apply.
- `cardre/registry.py`: default node registry.
- `sidecar/`: FastAPI project, dataset, plan, run, and artifact endpoints.
- `frontend/`: Tauri/React scaffold for the Phase 1 desktop shell.

## Phase 2 Full Target

The complete Phase 2 target is a fixed minimum viable scorecard pathway:

```text
Import Dataset
-> Define Modelling Metadata
-> Apply Exclusions
-> Profile Dataset
-> Validate Binary Target
-> Development Sample Definition
-> Train/Test/OOT Split
-> Missing/Outlier Treatment
-> Automatic Fine Classing
-> Initial WOE/IV Diagnostics
-> Variable Clustering
-> Variable Selection
-> Manual Bin Editing / Coarse Classing
-> Final WOE/IV Calculation
-> WOE Transform Train
-> Logistic Regression
-> Score Scaling
-> Build Summary Report
-> Apply WOE Mapping to train/test/oot
-> Apply Model to train/test/oot
-> Validation Metrics by Role
-> Cutoff / Strategy Analysis
-> Technical Manifest Export
```

Do not attempt the full target in one implementation pass. The next implementable
slice is Phase 2A.

## Phase 2A MVP Scope

Phase 2A is the immediate implementation target. It proves the binning/WOE spine
without requiring model fitting, scoring, validation metrics, or cutoff analysis.

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

Phase 2A definition of done:

- A fresh project can register the fixed scorecard pathway with Phase 2A steps.
- German Credit can run through final WOE/IV and selected-variable artifacts.
- Fit/selection/refinement nodes cannot consume `test` or `oot` tabular data.
- The manifest stub is generated from the current `run_id`, `plan_version_id`,
  parent run-step evidence, and immutable artifact IDs.
- The run preserves all artifact hashes, params hashes, node versions, warnings,
  and structured errors needed for replay.
- Model, scorecard, scoring, validation metrics, cutoff analysis, and final audit
  export remain Phase 2B/2C work.

## Workstream 1: Foundation Cleanup And Contracts

Objectives:

- Add explicit node metadata for display name, artifact contracts, params schema,
  and GUI summary metadata where useful.
- Add shared helpers for writing JSON and Parquet artifacts so scorecard nodes do
  not duplicate artifact registration boilerplate.
- Keep SQLite metadata-only. Tabular outputs remain Parquet; definitions and
  reports remain JSON.
- Keep train/test/OOT access enforced by the executor rather than node convention.
- Replace category-only role filtering with explicit node-level input contracts.
- Retain a hard leakage rule: fitting or learning logic may not consume `test` or
  `oot` tabular artifacts.

Acceptance criteria:

- Existing Phase 1 tests still pass.
- Shared artifact helpers preserve `physical_hash`, `logical_hash`, media type,
  role, and metadata.
- New node outputs are replayable through existing execution fingerprints.
- Mixed-input nodes receive the exact roles they declare without being marked as
  `transform` to bypass filtering.
- Tests prove fit/learning nodes reject `test` and `oot` datasets even when those
  artifacts are wired as parents.

## Workstream 2: Scorecard Pathway Template

Objectives:

- Add a fixed Phase 2A scorecard pathway registered on project creation.
- Keep the Phase 1 proof pathway only if useful for smoke tests.
- Use stable step IDs that match domain language and remain suitable for audit
  manifests.

Suggested step IDs:

- `import`
- `define-metadata`
- `apply-exclusions`
- `profile`
- `validate-target`
- `sample-definition`
- `split`
- `explicit-missing-outlier-treatment`
- `fine-classing`
- `initial-woe-iv`
- `variable-clustering`
- `variable-selection`
- `manual-binning`
- `final-woe-iv`
- `technical-manifest-stub`

Phase 2B adds `woe-transform-train`, `logistic-regression`, `score-scaling`, and
`build-summary-report`. Phase 2C adds `apply-woe`, `apply-model`,
`validation-metrics`, `cutoff-analysis`, and the final technical manifest.

Acceptance criteria:

- Creating a project registers a fixed Phase 2A scorecard pathway.
- `GET /plans/{plan_id}` returns all scorecard steps with backend-computed
  status and staleness.
- Dummy fit/apply nodes are no longer part of the primary scorecard path.

## Workstream 3: Metadata, Exclusion, And Sample Nodes

Implement lightweight auditable config/report nodes:

- `cardre.define_modelling_metadata`
  - Captures population, product, segment, target column, good/bad values,
    indeterminate values, observation window, and performance window.
  - Produces a JSON definition/report artifact.
- `cardre.apply_exclusions`
  - Accepts explicit exclusion rules with reasons.
  - Phase 2 supports simple column/operator/value rules.
  - Produces a filtered Parquet dataset and JSON exclusion report.
- `cardre.development_sample_definition`
  - Captures sample method, weights column, base bad rate, and prior-probability
    metadata.
  - Phase 2 may record metadata without advanced weighting logic.

Acceptance criteria:

- Exclusion output includes row counts before/after and rule-level counts.
- Metadata and sample assumptions are persisted and included in the manifest.
- Missing modelling-critical config fails with structured errors.

## Workstream 4: Data Preparation

For Phase 2A, implement explicit-only treatment as
`cardre.explicit_missing_outlier_treatment`.

Minimum behavior:

- Pass-through by default.
- Optional simple numeric/categorical imputation using user-supplied constants.
- Optional numeric cap/floor using user-supplied explicit bounds.
- No learned percentiles, means, medians, modes, or other parameters in Phase 2A.
- Do not conflate imputation with fine-classing `missing_policy`.

Acceptance criteria:

- Treatment definitions are JSON artifacts.
- Transformed datasets remain Parquet artifacts.
- The node records all explicit treatment parameters and affected counts.
- The node does not learn from combined train/test/OOT data.

Future learned treatment must be split into `fit_missing_outlier_treatment`
(`fit`, consumes `train` only) and `apply_missing_outlier_treatment` (`apply`,
consumes train/test/OOT plus the treatment definition).

## Workstream 5: Automatic Fine Classing

Implement `cardre.fine_classing` as a fit node consuming `train` only.

Minimum algorithm:

- Numeric variables use quantile-based initial bins.
- Configurable `max_bins`, `min_bin_fraction`, and `missing_policy`.
- Categorical variables start as category groups.
- High-cardinality categoricals emit warnings or use top-N plus fallback.
- Target, role, and non-feature columns are excluded.
- Bin IDs are stable and immutable within the generated definition.

Acceptance criteria:

- Fit node cannot consume `test` or `oot` artifacts.
- Bin definitions include variable name, bin IDs, boundaries/categories, missing
  handling, counts, event counts, and non-event counts.
- Output is deterministic for the same input and params.
- Sparse-bin and zero-cell conditions are recorded as warnings.

## Workstream 6: WOE/IV Calculation

Implement `cardre.calculate_woe_iv`.

Rules:

- This is a diagnostic/selection node, not a dataset transform.
- It consumes train data and bin definitions.
- It computes WOE and IV by variable/bin.
- It uses a documented event convention: event = bad, non-event = good.
- It uses `woe = ln(non_event_distribution / event_distribution)` and
  `iv_component = (non_event_distribution - event_distribution) * woe`.
- Infinite WOE is not allowed silently.
- Default zero-cell policy blocks final WOE use unless explicit smoothing is
  configured with a rationale.

Outputs:

- Bin-level WOE report.
- IV ranking table.

Acceptance criteria:

- Initial WOE/IV uses automatic fine-classing definitions.
- Final WOE/IV uses refined/manual definitions.
- IV rankings are deterministic and artifact-backed.

## Workstream 7: Variable Clustering And Selection

Implement:

- `cardre.variable_clustering`
  - Computes train-only correlation/redundancy groups.
  - Phase 2 may use numeric correlations on candidate variables or WOE features.
- `cardre.variable_selection`
  - Selects variables by IV threshold, maximum variable count, missing/sparse-bin
    warnings, and cluster de-duplication.
  - Emits explicit inclusion/exclusion reasons.

Acceptance criteria:

- Every selected and rejected variable has a reason.
- Manual binning consumes the selected-variable artifact.
- Tests cover IV thresholding and correlated-variable de-duplication.

## Workstream 8: Manual Binning / Coarse Classing

Implement `cardre.manual_binning` as a refinement node.

Minimum behavior:

- Accept automatic bin definitions, selected-variable artifact, and JSON override
  params.
- Support merging adjacent numeric bins.
- Support grouping categorical levels.
- Support isolating missing or special values.
- Require a reason for every override.
- If no overrides exist, pass through selected variables' automatic bins as the
  refined definitions.

Acceptance criteria:

- Overrides reference immutable source `bin_id`s, not array indexes.
- Invalid merges fail clearly.
- Every manual decision is replayable from step params and artifact inputs.

## Workstream 9: WOE Transform

Phase 2B workstream.

Implement:

- `cardre.woe_transform_train`
  - Consumes train data plus final WOE/bin definitions.
  - Produces a WOE-transformed train Parquet artifact.
- `cardre.apply_woe_mapping`
  - Consumes train/test/OOT data plus build-stream definitions.
  - Produces role-tagged WOE-transformed artifacts.
  - Records fallback counts for missing or unseen validation values.

Acceptance criteria:

- Transform nodes do not fit new WOE values.
- Validation roles never recalculate WOE.
- Fallback usage is reported by role.

## Workstream 10: Logistic Regression

Phase 2B workstream.

Implement `cardre.logistic_regression` as a fit node consuming WOE-transformed
train data only.

Implementation note:

- Use `scikit-learn` for Phase 2 unless a lighter dependency is explicitly chosen.

Outputs:

- JSON model artifact with coefficients, intercept, feature order, class mapping,
  training params, convergence metadata, and warnings.

Acceptance criteria:

- Model fit is deterministic for fixed params.
- `predicted_bad_probability` orientation is explicit and does not depend on
  scikit-learn's implicit class ordering.
- Coefficient signs and convergence status are recorded.
- Perfect separation or convergence failure surfaces as structured warnings or
  errors.

## Workstream 11: Score Scaling

Phase 2B workstream.

Implement `cardre.score_scaling`.

Inputs:

- Logistic regression model artifact.
- Scaling params: points to double odds, base score, base odds, and score
  direction.

Outputs:

- Scorecard JSON artifact.
- Optional scorecard CSV artifact.

Acceptance criteria:

- Points allocation is deterministic.
- Scorecard artifact is sufficient for Cardre's internal scorer.
- A parity test compares model/log-odds/score output from persisted artifacts.

## Workstream 12: Apply Model And Validation Metrics

Phase 2C workstream.

Implement:

- `cardre.apply_model`
  - Applies the fitted model and scorecard to role-tagged WOE datasets.
  - Produces prediction/score Parquet artifacts by role.
- `cardre.validation_metrics`
  - Computes AUC, Gini, KS, calibration summary, and score distributions by role.
  - PSI is included if the implementation remains stable and small.
- `cardre.cutoff_analysis`
  - Produces approval rate, bad rate, and capture rate by cutoff band.

Acceptance criteria:

- Metrics are separated by `train`, `test`, and `oot`.
- Validation nodes do not fit or mutate definitions.
- Reports are inspectable through existing artifact APIs.

## Workstream 13: Technical Manifest Export

Implement `cardre.technical_manifest_export`.

Phase 2A implements a manifest stub that covers evidence through final WOE/IV.
Phase 2C extends it with model, scorecard, validation, and cutoff evidence.

Minimum manifest contents:

- Project ID and name.
- Plan version ID and run ID.
- Step list and statuses.
- Step params hashes and node versions.
- Input and output artifact IDs.
- Artifact physical and logical hashes.
- Modelling metadata.
- Selected variables.
- Final bin definitions.
- Model coefficients when Phase 2B is implemented.
- Score scaling params when Phase 2B is implemented.
- Validation metrics when Phase 2C is implemented.
- Warnings and errors summary.

Acceptance criteria:

- Manifest is JSON and registered as an artifact.
- Raw datasets are not exported by default.
- Manifest generation uses `context.run_id`, `context.plan_version_id`, parent
  run-step evidence, and immutable artifact IDs. It must not infer from latest
  run or mutable project state.
- Manifest generation is deterministic for the same run evidence.

## Workstream 14: Sidecar/API Updates

Keep API changes minimal:

- Register the Phase 2A scorecard pathway on project creation.
- Ensure imports update the Phase 2A pathway import step params.
- Add artifact content/summary endpoints only where required for report
  inspection.
- Keep run triggering through `POST /runs` unless asynchronous execution becomes
  necessary.

Acceptance criteria:

- Existing `/projects`, `/datasets/import`, `/plans/{plan_id}`, and `/runs`
  behavior remains compatible.
- API tests can run the German Credit pathway through final WOE/IV.
- Final WOE/IV, selected-variable artifacts, refined-bin artifacts, and the
  manifest stub are discoverable from API responses.

## Milestones

### Phase 2A: Binning And WOE Foundation

- Pathway template.
- Metadata/exclusion/sample nodes.
- Node-level input contracts and hard leakage tests.
- Split strategy contract with recorded train/test/OOT assignment evidence.
- Explicit-only missing/outlier treatment or pass-through.
- Fine classing.
- WOE/IV.
- Variable clustering/selection.
- Manual binning pass-through and JSON overrides.
- Manifest stub through final WOE/IV.

### Phase 2B: Model And Scorecard

- WOE transform.
- Logistic regression.
- Score scaling.
- Scorecard artifact.
- Internal scorer parity test.

### Phase 2C: Validation And Export

- Apply WOE/model to train/test/OOT.
- Metrics by role.
- Cutoff analysis.
- Final technical manifest export.
- Minimal sidecar/report access polish.

## Out Of Scope

- Full manual binning React editor.
- Branch duplication and champion/challenger workflows.
- Governance-quality human-readable report.
- SQL/Python scoring code export beyond internal parity artifacts.
- Reject inference.
- Freeform DAG editing.
- Production packaging hardening beyond the Phase 1 shell behavior.

## Primary Risks

- Manual binning can expand quickly; keep Phase 2 to JSON override replay plus
  audit evidence.
- WOE zero-cell behavior must be strict to avoid invalid model artifacts.
- Fit/apply leakage prevention must remain executor-enforced.
- Artifact writing should be centralized before adding many nodes, or the node
  module will become difficult to maintain.
