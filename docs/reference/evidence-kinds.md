# Evidence Kinds

## Canonical Step IDs

Evidence is resolved by canonical step IDs defined in `cardre/application/reporting/contracts.py`:

| Canonical ID | Description |
|-------------|-------------|
| `final-woe-iv` | Final WOE/IV evidence |
| `model-fit` | Model fit evidence |
| `score-scaling` | Score scaling evidence |
| `validation-metrics` | Validation metrics evidence |
| `cutoff-analysis` | Cutoff analysis evidence |
| `manual-binning` | Manual binning evidence |
| `variable-clustering` | Variable clustering evidence |
| `technical-manifest` | Technical manifest (comparison mode) |

## Required Steps by Report Mode

The canonical required-step lists are defined in
`cardre/application/reporting/contracts.py`:

| Mode | Required Steps |
|------|---------------|
| Branch report | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics`, `cutoff-analysis` |
| Champion report | `final-woe-iv`, `model-fit`, `score-scaling`, `freeze-scorecard-bundle`, `apply-model`, `validation-metrics`, `cutoff-analysis`, `scorecard-table-export`, `scoring-export-python`, `scoring-export-sql` |
| Full collector | everything in Champion plus `manual-binning`, `variable-clustering`, `coefficient-sign-check`, `separation-diagnostics`, `vif-diagnostics`, `calibration-diagnostics`, `apply-exclusions`, `sample-definition`, `explicit-missing-outlier-treatment`, `initial-woe-iv`, `model-limitations`, `apply-woe` |
| Comparison | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics`, `cutoff-analysis`, `technical-manifest` |

## Evidence Kinds

The `EvidenceReader` (`cardre/adapters/evidence/reader.py`) resolves artifacts as
typed evidence via the profiles and parsers in `cardre/adapters/evidence/`. The
following kinds are defined in `cardre/domain/evidence/kinds.py`. This table lists
the most commonly used kinds; the full enum covers all artifact types in the engine.

| Kind | Schema | Typed Model |
|------|--------|-------------|
| `MODELLING_METADATA` | `cardre.modelling_metadata.v1` | `ModellingMetadata` |
| `MODEL_ARTIFACT` | `cardre.model_artifact.v1` | `ModelArtifactV1` |
| `SCORE_SCALING` | `cardre.score_scaling.v1` | `ScoreScaling` |
| `BIN_DEFINITION` | `cardre.bin_definition.v1` | `BinDefinition` |
| `WOE_TABLE` | `cardre.woe_table.v1` | `WoeTable` |
| `IV_TABLE` | `cardre.iv_table.v1` | `IvTable` |
| `SELECTION_DEFINITION` | `cardre.selection_definition.v1` | `SelectionDefinition` |
| `EXCLUSION_SUMMARY` | `cardre.exclusion_summary.v1` | `ExclusionSummary` |
| `SCORED_DATASET` | `cardre.scored_dataset.v1` | `ScoredDataset` |
| `EXPLAINABILITY_REPORT` | `cardre.explainability_report.v1` | `ExplainabilityReport` |
| `CALIBRATION_REPORT` | `cardre.calibration_report.v1` | (raw dict) |
| `VARIABLE_CLUSTERING` | `cardre.variable_clustering_evidence.v1` | `VariableClusteringEvidence` |
| `FROZEN_SCORECARD_BUNDLE` | `cardre.frozen_scorecard_bundle.v1` | (raw dict) |
| `MANUAL_BINNING_OVERRIDES` | `cardre.manual_binning_overrides.v1` | `ManualBinningOverrides` |
| `COEFFICIENT_SIGN_DIAGNOSTICS` | `cardre.coefficient_sign_diagnostics.v1` | `CoefficientSignDiagnostics` |
| `SEPARATION_DIAGNOSTICS` | `cardre.separation_diagnostics.v1` | `SeparationDiagnostics` |
| `VIF_DIAGNOSTICS` | `cardre.vif_diagnostics.v1` | `VifDiagnostics` |
| `CALIBRATION_DIAGNOSTICS` | `cardre.calibration_diagnostics.v1` | `CalibrationDiagnostics` |
| `FEATURE_SELECTION_EVIDENCE` | `cardre.feature_selection_evidence.v1` | `FeatureSelectionEvidence` |
| `CUTOFF_ANALYSIS` | `cardre.cutoff_analysis.v1` | `CutoffAnalysis` |
| `VALIDATION_METRICS` | `cardre.validation_metrics.v1` | `ValidationMetrics` |
| `SCORE_TABLE` | `cardre.scorecard_table.v1` | `ScoreTable` |
| `SCORING_EXPORT_PYTHON` | `cardre.scoring_export_python.v1` | `ScoringExportPython` |
| `SCORING_EXPORT_SQL` | `cardre.scoring_export_sql.v1` | `ScoringExportSQL` |

The 4 diagnostics kinds (`COEFFICIENT_SIGN_DIAGNOSTICS`, `SEPARATION_DIAGNOSTICS`,
`VIF_DIAGNOSTICS`, `CALIBRATION_DIAGNOSTICS`) and `MANUAL_BINNING_OVERRIDES` were
added during the thermo-nuclear quality sprint (PR2).

## Resolution Rules

- Evidence is resolved by canonical step ID, not by step instance ID. The
  canonical IDs and their evidence kinds are defined in
  `cardre/application/reporting/contracts.py`.
- A persisted step's `canonical_step_id` must be exactly the current canonical
  ID. There are no legacy aliases or fallback readers (see ADR 0015): a step
  whose `node_version` or canonical identity is not the current one is rejected
  before execution.
