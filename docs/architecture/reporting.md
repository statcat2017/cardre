# Reporting

## Overview

The reporting system produces governance-quality report bundles from immutable run artifacts. It is a read-only consumer of run evidence — it must not become a second modelling execution path.

## Modules

| Module | File | Responsibility |
|--------|------|----------------|
| `schema.py` | `cardre/reporting/schema.py` | Pydantic models for `ReportBundle` and all sub-sections |
| `collector.py` | `cardre/reporting/collector.py` | Builds `ReportBundle` from run artifacts via `ArtifactEvidenceReader` |
| `readiness.py` | `cardre/reporting/readiness.py` | Deprecation shim; actual logic in `cardre/readiness/check.py` |
| `renderer_html.py` | `cardre/reporting/renderer_html.py` | Renders `ReportBundle` to HTML |
| `evidence_contract.py` | `cardre/reporting/evidence_contract.py` | Canonical step IDs and evidence resolution rules |
| `limitation_codes.py` | `cardre/reporting/limitation_codes.py` | Model limitation codes |
| `templates/` | `cardre/reporting/templates/` | HTML report templates |

## Report Generation Service

The `ReportGenerationService` (`cardre/services/report_generation_service.py`) orchestrates the full report lifecycle:

1. **Readiness check**: verifies all required evidence is available for the requested report mode.
2. **Collection**: builds the `ReportBundle` from run artifacts.
3. **Rendering**: produces `report.html` from the bundle.
4. **Writing**: saves `report_bundle.json` and `report.html` as artifacts.

## Report Bundle Schema

The `ReportBundle` Pydantic model (`cardre/reporting/schema.py`) has these top-level fields:

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

Evidence is resolved by canonical step IDs defined in `evidence_contract.py`:

- `final-woe-iv`
- `model-fit`
- `score-scaling`
- `validation-metrics`
- `cutoff-analysis`
- `manual-binning`
- `variable-clustering`
- `technical-manifest-stub` (comparison mode)

## Report Modes

The frontend `ExportPanel.tsx` uses two report modes:
- `"champion"` — report for the champion branch
- `"branch"` — report for a specific branch

Readiness checks verify that all required evidence is available for the requested mode.

## Export

The frontend `ExportPanel.tsx` provides the export UI:
- Selects report mode (`"champion"` or `"branch"`) and target branch
- Checks readiness via the API
- Calls `api.generateReport` with JSON and HTML output formats
- Renders the audit-pack export UI and readiness panel
