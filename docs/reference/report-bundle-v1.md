# Report Bundle v1

The report bundle is a Pydantic model (`cardre/reporting/schema.py`) that represents a complete governance-quality report.

## Top-Level Fields

| Field | Type | Description |
|-------|------|-------------|
| `report_summary` | `ReportSummary` | Metadata, generation info, source run/branch |
| `pathway_summary` | `PathwaySummary` | Step list, branch info, champion info |
| `dataset_info` | `DatasetTargetSummary` | Dataset roles, date ranges, target summary |
| `model_info` | `ModelInfo` | Model features, training params, interpretability |
| `score_scaling` | `ScoreScalingInfo` | Scorecard points, scaling params |
| `validation_info` | `ValidationInfo` | Metrics by role, stability (PSI), cutoff analysis |
| `manual_binning_review` | `ManualBinningReviewState` | Manual binning overrides, review state |
| `redundancy_review` | `RedundancyReviewInfo` | Variable clustering, redundancy analysis |
| `artifacts` | `list[ArtifactEntry]` | Artifact index (note: field is `artifacts`, not `artefacts`) |

## Sub-Sections

### ReportSummary
- `report_id`, `report_type`, `report_version`
- `generated_by`: `GeneratedBy` (tool, version, timestamp)
- `source`: `ReportSource` (run_id, plan_version_id, branch_id)
- `reproducibility`: `ReproducibilityInfo`

### PathwaySummary
- `steps`: list of `PathwayStep` (step_id, node_type, status)
- `branches`: list of `BranchSummary`
- `champion`: optional `ChampionInfo`

### ModelInfo
- `features`: list of `ModelFeature`
- `training_params`: dict
- `interpretability`: dict
- `limitations`: list of `Limitation`

### ValidationInfo
- `metrics_by_role`: `MetricsByRole` (train, test, oot)
- `stability`: `StabilityInfo` (PSI)
- `cutoff`: `CutoffInfo` (selected cutoff, cutoff table)

### ManualBinningReviewState
- `overrides`: list of `ManualIntervention`
- `review_status`: str
- `reviewed_by`, `reviewed_at`, `review_reason`

### RedundancyReviewInfo
- `clusters`: list of `RedundancyCluster`
- `members`: list of `RedundancyClusterMember`
