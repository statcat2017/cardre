# Report Bundle v1

The report bundle is a Pydantic model (`cardre/reporting/schema.py`) that represents a complete governance-quality report.

## Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | str | Schema version string |
| `project_id` | str | Project identifier |
| `run_id` | str | Source run identifier |
| `target_branch_id` | str | Target branch for the report |
| `report_mode` | str | Report mode (`"champion"` or `"branch"`) |
| `generated_at` | datetime | Generation timestamp |
| `generated_by` | `GeneratedBy` | Tool, version, timestamp |
| `source` | `ReportSource` | Run, plan version, branch references |
| `summary` | `ReportSummary` | Report metadata summary |
| `dataset_roles` | list[`DatasetRole`] | Dataset role descriptions |
| `pathway` | `PathwaySummary` | Step list and ordering |
| `branches` | list[`BranchSummary`] | Branch information |
| `champion` | `ChampionInfo` | Champion assignment (optional) |
| `variables` | list[`VariableInfo`] | Variable-level information |
| `model` | `ModelInfo` | Model features, training params, interpretability |
| `score_scaling` | `ScoreScalingInfo` | Scorecard points, scaling params |
| `validation` | `ValidationInfo` | Metrics by role, stability (PSI) |
| `cutoffs` | list[`CutoffInfo`] | Cutoff analysis results |
| `manual_interventions` | list[`ManualIntervention`] | Manual binning overrides |
| `manual_binning_review` | `ManualBinningReviewState` | Review state for manual binning |
| `redundancy_review` | `RedundancyReviewInfo` | Variable clustering, redundancy analysis |
| `limitations` | list[`Limitation`] | Model limitations |
| `reproducibility` | `ReproducibilityInfo` | Reproducibility metadata |
| `artifacts` | list[`ArtifactEntry`] | Artifact index (field is `artifacts`, not `artefacts`) |

## Canonical Step IDs

Evidence is resolved by canonical step IDs defined in `cardre/reporting/evidence_contract.py`:

| Canonical ID | Description |
|-------------|-------------|
| `final-woe-iv` | Final WOE/IV evidence |
| `model-fit` | Model fit evidence |
| `score-scaling` | Score scaling evidence |
| `validation-metrics` | Validation metrics evidence |
| `cutoff-analysis` | Cutoff analysis evidence |
| `manual-binning` | Manual binning evidence |
| `variable-clustering` | Variable clustering evidence |
| `technical-manifest-stub` | Technical manifest stub (comparison mode) |

## Legacy Aliases

| Legacy ID | Current ID |
|-----------|------------|
| `logistic-regression` | `model-fit` |

## Required Steps by Report Mode

| Mode | Required Steps |
|------|---------------|
| Branch report | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics` |
| Champion report | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics` |
| Full collector | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics`, `cutoff-analysis`, `manual-binning`, `variable-clustering` |
| Comparison | `final-woe-iv`, `model-fit`, `score-scaling`, `validation-metrics`, `cutoff-analysis`, `technical-manifest-stub` |
