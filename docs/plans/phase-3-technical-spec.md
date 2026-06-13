# Cardre Phase 3 Technical Specification

## Fixed Pathway Desktop GUI, reconciled to current repo state

---

## 1. Purpose

Phase 3 turns the completed Phase 2 scorecard engine into the first usable Cardre desktop workspace.

This phase does not add new scorecard modelling capability. It wraps the existing local engine, SQLite project store, Parquet/JSON artefact model, FastAPI sidecar, and fixed scorecard pathway in a Tauri/React desktop GUI.

By the end of Phase 3, a modeller should be able to:

* create or open a local Cardre project
* import a local dataset
* see the actual registered Scorecard Pathway
* configure node parameters through the UI
* run the pathway
* inspect node status, stale state, warnings, errors, and artefacts
* edit manual binning overrides through a table-based editor
* rerun stale downstream steps
* view validation and cutoff outputs
* export the technical manifest/audit evidence available from the current engine

The central product claim remains:

Cardre makes the scorecard modelling journey visible, editable, reproducible, and exportable.

Phase 3 is therefore a productisation and workflow phase, not another modelling-engine phase.

---

## 2. Product boundary

Phase 3 should produce the first credible desktop modelling experience over the Phase 2 engine.

It should not expand into branching, champion/challenger comparison, governance-quality report writing, plugin support, or freeform graph editing.

The fixed pathway desktop GUI should prove that the existing engine and artefact model can support a real workflow:

```
Create/open project
-> Import dataset
-> Configure fixed scorecard pathway
-> Run pathway
-> Inspect outputs
-> Edit manual binning overrides
-> Rerun stale downstream steps
-> Review validation/cutoff outputs
-> Export technical manifest
```

The user should not need to touch Python, SQLite, Parquet files, JSON artefacts, or FastAPI routes directly.

---

## 3. Repo reconciliation principles

Phase 3 must build on the actual repository state, not an idealised future API.

The GUI must:

* use actual pathway step IDs from `sidecar/proof_pathway.py`
* distinguish internal step IDs from human-facing display labels
* account for the hidden `__import__` plan used by dataset import
* add missing plan-list and artefact-preview/list APIs explicitly
* handle the current synchronous `/runs` behaviour honestly
* fix the Tauri shell build issue before extending the frontend
* treat the current React scaffold as a minimal prototype that will be substantially reworked
* build the manual binning editor around upstream artefact resolution, not only around current step params
* correct the technical manifest step ordering for newly created projects

Phase 3A is therefore a repo reconciliation slice as much as a GUI slice.

---

## 4. Current repo baseline

Phase 3 starts from this baseline:

```
sidecar/
  main.py
  routes/
    projects.py
    datasets.py
    plans.py
    runs.py
    artifacts.py
  proof_pathway.py
cardre/
  store.py
  executor.py
  registry.py
  nodes.py
  artifacts.py
  audit.py
frontend/
  src/
    components/
      WelcomeScreen
      ProjectView
      StepCardGrid
      StepCard
      ArtifactList
      ProfileOutput
  src-tauri/
    src/main.rs
```

Current backend characteristics:

* project creation registers both Proof Pathway and Scorecard Pathway
* Scorecard Pathway is built from Phase 2A, Phase 2B, and Phase 2C config lists
* dataset import runs through a hidden `__import__` plan
* after import, the import step params are updated in the proof and scorecard pathways
* `GET /plans/{plan_id}` exists
* `GET /plans` does not currently exist
* `GET /artifacts/{artifact_id}` exists
* artefact list and artefact preview endpoints do not currently exist
* `POST /runs` currently executes synchronously and returns only after execution completes

Current frontend characteristics:

* the existing React UI is Phase 1B-level scaffolding
* ProjectView tries to call `/plans`, which is not implemented
* ProjectView tries to call `/artifacts`, which is not implemented
* the layout is a simple centred project page, not the intended modelling workspace
* Phase 3 should treat the scaffold as something to rework, not merely decorate

---

## 5. Non-goals

Phase 3 must not implement:

* freeform DAG editing
* branch duplication
* champion/challenger comparison
* segment-specific challenger workflows
* rich governance-quality human-readable model development report
* formal model approval workflow
* plugin API
* hosted/cloud execution
* multi-user collaboration
* SQL/Python scoring export beyond existing internal artefacts
* PMML/ONNX export
* reject inference
* drag-and-drop bin boundary editing
* report designer
* row-level audit export by default

Branching belongs to Phase 4. Governance-quality report generation belongs to Phase 5. Extensibility belongs to Phase 6.

---

## 6. Phase 3A blocker: fix Tauri shell before GUI expansion

Phase 3A must start by fixing the Tauri shell.

The current `frontend/src-tauri/src/main.rs` should be rewritten so sidecar stdout and stderr are taken from `child.stdout` and `child.stderr` directly, rather than attempting borrow logic that will not compile cleanly.

Required pattern:

```rust
if let Some(stdout) = child.stdout.take() {
    let reader = BufReader::new(stdout);
    thread::spawn(move || {
        for line in reader.lines() {
            if let Ok(l) = line {
                eprintln!("[sidecar] {}", l);
            }
        }
    });
}
if let Some(stderr) = child.stderr.take() {
    let reader = BufReader::new(stderr);
    thread::spawn(move || {
        for line in reader.lines() {
            if let Ok(l) = line {
                eprintln!("[sidecar:err] {}", l);
            }
        }
    });
}
```

Acceptance criteria:

* `cargo check` passes for the Tauri app
* sidecar process starts
* `/health` is reached
* stdout and stderr are captured without borrow/ownership errors
* sidecar is killed when the window closes
* startup failure shows a useful diagnostic message

No Phase 3 GUI work should be considered reliable until this is fixed.

---

## 7. Correct Scorecard Pathway contract

The Phase 3 pathway view must use actual step IDs.

The UI may show friendly display labels, but the implementation must never depend on display labels. All API calls, route params, selection state, run evidence, editor logic, and tests must use `step_id`.

### 7.1 Corrected target pathway order

The current backend has `technical-manifest-stub` positioned before the Phase 2B and Phase 2C steps because it is currently included inside the Phase 2A config list. This should be corrected in Phase 3A for newly created projects.

Target effective order:

| Target position | Step ID | Display label | Node type |
|---|---|---|---|
| 0 | `import` | Import Dataset | `cardre.import_dataset` |
| 1 | `define-metadata` | Define Modelling Metadata | `cardre.define_modelling_metadata` |
| 2 | `apply-exclusions` | Apply Exclusions | `cardre.apply_exclusions` |
| 3 | `profile` | Profile Dataset | `cardre.profile_dataset` |
| 4 | `validate-target` | Validate Binary Target | `cardre.validate_binary_target` |
| 5 | `sample-definition` | Development Sample Definition | `cardre.development_sample_definition` |
| 6 | `split` | Train/Test/OOT Split | `cardre.split_train_test_oot` |
| 7 | `explicit-missing-outlier-treatment` | Explicit Missing/Outlier Treatment | `cardre.explicit_missing_outlier_treatment` |
| 8 | `fine-classing` | Automatic Fine Classing | `cardre.fine_classing` |
| 9 | `initial-woe-iv` | Initial WOE/IV Diagnostics | `cardre.calculate_woe_iv` |
| 10 | `variable-clustering` | Variable Clustering | `cardre.variable_clustering` |
| 11 | `variable-selection` | Variable Selection | `cardre.variable_selection` |
| 12 | `manual-binning` | Manual Bin Editing | `cardre.manual_binning` |
| 13 | `final-woe-iv` | Final WOE/IV Calculation | `cardre.calculate_woe_iv` |
| 14 | `woe-transform-train` | WOE Transform Train | `cardre.woe_transform_train` |
| 15 | `logistic-regression` | Logistic Regression | `cardre.logistic_regression` |
| 16 | `score-scaling` | Score Scaling | `cardre.score_scaling` |
| 17 | `build-summary-report` | Build Summary Report | `cardre.build_summary_report` |
| 18 | `apply-woe` | Apply WOE Mapping | `cardre.apply_woe_mapping` |
| 19 | `apply-model` | Apply Model | `cardre.apply_model` |
| 20 | `validation-metrics` | Validation Metrics by Role | `cardre.validation_metrics` |
| 21 | `cutoff-analysis` | Cutoff / Strategy Analysis | `cardre.cutoff_analysis` |
| 22 | `technical-manifest-stub` | Technical Manifest Stub | `cardre.technical_manifest_export` |

### 7.2 Step-ID rules

The UI must not invent new step IDs.

Examples:

* use `apply-woe`, not `apply-woe-mapping`
* use `apply-model`, not `score-model`
* use `technical-manifest-stub`, not `audit-export`, unless the backend step is renamed in a deliberate migration
* use `explicit-missing-outlier-treatment`, not `missing-outlier-treatment`

### 7.3 Display grouping

The GUI can group steps differently from their physical order, but should preserve backend position order within each group.

Suggested sections:

```
Project Definition
  import
  define-metadata
  apply-exclusions
  profile
  validate-target
  sample-definition

Split and Preparation
  split
  explicit-missing-outlier-treatment

Binning and Selection
  fine-classing
  initial-woe-iv
  variable-clustering
  variable-selection
  manual-binning
  final-woe-iv

Model Build
  woe-transform-train
  logistic-regression
  score-scaling
  build-summary-report

Validation and Strategy
  apply-woe
  apply-model
  validation-metrics
  cutoff-analysis

Export Evidence
  technical-manifest-stub
```

### 7.4 Frontend display metadata

Phase 3A should create explicit frontend display metadata keyed by real `step_id`.

```typescript
type StepDisplayMetadata = {
  stepId: string;
  expectedBackendPosition: number;
  displayOrder: number;
  section: string;
  label: string;
  shortDescription: string;
};
```

For new projects after the manifest-order fix, `expectedBackendPosition` and `displayOrder` should match.

Acceptance criteria:

* every known Scorecard Pathway step has display metadata
* display metadata is keyed by `step_id`
* the UI does not infer identity from labels
* tests fail if a backend step appears without display metadata
* tests fail if expected step IDs are missing from a newly created Scorecard Pathway

---

## 8. Technical manifest positioning fix

### 8.1 Problem

The current pathway places `technical-manifest-stub` before Phase 2B and Phase 2C steps.

This is confusing in the GUI because a modeller will see the manifest before WOE transform, logistic regression, scoring, validation metrics, and cutoff analysis.

It may also produce incomplete manifest evidence if the manifest executes before later run steps have completed.

### 8.2 Decision

Fix this in the backend pathway config during Phase 3A.

The manifest step should move to the end of the Scorecard Pathway and depend on the final evidence-producing steps.

### 8.3 Backend implementation

Refactor the pathway config so the manifest step is no longer embedded mid-flow inside the Phase 2A sequence.

Recommended structure:

```python
PHASE2A_PATHWAY_STEPS_CONFIG = [
    # Phase 2A steps through final-woe-iv only
]

PHASE2B_PATHWAY_STEPS_CONFIG = [
    # woe-transform-train through build-summary-report
]

PHASE2C_PATHWAY_STEPS_CONFIG = [
    # apply-woe through cutoff-analysis
]

TECHNICAL_MANIFEST_STEP_CONFIG = {
    "step_id": "technical-manifest-stub",
    "node_type": "cardre.technical_manifest_export",
    "node_version": "1",
    "category": "transform",
    "params": {},
    "parent_step_ids": [
        "define-metadata",
        "sample-definition",
        "split",
        "explicit-missing-outlier-treatment",
        "fine-classing",
        "variable-selection",
        "manual-binning",
        "final-woe-iv",
        "woe-transform-train",
        "logistic-regression",
        "score-scaling",
        "build-summary-report",
        "apply-woe",
        "apply-model",
        "validation-metrics",
        "cutoff-analysis",
    ],
    "branch_label": "",
}

# Register the scorecard pathway as:
full_config = (
    list(PHASE2A_PATHWAY_STEPS_CONFIG)
    + list(PHASE2B_PATHWAY_STEPS_CONFIG)
    + list(PHASE2C_PATHWAY_STEPS_CONFIG)
    + [TECHNICAL_MANIFEST_STEP_CONFIG]
)
```

Acceptance criteria:

* newly created projects place `technical-manifest-stub` at the end of the Scorecard Pathway
* the manifest step has position after `cutoff-analysis`
* the manifest step depends on final model, scoring, validation, and cutoff evidence
* the Phase 3 pathway view does not need a frontend-only ordering exception for new projects
* existing tests expecting the old position are updated deliberately

### 8.4 Migration note

Phase 3 does not need to migrate old projects unless backwards compatibility becomes a release requirement.

For existing local development projects:

* old projects may show the legacy order
* new projects use the corrected order
* project diagnostics may flag legacy pathway ordering as a warning

If migration is implemented, it must create a new plan version rather than mutate historical plan versions.

### 8.5 Fallback display rule

If the backend manifest-order fix is deferred, the frontend must treat `technical-manifest-stub` as a special display case.

Rules:

* render `technical-manifest-stub` in the final Export Evidence section, regardless of backend position
* keep API calls and run evidence tied to the real `step_id`
* display a warning in developer diagnostics that backend execution order is legacy
* do not pretend the backend execution order has changed

This is a fallback only. The preferred solution is the backend config correction.

---

## 9. Project and plan discovery

The current frontend has no reliable way to discover the scorecard plan ID. Phase 3A must fix this.

### 9.1 Required endpoint

Add:

```
GET /projects/{project_id}/plans
```

Response:

```json
{
  "project_id": "uuid",
  "plans": [
    {
      "plan_id": "uuid",
      "name": "Proof Pathway",
      "latest_version_id": "uuid",
      "is_default": false,
      "is_hidden": false
    },
    {
      "plan_id": "uuid",
      "name": "Scorecard Pathway",
      "latest_version_id": "uuid",
      "is_default": true,
      "is_hidden": false
    }
  ]
}
```

Rules:

* Scorecard Pathway is the default plan for Phase 3.
* Proof Pathway should not be the primary GUI pathway.
* hidden `__import__` plans should not be shown in normal plan navigation.
* the frontend must stop calling bare `GET /plans`.

### 9.2 Route consistency requirement

When adding `GET /projects/{project_id}/plans`, the route must use the same project registry and store-resolution logic as the existing plan routes.

Implementation requirements:

* resolve `project_id` through the same registry used by existing project and plan endpoints
* open `ProjectStore` from the registered project path
* return plans from `store.get_plans_for_project(project_id)`
* hide `__import__` from normal user-facing results unless explicitly requested
* mark Scorecard Pathway as default
* include `latest_version_id` for each returned plan
* keep behaviour consistent with `GET /plans/{plan_id}?project_id=...`

Acceptance criteria:

* newly created project returns a discoverable Scorecard Pathway
* frontend loads the Scorecard Pathway without hardcoded plan IDs
* `/plans` workaround is removed
* hidden `__import__` plan is excluded from normal user-facing plan lists
* `GET /projects/{project_id}/plans` and `GET /plans/{plan_id}?project_id={project_id}` resolve against the same store
* old projects with missing Scorecard Pathway return a structured warning rather than failing silently

---

## 10. Dataset import workflow

The dataset import UI must reflect the current two-stage backend reality.

### 10.1 Current backend flow

Actual flow:

```
User selects file
-> POST /datasets/import
-> hidden __import__ plan is created or reused
-> cardre.import_dataset runs in that hidden plan
-> canonical Parquet dataset artefact is registered
-> proof and scorecard pathway import step params are updated
-> new plan versions are created for those pathways
-> pathway import step becomes configured but not necessarily run in that pathway
```

### 10.2 UI behaviour

The UI must explain this clearly.

After import succeeds, show:

> Dataset imported and registered as a canonical Cardre artefact.
> The Scorecard Pathway import step has been configured to use this source file.
> Run the pathway to create run evidence for the configured scorecard plan.

### 10.3 Import screen

The import screen should include:

* native file selection where available
* manual path entry fallback
* source path
* dataset ID or import type where supported
* import button
* import result summary
* structured error display

### 10.4 Import result display

After import, show:

* source path
* imported artefact ID
* row count
* column count
* logical hash
* physical hash
* media type
* whether the Scorecard Pathway import step has been configured
* whether the Scorecard Pathway import step has been run after configuration

### 10.5 Important UX detail

The imported artefact from the hidden `__import__` plan and the output of the scorecard pathway import step are not the same run evidence.

The UI should avoid implying that importing the dataset has already run the scorecard pathway. It has configured the pathway.

### 10.6 Acceptance criteria

* user can select a file path from Tauri/native UI where available
* `POST /datasets/import` is called
* import result displays artefact summary
* Scorecard Pathway import step params are updated
* pathway view refreshes to show the new plan version
* user sees that the scorecard pathway still needs to be run
* import errors are shown with structured backend messages

---

## 11. Desktop workspace layout

Phase 3 should replace the current minimal project page with a modelling workspace.

Target layout:

```
┌──────────────────────────────────────────────────────────────┐
│ Top bar: Project | Scorecard Pathway | Run | Export | Status │
├───────────────┬────────────────────────────────┬─────────────┤
│ Left nav      │ Main workspace                 │ Inspector   │
│               │                                │             │
│ Dataset       │ Fixed pathway view             │ Step detail │
│ Pathway       │ Output viewers                 │ Params      │
│ Runs          │ Manual binning editor          │ Inputs      │
│ Artefacts     │ Validation/cutoff views        │ Outputs     │
│ Exports       │                                │ Warnings    │
├───────────────┴────────────────────────────────┴─────────────┤
│ Bottom drawer: run log / warnings / diagnostics              │
└──────────────────────────────────────────────────────────────┘
```

This is a substantial rework of the current scaffold.

Phase 3A should explicitly create the new shell/layout primitives before implementing rich output viewers.

### 11.1 Top bar

The top bar should show:

* project name
* current plan name
* run button
* export button
* sidecar health indicator
* current run status, if any

### 11.2 Left navigation

Minimum sections:

* Dataset
* Pathway
* Runs
* Artefacts
* Exports
* Diagnostics

### 11.3 Main workspace

The main workspace should switch between:

* fixed pathway view
* output viewers
* manual binning editor
* validation metrics viewer
* cutoff analysis viewer
* export screen

### 11.4 Inspector panel

The inspector should show the currently selected step or artefact.

Step inspector tabs:

* Overview
* Params
* Inputs
* Outputs
* Warnings
* Errors
* Run Evidence

### 11.5 Bottom drawer

The bottom drawer should show:

* run log
* warnings
* failed step information
* sidecar diagnostics
* project warnings

---

## 12. Step cards and status display

Each step card should be keyed by `step_id`.

Display fields:

* display label
* `step_id`
* `node_type`
* `category`
* backend status
* backend-computed stale marker
* backend position
* display order
* warning count, when available
* error count, when available
* latest run timestamp, when available
* primary action: inspect
* secondary action: run from here, once supported

Stored statuses:

```
not_run
queued
running
succeeded
failed
cancelled
```

Staleness remains backend-computed.

The frontend must not calculate official staleness. It may only display the `is_stale` value returned by the API.

### 12.1 Display state matrix

| Latest status | is_stale | Display |
|---|---|---|
| not_run | false | Not run |
| queued | false | Queued |
| running | false | Running |
| succeeded | false | Current |
| succeeded | true | Stale |
| failed | false | Failed |
| failed | true | Failed / upstream changed |
| cancelled | false | Cancelled |

Status should never be conveyed by colour alone. Always use text labels and icons.

---

## 13. Step inspector

### 13.1 Overview tab

Show:

* display label
* `step_id`
* `node_type`
* node version
* `category`
* backend position
* display section
* latest status
* stale state
* plan version
* latest run step ID where available
* short description

### 13.2 Params tab

The params editor should be generated from backend-provided schema or schema-like metadata where available.

Requirements:

* render string, number, integer, boolean, enum, nullable, arrays, and objects
* show defaults
* show required fields
* validate on edit
* validate on submit
* display backend validation errors
* show changed-from-last-run indicator where possible
* save only through backend API

The frontend must not mutate params locally as modelling truth.

### 13.3 Inputs tab

Show:

* input artefact ID
* `role`
* artefact type
* row count, where applicable
* column count, where applicable
* logical hash
* physical hash
* producing step, where known

### 13.4 Outputs tab

Show:

* output artefact ID
* `role`
* artefact type
* summary
* logical hash
* physical hash
* open/view action

### 13.5 Warnings and errors tabs

Warnings and errors should be structured and grouped where possible.

Each warning/error should show:

* code, where available
* severity, where available
* message
* affected variable/bin/step, where available
* suggested action, where available

### 13.6 Run evidence tab

Show:

* run ID
* run step ID
* plan version ID
* status
* started at
* finished at
* input artefact IDs
* output artefact IDs
* execution fingerprint summary

---

## 14. Parameter editing API

Phase 3C must add a real step parameter update endpoint if not already present.

Required endpoint:

```
POST /plans/{plan_id}/steps/{step_id}/params
```

Request:

```json
{
  "project_id": "uuid",
  "base_plan_version_id": "uuid",
  "params": {}
}
```

Response:

```json
{
  "plan_id": "uuid",
  "new_plan_version_id": "uuid",
  "changed_step_id": "manual-binning",
  "stale_step_ids": [
    "manual-binning",
    "final-woe-iv",
    "woe-transform-train",
    "logistic-regression",
    "score-scaling",
    "build-summary-report",
    "apply-woe",
    "apply-model",
    "validation-metrics",
    "cutoff-analysis",
    "technical-manifest-stub"
  ]
}
```

Rules:

* backend validates params
* backend creates a new plan version
* existing run history is retained
* frontend refreshes the plan after save
* stale state comes from backend
* unsaved UI drafts are not modelling truth
* saving params must not execute the step

Acceptance criteria:

* editing params creates a new plan version
* downstream stale state updates after plan refresh
* invalid params return structured errors
* historical run records remain unchanged

---

## 15. Run execution model

The current backend `POST /runs` executes synchronously. Phase 3 must handle that honestly.

### 15.1 Phase 3C MVP behaviour: synchronous runs

Initial Phase 3C should accept the current backend behaviour:

```
User clicks Run Pathway
-> frontend calls POST /runs
-> request blocks until run completes
-> UI shows indeterminate "Running..." state
-> run button and parameter editing are disabled
-> when response returns, frontend refreshes plan and run steps
```

Do not implement polling against synchronous execution. Polling only makes sense once the backend returns before execution completes.

### 15.2 Required UI during synchronous run

While `POST /runs` is pending:

* disable run controls
* show indeterminate progress
* keep navigation responsive where possible
* show "Cardre is running the local pathway"
* do not show fake per-step progress
* do not claim cancellation is available unless backend supports it
* prevent duplicate runs

### 15.3 Optional Phase 3C upgrade: background execution

If full Phase 2C runs become too slow for the synchronous UX, add background execution as an explicit Phase 3C subtask.

Then change the API to:

```
POST /runs
Response:
{
  "run_id": "uuid",
  "status": "queued"
}
```

Then polling becomes valid:

```
GET /runs/{run_id}
GET /runs/{run_id}/steps
```

Do not mix the two models.

### 15.4 Cancellation

Cancellation should only be shown if the backend has safe cancellation support.

No fake cancellation.

### 15.5 Acceptance criteria

MVP acceptance:

* synchronous run can complete from GUI
* UI does not freeze visually
* user cannot start duplicate runs
* plan refreshes after run
* failed runs display failed step evidence
* no polling UI is shown unless backend execution is truly async

Async acceptance, if implemented:

* `POST /runs` returns immediately
* run status can be polled
* step statuses update during execution
* cancellation is only shown if safe cancellation exists

---

## 16. Run history

Add a run history panel.

Display:

* run ID
* plan version ID
* started at
* finished at
* status
* step count
* succeeded step count where available
* failed step count where available
* producing manifest artefact where available

Required endpoints:

```
GET /projects/{project_id}/runs
GET /runs/{run_id}
GET /runs/{run_id}/steps
```

If `GET /projects/{project_id}/runs` does not exist, add it in Phase 3C.

Acceptance criteria:

* user can view previous runs for a project
* user can inspect run steps
* failed steps show errors
* reopening a project preserves run history

---

## 17. Artefact listing and preview APIs

Phase 3D must explicitly add artefact list and preview endpoints.

The current sidecar only supports single artefact metadata lookup. That is not enough for Phase 3 output viewers.

### 17.1 Required artefact list endpoint

```
GET /projects/{project_id}/artifacts
```

Query params:

```
role?
artifact_type?
producing_step_id?
run_id?
limit?
offset?
```

Response:

```json
{
  "project_id": "uuid",
  "artifacts": [
    {
      "artifact_id": "uuid",
      "artifact_type": "report",
      "role": "report",
      "media_type": "application/json",
      "path": "artifacts/example.json",
      "logical_hash": "sha256",
      "physical_hash": "sha256",
      "created_at": "iso",
      "metadata": {}
    }
  ]
}
```

### 17.2 Required artefact preview endpoint

```
GET /artifacts/{artifact_id}/preview
```

Query params:

```
limit=100
offset=0
```

Behaviour:

* JSON artefacts: return parsed JSON if small
* large JSON artefacts: return summary plus top-level keys
* Parquet artefacts: return paginated rows and schema
* manifests: return summary plus downloadable content reference
* never return full row-level datasets by default

Example Parquet preview response:

```json
{
  "artifact_id": "uuid",
  "media_type": "application/vnd.apache.parquet",
  "row_count": 1000,
  "column_count": 21,
  "columns": [
    {
      "name": "credit_amount",
      "dtype": "Int64"
    }
  ],
  "rows": [
    {
      "credit_amount": 1200
    }
  ],
  "limit": 100,
  "offset": 0
}
```

### 17.3 Required artefact summary endpoint

```
GET /artifacts/{artifact_id}/summary
```

This should return a display-oriented summary without loading the full artefact.

Used by:

* step inspector
* artefact list
* output viewer index
* audit export screen

### 17.4 Acceptance criteria

* frontend no longer calls non-existent `GET /artifacts`
* artefact list is project-scoped
* Parquet preview is paginated
* output viewers do not load large files into React memory
* raw row-level export remains explicit, not default

---

## 18. Output viewers

Phase 3D should implement simple viewers over existing Phase 2 artefacts.

Do not build a report designer.

### 18.1 Generic JSON viewer

For:

* definitions
* reports
* model artefacts
* scorecard artefacts
* manifest artefacts

Features:

* formatted JSON
* top-level summary
* copy artefact ID
* show logical and physical hash
* open raw JSON view

### 18.2 Generic table preview

For Parquet artefacts:

* paginated preview
* schema
* row count
* column count
* no editing
* no full in-memory load

### 18.3 Profile viewer

For profile output:

* row count
* column count
* column list
* dtypes
* null counts
* numeric stats where available
* high-cardinality warnings where available

### 18.4 WOE/IV viewer

For `initial-woe-iv` and `final-woe-iv` outputs:

* variable IV ranking
* bin-level WOE
* good count
* bad count
* event rate
* zero-cell warnings
* sparse-bin warnings

### 18.5 Variable selection viewer

For `variable-selection` output:

* selected variables
* rejected variables
* IV where available
* reason
* manual include/exclude flag where available

### 18.6 Model viewer

For `logistic-regression` output:

* model features
* coefficients
* intercept
* convergence metadata
* warnings
* target orientation

### 18.7 Scorecard viewer

For `score-scaling` output:

* base score
* base odds
* points to double odds
* score direction
* attribute points
* score range

### 18.8 Validation viewer

For `validation-metrics` output:

* train metrics
* test metrics
* OOT metrics
* AUC
* Gini
* KS
* calibration summary
* PSI if present

### 18.9 Cutoff viewer

For `cutoff-analysis` output:

* cutoff band
* approval rate
* bad rate
* capture rate
* population count
* role selector for train/test/OOT if present

---

## 19. Manual binning editor

Manual binning is the highest-risk Phase 3 feature. The frontend should be deliberately simple and backend-led.

### 19.1 Current backend contract

ManualBinningNode:

* has step ID `manual-binning`
* has node type `cardre.manual_binning`
* consumes definition artefacts
* expects upstream fine-classing bin definitions
* may also consume variable-selection definitions
* accepts JSON params shaped around overrides
* requires a non-empty reason for every override
* validates source bin IDs
* enforces adjacency for numeric `merge_bins`
* outputs refined bin definitions

### 19.2 Critical rule

The manual binning editor must not reconstruct source bins from the `manual-binning` step params.

It must reconstruct source bins from the latest current upstream fine-classing output artefact.

The current manual-binning params only represent proposed or saved overrides. They are not the source bin universe.

### 19.3 Editor-state endpoint

Add:

```
GET /plans/{plan_id}/steps/manual-binning/editor-state?project_id={project_id}
```

Response when ready:

```json
{
  "plan_id": "uuid",
  "plan_version_id": "uuid",
  "step_id": "manual-binning",
  "ready": true,
  "blocked_reason": null,
  "source": {
    "fine_classing_step_id": "fine-classing",
    "fine_classing_artifact_id": "uuid",
    "variable_selection_step_id": "variable-selection",
    "variable_selection_artifact_id": "uuid"
  },
  "selected_variables": [],
  "source_bins_by_variable": {},
  "current_overrides": [],
  "warnings": []
}
```

Response when blocked:

```json
{
  "ready": false,
  "blocked_reason": "Run fine-classing and variable-selection before editing manual bins.",
  "required_steps": [
    "fine-classing",
    "variable-selection"
  ]
}
```

### 19.4 Editor-state resolution algorithm

Backend logic:

1. Resolve current plan version for `plan_id`.
2. Load current steps.
3. Confirm `manual-binning` exists.
4. Confirm `fine-classing` is reachable as an upstream ancestor of `manual-binning`.
5. Confirm `variable-selection` is a direct parent of `manual-binning` in the current pathway config.
6. Compute staleness for the current plan version.
7. If `fine-classing` or `variable-selection` is stale, return `ready=false`.
8. Find latest successful current run step for `fine-classing`.
9. Find latest successful current run step for `variable-selection`.
10. Load the `fine-classing` output definition artefact.
11. Load the `variable-selection` output definition artefact.
12. Extract selected variables from `variable-selection`.
13. Filter fine-classing variables to selected variables.
14. Load current `manual-binning` step params.
15. Return source bins plus current overrides.

Important:

* current manual-binning output artefact is not the editor source
* current manual-binning params are only the saved override draft
* source bin IDs must remain immutable
* if the upstream run evidence is stale, the editor should not allow save
* resolution should be by step ID and ancestry, not merely by positional adjacency

### 19.5 Preview endpoint

Add:

```
POST /plans/{plan_id}/steps/manual-binning/preview
```

Request:

```json
{
  "project_id": "uuid",
  "plan_version_id": "uuid",
  "overrides": []
}
```

Response:

```json
{
  "valid": true,
  "refined_bins_by_variable": {},
  "diagnostics": {
    "override_count": 3,
    "warnings": []
  }
}
```

Preview rules:

* preview calls sidecar/backend logic
* preview must not calculate bins in React
* preview must not create official artefacts
* preview must not create a new plan version
* preview must use the same validation rules as ManualBinningNode
* preview should return refined bins and warnings only

### 19.6 Save endpoint

Use the general params endpoint:

```
POST /plans/{plan_id}/steps/{step_id}/params
```

Request:

```json
{
  "project_id": "uuid",
  "base_plan_version_id": "uuid",
  "params": {
    "overrides": [
      {
        "variable": "duration_months",
        "action": "merge_bins",
        "source_bin_ids": [
          "duration_months_bin_001",
          "duration_months_bin_002"
        ],
        "new_label": "Short duration",
        "reason": "Merged adjacent sparse bins to improve stability"
      }
    ]
  }
}
```

Save rules:

* backend validates
* every override requires reason
* invalid source bin IDs fail
* non-adjacent numeric merges fail
* new plan version is created
* downstream steps become stale
* official refined bins are created only when the pathway is run

### 19.7 Frontend manual binning UX

Frontend should be dumb and auditable:

* show selected variables
* show source bins
* allow selecting adjacent numeric bins
* allow grouping categorical bins
* require reason text before save
* call preview endpoint for validation/diagnostics
* call params endpoint to save
* refresh pathway after save

Deferred:

* drag-and-drop boundary editing
* live recomputation on every edit
* local WOE recalculation in React
* arbitrary new cutpoint creation

### 19.8 Acceptance criteria

* editor is disabled until fine-classing and variable-selection have current successful outputs
* source bins come from fine-classing output, not manual-binning params
* selected variables come from variable-selection output
* preview uses sidecar validation
* frontend performs no official bin recalculation
* backend rejects invalid overrides
* save creates new plan version
* official refined bins are created only by rerunning pathway steps

---

## 20. Audit export UI

Phase 3F should expose the technical manifest artefact produced by the pathway.

The current step ID is `technical-manifest-stub`. Unless the backend is deliberately migrated, the GUI should use that step ID.

The export UI should show:

* available manifest artefacts
* producing run
* producing plan version
* manifest logical hash
* manifest physical hash
* warnings and errors summary
* export path
* row-level data included: false by default

If Phase 2C later replaces `technical-manifest-stub` with a final manifest step, that change must be made explicitly in the pathway config and reflected in the display mapping.

Phase 3 should not silently rename the step in the frontend.

Acceptance criteria:

* user can find manifest output from `technical-manifest-stub`
* export excludes row-level data by default
* export path and hashes are displayed
* missing/corrupt artefacts produce useful diagnostics
* export UI does not imply a governance-quality human-readable report exists yet

---

## 21. Security and local data handling

Cardre is local-first, but credit data is sensitive.

Phase 3 should implement visible, basic local-data safety messaging.

Requirements:

* no cloud upload by default
* no telemetry containing dataset values
* no sensitive values in logs
* project path visible to user
* warning that projects should be stored in approved/encrypted locations
* audit export defaults exclude row-level data
* logs accessible for debugging but scrubbed where possible

The app should clearly document where raw and transformed data are stored.

---

## 22. Accessibility and UX requirements

Minimum UX quality:

* keyboard navigable main controls
* visible focus states
* readable contrast
* no colour-only status indicators
* status labels plus icons
* tables support horizontal scrolling
* long-running work never freezes the visible UI
* destructive actions require confirmation
* unsaved changes warning for params/manual binning drafts

Status labels should use words such as:

* Current
* Stale
* Failed
* Running
* Not run
* Cancelled

---

## 23. Testing strategy

### 23.1 Backend tests

Add or update tests for:

* corrected manifest step ordering
* `GET /projects/{project_id}/plans`
* hidden `__import__` exclusion from normal plan list
* scorecard plan discovery
* parameter update creates new plan version
* artefact list endpoint
* artefact summary endpoint
* artefact preview endpoint
* manual binning editor-state resolution
* manual binning preview
* invalid manual binning overrides
* stale upstream manual binning blocker

### 23.2 Frontend unit tests

Cover:

* step display metadata mapping
* unknown backend step handling
* pathway section grouping
* status rendering
* stale marker rendering
* import success messaging
* synchronous run loading state
* params form rendering
* artefact preview rendering
* manual binning draft state
* manual binning reason validation

### 23.3 Integration tests

Cover:

```
Create project
-> discover Scorecard Pathway
-> import dataset
-> refresh plan
-> run pathway
-> list artefacts
-> preview WOE/IV artefact
-> update manual-binning params
-> verify downstream stale state
```

### 23.4 Desktop smoke test

Cover:

* app launches
* sidecar starts
* `/health` passes
* project can be created
* Scorecard Pathway can be discovered
* dataset can be imported
* pathway can run synchronously
* artefacts are visible
* app can be closed and reopened

---

## 24. Revised implementation slices

### Phase 3A — Repo reconciliation, Tauri fix, and workspace shell

Deliverables:

* fix Tauri sidecar stdout/stderr handling
* confirm desktop shell compiles
* add `GET /projects/{project_id}/plans`
* remove frontend calls to non-existent `GET /plans`
* remove frontend calls to non-existent `GET /artifacts`
* add step display metadata keyed by real `step_id`
* add expected order/display order metadata
* correct `technical-manifest-stub` backend ordering for new projects
* keep hidden `__import__` out of normal plan navigation
* rework current ProjectView scaffold into the new workspace shell

Acceptance criteria:

* Tauri app compiles
* sidecar starts and health check passes
* new project creation still registers Proof Pathway and Scorecard Pathway
* newly created Scorecard Pathway has manifest step at the end
* frontend can discover Scorecard Pathway without hardcoded IDs
* frontend renders actual scorecard step IDs in backend order
* hidden `__import__` plan is not shown as a normal modelling plan
* legacy frontend calls to `/plans` and `/artifacts` are removed

### Phase 3B — Dataset import and pathway configuration UX

Deliverables:

* dataset import screen
* native path selection where available
* call existing `POST /datasets/import`
* display imported canonical artefact summary
* refresh project plans after import
* explain that import configures the pathway but does not itself run the scorecard pathway
* show configured source path on import step

Acceptance criteria:

* user imports German Credit or compatible local file
* hidden `__import__` execution succeeds
* canonical Parquet artefact summary is displayed
* Scorecard Pathway import params are updated
* new plan version is loaded in UI
* user understands that the pathway must still be run

### Phase 3C — Step params, synchronous run UX, and run history

Deliverables:

* `POST /plans/{plan_id}/steps/{step_id}/params`
* schema or schema-like param editing where available
* plan refresh after param save
* synchronous `POST /runs` UX
* indeterminate run state
* duplicate-run prevention
* run history panel
* run steps panel
* structured error display

Acceptance criteria:

* editing params creates new plan version
* stale state refreshes from backend
* pathway can be run synchronously from UI
* UI does not pretend to have polling progress
* run result refreshes plan status
* failed runs expose failed step and errors

Optional Phase 3C+:

* background run worker
* queued/running statuses during execution
* polling
* cancellation, if safe

### Phase 3D — Artefact list, previews, and output viewers

Deliverables:

* `GET /projects/{project_id}/artifacts`
* `GET /artifacts/{artifact_id}/summary`
* `GET /artifacts/{artifact_id}/preview`
* generic JSON viewer
* generic Parquet preview viewer
* profile viewer
* WOE/IV viewer
* variable selection viewer
* model viewer
* scorecard viewer
* validation metrics viewer
* cutoff analysis viewer

Acceptance criteria:

* frontend no longer calls non-existent artefact endpoints
* all output viewers use project-scoped artefact APIs
* Parquet previews are paginated
* JSON reports are readable
* WOE/IV and validation outputs are inspectable
* train/test/OOT metrics are clearly separated where present

### Phase 3E — Manual binning editor

Deliverables:

* editor-state endpoint
* preview endpoint
* source-bin resolution from upstream fine-classing artefact
* selected-variable resolution from upstream variable-selection artefact
* table-based bin editor
* numeric adjacent merge UI
* categorical grouping UI
* mandatory reason capture
* save overrides through params endpoint
* stale downstream refresh

Acceptance criteria:

* editor is disabled until fine-classing and variable-selection have current successful outputs
* source bins come from fine-classing output, not manual-binning params
* selected variables come from variable-selection output
* preview uses sidecar validation
* frontend performs no official bin recalculation
* backend rejects invalid overrides
* save creates new plan version
* official refined bins are created only by rerunning pathway steps

### Phase 3F — Technical manifest export UI and hardening

Deliverables:

* manifest artefact viewer
* export UI for available technical manifest artefacts
* local export path selection
* export result summary
* project diagnostics
* legacy pathway ordering diagnostic
* missing artefact handling
* E2E desktop smoke test

Acceptance criteria:

* user can find manifest output from `technical-manifest-stub`
* manifest appears visually in the final Export Evidence section
* export excludes row-level data by default
* export path and hashes are displayed
* missing/corrupt artefacts produce useful diagnostics
* full desktop flow works after app restart

---

## 25. End-to-end acceptance flow

The final Phase 3 E2E smoke flow:

1. Launch Cardre desktop app.
2. Sidecar starts and `/health` passes.
3. Create new local project.
4. Project registers Proof Pathway and corrected Scorecard Pathway.
5. UI discovers Scorecard Pathway through project plans endpoint.
6. UI renders actual backend step IDs with friendly display labels.
7. Confirm `technical-manifest-stub` appears at the end of the pathway.
8. Import dataset through `POST /datasets/import`.
9. UI explains hidden import plan and pathway import-step configuration.
10. Refresh Scorecard Pathway.
11. Run pathway synchronously.
12. UI shows indeterminate running state.
13. Run completes.
14. Pathway statuses refresh.
15. Open profile artefact viewer.
16. Open WOE/IV artefact viewer.
17. Open variable selection viewer.
18. Open manual binning editor.
19. Editor resolves source bins from fine-classing output.
20. Editor resolves selected variables from variable-selection output.
21. Add valid merge override with reason.
22. Preview override through sidecar.
23. Save override as manual-binning params.
24. New plan version is created.
25. Downstream steps show stale from backend.
26. Rerun pathway.
27. Open validation metrics.
28. Open cutoff analysis.
29. Open technical manifest artefact.
30. Export audit evidence.
31. Close and reopen project.
32. Confirm plan, run history, artefacts, and statuses persist.

---

## 26. Main risks and mitigations

### Risk 1: step-ID drift

Mitigation:

* centralise frontend display metadata by actual `step_id`
* do not hardcode display names into backend calls
* add a test that frontend expected IDs match backend plan IDs

### Risk 2: hidden import flow confuses users

Mitigation:

* explicitly label import as "dataset registration + pathway configuration"
* show that the pathway import step still needs run evidence
* display configured source path in the import step inspector

### Risk 3: synchronous runs feel broken

Mitigation:

* use clear indeterminate running state
* disable duplicate actions
* only add polling after backend is actually async

### Risk 4: artefact viewers load too much data

Mitigation:

* add paginated preview endpoints
* never load full Parquet files into React
* show summaries first

### Risk 5: manual binning editor becomes too clever

Mitigation:

* backend validates everything
* frontend edits override JSON through controlled UI
* preview calls sidecar
* official artefacts only appear after execution

### Risk 6: current frontend scaffold fights the target design

Mitigation:

* Phase 3A explicitly reworks the scaffold
* keep useful API client/types where possible
* do not try to grow the whole modelling workspace out of the current centred ProjectView

### Risk 7: manifest step remains in legacy mid-flow position

Mitigation:

* fix backend pathway config in Phase 3A
* for old projects, show a diagnostics warning
* only use frontend display override as a fallback
* never mutate historical plan versions silently

---

## 27. Final definition of done

Phase 3 is done when:

A user can launch Cardre, create a local project, discover the registered Scorecard Pathway, import a dataset through the existing hidden import-plan flow, see the actual Phase 2A/2B/2C step IDs rendered as a friendly fixed pathway, run the pathway from the desktop UI, inspect artefacts through project-scoped list/summary/preview endpoints, edit manual binning overrides using upstream fine-classing and variable-selection artefacts, save those overrides as backend-validated params, rerun stale downstream steps, view validation and cutoff outputs, and export the technical manifest evidence available from the current pathway.

The corrected Scorecard Pathway for new projects must place `technical-manifest-stub` at the end of the pathway so the GUI and run evidence both reflect the real modelling journey.

The user should not need to touch Python, SQLite, Parquet files, JSON artefacts, or FastAPI routes directly.
