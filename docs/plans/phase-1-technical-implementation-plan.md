# Phase 1 Technical Implementation Plan

This document is written for an implementation agent with limited context. Follow
it in order. Do not start scorecard modelling features before completing the
Phase 1A foundation.

## Objective

Phase 1 proves Cardre's local, reproducible execution foundation.

Phase 1A builds the Python engine/storage proof:

- local `.cardre` project directory
- SQLite metadata database
- filesystem artifact store
- immutable artifacts with physical and logical hashes
- German Credit dataset import into canonical Parquet
- fixed proof pathway execution
- train/test/OOT split artifacts
- role-based leakage prevention
- run/run-step audit evidence
- execution fingerprints
- computed staleness
- replay from changed steps

Phase 1B proves the desktop shell:

- FastAPI sidecar
- React/Tauri shell
- create/open project
- import German Credit
- run proof pathway
- display statuses/stale markers from backend state

Phase 1 does **not** implement real fine classing, WOE/IV, logistic regression,
manual binning, score scaling, or full governance reports.

## Required Technical Decisions

- Use `polars` for tabular reading/transforms/profiling.
- Use `pyarrow`/Parquet for canonical dataset artifacts.
- Use SQLite for metadata only. Do not store tabular data or blobs in SQLite.
- Use filesystem artifacts for datasets, reports, definitions, and models.
- Store both `physical_hash` and `logical_hash` for every artifact.
- Treat stale state as computed, not stored.
- Preserve old runs and run steps. Never mutate run history.
- Enforce train/test/OOT role access in the executor before node execution.

## Dependencies

Add in Phase 1A:

- `polars`
- `pyarrow`
- `pydantic`
- `pytest`

Add in Phase 1B:

- `fastapi`
- `uvicorn`

Avoid `pandas` unless absolutely needed for the Taiwan `.xls` file. The Phase 1A
canonical import target is German Credit, so `.xls` support can wait.

## Dataset Fixtures

Use `docs/data-sources/phase-1-datasets.json`.

Primary Phase 1A fixture:

- Dataset: UCI Statlog German Credit Data
- Source file: `german.data`
- Local ignored raw archive path:
  `input/credit/uci-german-credit/raw/statlog-german-credit-data.zip`
- Archive SHA-256:
  `e12d9d5def6845c0622634a1cd2ab87fa470668c4298f1ec52a4e403376a435b`
- Target mapping: `1 = good`, `2 = bad`
- Rows: 1,000
- Features: 20

Secondary fixture for later Phase 1A/Phase 2 performance checks:

- Dataset: UCI Default of Credit Card Clients
- Source file inside archive: `default of credit card clients.xls`
- Local ignored raw archive path:
  `input/credit/uci-default-credit-card-clients/raw/default-credit-card-clients.zip`
- Archive SHA-256:
  `56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602`
- Target mapping: `0 = non_default`, `1 = default`
- Defer importer unless Excel support is already easy.

Raw datasets are ignored by git. Do not commit them.

## Target Project Layout

Each Cardre project is a directory:

```text
example.cardre/
  cardre.sqlite
  datasets/
  artifacts/
  exports/
  logs/
```

SQLite stores metadata only:

- project metadata
- plans and plan versions
- plan steps
- runs and run steps
- artifact references
- warnings/errors

Filesystem stores artifact bytes:

- canonical Parquet datasets
- JSON reports
- JSON definitions
- technical manifests

## Phase 1A Slice 1: SQLite Schema And Project Store

Implement first. Do not implement nodes before this is stable.

### Tables

Create the initial SQLite schema with these tables:

#### `projects`

- `project_id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `cardre_version TEXT NOT NULL`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

#### `plans`

- `plan_id TEXT PRIMARY KEY`
- `project_id TEXT NOT NULL`
- `name TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

#### `plan_versions`

- `plan_version_id TEXT PRIMARY KEY`
- `plan_id TEXT NOT NULL`
- `version_number INTEGER NOT NULL`
- `created_at TEXT NOT NULL`
- `description TEXT NOT NULL DEFAULT ''`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

#### `plan_steps`

- `step_id TEXT NOT NULL`
- `plan_version_id TEXT NOT NULL`
- `node_type TEXT NOT NULL`
- `node_version TEXT NOT NULL`
- `category TEXT NOT NULL`
- `params_json TEXT NOT NULL`
- `params_hash TEXT NOT NULL`
- `parent_step_ids_json TEXT NOT NULL`
- `branch_label TEXT NOT NULL DEFAULT ''`
- `position INTEGER NOT NULL`
- primary key: `(plan_version_id, step_id)`

#### `runs`

- `run_id TEXT PRIMARY KEY`
- `plan_version_id TEXT NOT NULL`
- `status TEXT NOT NULL`
- `started_at TEXT NOT NULL`
- `finished_at TEXT`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

#### `run_steps`

- `run_step_id TEXT PRIMARY KEY`
- `run_id TEXT NOT NULL`
- `step_id TEXT NOT NULL`
- `plan_version_id TEXT NOT NULL`
- `status TEXT NOT NULL`
- `started_at TEXT NOT NULL`
- `finished_at TEXT`
- `input_artifact_ids_json TEXT NOT NULL`
- `output_artifact_ids_json TEXT NOT NULL`
- `execution_fingerprint_json TEXT NOT NULL`
- `warnings_json TEXT NOT NULL DEFAULT '[]'`
- `errors_json TEXT NOT NULL DEFAULT '[]'`

#### `artifacts`

- `artifact_id TEXT PRIMARY KEY`
- `artifact_type TEXT NOT NULL`
- `role TEXT NOT NULL`
- `path TEXT NOT NULL`
- `physical_hash TEXT NOT NULL`
- `logical_hash TEXT NOT NULL`
- `media_type TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

#### `warnings`

- `warning_id TEXT PRIMARY KEY`
- `run_step_id TEXT`
- `code TEXT NOT NULL`
- `message TEXT NOT NULL`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

#### `errors`

- `error_id TEXT PRIMARY KEY`
- `run_step_id TEXT`
- `code TEXT NOT NULL`
- `message TEXT NOT NULL`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`

### ProjectStore Responsibilities

Implement `ProjectStore` around a project root path.

Required methods:

- initialize/open project directory
- initialize SQLite schema
- get SQLite connection
- write bytes to project artifact path
- register artifact metadata in SQLite
- read artifact metadata by ID
- write/read plan version and plan steps
- write/read runs and run steps
- transaction helper for multi-step updates

Acceptance tests:

- creating a project creates `cardre.sqlite`, `datasets/`, `artifacts/`, `exports/`, `logs/`
- schema exists after initialization
- SQLite contains no tabular blobs
- registering an artifact writes metadata and preserves file path

## Phase 1A Slice 2: Artifact Model And Hashing

Replace any single-hash model with physical/logical hash fields.

### ArtifactRef

Use a dataclass or Pydantic model containing:

- `artifact_id`
- `artifact_type`
- `role`
- `path`
- `physical_hash`
- `logical_hash`
- `media_type`
- `metadata`

### Physical Hash

Compute SHA-256 over raw file bytes.

### Logical Hash

JSON artifacts:

- JSON encode with sorted keys and compact separators
- UTF-8 bytes
- SHA-256

Tabular artifacts:

- Convert to Arrow table with canonical column order.
- Use deterministic row order from source unless a semantic sort key is declared.
- Use stable null representation.
- Hash canonical Arrow IPC bytes or another deterministic Arrow representation.
- Do **not** use raw Parquet file bytes as logical hash.

Parquet physical bytes may vary across writers/settings. Therefore:

- `physical_hash`: Parquet file bytes
- `logical_hash`: canonical table content

Acceptance tests:

- same JSON object with different key order has same logical hash
- same table imported twice has same logical hash
- physical and logical hashes are both recorded

## Phase 1A Slice 3: German Credit Importer

Implement this before executor work.

### Input

Accept either:

- extracted `german.data`
- local UCI ZIP archive containing `german.data`

If reading the ZIP, use Python `zipfile` from the standard library.

### Column Names

Use documented UCI columns:

```text
checking_account_status
duration_months
credit_history
purpose
credit_amount
savings_account_bonds
present_employment_since
installment_rate_percent_disposable_income
personal_status_sex
other_debtors_guarantors
present_residence_since
property
age_years
other_installment_plans
housing
existing_credits_at_bank
job
people_liable_maintenance
telephone
foreign_worker
credit_risk_class
```

### Target Handling

Source target:

- `1 = good`
- `2 = bad`

Create/import a semantic target column named `credit_risk_class` containing the
source value or normalized labels. Record target mapping in artifact metadata.

Recommended metadata:

```json
{
  "source_dataset_id": "uci-statlog-german-credit",
  "row_count": 1000,
  "column_count": 21,
  "target_column": "credit_risk_class",
  "target_mapping": {"1": "good", "2": "bad"},
  "source_file": "german.data"
}
```

### Output

- canonical Parquet dataset artifact
- `artifact_type = dataset`
- `role = input`
- media type: `application/vnd.apache.parquet`
- registered in SQLite

Acceptance tests:

- importing German Credit creates a Parquet artifact
- artifact row count is 1,000
- artifact target metadata is correct
- reimport same source produces same logical hash
- artifact file exists on disk

First meaningful green test:

```text
Given local German Credit raw archive/file
When Cardre imports it
Then a canonical Parquet dataset artifact is written
And artifact metadata is stored in SQLite
And re-importing the same source produces the same logical_hash
```

## Phase 1A Slice 4: Node Registry And Node Contracts

Introduce node contracts before implementing many nodes.

### NodeType Contract

Each node type defines:

- `node_type`
- `version`
- `category`
- `input_roles`
- `output_roles`
- `params_schema`
- `run(context)`

Categories:

- `fit`
- `apply`
- `selection`
- `refinement`
- `transform`

### ExecutionContext

Pass this to nodes:

- `store`
- `run_id`
- `plan_version_id`
- `step_spec`
- `parent_run_steps`
- `input_artifacts`
- `validated_params`
- `runtime_metadata`

Nodes return outputs and metrics. Nodes should not directly mutate plan/run
state.

### Proof Nodes

Implement minimal nodes:

- `cardre.import_dataset`
- `cardre.profile_dataset`
- `cardre.validate_binary_target`
- `cardre.split_train_test_oot`
- `cardre.dummy_fit`
- `cardre.dummy_apply`

Acceptance tests:

- registry can register and resolve nodes by `node_type`
- missing node type fails cleanly
- node params are included in params hash

## Phase 1A Slice 5: Executor And Run Records

Implement topological execution over `plan_steps`.

Required executor behaviour:

- validate plan has no duplicate step IDs
- validate parents exist earlier in topological order
- resolve input artifacts from parent `run_steps`
- validate artifact roles before running a node
- run node
- register output artifacts
- create `run_step`
- compute execution fingerprint
- commit each step's evidence transactionally

### Execution Fingerprint

Record JSON containing:

- `plan_version_id`
- `step_id`
- `node_type`
- `node_version`
- `params_hash`
- `parent_run_step_ids`
- `input_artifact_logical_hashes`
- `output_artifact_logical_hashes`
- `python_version`
- `cardre_version`
- dependency lock/hash if available

Acceptance tests:

- running a proof plan writes `runs` and `run_steps`
- each run step has input/output artifact IDs
- each run step has execution fingerprint with required fields
- failed step records structured error and does not mark descendants current

## Phase 1A Slice 6: Split Node And Role Enforcement

### Split Params

Initial params:

- `train_fraction`
- `test_fraction`
- `oot_fraction`
- `method = random`
- `random_seed`

Validate fractions sum to 1.0.

### Split Outputs

The split node produces three dataset artifacts:

- role: `train`
- role: `test`
- role: `oot`

Artifact metadata includes:

- source artifact ID
- split params
- row count
- role

### Role Enforcement

Executor blocks invalid role access before node execution.

Rules:

- Fit nodes may consume `train` only after split.
- Apply nodes may consume `train`, `test`, `oot`, plus `definition` artifacts.
- Selection/refinement nodes consume reports/definitions unless explicitly
  configured otherwise.

Acceptance tests:

- split creates three immutable artifacts with roles
- fit node consuming `train` succeeds
- fit node wired to `test` fails before execution
- apply node consuming `train`, `test`, `oot`, and definition succeeds

## Phase 1A Slice 7: Staleness And Replay

Do not store stale state.

Implement computed currentness:

- compare current plan step params hash to latest successful run step
- compare node type/version
- compare parent output logical hashes
- compare input artifact logical hashes
- if parent changed, descendants are stale

Replay behaviour:

- changing step params creates a new plan version
- rerun changed step and descendants only
- retain unaffected ancestor/sibling run evidence by reference or copy into new run
- preserve old run records

Acceptance tests:

- changing split params marks downstream stale
- replay from changed split produces new downstream artifacts
- unchanged upstream/import evidence remains valid
- old run remains queryable
- new run references new plan version

## Phase 1B: Desktop Shell Proof

Start only after Phase 1A tests are green.

### Backend API

Implement FastAPI sidecar endpoints:

- `GET /health`
- `POST /projects`
- `GET /projects/{project_id}`
- `POST /datasets/import`
- `GET /plans/{plan_id}`
- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/steps`
- `GET /artifacts/{artifact_id}`

The API owns validation and state transitions. React must not infer staleness or
mutate audit state locally.

### Minimal GUI

- create/open local project
- choose German Credit file/archive
- run proof pathway
- show step cards
- show statuses: not run, queued, running, succeeded, failed, cancelled
- show stale markers from API-computed state
- show artifact list
- show basic profile output

### Tauri Sidecar Lifecycle

- choose/reserve localhost port
- start sidecar
- wait for `/health`
- pass API URL to React
- capture sidecar logs to local file
- shut down sidecar on app exit
- surface startup failure clearly

Acceptance tests:

- app launches
- sidecar starts
- `/health` passes
- project can be created/opened
- German Credit can be imported from local disk
- proof pathway can run
- UI displays backend statuses/stale markers
- SQLite records and artifact files are created locally
- shutdown stops sidecar cleanly

## PR / Work Chunk Order

Execute in this order:

1. Schema + `ProjectStore`.
2. Artifact model + physical/logical hashing.
3. German Credit importer + canonical Parquet artifact.
4. Node registry + proof node contracts.
5. Executor + run/run-step records + execution fingerprints.
6. Train/test/OOT split + role enforcement.
7. Staleness + replay.
8. FastAPI sidecar.
9. Tauri/React shell proof.

Keep each chunk small and testable.

## Verification Commands

Use:

```bash
pytest
python3 -m json.tool docs/data-sources/phase-1-datasets.json >/tmp/phase1-datasets.validated.json
sha256sum input/credit/uci-german-credit/raw/statlog-german-credit-data.zip
```

Expected German Credit archive hash:

```text
e12d9d5def6845c0622634a1cd2ab87fa470668c4298f1ec52a4e403376a435b
```

## Definition Of Done

Phase 1 is done when:

- German Credit imports into a canonical Parquet artifact.
- Reimport produces the same logical hash.
- SQLite records all metadata and no tabular blobs.
- Split produces train/test/OOT role-tagged artifacts.
- Fit nodes cannot read test/OOT artifacts.
- Dummy apply node can consume split data plus build definition artifact.
- Execution fingerprints are recorded.
- Staleness is computed from fingerprints and parent outputs.
- Replay reruns only changed step descendants and preserves old runs.
- Desktop shell can trigger and display the proof pathway through the sidecar.
