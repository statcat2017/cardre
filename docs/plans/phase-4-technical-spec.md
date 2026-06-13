# Cardre Phase 4 Technical Specification

## Branching and Champion/Challenger

⸻

### 1. Purpose

Phase 4 extends Cardre from a fixed-pathway desktop scorecard builder into a constrained branchable modelling workspace.

By the end of Phase 3, a modeller should be able to create or open a local Cardre project, import a dataset, configure and run the registered Scorecard Pathway, inspect statuses, stale state, warnings, errors, and artefacts, edit manual binning overrides, view validation and cutoff outputs, and export the technical manifest evidence.

Phase 4 adds the first user-facing implementation of Cardre's larger product claim:

Cardre makes the scorecard modelling journey visible, editable, branchable, reproducible, and exportable for audit.

The purpose of Phase 4 is to let a modeller:

1. Create constrained challenger branches from approved points in the scorecard pathway.
2. Run branch-specific downstream steps while preserving shared upstream evidence.
3. Compare challenger and baseline outputs side by side.
4. Mark one branch as champion with a required rationale.
5. Export the selected branch with complete lineage and audit evidence.

Phase 4 must not turn Cardre into a freeform DAG editor. The branching model remains constrained, reproducible, backend-owned, and audit-first.

⸻

### 2. Product Boundary

Phase 4 implements branching inside the fixed scorecard pathway.

It does not implement arbitrary graph editing.

The correct mental model is:

Branches are versioned, auditable modelling lanes derived from an existing plan version.

The incorrect mental model is:

Branches are arbitrary user-drawn pipelines or copied artefact folders.

Phase 4 should cover:

* baseline branch migration for existing projects
* branch-aware step identity
* constrained branch creation
* branch-aware parameter editing
* branch-aware manual binning
* branch-scoped execution
* branch comparison
* champion selection
* selected branch export
* constrained segment-specific challenger branches

Phase 4 must defer:

* freeform DAG canvas editing
* arbitrary node insertion or deletion
* branch merging
* plugin nodes
* project-local custom Python nodes
* hosted execution
* multi-user collaboration
* formal approval workflow
* governance-quality narrative report generation
* report designer
* PMML/ONNX export
* reject inference

Phase 5 remains the governance-quality model development report phase.

Phase 6 remains the extensibility/plugin phase.

⸻

### 3. Core Principles

#### 3.1 Branches are plan-derived lanes, not copied artefacts

Creating a branch must:

* create branch metadata
* duplicate selected downstream step configurations
* create generated branch-specific step IDs
* preserve canonical step identity
* preserve links to shared upstream steps
* create a new plan version
* create branch step map records
* require a branch creation reason

Creating a branch must not:

* copy historical run records
* copy output artefacts and pretend they are new evidence
* mutate historical plan versions
* mutate historical run evidence
* rewrite execution fingerprints
* duplicate large data artefacts unnecessarily
* create official outputs before execution

Branch outputs only become official when branch-owned steps are executed.

#### 3.2 Backend owns branching logic

React may display branches, lanes, comparison tables, branch statuses, champion badges, and branch inspectors.

React must not:

* generate official branch step IDs
* calculate official staleness
* decide whether two branches are comparable
* copy artefacts
* mutate audit records
* infer branch lineage from string splitting
* decide which upstream artefacts a branch should use

The Python engine, FastAPI sidecar, and SQLite project store remain the source of truth.

#### 3.3 GUI state is not modelling truth

Phase 4 preserves the existing Cardre rule:

GUI state is not modelling truth.

Unsaved UI drafts are not official.

Official model state exists only through:

* project metadata
* plan versions
* branch metadata
* branch step maps
* run records
* run step records
* artefact records
* immutable artefact files
* comparison artefacts
* champion assignment records

#### 3.4 Runs are evidence; plan versions are design state

A plan version represents the current design of a modelling pathway or branch.

A run represents execution evidence against a plan version.

Normal branch execution must not create a new plan version. It creates run records and artefacts against the branch's current head_plan_version_id.

Parameter edits and branch creation create new plan versions.

⸻

### 4. Non-Goals

Phase 4 must not implement:

* arbitrary freeform DAG editing
* drag-and-drop graph construction
* arbitrary branch-point selection
* branch merging
* custom Python nodes
* plugin discovery
* multi-user review
* model approval workflow
* automatic winner selection
* row-level export by default
* cloud sync
* hosted execution
* reject inference
* regulator-ready certification claims

The comparison screen can highlight metrics, warnings, stale evidence, missing evidence, and trade-offs.

It must not declare an automatic winner.

Champion selection is a recorded modelling decision made by the user.

⸻

### 5. Core Terminology

#### 5.1 Baseline Branch

The baseline branch is the original fixed Scorecard Pathway represented as a branch.

Existing Phase 3 projects do not yet have branch metadata. Phase 4A0 migrates them into the branch model by creating a baseline branch.

The baseline branch:

* references the existing Scorecard Pathway
* uses the original fixed step IDs
* has branch type baseline
* has no branch point
* can be compared against challengers
* can be marked champion
* can be exported

Baseline migration is metadata-only.

It must not rewrite:

* historical run records
* run step records
* artefact records
* artefact files
* execution fingerprints

#### 5.2 Challenger Branch

A challenger branch is a duplicated downstream modelling lane created from a permitted branch point.

Examples:

* different manual binning choices
* different variable-selection configuration
* different logistic regression settings
* different score scaling
* different cutoff strategy
* segment-specific scorecard experiment

A challenger branch owns its duplicated downstream steps.

It may share upstream evidence with the baseline or another branch.

#### 5.3 Branch Point

The branch point is the canonical pathway step where a challenger begins to diverge.

Phase 4 MVP supports these branch points:

| Branch point | Branch type | Purpose | Duplicated downstream scope |
|---|---|---|---|
| sample-definition | segment_challenger | Segment-specific scorecard experiment | sample-definition through branch manifest |
| variable-selection | variable_selection_challenger | Variable-selection experiment | variable-selection through branch manifest |
| manual-binning | binning_challenger | Coarse-classing/binning experiment | manual-binning through branch manifest |
| logistic-regression | model_challenger | Model-fitting experiment | logistic-regression through branch manifest |
| score-scaling | score_scaling_challenger | Score scaling experiment | score-scaling through branch manifest |
| cutoff-analysis | cutoff_strategy_challenger | Strategy/cutoff-only experiment | cutoff-analysis plus branch manifest |

Do not allow Phase 4 users to branch from arbitrary technical steps such as:

* import
* profile
* validate-target
* apply-woe
* apply-model
* technical-manifest-stub

#### 5.4 Actual Step ID

The actual step_id is the unique step instance ID used in APIs, execution, run evidence, and artefact lineage.

Examples:

```
manual-binning
manual-binning__br_a81f3c
logistic-regression__br_a81f3c
validation-metrics__br_a81f3c
```

All API calls must use actual step_id.

#### 5.5 Canonical Step ID

The canonical_step_id identifies the fixed scorecard pathway slot represented by a step.

Examples:

| Actual step ID | Canonical step ID |
|---|---|
| manual-binning | manual-binning |
| manual-binning__br_a81f3c | manual-binning |
| logistic-regression__br_a81f3c | logistic-regression |
| cutoff-analysis__br_b42c99 | cutoff-analysis |

Branch comparison aligns branches by canonical_step_id.

The frontend must not infer canonical identity by splitting strings.

The backend must return canonical identity explicitly.

⸻

### 6. Required Phase 4A0 Foundation

No branch creation, branch execution, branch comparison, or champion assignment work may start until Phase 4A0 is complete.

Phase 4A0 is the schema, compatibility, and migration foundation.

It must prove that existing Phase 3 projects can be opened, migrated into a baseline branch model, and queried through the new branch-aware read model without rewriting historical execution evidence.

⸻

### 7. Branch-Aware StepSpec

#### 7.1 Requirement

canonical_step_id and branch_id must exist in the Python layer, not just in TypeScript or API concepts.

The existing StepSpec should be extended directly.

Do not create a separate BranchStepSpec wrapper in Phase 4.

#### 7.2 Backwards-compatible dataclass shape

StepSpec must be backwards-compatible with existing call sites.

Because current code constructs StepSpec(...) directly in pathway setup and tests, the new fields must not be required positional arguments.

Target shape:

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class StepSpec:
    step_id: str
    node_type: str
    node_version: str
    category: str
    params: JsonDict
    params_hash: str
    parent_step_ids: list[str]
    branch_label: str
    position: int
    canonical_step_id: str = field(default="", kw_only=True)
    branch_id: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.canonical_step_id:
            object.__setattr__(self, "canonical_step_id", self.step_id)
```

Rules:

* Existing StepSpec(...) call sites continue to work.
* For baseline/legacy steps, canonical_step_id defaults to step_id.
* For legacy steps before migration, branch_id defaults to None.
* After baseline migration, baseline steps should have the baseline branch ID where plan versions are rewritten or new plan versions are created.
* New branch-owned steps must always have a non-null branch_id.
* Shared upstream steps in a branch map may have their own original branch ID but still appear in another branch's effective pathway through branch_step_map.

#### 7.3 to_dict

to_dict must include:

```python
"canonical_step_id": self.canonical_step_id,
"branch_id": self.branch_id,
```

#### 7.4 from_dict

from_dict must tolerate legacy records:

```python
canonical_step_id=data.get("canonical_step_id", data["step_id"]),
branch_id=data.get("branch_id"),
```

#### 7.5 replace_step_params

replace_step_params must preserve:

```python
canonical_step_id=s.canonical_step_id,
branch_id=s.branch_id,
```

This is mandatory because replace_step_params reconstructs StepSpec objects manually.

Dropping branch metadata during a param edit would corrupt branch lineage.

⸻

### 8. Database Schema Changes

SQLite remains metadata-only.

Tabular artefacts remain Parquet.

Small definitions, reports, manifests, and comparison outputs remain JSON.

Phase 4A0 must create all branch-related tables together so constraints and migrations are consistent.

#### 8.1 plan_branches

```sql
CREATE TABLE plan_branches (
    branch_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    branch_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    base_branch_id TEXT,
    base_plan_version_id TEXT NOT NULL,
    head_plan_version_id TEXT NOT NULL,
    branch_point_step_id TEXT,
    branch_point_canonical_step_id TEXT,
    segment_filter_spec_json TEXT,
    created_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(project_id),
    FOREIGN KEY(plan_id) REFERENCES plans(plan_id)
);
```

Allowed branch_type values:

```
baseline
variable_selection_challenger
binning_challenger
model_challenger
score_scaling_challenger
cutoff_strategy_challenger
segment_challenger
```

Allowed status values:

```
active
archived
```

#### 8.2 branch_step_map

```sql
CREATE TABLE branch_step_map (
    branch_step_map_id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL,
    plan_version_id TEXT NOT NULL,
    canonical_step_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    source_branch_id TEXT,
    source_step_id TEXT,
    is_shared_upstream INTEGER NOT NULL DEFAULT 0,
    is_branch_owned INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(branch_id) REFERENCES plan_branches(branch_id)
);
```

Purpose:

* maps branch effective pathway to actual step IDs
* supports canonical comparison
* supports branch-aware ancestry resolution
* lets the UI display branches without guessing generated IDs
* lets execution determine which steps belong to the selected branch

#### 8.3 branch_comparisons

branch_comparisons stores comparison intent.

It should not be treated as an immutable comparison result.

```sql
CREATE TABLE branch_comparisons (
    comparison_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    baseline_branch_id TEXT NOT NULL,
    challenger_branch_ids_json TEXT NOT NULL,
    comparison_spec_json TEXT NOT NULL,
    latest_snapshot_id TEXT,
    latest_ready INTEGER,
    latest_readiness_json TEXT,
    created_at TEXT NOT NULL,
    created_reason TEXT,
    FOREIGN KEY(baseline_branch_id) REFERENCES plan_branches(branch_id)
);
```

#### 8.4 branch_comparison_snapshots

Every comparison refresh creates a new immutable comparison artefact and a new snapshot row.

```sql
CREATE TABLE branch_comparison_snapshots (
    comparison_snapshot_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    comparison_artifact_id TEXT NOT NULL,
    readiness_json TEXT NOT NULL,
    source_plan_version_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_reason TEXT,
    FOREIGN KEY(comparison_id) REFERENCES branch_comparisons(comparison_id)
);
```

Purpose:

* preserves comparison history
* avoids mutating previous comparison outputs
* supports audit export
* allows champion assignment to reference a specific comparison snapshot

#### 8.5 champion_assignments

```sql
CREATE TABLE champion_assignments (
    champion_assignment_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    champion_branch_id TEXT NOT NULL,
    comparison_id TEXT NOT NULL,
    comparison_snapshot_id TEXT NOT NULL,
    comparison_artifact_id TEXT NOT NULL,
    selected_plan_version_id TEXT NOT NULL,
    assigned_reason TEXT NOT NULL,
    assigned_by TEXT,
    assigned_at TEXT NOT NULL,
    superseded_at TEXT,
    superseded_by_assignment_id TEXT,
    FOREIGN KEY(champion_branch_id) REFERENCES plan_branches(branch_id),
    FOREIGN KEY(comparison_id) REFERENCES branch_comparisons(comparison_id),
    FOREIGN KEY(comparison_snapshot_id) REFERENCES branch_comparison_snapshots(comparison_snapshot_id)
);
```

Allowed scope_type values:

```
project
segment
custom
```

MVP rule:

* only one active champion per project_id + plan_id + scope_type + scope_key
* assigning a new champion supersedes the previous active assignment
* champion assignment requires a non-empty rationale
* champion assignment requires a comparison snapshot

⸻

### 9. Branch Head Version Semantics

#### 9.1 Definition

head_plan_version_id is the latest plan version representing the current design state of a branch.

It is updated atomically whenever a branch-affecting design operation creates a new plan version.

Examples:

* branch creation
* branch-owned parameter edit
* branch-owned manual-binning override save
* future branch-structure edit
* branch archive/reactivation if represented as plan state

A normal run does not create a new plan version.

A normal run creates execution evidence against the branch's current head_plan_version_id.

#### 9.2 Atomic update rule

When a branch-owned param edit creates a new plan version:

1. validate request
2. create new plan version
3. create or copy branch step map rows for the new plan version
4. update plan_branches.head_plan_version_id
5. commit in one transaction

If any step fails, no partial branch-head update should remain.

#### 9.3 Baseline semantics

For baseline migration:

base_plan_version_id = earliest Scorecard Pathway plan version
head_plan_version_id = latest Scorecard Pathway plan version

For a newly created challenger branch:

base_plan_version_id = plan version branched from
head_plan_version_id = newest plan version after branch creation or later branch edits

⸻

### 10. Baseline Branch Migration

#### 10.1 Purpose

Existing Phase 3 projects do not have branch metadata.

Phase 4A0 must migrate them into the branch model without rewriting historical execution evidence.

#### 10.2 Migration algorithm

For each existing project:

1. Open the project store.
2. Find user-facing Scorecard Pathway plans.
3. Exclude hidden __import__ plans.
4. For each Scorecard Pathway:
    1. load all plan versions for that plan, oldest to newest
    2. find earliest plan version ID
    3. find latest plan version ID
    4. create one plan_branches row:
        * branch_type = "baseline"
        * name = "Baseline"
        * base_plan_version_id = earliest_plan_version_id
        * head_plan_version_id = latest_plan_version_id
        * branch_point_step_id = null
        * branch_point_canonical_step_id = null
        * created_reason = "Created automatically during Phase 4 baseline branch migration."
5. For every plan version in that plan:
    1. load its steps
    2. for each step:
        * infer canonical_step_id = step.step_id if missing
        * insert a branch_step_map row:
            * branch_id = baseline_branch_id
            * plan_version_id = current_plan_version_id
            * canonical_step_id = step.step_id
            * step_id = step.step_id
            * source_branch_id = null
            * source_step_id = null
            * is_shared_upstream = 0
            * is_branch_owned = 1
6. Do not update run_steps.
7. Do not update artefact records.
8. Do not rewrite execution fingerprints.
9. Mark migration version in project metadata.

#### 10.3 Historical plan versions

Branch mapping must be created for every historical plan version, not just the latest version.

Run history and old manifest inspection must remain explainable after migration.

#### 10.4 Migration idempotency

Migration must be idempotent.

If baseline branch metadata already exists for a plan, migration must not create duplicate baseline branches.

If some branch step map rows exist and others are missing, migration should either:

* complete the missing rows safely, or
* fail with a clear diagnostic requiring repair

Do not silently create inconsistent branch maps.

⸻

### 11. Pre-Phase-4 Project Fixture

#### 11.1 Requirement

Phase 4A0 must include a pre-Phase-4 completed project fixture.

This fixture must represent a fully-run Phase 3 Scorecard Pathway with no branch-related tables.

It may be either:

* a committed compressed .cardre project directory, or
* a deterministic fixture-generation script that explicitly creates the old schema and completed Phase 3 run state

The fixture must not be generated through current Phase 4 code paths.

#### 11.2 Fixture contents

The fixture must include:

* project metadata
* Scorecard Pathway plan
* at least one historical plan version
* a completed run
* run step records
* artefact records
* actual artefact files
* no plan_branches
* no branch_step_map
* no branch_comparisons
* no branch_comparison_snapshots
* no champion_assignments

#### 11.3 Acceptance criteria

Migration tests must prove:

* fixture opens before migration using compatibility read path
* migration creates baseline branch
* every historical plan version gets branch step map rows
* run records are not rewritten
* artefact records are not rewritten
* artefact paths still resolve
* execution fingerprints remain unchanged
* branch list endpoint works after migration
* baseline branch can be used in comparison setup after migration

Migration tests built only from freshly-created Phase 4 projects are not sufficient.

⸻

### 12. Branch Creation

#### 12.1 Endpoint

POST /plans/{plan_id}/branches

Request:

```json
{
  "project_id": "uuid",
  "base_plan_version_id": "uuid",
  "base_branch_id": "uuid",
  "branch_point_step_id": "manual-binning",
  "name": "Coarser utilisation bins",
  "description": "Merge sparse utilisation bands and test stability.",
  "branch_type": "binning_challenger",
  "created_reason": "Initial WOE showed sparse high-utilisation bins with unstable event rate.",
  "segment_filter_spec": null
}
```

#### 12.2 Validation

Backend must validate:

* project exists
* plan belongs to project
* base branch exists
* base branch belongs to plan
* base_plan_version_id equals the base branch's head_plan_version_id
* branch point step exists in the base plan version
* branch point canonical step is allowed
* branch type matches branch point
* branch name is non-empty
* created reason is non-empty
* segment filter spec is present for segment branches
* segment filter spec is absent or ignored for non-segment branches
* base branch has sufficient upstream evidence, or branch is created as blocked/not-run with diagnostics

#### 12.3 Branch point validation

Allowed branch point mapping:

```python
{
  "sample-definition": "segment_challenger",
  "variable-selection": "variable_selection_challenger",
  "manual-binning": "binning_challenger",
  "logistic-regression": "model_challenger",
  "score-scaling": "score_scaling_challenger",
  "cutoff-analysis": "cutoff_strategy_challenger"
}
```

Any other branch point should return:

```json
{
  "code": "BRANCH_POINT_NOT_ALLOWED",
  "message": "Branching from step profile is not supported in Phase 4."
}
```

#### 12.4 Descendant closure

Backend computes the descendant closure from the branch point.

For manual-binning:

```
manual-binning
final-woe-iv
woe-transform-train
logistic-regression
score-scaling
build-summary-report
apply-woe
apply-model
validation-metrics
cutoff-analysis
technical-manifest-stub
```

The duplicated closure must include all downstream steps required to produce branch-specific:

* refined bins
* final WOE/IV
* WOE-transformed train data
* model coefficients
* scorecard scaling
* summary report
* scored train/test/OOT outputs
* validation metrics
* cutoff analysis
* technical manifest

#### 12.5 Step ID generation

For each duplicated step:

```
{canonical_step_id}__br_{short_branch_id}
```

Example:

```
manual-binning__br_a81f3c
final-woe-iv__br_a81f3c
logistic-regression__br_a81f3c
validation-metrics__br_a81f3c
technical-manifest-stub__br_a81f3c
```

Rules:

* generated IDs must be unique within a plan version
* generated IDs must be stable within the branch
* generated IDs must be opaque
* do not include user-entered branch names
* do not let the frontend generate them
* do not rely on frontend string splitting to recover branch identity

#### 12.6 Parent remapping

For each duplicated step:

* if a parent is inside the duplicated closure, remap parent to the duplicated step ID
* if a parent is outside the duplicated closure, keep parent pointing to the shared upstream step
* do not copy artefacts
* do not copy run records

Example:

```
Baseline:
variable-selection -> manual-binning -> final-woe-iv

Branch from manual-binning:
variable-selection -> manual-binning__br_a81f3c -> final-woe-iv__br_a81f3c
```

#### 12.7 New branch step metadata

Each duplicated branch-owned step must have:

```json
{
  "step_id": "manual-binning__br_a81f3c",
  "canonical_step_id": "manual-binning",
  "branch_id": "br_a81f3c",
  "branch_label": "Coarser utilisation bins"
}
```

#### 12.8 Plan version creation

Branch creation creates a new plan version containing:

* existing baseline steps
* existing branch steps from other branches
* newly duplicated branch steps
* updated branch metadata
* branch step map records for the new plan version

Existing run history remains untouched.

#### 12.9 Response

```json
{
  "branch_id": "br_a81f3c",
  "plan_id": "uuid",
  "new_plan_version_id": "uuid",
  "name": "Coarser utilisation bins",
  "branch_type": "binning_challenger",
  "branch_point_step_id": "manual-binning",
  "branch_point_canonical_step_id": "manual-binning",
  "created_step_ids": {
    "manual-binning": "manual-binning__br_a81f3c",
    "final-woe-iv": "final-woe-iv__br_a81f3c",
    "woe-transform-train": "woe-transform-train__br_a81f3c",
    "logistic-regression": "logistic-regression__br_a81f3c",
    "score-scaling": "score-scaling__br_a81f3c",
    "build-summary-report": "build-summary-report__br_a81f3c",
    "apply-woe": "apply-woe__br_a81f3c",
    "apply-model": "apply-model__br_a81f3c",
    "validation-metrics": "validation-metrics__br_a81f3c",
    "cutoff-analysis": "cutoff-analysis__br_a81f3c",
    "technical-manifest-stub": "technical-manifest-stub__br_a81f3c"
  },
  "shared_upstream_step_ids": [
    "import",
    "define-metadata",
    "apply-exclusions",
    "profile",
    "validate-target",
    "sample-definition",
    "split",
    "explicit-missing-outlier-treatment",
    "fine-classing",
    "initial-woe-iv",
    "variable-clustering",
    "variable-selection"
  ],
  "status": "not_run",
  "warnings": []
}
```

⸻

### 13. Branch-Aware Read Model

#### 13.1 Branch list endpoint

GET /projects/{project_id}/branches

Query params:

```
plan_id?
status?
branch_type?
```

Response:

```json
{
  "project_id": "uuid",
  "branches": [
    {
      "branch_id": "br_baseline",
      "plan_id": "uuid",
      "name": "Baseline",
      "branch_type": "baseline",
      "status": "active",
      "base_branch_id": null,
      "base_plan_version_id": "uuid",
      "head_plan_version_id": "uuid",
      "branch_point_step_id": null,
      "branch_point_canonical_step_id": null,
      "is_champion": true,
      "latest_run_id": "uuid",
      "readiness": "ready",
      "warning_count": 0,
      "error_count": 0
    }
  ]
}
```

#### 13.2 Branch detail endpoint

GET /branches/{branch_id}

Response:

```json
{
  "branch_id": "br_a81f3c",
  "project_id": "uuid",
  "plan_id": "uuid",
  "name": "Coarser utilisation bins",
  "description": "Merge sparse utilisation bands and test stability.",
  "branch_type": "binning_challenger",
  "status": "active",
  "base_branch_id": "br_baseline",
  "base_plan_version_id": "uuid",
  "head_plan_version_id": "uuid",
  "branch_point_step_id": "manual-binning",
  "branch_point_canonical_step_id": "manual-binning",
  "created_reason": "Initial WOE showed sparse high-utilisation bins with unstable event rate.",
  "steps": [
    {
      "step_id": "manual-binning__br_a81f3c",
      "canonical_step_id": "manual-binning",
      "branch_id": "br_a81f3c",
      "is_shared_upstream": false,
      "is_branch_owned": true
    }
  ]
}
```

#### 13.3 Plan response changes

Plan step responses must include:

```json
{
  "step_id": "manual-binning__br_a81f3c",
  "canonical_step_id": "manual-binning",
  "branch_id": "br_a81f3c",
  "branch_label": "Coarser utilisation bins",
  "node_type": "cardre.manual_binning",
  "category": "refinement",
  "status": "succeeded",
  "is_stale": false,
  "position": 42,
  "params": {}
}
```

Rules:

* API calls use actual step_id
* UI display grouping may use canonical_step_id
* comparison aligns by canonical_step_id
* unknown canonical IDs should produce diagnostics, not crashes

⸻

### 14. Branch-Aware Parameter Editing

#### 14.1 Existing endpoint remains

POST /plans/{plan_id}/steps/{step_id}/params

This endpoint must accept generated branch step IDs.

Example:

POST /plans/{plan_id}/steps/manual-binning__br_a81f3c/params

#### 14.2 Branch edit rules

When editing a branch-owned step:

* validate actual step_id
* identify owning branch
* validate branch is active
* validate base plan version equals branch head
* validate params against node schema
* create new plan version
* preserve all branch metadata on all steps
* update the owning branch's head_plan_version_id
* create branch step map rows for the new plan version
* compute stale state
* return stale branch descendants

#### 14.3 Staleness

Editing a branch-owned step must stale:

* the changed branch-owned step
* its branch-owned descendants

It must not stale:

* baseline branch descendants
* unrelated challenger branches
* shared upstream steps

If a shared upstream step is edited in future functionality, all dependent branches should become stale or blocked. Phase 4 MVP does not need shared-upstream editing beyond existing baseline pathway editing.

#### 14.4 Response

```json
{
  "plan_id": "uuid",
  "new_plan_version_id": "uuid",
  "changed_step_id": "manual-binning__br_a81f3c",
  "branch_id": "br_a81f3c",
  "stale_step_ids": [
    "manual-binning__br_a81f3c",
    "final-woe-iv__br_a81f3c",
    "woe-transform-train__br_a81f3c",
    "logistic-regression__br_a81f3c",
    "score-scaling__br_a81f3c",
    "build-summary-report__br_a81f3c",
    "apply-woe__br_a81f3c",
    "apply-model__br_a81f3c",
    "validation-metrics__br_a81f3c",
    "cutoff-analysis__br_a81f3c",
    "technical-manifest-stub__br_a81f3c"
  ]
}
```

⸻

### 15. Branch-Aware Manual Binning

#### 15.1 Generalise fixed manual-binning endpoint

Phase 3 manual binning was fixed around:

```
manual-binning
fine-classing
variable-selection
```

Phase 4 must support branch-generated step IDs.

Endpoint:

GET /plans/{plan_id}/steps/{step_id}/editor-state?project_id={project_id}

Where step_id may be:

```
manual-binning
manual-binning__br_a81f3c
```

#### 15.2 Validation

Backend must validate:

* plan exists
* step exists
* step node type is cardre.manual_binning
* step canonical ID is manual-binning
* branch exists if branch_id is present
* branch is active
* required upstream source steps are resolvable
* required upstream source steps are current
* required upstream artefacts exist and are readable

#### 15.3 Branch-aware upstream resolution

The manual binning editor must resolve:

* source bins from nearest upstream ancestor with canonical_step_id = "fine-classing"
* selected variables from nearest upstream ancestor with canonical_step_id = "variable-selection"

It must resolve actual step IDs by branch-aware graph ancestry.

It must not hardcode:

```
fine-classing
variable-selection
manual-binning
```

except as canonical step IDs.

#### 15.4 Ancestor resolution algorithm

Required helper:

```python
def find_nearest_ancestor_by_canonical_step_id(
    *,
    steps: list[StepSpec],
    branch_step_map: list[BranchStepMapRow],
    target_step_id: str,
    branch_id: str,
    canonical_step_id: str,
) -> StepSpec | None:
    steps_by_id = {s.step_id: s for s in steps}
    target = steps_by_id[target_step_id]
    # Step IDs considered part of this branch's effective pathway.
    # Includes both branch-owned steps and shared upstream steps.
    branch_scope_step_ids = {
        row.step_id
        for row in branch_step_map
        if row.branch_id == branch_id
    }
    if target_step_id not in branch_scope_step_ids:
        raise PlanValidationError(
            "STEP_NOT_IN_BRANCH",
            f"Step {target_step_id} is not in branch {branch_id}",
        )
    visited = set()
    queue = [(parent_id, 1) for parent_id in target.parent_step_ids]
    candidates = []
    while queue:
        current_step_id, depth = queue.pop(0)
        if current_step_id in visited:
            continue
        visited.add(current_step_id)
        if current_step_id not in branch_scope_step_ids:
            continue
        current = steps_by_id[current_step_id]
        if current.canonical_step_id == canonical_step_id:
            candidates.append((depth, current.position, current))
            continue
        for parent_id in current.parent_step_ids:
            queue.append((parent_id, depth + 1))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1]))
    best_depth = candidates[0][0]
    best = [item for item in candidates if item[0] == best_depth]
    if len(best) > 1 and best[0][1] == best[1][1]:
        raise PlanValidationError(
            "AMBIGUOUS_BRANCH_ANCESTOR",
            f"Multiple ancestors found for canonical step {canonical_step_id}",
        )
    return candidates[0][2]
```

Tie-breaking rule:

* prefer nearest graph ancestor
* if multiple are equally near, prefer greatest position less than target position
* if still ambiguous, raise AMBIGUOUS_BRANCH_ANCESTOR

Do not use string construction such as:

```python
"variable-selection__br_" + branch_id
```

#### 15.5 Editor-state response

```json
{
  "plan_id": "uuid",
  "plan_version_id": "uuid",
  "branch_id": "br_a81f3c",
  "step_id": "manual-binning__br_a81f3c",
  "canonical_step_id": "manual-binning",
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

#### 15.6 Preview endpoint

POST /plans/{plan_id}/steps/{step_id}/manual-binning/preview

Request:

```json
{
  "project_id": "uuid",
  "plan_version_id": "uuid",
  "overrides": []
}
```

Rules:

* supports baseline and branch manual-binning steps
* preview calls backend validation
* preview uses branch-aware upstream resolution
* preview creates no official artefacts
* preview creates no plan version
* preview performs no React-side bin calculations

#### 15.7 Save

Save uses the general params endpoint:

POST /plans/{plan_id}/steps/{step_id}/params

Saving manual-binning overrides:

* validates source bin IDs
* requires reasons
* rejects non-adjacent numeric merges
* creates new plan version
* updates branch head if branch-owned
* marks branch descendants stale
* official refined bins are created only by rerunning branch steps

⸻

### 16. Branch Execution

#### 16.1 Endpoint

Extend POST /runs.

Request:

```json
{
  "project_id": "uuid",
  "plan_id": "uuid",
  "plan_version_id": "uuid",
  "run_scope": "branch",
  "branch_id": "br_a81f3c",
  "from_step_id": null,
  "to_step_id": null
}
```

Allowed run_scope values:

```
full_plan
branch
step_descendants
```

There is no comparison_refresh run scope.

Comparison refresh is not node execution and must not create run records.

#### 16.2 Branch execution rules

When running a branch:

1. Load branch.
2. Confirm branch is active.
3. Confirm request plan version equals branch head_plan_version_id.
4. Load branch step map for the branch and plan version.
5. Determine branch-owned steps.
6. Determine shared upstream steps.
7. Confirm required shared upstream evidence is current.
8. If shared upstream evidence is stale, block branch run.
9. Execute stale or not-run branch-owned steps in topological order.
10. Record run steps against actual branch step IDs.
11. Associate run with branch_id.
12. Do not rerun current shared upstream steps.
13. Do not update head_plan_version_id for a normal run.

#### 16.3 Shared upstream stale blocker

Example:

```json
{
  "status": "blocked",
  "code": "SHARED_UPSTREAM_STALE",
  "message": "This branch cannot run because shared upstream step variable-selection is stale.",
  "stale_shared_step_ids": [
    "variable-selection"
  ],
  "suggested_action": "Run the shared pathway up to variable-selection, then rerun this branch."
}
```

#### 16.4 Synchronous and async compatibility

If Phase 3 still uses synchronous execution:

* POST /runs may block until completion
* UI shows indeterminate running state
* UI must not fake per-step progress
* UI must prevent duplicate branch runs

If background execution exists:

* POST /runs returns queued run ID
* UI polls run status
* cancellation only appears if safe backend cancellation exists

Do not mix fake async with synchronous execution.

#### 16.5 Synchronous response

```json
{
  "run_id": "uuid",
  "branch_id": "br_a81f3c",
  "status": "succeeded",
  "executed_step_ids": [
    "manual-binning__br_a81f3c",
    "final-woe-iv__br_a81f3c",
    "woe-transform-train__br_a81f3c",
    "logistic-regression__br_a81f3c",
    "score-scaling__br_a81f3c",
    "build-summary-report__br_a81f3c",
    "apply-woe__br_a81f3c",
    "apply-model__br_a81f3c",
    "validation-metrics__br_a81f3c",
    "cutoff-analysis__br_a81f3c",
    "technical-manifest-stub__br_a81f3c"
  ],
  "warnings": []
}
```

⸻

### 17. Branch Comparisons

#### 17.1 Purpose

The comparison engine returns an audit-friendly comparison between baseline and challenger branches.

It compares:

* WOE/IV outputs
* bin definitions
* selected variables
* model coefficients
* score scaling
* validation metrics by role
* calibration
* cutoff/strategy outputs
* warnings and errors
* fallback usage where available
* manifest completeness

#### 17.2 Create comparison intent

POST /branch-comparisons

Request:

```json
{
  "project_id": "uuid",
  "plan_id": "uuid",
  "baseline_branch_id": "br_baseline",
  "challenger_branch_ids": [
    "br_a81f3c",
    "br_b42c99"
  ],
  "comparison_spec": {
    "roles": ["train", "test", "oot"],
    "include_woe_iv": true,
    "include_model": true,
    "include_validation": true,
    "include_cutoff": true,
    "include_warnings": true
  },
  "created_reason": "Compare binning challenger against baseline before champion selection."
}
```

Response:

```json
{
  "comparison_id": "cmp_123",
  "project_id": "uuid",
  "plan_id": "uuid",
  "baseline_branch_id": "br_baseline",
  "challenger_branch_ids": [
    "br_a81f3c",
    "br_b42c99"
  ],
  "latest_snapshot_id": null,
  "latest_ready": null,
  "warnings": []
}
```

Creating comparison intent does not create model evidence.

#### 17.3 Refresh comparison

POST /branch-comparisons/{comparison_id}/refresh

Rules:

* does not execute modelling nodes
* does not create run records
* reads existing branch evidence
* recomputes readiness
* creates a new immutable comparison JSON artefact if ready
* creates a new branch_comparison_snapshots row
* updates latest snapshot pointer on branch_comparisons

Response:

```json
{
  "comparison_id": "cmp_123",
  "comparison_snapshot_id": "cmp_snap_456",
  "ready": true,
  "comparison_artifact_id": "artifact_uuid",
  "refreshed_at": "iso",
  "warnings": []
}
```

If blocked:

```json
{
  "comparison_id": "cmp_123",
  "comparison_snapshot_id": null,
  "ready": false,
  "comparison_artifact_id": null,
  "blocked_reason": "Challenger branch has no current validation-metrics output.",
  "missing_or_stale": [
    {
      "branch_id": "br_a81f3c",
      "canonical_step_id": "validation-metrics",
      "step_id": "validation-metrics__br_a81f3c",
      "status": "not_run"
    }
  ]
}
```

#### 17.4 Read comparison

GET /branch-comparisons/{comparison_id}

Returns comparison intent and latest snapshot summary.

#### 17.5 Read comparison snapshot

GET /branch-comparison-snapshots/{comparison_snapshot_id}

Returns immutable comparison snapshot metadata and artefact reference.

#### 17.6 Comparison readiness

A branch is comparison-ready only if current successful evidence exists for required canonical steps.

For normal model/binner branches, minimum required canonical evidence:

```
final-woe-iv
logistic-regression
score-scaling
validation-metrics
cutoff-analysis
technical-manifest-stub
```

For cutoff-only branches, minimum evidence may be:

```
cutoff-analysis
technical-manifest-stub
```

plus shared current validation evidence.

Readiness checks must not trigger execution.

Readiness may be cached.

Cache must be invalidated when:

* branch params change
* branch head plan version changes
* relevant branch run completes
* branch is archived
* comparison spec changes

Explicit refresh recomputes readiness.

⸻

### 18. Comparison Content Contract

#### 18.1 Branch summary

```json
{
  "branch_id": "br_a81f3c",
  "name": "Coarser utilisation bins",
  "branch_type": "binning_challenger",
  "branch_point_canonical_step_id": "manual-binning",
  "latest_run_id": "uuid",
  "latest_plan_version_id": "uuid",
  "is_champion": false,
  "readiness": "ready",
  "warning_count": 3,
  "error_count": 0
}
```

#### 18.2 WOE/IV comparison

```json
{
  "woe_iv": {
    "variables": [
      {
        "variable": "duration_months",
        "baseline": {
          "iv": 0.18,
          "bin_count": 6,
          "zero_cell_warning_count": 0,
          "sparse_bin_warning_count": 1,
          "monotonicity_warning": false
        },
        "challengers": {
          "br_a81f3c": {
            "iv": 0.16,
            "bin_count": 4,
            "zero_cell_warning_count": 0,
            "sparse_bin_warning_count": 0,
            "monotonicity_warning": false
          }
        },
        "difference": {
          "iv_delta_vs_baseline": -0.02,
          "bin_count_delta_vs_baseline": -2
        }
      }
    ]
  }
}
```

#### 18.3 Model comparison

```json
{
  "model": {
    "variables": [
      {
        "variable": "duration_months",
        "baseline": {
          "included": true,
          "coefficient": 0.42,
          "points_range": 55
        },
        "challengers": {
          "br_a81f3c": {
            "included": true,
            "coefficient": 0.39,
            "points_range": 47
          }
        }
      }
    ],
    "branch_level": {
      "baseline": {
        "feature_count": 8,
        "converged": true,
        "warnings": []
      },
      "br_a81f3c": {
        "feature_count": 8,
        "converged": true,
        "warnings": []
      }
    }
  }
}
```

#### 18.4 Validation comparison

Validation metrics must be separated by role.

```json
{
  "validation": {
    "roles": {
      "train": {
        "baseline": {
          "auc": 0.74,
          "gini": 0.48,
          "ks": 0.36,
          "calibration": {}
        },
        "br_a81f3c": {
          "auc": 0.73,
          "gini": 0.46,
          "ks": 0.34,
          "calibration": {}
        }
      },
      "test": {},
      "oot": {}
    }
  }
}
```

#### 18.5 Cutoff comparison

```json
{
  "cutoff": {
    "roles": {
      "oot": [
        {
          "cutoff": 620,
          "baseline": {
            "approval_rate": 0.58,
            "bad_rate": 0.041,
            "capture_rate": 0.72,
            "population_count": 12000
          },
          "br_a81f3c": {
            "approval_rate": 0.57,
            "bad_rate": 0.039,
            "capture_rate": 0.74,
            "population_count": 12000
          }
        }
      ]
    }
  }
}
```

#### 18.6 Warning comparison

Comparison output must surface:

* zero-cell WOE warnings
* smoothing policy usage
* sparse bins
* non-monotonic WOE
* model convergence warnings
* coefficient sign warnings
* high fallback usage
* calibration warnings
* PSI/stability warnings where present
* missing evidence
* stale evidence

Warnings must not be buried behind raw JSON only.

⸻

### 19. Champion Assignment

#### 19.1 MVP rule

Phase 4 MVP requires a comparison snapshot before a branch can be marked champion.

No comparison snapshot, no champion assignment.

There is no force mode in Phase 4 MVP.

#### 19.2 Endpoint

POST /plans/{plan_id}/champion

Request:

```json
{
  "project_id": "uuid",
  "branch_id": "br_a81f3c",
  "comparison_id": "cmp_123",
  "comparison_snapshot_id": "cmp_snap_456",
  "scope_type": "project",
  "scope_key": "default",
  "assigned_reason": "Selected challenger because OOT bad rate at target approval was lower, sparse-bin warnings were reduced, and Gini loss was immaterial."
}
```

#### 19.3 Validation

Backend must validate:

* project exists
* plan exists
* branch exists
* branch belongs to plan/project
* branch is active
* branch has current successful evidence
* comparison exists
* comparison snapshot exists
* comparison snapshot is ready
* comparison snapshot includes selected branch
* comparison snapshot includes baseline branch
* assigned reason is non-empty
* scope is valid

#### 19.4 Supersession

If another active champion exists for the same:

project_id + plan_id + scope_type + scope_key

then assigning the new champion must:

1. set superseded_at on previous assignment
2. create new champion assignment
3. link old assignment to new assignment where possible
4. commit atomically

#### 19.5 Response

```json
{
  "champion_assignment_id": "champ_123",
  "plan_id": "uuid",
  "champion_branch_id": "br_a81f3c",
  "previous_champion_branch_id": "br_baseline",
  "scope_type": "project",
  "scope_key": "default",
  "assigned_at": "iso",
  "assigned_reason": "Selected challenger because OOT bad rate at target approval was lower, sparse-bin warnings were reduced, and Gini loss was immaterial."
}
```

#### 19.6 Rules

Champion assignment:

* does not mutate model artefacts
* does not delete challengers
* does not rewrite run evidence
* creates audit metadata
* is included in branch export
* is visible in UI
* can be superseded
* cannot target archived branches

⸻

### 20. Segment-Specific Challenger Branches

#### 20.1 Purpose

Segment branches allow the modeller to test whether a separate scorecard for a subpopulation is justified.

Segment branches are governance-sensitive and must remain constrained.

#### 20.2 Branch point

Segment branches are created from:

sample-definition

They duplicate:

```
sample-definition
split
explicit-missing-outlier-treatment
fine-classing
initial-woe-iv
variable-clustering
variable-selection
manual-binning
final-woe-iv
woe-transform-train
logistic-regression
score-scaling
build-summary-report
apply-woe
apply-model
validation-metrics
cutoff-analysis
technical-manifest-stub
```

#### 20.3 Segment filter spec

Segment filters reuse the exact ApplyExclusionsNode rule contract:

```json
{
  "segment_filter_spec": {
    "name": "Homeowners only",
    "rules": [
      {
        "column": "housing_status",
        "operator": "==",
        "value": "owner",
        "reason": "Assess whether a separate homeowner scorecard is justified."
      }
    ]
  }
}
```

Supported operators:

```
==
!=
<
<=
>
>=
in
not_in
is_null
is_not_null
```

Validation semantics:

* non-empty reason required
* known column required
* supported operator required
* value required except where operator semantics do not require it
* same error handling as exclusion rules

Implementation should extract and reuse shared rule validation/filter logic rather than duplicating it inside branch services.

#### 20.4 Semantic distinction

Exclusion rules remove rows from the modelling population for documented policy or data-quality reasons.

Segment filters define a challenger branch population.

They may share validation mechanics but they are different modelling decisions and must be labelled differently in audit evidence.

#### 20.5 Segment branch warnings

The UI should warn:

Segment-specific challengers can produce unstable models if the segment sample is too small or not representative. Review train/test/OOT counts, bad-rate stability, and cutoff trade-offs before marking champion.

Segment branches must show:

* segment row count
* train/test/OOT row counts
* bad rate by role
* warnings for small samples
* warnings for low bad counts
* warnings for unstable validation metrics

No regulator-ready claims.

⸻

### 21. Selected Branch Export

#### 21.1 Endpoint

POST /exports/audit-pack

Request:

```json
{
  "project_id": "uuid",
  "plan_id": "uuid",
  "branch_id": "br_a81f3c",
  "comparison_id": "cmp_123",
  "comparison_snapshot_id": "cmp_snap_456",
  "include_row_level_data": false,
  "export_path": "/local/path/export"
}
```

#### 21.2 Export contents

Selected branch export should include:

* project metadata
* selected branch metadata
* branch creation reason
* base branch reference
* branch point
* branch step map
* shared upstream evidence
* branch-owned downstream evidence
* selected plan version
* run IDs
* run step IDs
* input artefact references
* output artefact references
* logical hashes
* physical hashes
* node type versions
* params and params hashes
* warnings
* errors
* WOE/IV outputs
* model artefacts
* scorecard artefacts
* validation metrics
* cutoff analysis
* comparison snapshot artefact, if provided
* champion assignment, if branch is champion
* technical manifest for selected branch

#### 21.3 Export rules

* export selected branch only by default
* include shared upstream lineage required to explain the branch
* exclude unrelated challenger branches unless explicitly requested
* exclude row-level data by default
* display export path and hashes
* missing artefacts produce structured diagnostics
* corrupt artefacts produce structured diagnostics
* export must not imply that Phase 5's human-readable governance report exists yet

⸻

### 22. Frontend UX

Phase 4 extends the Phase 3 workspace shell.

It should not replace the desktop layout.

#### 22.1 Navigation

Add:

```
Branches
Compare
Champion
```

Suggested nav:

```
Dataset
Pathway
Branches
Compare
Runs
Artefacts
Exports
Diagnostics
```

#### 22.2 Branch manager

Branch manager shows:

* branch name
* branch type
* branch point
* base branch
* status
* stale/not-run/current state
* latest run timestamp
* champion badge
* warning count
* error count
* archive action
* run branch action
* compare action

#### 22.3 Create branch wizard

Steps:

1. Choose base branch.
2. Choose branch type.
3. Choose branch point.
4. Name branch.
5. Enter branch reason.
6. Configure optional segment filter.
7. Review shared upstream steps.
8. Review duplicated downstream steps.
9. Create branch.

Wizard must explain:

* which steps are shared
* which steps are duplicated
* run history is not copied
* artefacts are not copied
* branch must be run to create official evidence

#### 22.4 Pathway display modes

Add:

```
Single Branch View
Branch Lane View
Comparison View
```

**Single Branch View**

Shows one branch's effective pathway.

Shared upstream steps have a "shared" indicator.

Branch-owned steps have a branch label.

**Branch Lane View**

Shows baseline and selected challengers as constrained lanes after branch points.

This is not a freeform canvas.

**Comparison View**

Shows side-by-side comparison cards/tables.

#### 22.5 Branch-aware inspector

The Phase 4 inspector must not become a dumping ground.

Add a compact identity section:

* display label
* actual step_id
* canonical_step_id
* branch name
* branch ownership: shared or branch-owned

Verbose IDs should be behind expand/copy controls.

Branch metadata should be collapsible.

Comparison readiness should not appear on every step by default. It should appear only for comparison-relevant steps or in the Compare view.

Acceptance criteria:

* baseline step inspector remains readable
* branch step inspector shows branch identity without overwhelming params
* actual step_id is copyable
* branch-owned/shared state is visible
* params/manual-binning actions remain prominent

#### 22.6 Champion UX

Champion assignment uses a modal.

Fields:

* branch selected
* comparison selected
* comparison snapshot selected
* scope
* rationale text
* warnings
* confirmation that previous champion will be superseded

Champion button is disabled unless:

* branch is active
* comparison snapshot exists
* comparison snapshot is ready
* selected branch is included in snapshot
* rationale text is non-empty

#### 22.7 Accessibility

Continue Phase 3 rules:

* no colour-only statuses
* text labels plus icons
* keyboard navigable controls
* visible focus states
* tables support horizontal scrolling
* destructive actions require confirmation
* stale/missing evidence states are readable by text

⸻

### 23. API Summary

New or changed Phase 4 endpoints:

```
GET  /projects/{project_id}/branches
GET  /branches/{branch_id}
PATCH /branches/{branch_id}
POST /branches/{branch_id}/archive
POST /plans/{plan_id}/branches
GET  /plans/{plan_id}/branches
POST /runs
GET  /runs/{run_id}
GET  /runs/{run_id}/steps
GET  /plans/{plan_id}/steps/{step_id}/editor-state
POST /plans/{plan_id}/steps/{step_id}/manual-binning/preview
POST /plans/{plan_id}/steps/{step_id}/params
POST /branch-comparisons
GET  /branch-comparisons/{comparison_id}
POST /branch-comparisons/{comparison_id}/refresh
GET  /branch-comparison-snapshots/{comparison_snapshot_id}
POST /plans/{plan_id}/champion
GET  /plans/{plan_id}/champion
POST /exports/audit-pack
```

Removed from proposal:

```
run_scope = comparison_refresh
```

Comparison refresh is not a run.

⸻

### 24. Testing Strategy

#### 24.1 Backend tests

Add tests for:

* StepSpec backwards-compatible construction
* StepSpec.__post_init__ canonical backfill
* StepSpec.to_dict includes branch fields
* StepSpec.from_dict tolerates missing branch fields
* replace_step_params preserves branch fields
* schema migration creates all branch tables
* pre-Phase-4 fixture migration
* baseline branch creation
* branch step map for every historical plan version
* run records unchanged after migration
* artefacts unchanged after migration
* branch list endpoint after migration
* branch creation from each permitted branch point
* branch creation rejects forbidden branch points
* branch creation requires reason
* generated step IDs unique
* canonical step IDs preserved
* descendant closure correct
* parent remapping correct
* no artefacts copied during branch creation
* no run records copied during branch creation
* branch head updates after branch param edit
* branch-owned param edit stales only branch descendants
* shared upstream stale blocker works
* branch run executes only branch-owned stale steps
* branch-aware manual binning editor resolves generated step IDs
* branch-aware ancestor resolution handles branch-owned and shared upstream steps
* ambiguous ancestor detection
* segment filter reuses exclusion operator contract
* comparison intent creation
* comparison refresh creates immutable snapshot
* comparison readiness blocks missing evidence
* champion assignment requires comparison snapshot
* champion assignment supersedes previous champion
* selected branch export includes lineage
* selected branch export excludes row-level data by default

#### 24.2 Frontend unit tests

Add tests for:

* branch manager rendering
* branch creation wizard validation
* branch lane rendering
* single branch view
* canonical vs actual step ID display
* branch-owned/shared indicators
* branch-aware step inspector
* comparison table rendering
* missing comparison evidence state
* stale comparison evidence state
* champion modal rationale requirement
* champion button disabled without comparison snapshot
* champion badge rendering
* archive confirmation

#### 24.3 Integration flow: baseline migration

```
Load pre-Phase-4 completed project fixture
-> run Phase 4 migration
-> confirm baseline branch exists
-> confirm branch_step_map exists for every historical plan version
-> confirm old run records still load
-> confirm old artefacts still preview
-> confirm branch list endpoint works
```

#### 24.4 Integration flow: binning challenger

```
Create/open migrated project
-> run baseline pathway if needed
-> create manual-binning challenger
-> edit challenger manual-binning params
-> run challenger branch
-> compare baseline vs challenger
-> refresh comparison
-> mark challenger champion with reason
-> export champion branch
-> close/reopen project
-> confirm branches, comparison snapshot, champion assignment, and export evidence persist
```

#### 24.5 Integration flow: segment challenger

```
Create/open project
-> run baseline pathway
-> create segment challenger from sample-definition
-> apply structured segment filter
-> run segment branch
-> confirm segment-specific split artefacts
-> confirm segment validation metrics
-> compare segment branch where meaningful
-> export segment branch evidence
```

⸻

### 25. Implementation Slices

#### Phase 4A0 — Branch schema, StepSpec compatibility, and legacy baseline migration

Deliverables:

* add branch-aware StepSpec fields:
    * canonical_step_id
    * branch_id
* preserve backwards-compatible construction
* update to_dict
* update from_dict
* update replace_step_params
* create tables:
    * plan_branches
    * branch_step_map
    * branch_comparisons
    * branch_comparison_snapshots
    * champion_assignments
* add project schema migration
* add metadata-only baseline migration
* populate branch_step_map for every historical plan version
* add deterministic pre-Phase-4 completed project fixture
* add migration regression tests against fixture

Acceptance criteria:

* existing StepSpec(...) call sites continue to work
* legacy steps deserialize with canonical_step_id == step_id
* legacy steps deserialize with branch_id is None before migration
* migration creates one baseline branch per Scorecard Pathway
* migration maps every historical step in every historical plan version
* migration does not rewrite run_steps
* migration does not rewrite artefacts
* migration does not rewrite execution fingerprints
* new plan versions always write canonical_step_id and branch_id

No Phase 4 branch creation work may start before this slice is complete.

#### Phase 4A — Branch-aware read model and baseline UI

Deliverables:

* GET /projects/{project_id}/branches
* GET /branches/{branch_id}
* branch-aware plan response fields
* baseline branch manager UI
* branch-aware inspector identity section
* frontend display metadata updated for canonical step IDs

Acceptance criteria:

* migrated project shows baseline branch
* branch list works for migrated projects
* plan response includes canonical_step_id and branch_id
* baseline inspector remains readable
* actual step IDs are still used in API calls

#### Phase 4B — Branch creation

Deliverables:

* POST /plans/{plan_id}/branches
* permitted branch point validation
* branch type validation
* descendant closure algorithm
* branch step ID generation
* parent remapping
* branch creation wizard
* branch lane display

Acceptance criteria:

* user can create challenger from manual-binning
* user can create challenger from logistic-regression
* forbidden branch points are rejected
* reason is required
* duplicated steps are not run automatically
* shared upstream is displayed clearly
* branch head plan version is set correctly

#### Phase 4C — Branch-aware editing and execution

Deliverables:

* generated step IDs accepted by params endpoint
* branch-owned param edits update branch head
* branch-aware manual binning editor
* branch-aware manual binning preview
* branch-aware ancestor resolution helper
* branch-scoped POST /runs
* shared-upstream stale blocker
* branch-scoped run history

Acceptance criteria:

* branch param edit stales only branch descendants
* baseline remains current after challenger edits
* manual binning editor works for generated step IDs
* ancestor resolution does not hardcode actual step IDs
* branch run executes only needed branch-owned stale steps
* shared upstream stale evidence blocks branch run with useful error

#### Phase 4D — Comparison engine and immutable snapshots

Deliverables:

* POST /branch-comparisons
* POST /branch-comparisons/{comparison_id}/refresh
* GET /branch-comparisons/{comparison_id}
* GET /branch-comparison-snapshots/{comparison_snapshot_id}
* comparison readiness engine
* comparison JSON artefact
* WOE/IV comparison
* model comparison
* validation comparison
* cutoff comparison
* warning comparison
* comparison UI

Acceptance criteria:

* comparison intent can be created
* refresh does not execute modelling nodes
* refresh creates immutable snapshot artefact
* missing evidence blocks comparison clearly
* train/test/OOT metrics are separated
* UI does not declare automatic winner

#### Phase 4E — Champion assignment and selected branch export

Deliverables:

* POST /plans/{plan_id}/champion
* GET /plans/{plan_id}/champion
* champion UI
* supersession logic
* selected branch export
* branch-aware technical manifest extension

Acceptance criteria:

* champion requires comparison snapshot
* champion requires rationale
* previous champion is superseded
* champion assignment persists after reopen
* selected branch export includes lineage
* selected branch export includes comparison snapshot and champion metadata
* export excludes row-level data by default

#### Phase 4F — Segment-specific challenger branches

Deliverables:

* segment branch creation from sample-definition
* structured segment filter spec
* reuse ApplyExclusionsNode rule contract
* segment-specific branch run
* segment-specific validation display
* segment branch export

Acceptance criteria:

* segment branch creates its own downstream split/model/validation evidence
* segment filter is recorded with reason
* unsupported operators are rejected
* small-sample warnings are displayed
* no arbitrary Python or SQL filters are allowed
* segment branch can be exported

⸻

### 26. Risks and Mitigations

**Risk 1:** Existing projects break after StepSpec changes

Mitigation:

* keyword-only defaults
* __post_init__ backfill
* tolerant from_dict
* migration fixture from real pre-Phase-4 project

**Risk 2:** Branch lineage is inferred from strings

Mitigation:

* explicit canonical_step_id
* explicit branch_id
* explicit branch_step_map
* no frontend ID generation
* no string split identity logic

**Risk 3:** Baseline migration only works for fresh projects

Mitigation:

* committed or scripted pre-Phase-4 fixture
* migration tests against old schema
* branch APIs tested against migrated fixture

**Risk 4:** Manual binning remains hardcoded to baseline

Mitigation:

* generalised get_manual_binning_editor_state(plan_id, step_id)
* branch-aware ancestor resolver
* actual upstream step IDs resolved from branch map

**Risk 5:** Comparison refresh mutates evidence

Mitigation:

* refresh uses POST
* every refresh creates immutable comparison artefact
* snapshots table preserves comparison history

**Risk 6:** Champion can be assigned without evidence

Mitigation:

* comparison snapshot required for MVP
* ready snapshot required
* rationale required

**Risk 7:** Segment filters duplicate exclusion logic

Mitigation:

* extract shared filter validation helper
* reuse exact exclusion operator contract
* preserve separate segment/audit semantics

**Risk 8:** Inspector becomes unusably dense

Mitigation:

* compact identity section
* collapsible branch metadata
* copy controls for verbose IDs
* comparison readiness shown primarily in Compare view

⸻

### 27. End-to-End Acceptance Flow

Final Phase 4 acceptance flow:

1. Open a completed pre-Phase-4 project.
2. Run Phase 4 migration.
3. Confirm baseline branch is created.
4. Confirm historical run records still load.
5. Confirm artefacts still preview.
6. Open branch manager.
7. Create a manual-binning challenger branch.
8. Confirm shared upstream and duplicated downstream steps are displayed.
9. Open branch manual-binning editor.
10. Confirm source bins resolve from branch-aware ancestry.
11. Add valid override with reason.
12. Save override.
13. Confirm new plan version is created.
14. Confirm challenger branch head updates.
15. Confirm challenger descendants are stale.
16. Confirm baseline remains current.
17. Run challenger branch.
18. Confirm branch-owned steps execute.
19. Create comparison intent.
20. Refresh comparison.
21. Confirm immutable comparison snapshot and artefact are created.
22. Inspect WOE/IV comparison.
23. Inspect model comparison.
24. Inspect train/test/OOT validation comparison.
25. Inspect cutoff comparison.
26. Mark challenger champion with rationale.
27. Confirm previous champion is superseded.
28. Export selected champion branch.
29. Confirm export includes shared upstream lineage, branch-owned evidence, comparison snapshot, champion assignment, hashes, warnings, and technical manifest.
30. Close and reopen project.
31. Confirm baseline, challenger, comparison snapshot, champion assignment, run history, artefacts, and export evidence persist.

⸻

### 28. Final Definition of Done

Phase 4 is done when:

A user can open a Phase 3-complete Cardre project, migrate it into the branch model without rewriting historical run evidence, see the baseline branch, create constrained challenger branches from approved scorecard pathway points, edit branch-specific parameters or manual binning choices, run challenger branches without corrupting shared upstream or baseline evidence, compare branches across WOE/IV, binning, variables, model outputs, validation metrics, and cutoff trade-offs, mark a champion branch with rationale based on an immutable comparison snapshot, and export the selected branch with complete lineage, hashes, run evidence, warnings, comparison evidence, champion metadata, and technical manifest evidence.

The user should still not need to touch Python, SQLite, Parquet, JSON artefacts, or FastAPI routes directly.

The implementation must not proceed past Phase 4A0 until legacy Phase 3 projects can be opened, migrated into a baseline branch, and queried through the branch-aware read model without rewriting historical execution evidence.

That is the line between real branchable auditability and a demo-only branching mirage.
