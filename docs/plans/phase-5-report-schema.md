# Phase 5 Report Schema

## Overview

Phase 5 introduces two canonical schemas:

- `cardre.report_bundle.v1` — the governance report bundle
- `cardre.woe_iv_evidence.v1` — controlled WOE/IV evidence artefact

Both schemas are versioned. The report bundle is JSON-first; HTML is a rendered view.

## cardre.report_bundle.v1

The report bundle is the canonical machine-readable governance report.

### Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Always `"cardre.report_bundle.v1"` |
| `project_id` | string | Project UUID |
| `run_id` | string | Run UUID |
| `target_branch_id` | string | The branch the report targets |
| `report_mode` | string | `"champion"` or `"branch"` |
| `generated_at` | ISO datetime | When the report was generated |
| `generated_by` | object | `{ cardre_version: "0.1.0" }` |
| `source` | object | Run manifest path, hashes |
| `summary` | object | Executive summary |
| `dataset_roles` | array | train/test/oot dataset summaries |
| `pathway` | object | Plan pathway steps |
| `branches` | object | All branches with champion/target status |
| `champion` | object | Champion assignment |
| `variables` | array | Per-variable WOE/IV evidence |
| `model` | object | Model coefficients |
| `score_scaling` | object | Scorecard scaling parameters |
| `validation` | object | Validation metrics by role |
| `cutoffs` | object | Cutoff analysis tables |
| `manual_interventions` | array | Manual binning edits and overrides |
| `limitations` | array | Warnings and blockers |
| `reproducibility` | object | Execution fingerprints |
| `artefacts` | array | Artefact index |

### Summary

Key fields:

- `model_name`: Project name
- `target_column`: The modelled binary target
- `final_variable_count`: Number of variables in the final scorecard
- `excluded_variable_count`: Number of variables excluded upstream
- `report_status`: `"complete"`, `"complete_with_warnings"`, or `"blocked"`

### Champion

Two states:

- `"selected"`: A champion assignment exists
- `"not_available"`: No active champion assignment

In `"selected"` mode, the object includes `assignment_id`, `champion_branch_id`, `comparison_artifact_id`, `rationale`, and `selected_at`.

### Variables

Each variable record includes:

- `variable_name`, `iv`, `final_bin_count`
- `woe_smoothing`: smoothing config and whether it was applied
- `affected_bins`: bins that triggered zero-cell handling
- `bins`: final bin definitions with WOE and IV contribution
- `source_step_refs`: evidence traceability (exact vs inherited)

### Limitations

Each limitation has:

- `severity`: `"warning"`, `"info"`, or `"blocker"`
- `code`: A machine-readable code (e.g. `"NO_OOT_SAMPLE"`)
- `message`: Human-readable explanation

### Reproducibility

Uses the existing `execution_fingerprint` from run steps. Does **not** read the current machine environment.

## cardre.woe_iv_evidence.v1

Emitted by `CalculateWoeIvNode` as a JSON artefact.

### Fields

| Field | Description |
|-------|-------------|
| `schema_version` | `"cardre.woe_iv_evidence.v1"` |
| `project_id` | Project UUID |
| `run_id` | Run UUID |
| `branch_id` | Branch the step belongs to |
| `step_id` | Generated branch-scoped step ID |
| `canonical_step_id` | `"calculate_woe_iv"` |
| `dataset_role` | Always `"train"` |
| `target_column` | The modelled target |
| `config.smoothing` | object: `enabled`, `method`, `alpha`, `zero_cell_policy` |
| `variables` | array of per-variable evidence |

### Variable evidence

Each variable record contains:

- `variable_name`, `status`, `iv`
- `smoothing_applied`, `zero_cell_encountered`
- `affected_bins`: bins with zero-cell handling (raw counts, smoothed counts, WOE delta)
- `bins`: bin definitions (label, counts, WOE, IV)

## Version compatibility

- New WOE/IV steps emit `cardre.woe_iv_evidence.v1` alongside the legacy parquet/json artefacts
- The report collector prefers v1 evidence and warns when only legacy evidence is found
- Report bundle v1 is forwards-compatible: new sections can be added without breaking consumers
