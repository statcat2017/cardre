# Cardre Phase 5 Technical Specification and Attack Implementation Plan

## 1. Phase 5 Objective

Phase 5 adds governance-quality reporting and audit-pack generation to Cardre.

The purpose of Phase 5 is not simply to generate a nice-looking PDF or export screen. The purpose is to prove that a completed scorecard modelling run is:

* reproducible;
* branch-aware;
* evidence-backed;
* auditable;
* locally exportable;
* understandable by a model development, validation, or governance reviewer.

The central Phase 5 principle is:

> Cardre Phase 5 generates a governance report by resolving branch-scoped canonical modelling evidence from immutable run artefacts, using controlled evidence schemas and the existing audit-pack export path. The report is JSON-first, HTML-rendered, table-first, offline, and explicit about missing evidence.

The canonical output of Phase 5 is:

```
report_bundle.json
```

The user-facing rendered output is:

```
report.html
```

The exportable deliverable is an extended branch audit pack produced through the existing export_service.py.

PDF export is explicitly out of scope for Phase 5.

---

## 2. Product Goal

By the end of Phase 5, a Cardre user should be able to complete a scorecard modelling pathway and export a local audit pack containing:

* model development report;
* machine-readable report bundle;
* final scorecard definition;
* branch/champion/challenger comparison evidence;
* WOE/IV and binning evidence;
* manual intervention evidence;
* model coefficients;
* score scaling configuration;
* validation metrics;
* cutoff analysis, where available;
* reproducibility manifest;
* artefact index and checksums.

The report should be strong enough to support an internal model development file. It should not pretend to be a full enterprise model-risk workflow system.

---

## 3. Core Architectural Decision

Phase 5 reports must be generated from immutable run artefacts, not from transient GUI state.

Correct architecture:

```
engine run
  → immutable artefacts
  → controlled evidence schemas
  → branch-aware report collector
  → report_bundle.json
  → report.html
  → extended audit pack
```

Incorrect architecture:

```
current GUI state
  → pretty report
```

The report generator is a read-only artefact consumer. It must not become a second modelling execution path.

---

## 4. Scope

### 4.1 In scope

Phase 5 includes:

* report_bundle.json schema v1.
* Controlled WOE/IV evidence artefact schema.
* Branch-aware report collection.
* Champion-aware and arbitrary-branch reporting.
* Report readiness validation.
* Table-first offline HTML rendering.
* Extension of the existing branch audit-pack export.
* Report artefact indexing.
* Checksums for exported report files.
* Minimal frontend integration through the existing ExportPanel.tsx.
* Structural HTML tests.
* Golden JSON tests for report bundle output.
* Documentation of report schema and audit-pack structure.

### 4.2 Out of scope

Phase 5 does not include:

* PDF generation.
* Interactive charts.
* Chart.js, external JS, or external CSS in reports.
* Hosted collaboration.
* Approval workflow.
* E-signatures.
* Role-based access control.
* Enterprise policy configuration.
* Configurable report designer.
* Regulatory submission automation.
* Arbitrary visual DAG report generation.
* Exporting raw source datasets by default.

---

## 5. Phase 4 Assumptions

Phase 5 assumes the end of Phase 4 has delivered:

* backend-owned branch model;
* generated branch-scoped step IDs;
* stable canonical_step_id;
* branch_step_map;
* branch-scoped evidence lookup;
* comparison_artifact_id;
* champion_service.py;
* export_branch_audit_pack;
* manual-binning service generalized across branches;
* immutable run artefacts;
* run step execution fingerprints.

Important existing Phase 4 realities:

* generated step IDs look like `manual-binning__br_a81f3c`;
* reports cannot hardcode examples like `branch_main.step_woe_003`;
* champion selection currently goes through champion_service.py;
* champion assignment requires a comparison snapshot and rationale;
* Phase 4 already has an audit-pack export path in export_service.py.

Phase 5 must extend this architecture rather than creating parallel concepts.

---

## 6. Hard Pre-flight Gates

Before Batch 1 of Phase 5 begins, three boundary issues must be resolved.

---

### 6.1 Gate A — Controlled WOE/IV evidence artefact

The existing CalculateWoeIvNode currently embeds smoothing evidence inside a summary JSON shape. That is too fragile for Phase 5.

Phase 5 requires a dedicated, versioned evidence artefact:

```
woe_iv_evidence.json
```

This artefact must be emitted by the WOE/IV calculation step and registered in the normal run artefact store.

Required schema:

```json
{
  "schema_version": "cardre.woe_iv_evidence.v1",
  "project_id": "string",
  "run_id": "string",
  "branch_id": "string",
  "step_id": "manual-binning__br_a81f3c",
  "canonical_step_id": "calculate_woe_iv",
  "dataset_role": "train",
  "target_column": "bad_flag",
  "config": {
    "smoothing": {
      "enabled": true,
      "method": "additive",
      "alpha": 0.5,
      "zero_cell_policy": "block"
    }
  },
  "variables": [
    {
      "variable_name": "applicant_age",
      "status": "included",
      "iv": 0.126,
      "smoothing_applied": true,
      "zero_cell_encountered": false,
      "affected_bins": [
        {
          "bin_id": "bin_001",
          "reason": "zero_bad",
          "raw_good_count": 120,
          "raw_bad_count": 0,
          "smoothed_good_count": 120.5,
          "smoothed_bad_count": 0.5,
          "raw_woe": null,
          "smoothed_woe": -1.42,
          "final_woe": -1.42,
          "woe_delta": null
        }
      ],
      "bins": [
        {
          "bin_id": "bin_001",
          "label": "<= 21",
          "lower": null,
          "upper": 21,
          "good_count": 3000,
          "bad_count": 180,
          "bad_rate": 0.0566,
          "woe": -0.12,
          "iv_contribution": 0.004
        }
      ]
    }
  ]
}
```

Phase 5 rule:

> For new Phase 5 reports, WOE evidence must come from `cardre.woe_iv_evidence.v1`.
> Legacy summary parsing is allowed only as a warning-producing compatibility fallback, not as the normal path.

If a selected branch has a completed WOE/IV step but no controlled evidence artefact, report readiness should block with:

```json
{
  "status": "blocked",
  "code": "MISSING_WOE_IV_EVIDENCE_V1",
  "message": "The selected branch has a completed WOE/IV step but no controlled WOE/IV evidence artefact."
}
```

---

### 6.2 Gate B — Shared branch step resolver

The report collector must not infer step IDs.

It must resolve evidence using:

```
target_branch_id
+ canonical_step_id
→ branch_step_map
→ exact branch step if available
→ nearest ancestor step if inherited
→ artefact IDs
```

The collector should use the same ancestor resolution behaviour as Phase 4, currently represented by:

```
PlanService._find_nearest_ancestor_by_canonical_step_id
```

Recommended extraction:

```
sidecar/branching/step_resolver.py
```

Public contract:

```python
resolve_step_for_branch(
    *,
    branch_id: str,
    canonical_step_id: str,
    allow_ancestor: bool = True,
) -> ResolvedStepRef
```

Return object:

```json
{
  "requested_branch_id": "challenger_a",
  "resolved_branch_id": "main",
  "canonical_step_id": "calculate_woe_iv",
  "step_id": "calculate-woe-iv__br_main",
  "resolution": "exact",
  "artifact_ids": ["artifact_123"]
}
```

The report bundle must preserve whether evidence was exact or inherited:

```json
{
  "source_step_refs": [
    {
      "requested_branch_id": "challenger_a",
      "resolved_branch_id": "main",
      "canonical_step_id": "calculate_woe_iv",
      "step_id": "calculate-woe-iv__br_main",
      "resolution": "ancestor"
    }
  ]
}
```

This is essential because challenger branches may inherit earlier modelling evidence from a parent branch.

---

### 6.3 Gate C — Export service ownership

Phase 5 must extend the existing export service.

It must not create a parallel audit-pack export path.

Current Phase 4 export ownership:

```
export_service.py
  export_branch_audit_pack
```

Phase 5 rule:

> `export_service.py` owns packaging.
> `reporting/` owns report collection and rendering.

Phase 5 should add report files into the existing audit pack rather than replacing the existing export format.

---

## 7. Design Principles

### 7.1 Report from artefacts, not UI state

The GUI may request report generation, but the content must come from frozen run artefacts.

The report collector must not depend on:

* selected tabs;
* expanded nodes;
* current React state;
* browser memory;
* unsaved UI choices.

---

### 7.2 Structured report first, rendered report second

Cardre should generate:

```
report_bundle.json
```

Then render:

```
report.html
```

The JSON bundle is canonical. HTML is a user-facing rendering.

---

### 7.3 Table-first rendering

Phase 5 reports should use static tables rather than charts.

No required WOE plots, no interactive charts, no bundled Chart.js.

Reason:

* tables are more auditable;
* tables are easier to test;
* tables are easier to render offline;
* tables reduce packaging risk;
* tables align better with model governance review.

WOE charts can be reconsidered in a later phase.

---

### 7.4 Branch-aware by default

Reports must understand:

* target branch;
* inherited branch evidence;
* champion branch, where available;
* challenger branches, where available;
* comparison artefacts, where available;
* branch-specific manual interventions.

---

### 7.5 Explicit limitations

The report should disclose missing evidence rather than hide it.

Examples:

* no OOT sample;
* no champion assignment;
* no champion rationale;
* no challenger comparison;
* no cutoff analysis;
* smoothing applied;
* zero-cell handling used;
* inherited branch evidence;
* missing manual intervention reasons.

---

### 7.6 Deterministic output

Given the same completed run directory, Cardre should regenerate materially identical report evidence.

Generated timestamps may differ, but report content, ordering, artefact references, hashes, and warning codes should be stable.

---

## 8. User Stories

### 8.1 Generate a champion report

As a modeller, I can generate a governance report for the selected champion branch.

Acceptance:

* champion assignment is resolved;
* champion rationale is included;
* comparison artefact is referenced;
* final scorecard is included;
* train validation metrics are included;
* report blocks if champion evidence is incomplete.

---

### 8.2 Generate a report for any branch

As a modeller, I can generate a report for a specific branch, even if it is not the champion.

Acceptance:

* target branch is clearly shown;
* missing champion assignment is a warning, not a blocker;
* inherited artefacts are disclosed;
* branch-specific final scorecard and metrics are used;
* report does not pretend the branch is champion.

---

### 8.3 Export an audit pack

As a modeller, I can export a branch audit pack containing the report and supporting artefacts.

Acceptance:

* existing Phase 4 export files remain;
* `report/report_bundle.json` is added;
* `report/report.html` is added;
* supporting report artefacts are added under `report_artifacts/`;
* checksums cover new files;
* raw datasets are not exported by default.

---

### 8.4 Review manual decisions

As a reviewer, I can see where the modeller manually changed the pathway.

Acceptance:

* manual bin edits are listed;
* variable exclusions are listed;
* bin merges/splits are listed;
* champion selection is listed where available;
* cutoff selection is listed where available;
* missing reasons are visible warnings.

---

### 8.5 Review WOE smoothing and zero-cell handling

As a reviewer, I can see how WOE smoothing was applied.

Acceptance:

* smoothing enabled/disabled is shown;
* smoothing method is shown;
* alpha is shown;
* zero-cell policy is shown;
* affected bins are shown;
* raw and final WOE are shown where available;
* report blocks if controlled WOE evidence is missing.

---

### 8.6 Reconstruct scorecard definition

As a reviewer, I can use the audit pack to reconstruct the final scorecard.

Acceptance:

* final bin definitions are exported;
* WOE values are exported;
* model coefficients are exported;
* intercept is exported;
* score scaling is exported;
* missing/unseen/out-of-range handling is exported where available.

---

## 9. Architecture

Phase 5 preserves the current local-first architecture:

```
Tauri shell
  React + TypeScript GUI
    local HTTP calls
      FastAPI sidecar
        Python scorecard engine
        SQLite metadata
        Parquet/JSON artefacts
        export_service.py
        reporting/
```

New reporting module:

```
sidecar/
  reporting/
    schema.py
    collector.py
    readiness.py
    renderer_html.py
    validators.py
```

Branch resolver:

```
sidecar/
  branching/
    step_resolver.py
```

Existing export service extended:

```
sidecar/
  export_service.py
```

---

## 10. Reporting Module Responsibilities

### 10.1 ReportCollector

The collector builds ReportBundle from immutable artefacts.

Responsibilities:

* load project/run metadata;
* resolve target branch;
* resolve canonical steps through branch resolver;
* load controlled WOE/IV evidence;
* load model artefacts;
* load scorecard artefacts;
* load validation metrics;
* load comparison artefacts;
* load champion assignment where available;
* load manual interventions;
* load execution fingerprints from run steps;
* generate warnings and limitations;
* produce deterministic report bundle.

The collector must not:

* hardcode generated step IDs;
* infer branch ancestry itself;
* read current GUI state;
* re-run modelling logic;
* re-read the current machine environment as if it were the model execution environment.

---

### 10.2 ReportBundle

The canonical machine-readable report object.

Responsibilities:

* stable schema version;
* stable ordering;
* evidence references;
* branch references;
* warnings and limitations;
* deterministic JSON serialization.

---

### 10.3 ReportReadiness

Validates whether a report can be generated.

Responsibilities:

* distinguish champion mode and branch mode;
* return blockers;
* return warnings;
* explain missing evidence in user-readable terms.

---

### 10.4 HtmlReportRenderer

Renders ReportBundle into self-contained offline HTML.

Responsibilities:

* embed CSS;
* render static tables;
* render warning callouts;
* render artefact references;
* avoid external network dependencies;
* avoid external JS/CSS;
* avoid interactive charts.

---

### 10.5 export_service.py

Owns audit-pack packaging.

Responsibilities:

* preserve existing Phase 4 audit-pack structure;
* call reporting collector;
* call HTML renderer;
* write report files into existing audit pack;
* add report artefacts;
* update artefact index;
* update checksums.

---

## 11. Report Bundle Schema

### 11.1 Top-level schema

```json
{
  "schema_version": "cardre.report_bundle.v1",
  "project_id": "string",
  "run_id": "string",
  "target_branch_id": "string",
  "report_mode": "branch",
  "generated_at": "iso_datetime",
  "generated_by": {
    "cardre_version": "0.1.0"
  },
  "source": {
    "run_manifest_path": "string",
    "run_manifest_hash": "string",
    "pathway_hash": "string",
    "artefact_root": "string"
  },
  "summary": {},
  "dataset_roles": [],
  "pathway": {},
  "branches": {},
  "champion": {},
  "variables": [],
  "model": {},
  "score_scaling": {},
  "validation": {},
  "cutoffs": {},
  "manual_interventions": [],
  "limitations": [],
  "reproducibility": {},
  "artefacts": []
}
```

### 11.2 summary

```json
{
  "model_name": "string",
  "target_column": "bad_flag",
  "observation_level": "account/application/customer",
  "development_sample": "train",
  "validation_samples": ["test", "oot"],
  "candidate_branch_count": 3,
  "target_branch_id": "challenger_a",
  "champion_branch_id": "main",
  "final_variable_count": 12,
  "excluded_variable_count": 18,
  "report_status": "complete_with_warnings"
}
```

### 11.3 dataset_roles

```json
{
  "role": "train",
  "dataset_id": "dataset_train_001",
  "row_count": 120000,
  "column_count": 84,
  "target": {
    "good_count": 114000,
    "bad_count": 6000,
    "bad_rate": 0.05
  },
  "date_range": {
    "min": "2022-01-01",
    "max": "2023-12-31"
  },
  "artefacts": []
}
```

Required role:

* train

Optional roles:

* test
* oot

Missing oot is a warning, not a blocker.

---

### 11.4 pathway

```json
{
  "pathway_id": "fixed_scorecard_pathway_v1",
  "steps": [
    {
      "canonical_step_id": "calculate_woe_iv",
      "step_id": "calculate-woe-iv__br_main",
      "branch_id": "main",
      "step_type": "calculate_woe_iv",
      "status": "complete",
      "config_hash": "sha256...",
      "resolution": "exact"
    }
  ]
}
```

Important:

* `canonical_step_id` must be present.
* generated branch-local `step_id` must be present.
* evidence inherited from an ancestor branch must be marked as `resolution: "ancestor"`.

---

### 11.5 branches

```json
{
  "branching_model": "plan_derived_lanes",
  "target_branch_id": "challenger_a",
  "branches": [
    {
      "branch_id": "main",
      "name": "Baseline",
      "parent_branch_id": null,
      "created_from_canonical_step_id": null,
      "is_target_branch": false,
      "is_champion": true,
      "status": "complete"
    },
    {
      "branch_id": "challenger_a",
      "name": "Alternative coarse binning",
      "parent_branch_id": "main",
      "created_from_canonical_step_id": "manual_binning",
      "is_target_branch": true,
      "is_champion": false,
      "status": "complete"
    }
  ]
}
```

---

### 11.6 champion

The champion schema must reflect the current Phase 4 implementation.

Do not invent unsupported selection modes such as `metric_rank` or `default`.

Schema:

```json
{
  "champion_status": "selected",
  "assignment_id": "champion_assignment_001",
  "champion_branch_id": "main",
  "comparison_artifact_id": "comparison_artifact_001",
  "rationale": "Selected due to stronger OOT Gini and simpler binning.",
  "selected_at": "iso_datetime",
  "target_branch_is_champion": true
}
```

If no champion assignment exists:

```json
{
  "champion_status": "not_available",
  "assignment_id": null,
  "champion_branch_id": null,
  "comparison_artifact_id": null,
  "rationale": null,
  "selected_at": null,
  "target_branch_is_champion": false
}
```

Warning code:

```
NO_CHAMPION_ASSIGNMENT
```

In champion report mode, missing champion assignment is a blocker.

In branch report mode, missing champion assignment is a warning.

---

### 11.7 variables

Each candidate/final variable should get a record.

```json
{
  "variable_name": "applicant_age",
  "role": "included",
  "branch_id": "challenger_a",
  "type": "numeric",
  "final_bin_count": 5,
  "iv": 0.126,
  "monotonicity_status": "monotonic",
  "manual_edits": true,
  "woe_smoothing": {
    "enabled": true,
    "method": "additive",
    "alpha": 0.5,
    "zero_cell_policy": "block",
    "smoothing_applied": true,
    "zero_cell_encountered": false,
    "affected_bin_count": 1
  },
  "source_step_refs": [
    {
      "requested_branch_id": "challenger_a",
      "resolved_branch_id": "main",
      "canonical_step_id": "calculate_woe_iv",
      "step_id": "calculate-woe-iv__br_main",
      "resolution": "ancestor"
    }
  ],
  "bins": [
    {
      "bin_id": "bin_001",
      "label": "<= 21",
      "lower": null,
      "upper": 21,
      "good_count": 3000,
      "bad_count": 180,
      "bad_rate": 0.0566,
      "woe": -0.12,
      "iv_contribution": 0.004
    }
  ],
  "affected_bins": [
    {
      "bin_id": "bin_001",
      "reason": "zero_bad",
      "raw_good_count": 120,
      "raw_bad_count": 0,
      "smoothed_good_count": 120.5,
      "smoothed_bad_count": 0.5,
      "raw_woe": null,
      "final_woe": -1.42
    }
  ],
  "artefacts": []
}
```

---

### 11.8 model

```json
{
  "model_type": "logistic_regression_scorecard",
  "branch_id": "challenger_a",
  "target": "bad_flag",
  "features": [
    {
      "variable_name": "applicant_age",
      "coefficient": -0.4321,
      "standard_error": 0.031,
      "p_value": 0.001,
      "included": true
    }
  ],
  "intercept": -2.154,
  "regularisation": null,
  "fit_dataset_role": "train",
  "fitting_config_hash": "sha256..."
}
```

---

### 11.9 score_scaling

```json
{
  "base_score": 600,
  "base_odds": "50:1",
  "pdo": 20,
  "factor": 28.8539,
  "offset": 487.123,
  "score_direction": "higher_is_better",
  "rounding": "nearest_integer",
  "min_score": 300,
  "max_score": 900
}
```

The report must include:

* base score;
* base odds;
* PDO;
* factor;
* offset;
* score direction;
* rounding treatment.

---

### 11.10 validation

Metrics must be reported by dataset role.

```json
{
  "metrics_by_role": [
    {
      "role": "train",
      "row_count": 120000,
      "auc": 0.742,
      "gini": 0.484,
      "ks": 0.361,
      "bad_rate": 0.05,
      "score_mean": 612.4,
      "score_min": 311,
      "score_max": 842
    },
    {
      "role": "oot",
      "row_count": 30000,
      "auc": 0.711,
      "gini": 0.422,
      "ks": 0.318,
      "bad_rate": 0.057
    }
  ],
  "stability": {
    "psi_by_role": [
      {
        "comparison": "train_vs_oot",
        "score_psi": 0.083
      }
    ]
  }
}
```

Minimum required metrics:

* row count;
* bad rate;
* AUC;
* Gini;
* KS;
* score distribution summary.

Optional metrics:

* PSI;
* decile table;
* calibration table;
* cutoff table;
* approval-rate table;
* population stability by variable.

---

### 11.11 cutoffs

```json
{
  "cutoff_tables": [
    {
      "role": "oot",
      "rows": [
        {
          "score_cutoff": 500,
          "approval_rate": 0.92,
          "bad_rate": 0.061,
          "capture_rate": 0.97
        }
      ]
    }
  ],
  "selected_cutoff": {
    "score": 540,
    "selection_reason": "Illustrative cutoff only; no production policy selected."
  }
}
```

The report must distinguish between:

* model development cutoff analysis;
* actual business policy selection.

Unless the user explicitly selected a policy cutoff, the report must not imply one was approved.

---

### 11.12 manual_interventions

```json
[
  {
    "intervention_id": "mi_001",
    "branch_id": "challenger_a",
    "canonical_step_id": "manual_binning",
    "step_id": "manual-binning__br_a81f3c",
    "type": "merge_bins",
    "variable_name": "applicant_age",
    "before_artifact": "artefacts/binning/applicant_age_auto.json",
    "after_artifact": "artefacts/binning/applicant_age_manual.json",
    "reason": "Merged sparse young-age bins for stability.",
    "created_at": "iso_datetime"
  }
]
```

Minimum intervention types:

* merge_bins;
* split_bin;
* rename_bin;
* exclude_variable;
* include_variable;
* force_monotonicity;
* override_missing_handling;
* select_champion;
* select_cutoff.

---

### 11.13 limitations

```json
[
  {
    "severity": "warning",
    "code": "NO_OOT_SAMPLE",
    "message": "No OOT dataset role was present for this run."
  },
  {
    "severity": "warning",
    "code": "NO_CHAMPION_ASSIGNMENT",
    "message": "No champion branch has been assigned for this run."
  },
  {
    "severity": "warning",
    "code": "INHERITED_BRANCH_EVIDENCE",
    "message": "Some evidence for the target branch was inherited from an ancestor branch."
  },
  {
    "severity": "info",
    "code": "PDF_OUT_OF_SCOPE",
    "message": "PDF export is not produced in Phase 5. JSON and HTML are canonical."
  }
]
```

Warnings should be deterministic and code-based.

Suggested warning catalogue:

```
NO_OOT_SAMPLE
NO_TEST_SAMPLE
NO_CHAMPION_ASSIGNMENT
MISSING_CHAMPION_RATIONALE
NO_CHALLENGER_COMPARISON
TARGET_BRANCH_NOT_CHAMPION
INHERITED_BRANCH_EVIDENCE
NO_CUTOFF_ANALYSIS
MISSING_MANUAL_INTERVENTION_REASON
SMOOTHING_APPLIED
ZERO_CELL_POLICY_USED
LEGACY_WOE_SUMMARY_USED
PDF_OUT_OF_SCOPE
```

Suggested blocker catalogue:

```
TARGET_BRANCH_NOT_FOUND
TARGET_BRANCH_INCOMPLETE
CHAMPION_ASSIGNMENT_MISSING
CHAMPION_BRANCH_INCOMPLETE
MISSING_REQUIRED_CANONICAL_STEP
MISSING_WOE_IV_EVIDENCE_V1
MISSING_FINAL_SCORECARD
MISSING_MODEL_COEFFICIENTS
MISSING_SCORE_SCALING
MISSING_TRAIN_VALIDATION_METRICS
MISSING_RUN_MANIFEST
MISSING_PATHWAY
ARTEFACT_HASH_UNRESOLVED
```

---

### 11.14 reproducibility

Do not read the current report-generation machine environment and present it as the model execution environment.

Use the existing run step `execution_fingerprint`.

```json
{
  "run_id": "run_123",
  "manifest_hash": "sha256...",
  "pathway_hash": "sha256...",
  "execution_fingerprints": [
    {
      "step_id": "fit-model__br_main",
      "canonical_step_id": "fit_model",
      "python_version": "3.12.x",
      "platform": "darwin",
      "package_fingerprint": {}
    }
  ],
  "report_generation": {
    "generated_at": "iso_datetime",
    "cardre_version": "0.1.0"
  }
}
```

Use current single source of version truth:

```json
{
  "generated_by": {
    "cardre_version": "0.1.0"
  }
}
```

Do not introduce separate `app_version` and `engine_version` until the codebase actually supports them.

---

## 12. Audit Pack Structure

Phase 5 extends the existing Phase 4 branch audit pack.

It does not replace it.

Recommended structure:

```
audit_pack/
  project.json
  branch.json
  run_steps.json
  comparison.json
  manifest.json
  artefact_index.json
  checksums.sha256
  report/
    report_bundle.json
    report.html
  report_artifacts/
    scorecard/
      final_scorecard.json
      final_scorecard.csv
      scoring_config.json
    model/
      coefficients.json
      score_scaling.json
      model_summary.json
    validation/
      metrics_by_role.json
      metrics_by_role.csv
      cutoff_tables.csv
      decile_tables.csv
    binning/
      variable_summary.csv
      woe_iv_evidence.json
      bins/
    pathway/
      pathway.json
      manual_interventions.json
    branches/
      branch_summary.json
      champion_comparison.json
```

Rules:

* preserve existing Phase 4 files;
* add report outputs under `report/`;
* add report-supporting files under `report_artifacts/`;
* do not export raw datasets by default;
* checksums must cover new report files;
* artefact index must include new report files.

---

## 13. API Specification

### 13.1 Report readiness

```
POST /projects/{project_id}/runs/{run_id}/report-readiness
```

Request:

```json
{
  "target_branch_id": "challenger_a",
  "report_mode": "branch",
  "include_challenger_comparison": true
}
```

Response:

```json
{
  "ready": true,
  "status": "ready_with_warnings",
  "blockers": [],
  "warnings": [
    {
      "code": "NO_CHAMPION_ASSIGNMENT",
      "message": "No champion branch has been assigned for this run."
    }
  ]
}
```

Supported report modes:

* `champion`
* `branch`

**Champion mode blockers**

Block if:

* no champion assignment exists;
* champion branch is incomplete;
* champion branch missing required artefacts;
* final scorecard missing;
* model coefficients missing;
* score scaling missing;
* train validation metrics missing;
* controlled WOE/IV evidence missing.

**Branch mode blockers**

Block if:

* target branch does not exist;
* target branch incomplete;
* target branch cannot resolve required canonical steps;
* final scorecard missing for target branch;
* model coefficients missing for target branch;
* score scaling missing for target branch;
* train validation metrics missing for target branch;
* controlled WOE/IV evidence missing for target branch.

**Branch mode warnings**

Warn, but do not block, if:

* no champion assignment exists;
* no champion rationale exists;
* no challenger comparison exists;
* target branch is not champion;
* no OOT sample exists;
* no cutoff analysis exists;
* evidence is inherited from ancestor branch.

---

### 13.2 Generate report

```
POST /projects/{project_id}/runs/{run_id}/reports
```

Request:

```json
{
  "target_branch_id": "challenger_a",
  "report_mode": "branch",
  "include_challenger_comparison": true,
  "include_supporting_artifacts": true,
  "output_formats": ["json", "html"],
  "export_zip": true
}
```

Response:

```json
{
  "report_id": "report_001",
  "status": "complete_with_warnings",
  "report_bundle_path": "audit_pack/report/report_bundle.json",
  "html_path": "audit_pack/report/report.html",
  "export_path": "exports/cardre_audit_pack_run_001",
  "zip_path": "exports/cardre_audit_pack_run_001.zip",
  "warnings": [
    {
      "code": "NO_OOT_SAMPLE",
      "message": "No OOT dataset role was present for this run."
    }
  ]
}
```

### 13.3 Get report metadata

```
GET /projects/{project_id}/runs/{run_id}/reports/{report_id}
```

Response:

```json
{
  "report_id": "report_001",
  "created_at": "iso_datetime",
  "target_branch_id": "challenger_a",
  "report_mode": "branch",
  "html_path": "audit_pack/report/report.html",
  "bundle_path": "audit_pack/report/report_bundle.json",
  "export_path": "exports/cardre_audit_pack_run_001",
  "zip_path": "exports/cardre_audit_pack_run_001.zip",
  "status": "complete_with_warnings"
}
```

---

## 14. GUI Specification

Phase 5 extends the existing ExportPanel.tsx.

It should not introduce a disconnected report-generation screen.

Recommended structure:

```
ExportPanel.tsx
  ReportReadinessPanel.tsx
  GenerateReportButton.tsx
  GeneratedReportList.tsx
  ExportWarnings.tsx
```

The UI should align with existing state handling used by StepInspector and TopBar.

---

### 14.1 Export panel content

The export panel should show:

```
Audit Pack Export
Report mode:
[ Champion report | Branch report ]
Target branch:
[ Main baseline v3 ]
Readiness:
✓ Final scorecard available
✓ Model coefficients available
✓ Train validation metrics available
✓ WOE/IV evidence available
⚠ No OOT sample
⚠ Target branch is not champion
[ Generate audit pack ]
Generated reports:
------------------------------------------------
Created              Branch          Format       Status
2026-06-13 22:10     challenger_a    HTML, JSON   Complete with warnings
[Open report] [Reveal folder] [Export zip]
```

### 14.2 UI states

Required states:

* Blocked
* Ready with warnings
* Ready
* Generating
* Generated
* Failed

Rules:

* blocked reports cannot be generated;
* warnings are visible before generation;
* warning codes are visible in generated report;
* generated reports remain visible in export history.

---

## 15. HTML Report Specification

The HTML report is static, self-contained, and offline.

It must not include:

* external CSS;
* external JS;
* remote fonts;
* Chart.js;
* interactive charts;
* CDN links.

The renderer should produce readable, governance-style tables.

---

### 15.1 Required sections

Recommended report order:

1. Executive summary
2. Data overview
3. Development pathway
4. Branch and champion selection
5. Candidate variable treatment
6. Manual binning and overrides
7. WOE/IV evidence
8. Final scorecard model
9. Score scaling
10. Validation results
11. Cutoff analysis
12. Limitations and warnings
13. Reproducibility manifest
14. Artefact index

### 15.2 Executive summary

Should include:

* project name;
* run ID;
* target branch;
* report mode;
* champion branch, where available;
* target column;
* final variable count;
* train/test/OOT availability;
* headline metrics;
* warning count;
* blocker count should always be zero for generated reports.

---

### 15.3 Branch and champion selection

Should include:

* all branches;
* target branch;
* champion branch, where available;
* comparison artefact ID, where available;
* champion rationale, where available;
* target branch champion status;
* inherited evidence warnings.

Example table:

| Branch | Train Gini | Test Gini | OOT Gini | Variables | Manual edits | Status |
|--------|-----------|----------|---------|-----------|-------------|--------|
| Main | 0.48 | 0.45 | 0.42 | 12 | 8 | Champion |
| Challenger A | 0.51 | 0.43 | 0.38 | 16 | 14 | Target branch |

---

### 15.4 Manual binning and overrides

This should be a major section, not an appendix.

Render as tables.

Example:

```
Variable: applicant_age

Automatic bins
Bin        Good   Bad   Bad rate   WOE     IV contrib
<=21       3000   180   5.66%      -0.12   0.004

Final bins
Bin        Good   Bad   Bad rate   WOE     IV contrib   Manual change
<=25       5200   260   5.00%      -0.18   0.009        merged bins 1-2
```

No required charts in Phase 5.

---

### 15.5 WOE/IV evidence

The report must render:

* smoothing enabled;
* smoothing method;
* alpha;
* zero-cell policy;
* variables affected;
* affected bins;
* raw counts;
* smoothed counts;
* raw WOE, where available;
* final WOE.

Example:

| Variable | Smoothing applied | Alpha | Zero-cell policy | Affected bins |
|----------|-----------------|-------|-----------------|--------------|
| applicant_age | Yes | 0.5 | block | 1 |
| income_band | No | 0.5 | block | 0 |

Affected-bin detail:

| Variable | Bin | Reason | Raw good | Raw bad | Smoothed good | Smoothed bad | Final WOE |
|----------|-----|--------|---------|--------|--------------|-------------|----------|
| applicant_age | <=21 | zero_bad | 120 | 0 | 120.5 | 0.5 | -1.42 |

---

### 15.6 Limitations and warnings

Warnings must be visible in the report, not buried.

Example:

```
Warning: NO_OOT_SAMPLE
No OOT dataset role was present for this run.

Warning: NO_CHAMPION_ASSIGNMENT
No champion branch has been assigned for this run.
```

---

## 16. Validation Rules

### 16.1 Blocking checks

Block report generation when required evidence is missing.

Blockers:

```
TARGET_BRANCH_NOT_FOUND
TARGET_BRANCH_INCOMPLETE
CHAMPION_ASSIGNMENT_MISSING
CHAMPION_BRANCH_INCOMPLETE
MISSING_REQUIRED_CANONICAL_STEP
MISSING_WOE_IV_EVIDENCE_V1
MISSING_FINAL_SCORECARD
MISSING_MODEL_COEFFICIENTS
MISSING_SCORE_SCALING
MISSING_TRAIN_VALIDATION_METRICS
MISSING_RUN_MANIFEST
MISSING_PATHWAY
ARTEFACT_HASH_UNRESOLVED
```

### 16.2 Warning checks

Warn but allow report generation when non-critical evidence is missing.

Warnings:

```
NO_OOT_SAMPLE
NO_TEST_SAMPLE
NO_CHAMPION_ASSIGNMENT
MISSING_CHAMPION_RATIONALE
NO_CHALLENGER_COMPARISON
TARGET_BRANCH_NOT_CHAMPION
INHERITED_BRANCH_EVIDENCE
NO_CUTOFF_ANALYSIS
MISSING_MANUAL_INTERVENTION_REASON
SMOOTHING_APPLIED
ZERO_CELL_POLICY_USED
LEGACY_WOE_SUMMARY_USED
PDF_OUT_OF_SCOPE
```

---

## 17. Testing Strategy

### 17.1 Unit tests

Add tests for:

* woe_iv_evidence.v1 creation;
* branch step resolver;
* exact branch step resolution;
* inherited ancestor step resolution;
* report schema validation;
* report readiness;
* champion mode blocking;
* branch mode warning behaviour;
* report collector;
* manual intervention extraction;
* WOE smoothing extraction;
* limitation generation;
* artefact index generation;
* checksum generation.

---

### 17.2 Fixture tests

Fixtures:

* single_branch_complete/
* champion_with_challenger/
* challenger_without_champion_assignment/
* inherited_branch_evidence/
* missing_oot_warning/
* missing_champion_reason_warning/
* missing_woe_evidence_blocker/
* smoothing_applied/
* zero_cell_blocked/

Each fixture should test deterministic report-bundle generation.

---

### 17.3 Golden JSON tests

Use golden assertions for:

* expected_report_bundle.json
* expected_limitations.json
* expected_artefact_index.json

The JSON bundle is the main assertion surface.

---

### 17.4 Structural HTML tests

Do not full-DOM diff the HTML.

Instead assert:

* Executive summary section exists;
* Branch and champion selection section exists when branch metadata exists;
* Manual binning and overrides section exists;
* WOE/IV evidence section exists;
* Limitations and warnings section exists;
* manifest hash appears;
* target branch ID appears;
* warning codes render;
* smoothing evidence renders;
* inherited branch references render;
* no champion assignment warning renders in branch mode where relevant;
* no external script references exist;
* no external stylesheet references exist.

---

### 17.5 GUI tests

Minimal GUI tests:

* ExportPanel.tsx renders report readiness;
* blocked state disables generate button;
* warning state allows generation;
* branch/champion mode selector works;
* generated report appears in history;
* open report action is wired;
* reveal folder action is wired.

---

## 18. Definition of Done

Phase 5 is complete when:

1. CalculateWoeIvNode emits cardre.woe_iv_evidence.v1.
2. Report collector uses branch resolver, not hardcoded step IDs.
3. Reports can target champion or arbitrary branch.
4. Missing champion assignment blocks champion mode but only warns in branch mode.
5. Champion schema reflects current champion_service.py.
6. report_bundle.json is generated deterministically.
7. report.html is generated as self-contained offline HTML.
8. HTML rendering is table-first.
9. No PDF export exists in Phase 5.
10. Existing export_service.py owns audit-pack export.
11. Phase 4 export structure is preserved.
12. Report files are added under report/.
13. Supporting artefacts are added under report_artifacts/.
14. Environment metadata comes from execution fingerprints.
15. Structural HTML tests exist.
16. Golden report bundle tests exist.
17. Frontend report generation is integrated into ExportPanel.tsx.
18. No report content is generated from transient GUI state.

---

## 19. Attack Implementation Plan

The goal is to parallelise as much work as possible into as few batches as possible.

The recommended structure is:

```
Pre-flight hardening
Batch 1: backend contracts, collector, readiness, export integration
Batch 2: renderer, GUI, tests, packaging polish
```

---

## 20. Pre-flight Hardening

This is mandatory before the main Phase 5 build starts.

### Workstream A — WOE/IV evidence boundary

Implement:

```
cardre.woe_iv_evidence.v1
```

Tasks:

1. Update CalculateWoeIvNode to emit woe_iv_evidence.json.
2. Include smoothing config.
3. Include smoothing method.
4. Include smoothing alpha.
5. Include zero-cell policy.
6. Include affected bins.
7. Include raw and smoothed counts where applicable.
8. Include final WOE and IV values.
9. Register artefact in normal run artefact store.
10. Add tests for smoothed and non-smoothed cases.

Acceptance:

> Given a completed WOE/IV step, a collector can find exactly one controlled WOE evidence artefact without parsing an uncontrolled summary shape.

---

### Workstream B — Shared branch step resolver

Implement or extract:

```
sidecar/branching/step_resolver.py
```

Tasks:

1. Wrap branch_step_map lookup.
2. Reuse ancestor resolution logic from PlanService.
3. Return exact versus inherited step resolution.
4. Return generated step ID.
5. Return canonical step ID.
6. Return resolved branch ID.
7. Return artefact IDs associated with the resolved step.
8. Add tests for main branch, challenger branch, and inherited ancestor evidence.

Acceptance:

> Given `branch_id` + `canonical_step_id`, the resolver returns the correct generated `step_id` for both exact and inherited branch evidence.

---

### Workstream C — Export service decision

Update implementation direction:

> Phase 5 extends export_service.py.
> No parallel packager entry point.

Tasks:

1. Inspect current export_branch_audit_pack structure.
2. Preserve existing export files.
3. Reserve report/ directory.
4. Reserve report_artifacts/ directory.
5. Add export manifest version marker if missing.
6. Add tests proving Phase 4 audit pack still works.

Acceptance:

> There is one audit-pack export path in the codebase.

---

## 21. Batch 1 — Backend Contracts, Collector, Readiness, Export Integration

Batch 1 can start after pre-flight hardening passes.

The goal of Batch 1 is to produce report_bundle.json through the backend and existing export service.

---

### Workstream 1 — Report schema

Build:

```
sidecar/reporting/schema.py
```

Tasks:

1. Define ReportBundle.
2. Define ResolvedStepRef.
3. Define dataset-role summary.
4. Define pathway summary.
5. Define branch summary.
6. Define champion status schema.
7. Define WOE/IV evidence reference schema.
8. Define variable summary.
9. Define model summary.
10. Define score scaling summary.
11. Define validation summary.
12. Define cutoff summary.
13. Define manual intervention summary.
14. Define limitation/warning schema.
15. Define reproducibility schema based on execution fingerprints.

Acceptance:

> ReportBundle serializes deterministically and validates against cardre.report_bundle.v1.

---

### Workstream 2 — Report collector

Build:

```
sidecar/reporting/collector.py
```

Tasks:

1. Load project metadata.
2. Load run metadata.
3. Resolve target branch using shared branch resolver.
4. Resolve canonical steps to generated branch-scoped step IDs.
5. Load WOE/IV evidence v1.
6. Load model artefacts.
7. Load scorecard artefacts.
8. Load score-scaling artefacts.
9. Load validation metrics.
10. Load comparison artefact via comparison_artifact_id.
11. Load champion assignment if available.
12. Load manual interventions.
13. Load execution fingerprints from run steps.
14. Generate limitations and warnings.
15. Produce ReportBundle.

Acceptance:

> Collector works for:
> - champion branch;
> - challenger branch;
> - branch with inherited ancestor evidence;
> - branch with no champion assignment.

---

### Workstream 3 — Readiness validator

Build:

```
sidecar/reporting/readiness.py
```

Tasks:

1. Add report_mode.
2. Add target_branch_id.
3. Implement champion-mode blockers.
4. Implement branch-mode blockers.
5. Implement warning catalogue.
6. Return structured blockers.
7. Return structured warnings.
8. Add user-readable messages.

Acceptance:

> Champion reports block without champion assignment.
> Branch reports warn, but do not block, without champion assignment.

---

### Workstream 4 — API endpoints

Build:

```
sidecar/api/reports.py
```

Endpoints:

```
POST /projects/{project_id}/runs/{run_id}/report-readiness
POST /projects/{project_id}/runs/{run_id}/reports
GET  /projects/{project_id}/runs/{run_id}/reports/{report_id}
```

Tasks:

1. Wire readiness endpoint.
2. Wire report generation endpoint.
3. Persist generated report metadata.
4. Return existing export-service paths.
5. Return warnings and blockers in frontend-friendly form.
6. Add endpoint tests.

Acceptance:

> API can generate report_bundle.json for a target branch without the GUI knowing step IDs.

---

### Workstream 5 — Extend export_service.py

Tasks:

1. Call report collector.
2. Write report/report_bundle.json.
3. Preserve existing Phase 4 audit-pack files.
4. Copy report-supporting artefacts into report_artifacts/.
5. Add report files to artefact index.
6. Add report files to checksum generation.
7. Add tests for extended audit pack.

Acceptance:

> Phase 4 audit pack still works, and Phase 5 report files are added without a second export path.

---

### Batch 1 Merge Gate

Batch 1 is done when:

* controlled WOE evidence exists;
* branch resolver works;
* report readiness works;
* collector produces report_bundle.json;
* export service writes report/report_bundle.json;
* champion mode works;
* branch mode works;
* inherited branch evidence is handled;
* missing champion assignment behaves correctly by report mode.

---

## 22. Batch 2 — Renderer, GUI, Tests, Packaging Polish

Batch 2 turns the backend report bundle into a user-visible export experience.

---

### Workstream 1 — Table-first HTML renderer

Build:

```
sidecar/reporting/renderer_html.py
sidecar/reporting/templates/report.html.j2
```

Tasks:

1. Render self-contained HTML.
2. Embed CSS.
3. Render executive summary.
4. Render data overview.
5. Render development pathway.
6. Render branch/champion section.
7. Render manual binning tables.
8. Render WOE/IV evidence tables.
9. Render smoothing and zero-cell policy.
10. Render affected-bin tables.
11. Render model coefficients.
12. Render score scaling.
13. Render validation tables.
14. Render cutoff tables where available.
15. Render limitations/warnings.
16. Render reproducibility manifest.
17. Render artefact index.
18. Ensure no external JS/CSS.

Acceptance:

> HTML opens offline and contains all required evidence in static tables.

---

### Workstream 2 — ExportPanel integration

Extend:

```
ExportPanel.tsx
```

Add children:

```
ReportReadinessPanel.tsx
GenerateReportButton.tsx
GeneratedReportList.tsx
ExportWarnings.tsx
```

Tasks:

1. Add report mode selector.
2. Add target branch selector.
3. Show blockers.
4. Show warnings.
5. Disable generate button when blocked.
6. Allow generation when ready with warnings.
7. Generate audit pack through existing export flow.
8. Show generated report history.
9. Add open report action.
10. Add reveal folder action.
11. Add failed state.

Acceptance:

> User can generate and open a Phase 5 report from the existing export UI.

---

### Workstream 3 — Test fixtures

Create fixtures:

* single_branch_complete/
* champion_with_challenger/
* challenger_without_champion_assignment/
* inherited_branch_evidence/
* missing_oot_warning/
* missing_champion_reason_warning/
* missing_woe_evidence_blocker/
* smoothing_applied/
* zero_cell_blocked/

Acceptance:

> Each fixture has deterministic expected report_bundle.json assertions.

---

### Workstream 4 — HTML structural tests

Tasks:

1. Assert required headings exist.
2. Assert warning codes render.
3. Assert manifest hash renders.
4. Assert target branch renders.
5. Assert smoothing evidence renders.
6. Assert inherited branch step reference renders.
7. Assert no external script references exist.
8. Assert no external stylesheet references exist.
9. Assert no champion assignment warning renders in branch mode where relevant.

Acceptance:

> HTML renderer correctness is covered without brittle full-file snapshots.

---

### Workstream 5 — Packaging and cross-platform checks

Tasks:

1. Verify packaged app can write report files.
2. Verify exported HTML opens outside Cardre.
3. Verify paths work on macOS.
4. Verify paths work on Windows.
5. Verify paths work on Linux.
6. Verify zip export if already supported by existing export flow.
7. Verify no external network resources are required.
8. Verify no PDF dependency has been introduced.

Acceptance:

> A user can export, open, and share the audit pack without Cardre running.

---

### Workstream 6 — Documentation

Tasks:

1. Document cardre.report_bundle.v1.
2. Document cardre.woe_iv_evidence.v1.
3. Document branch step resolution.
4. Document report readiness modes.
5. Document extended audit-pack structure.
6. Document warning and blocker catalogue.
7. Document PDF as out of scope.
8. Add user-facing help copy explaining what the audit pack contains.

Acceptance:

> A developer can add report sections later without reverse-engineering the collector.
> A user can understand what the exported audit pack means.

---

### Batch 2 Merge Gate

Batch 2 is done when:

1. report.html is produced from report_bundle.json.
2. HTML is self-contained and offline.
3. HTML is table-first.
4. ExportPanel.tsx supports report readiness and generation.
5. Existing audit-pack export includes report files.
6. Structural HTML tests pass.
7. Golden JSON tests pass.
8. Packaged app can generate and open report output.
9. PDF remains out of scope.

---

## 23. Recommended Issue Breakdown

### Epic: Phase 5 Governance Report and Audit Pack

**Pre-flight**

1. Add cardre.woe_iv_evidence.v1.
2. Emit WOE/IV evidence from CalculateWoeIvNode.
3. Add smoothing and zero-cell affected-bin tests.
4. Extract shared branch step resolver.
5. Add exact branch step resolution tests.
6. Add inherited branch evidence tests.
7. Confirm Phase 5 extends export_service.py.

**Backend**

8. Add ReportBundle schema v1.
9. Add ResolvedStepRef schema.
10. Add report warning/blocker catalogue.
11. Add report readiness validator.
12. Add report collector.
13. Add dataset-role collector.
14. Add pathway collector.
15. Add branch/champion collector.
16. Add WOE/IV evidence collector.
17. Add model artefact collector.
18. Add scorecard artefact collector.
19. Add score scaling collector.
20. Add validation metrics collector.
21. Add cutoff analysis collector.
22. Add manual intervention collector.
23. Add reproducibility collector from execution fingerprints.
24. Add report API endpoints.
25. Extend export_service.py.
26. Add artefact index entries for report files.
27. Add checksums for report files.

**Frontend**

28. Extend ExportPanel.tsx.
29. Add ReportReadinessPanel.tsx.
30. Add GenerateReportButton.tsx.
31. Add GeneratedReportList.tsx.
32. Add ExportWarnings.tsx.
33. Add report mode selector.
34. Add target branch selector.
35. Add blocked/ready/generating/generated/failed states.
36. Add open report action.
37. Add reveal folder action.

**Rendering**

38. Add table-first HTML renderer.
39. Add embedded CSS.
40. Render executive summary.
41. Render data overview.
42. Render branch/champion section.
43. Render manual intervention tables.
44. Render WOE/IV evidence tables.
45. Render model and scorecard sections.
46. Render validation sections.
47. Render limitations/warnings.
48. Render reproducibility manifest.
49. Render artefact index.

**Tests**

50. Add single-branch fixture.
51. Add champion/challenger fixture.
52. Add challenger-without-champion fixture.
53. Add inherited-evidence fixture.
54. Add missing-OOT fixture.
55. Add missing-champion-rationale fixture.
56. Add missing-WOE-evidence blocker fixture.
57. Add smoothing-applied fixture.
58. Add zero-cell fixture.
59. Add golden report-bundle tests.
60. Add structural HTML tests.
61. Add API integration tests.
62. Add GUI tests.
63. Add export-service regression tests.

**Documentation**

64. Document report schema.
65. Document WOE/IV evidence schema.
66. Document branch resolver contract.
67. Document readiness endpoint.
68. Document audit-pack extension.
69. Document warning/blocker catalogue.
70. Document PDF out-of-scope decision.

---

## 24. Dependency Map

```
Pre-flight WOE evidence ─────┐
                             ├─→ Report collector ─→ Report bundle ─→ HTML renderer
Branch step resolver ────────┘             │                  │
                                           │                  └─→ Structural HTML tests
Export-service decision ───────────────────┘
                                           │
                                           └─→ Extended audit pack
                                                        │
                                                        └─→ ExportPanel integration
```

Critical path:

```
WOE evidence schema
→ branch resolver
→ report schema
→ collector
→ readiness
→ export service integration
→ HTML renderer
→ ExportPanel integration
→ tests
```

Parallelisable after pre-flight:

* report schema;
* readiness;
* API endpoint scaffolding;
* frontend mocked UI;
* HTML template skeleton;
* fixture design;
* documentation skeleton.

---

## 25. Final Phase 5 Acceptance Test

The strongest end-to-end test should be:

> Given a completed run directory with a target branch, inherited ancestor evidence, WOE smoothing, a comparison artefact, and a champion assignment, Cardre can generate an audit pack containing a deterministic report_bundle.json and self-contained report.html without reading GUI state, hardcoding step IDs, or re-running modelling logic.

A second critical test should be:

> Given a completed challenger branch with no champion assignment, Cardre can generate a branch-mode report with a NO_CHAMPION_ASSIGNMENT warning, but champion-mode report generation is blocked.

Together, these tests prove Phase 5 is correctly aligned with Phase 4's branch model and Cardre's wider governance claim.

---

## 26. Final Summary

Phase 5 should ship as a disciplined reporting layer, not a reporting product detour.

The corrected implementation is:

```
controlled evidence schemas
+ branch-aware canonical step resolution
+ existing audit-pack export path
+ JSON-first report bundle
+ static offline HTML
+ explicit warnings
```

This keeps Cardre focused on its strongest product claim:

> visible, editable, branchable, reproducible, and exportable scorecard modelling for audit.
