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

The `ReportBundle` Pydantic model (`cardre/reporting/schema.py`) includes:

- `report_summary`: metadata, generation info, source run/branch
- `pathway_summary`: step list, branch info, champion info
- `dataset_info`: dataset roles, date ranges, target summary
- `model_info`: model features, training params, interpretability
- `score_scaling`: scorecard points, scaling params
- `validation_info`: metrics by role, stability (PSI), cutoff analysis
- `manual_binning_review`: manual binning overrides, review state
- `redundancy_review`: variable clustering, redundancy analysis
- `artifacts`: artifact index (note: field is `artifacts`, not `artefacts`)

## Canonical Step IDs

Evidence is resolved by canonical step IDs defined in `evidence_contract.py`:

- `final-woe-iv`
- `model-fit`
- `score-scaling`
- `validation-metrics`
- `cutoff-analysis`
- `manual-binning`
- `variable-clustering`

## Report Modes

The report system supports multiple modes (standard, challenger comparison, etc.) controlled by the generation service. Readiness checks verify that all required evidence is available for the requested mode.

## Export

The frontend `ExportPanel.tsx` provides the export UI:
- Selects report mode and target branch
- Checks readiness via the API
- Calls `api.generateReport` with JSON and HTML output formats
- Renders the audit-pack export UI and readiness panel
