# Report Bundle v1

The report bundle is a Pydantic model (`cardre/application/reporting/schema.py`) that represents a complete report for a run.

## Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `project_id` | `str` | Project identifier |
| `run_id` | `str` | Run identifier |
| `summary` | `ReportSummary` | Model name, target column, variable counts |
| `pathway` | `PathwaySummary` | Step list and statuses |
| `dataset_roles` | `list[DatasetRole]` | Dataset roles, date ranges, target summary |
| `model` | `ModelInfo` | Model features, intercept |
| `score_scaling` | `ScoreScalingInfo` | Scorecard points, scaling params |
| `validation` | `ValidationInfo` | Metrics by role, stability (PSI) |
| `cutoffs` | `CutoffInfo` | Cutoff analysis |
| `manual_binning_review` | `ManualBinningReviewState` | Manual binning overrides, review state |
| `redundancy_review` | `RedundancyReviewInfo` | Variable clustering, redundancy analysis |
| `artifacts` | `list[ArtifactEntry]` | Artifact index |
| `limitations` | `list[Limitation]` | Blockers and warnings |
| `reproducibility` | `ReproducibilityInfo` | Manifest and pathway hashes |

## Sub-Sections

### ReportSummary
- `model_name`, `target_column`
- `observation_level`, `development_sample`, `validation_samples`
- `final_variable_count`, `excluded_variable_count`

### PathwaySummary
- `steps`: list of `PathwayStep` (canonical_step_id, step_id, step_type, status, config_hash)

### ModelInfo
- `features`: list of `ModelFeature`
- `target`, `intercept`, `fit_dataset_role`, `fitting_config_hash`

### ValidationInfo
- `metrics_by_role`: `MetricsByRole` (train, test, oot)
- `stability`: `StabilityInfo` (PSI)

### ManualBinningReviewState
- `review_status`: str
- `edited_variable_count`, `variables_edited`, `reasons`
- `reviewed_by`, `reviewed_at`, `review_reason`

### RedundancyReviewInfo
- `clusters`: list of `RedundancyCluster`
- `singleton_variables`: list of `str`
