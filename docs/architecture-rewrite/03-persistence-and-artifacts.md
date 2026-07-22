# 03 — Persistence and Artifacts

## Proposed SQLite schema (clean — version 1, no migration chain)

Per D18 (no ORM) and D10 (drop dead states). Replaces `cardre/store/schema.py` v101. No migration from v101; projects are recreated. Schema version row recorded but no migration runner shipped until first real release (ADR-0003).

### `store_meta`
```
key TEXT PRIMARY KEY,
value TEXT NOT NULL
```
Rows: `schema_family="cardre-v3"`, `schema_version="1"`, `created_by_cardre_version`.

### `projects`
```
project_id TEXT PRIMARY KEY,
name TEXT NOT NULL,
created_at TEXT NOT NULL,
cardre_version TEXT NOT NULL,
metadata_json TEXT NOT NULL DEFAULT '{}'
```
Unchanged from v2.

### `plans`
```
plan_id TEXT PRIMARY KEY,
project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
name TEXT NOT NULL,
created_at TEXT NOT NULL,
metadata_json TEXT NOT NULL DEFAULT '{}'
```
Unchanged.

### `plan_versions`
```
plan_version_id TEXT PRIMARY KEY,
plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
version_number INTEGER NOT NULL,
is_committed INTEGER NOT NULL DEFAULT 0,
created_at TEXT NOT NULL,
description TEXT NOT NULL DEFAULT '',
metadata_json TEXT NOT NULL DEFAULT '{}',
UNIQUE(plan_id, version_number)
```
Add CHECK constraint: `CHECK (is_committed IN (0,1))`. No new columns.

### `plan_steps`
```
step_id TEXT NOT NULL,
plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
node_type TEXT NOT NULL,
node_version TEXT NOT NULL,
category TEXT NOT NULL,
params_json TEXT NOT NULL,
params_hash TEXT NOT NULL,
branch_label TEXT NOT NULL DEFAULT '',
position INTEGER NOT NULL,
canonical_step_id TEXT NOT NULL DEFAULT '',
branch_id TEXT,
PRIMARY KEY (plan_version_id, step_id)
```
Unchanged.

### `plan_step_edges`
```
plan_version_id TEXT NOT NULL,
parent_step_id TEXT NOT NULL,
child_step_id TEXT NOT NULL,
edge_order INTEGER NOT NULL DEFAULT 0,
PRIMARY KEY (plan_version_id, parent_step_id, child_step_id),
FOREIGN KEY(plan_version_id, parent_step_id) REFERENCES plan_steps(plan_version_id, step_id) ON DELETE CASCADE,
FOREIGN KEY(plan_version_id, child_step_id) REFERENCES plan_steps(plan_version_id, step_id) ON DELETE CASCADE
```
Unchanged.

### `runs`
```
run_id TEXT PRIMARY KEY,
plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','cancelled','interrupted')),
run_scope TEXT NOT NULL CHECK (run_scope IN ('full_plan','branch')),
branch_id TEXT,
force INTEGER NOT NULL DEFAULT 0,
requested_by TEXT,
request_id TEXT,
created_at TEXT NOT NULL,
started_at TEXT NOT NULL,
finished_at TEXT,
heartbeat_at TEXT,
active_step_id TEXT,
cancel_requested INTEGER NOT NULL DEFAULT 0,
metadata_json TEXT NOT NULL DEFAULT '{}'
```
Changes vs v2: drops `queued_at`, `target_step_id` (already removed), dead `created`/`queued` statuses. Adds `cancel_requested` (D14). Adds CHECK constraints on `status` and `run_scope`.

### `run_steps`
```
run_step_id TEXT PRIMARY KEY,
run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
step_id TEXT NOT NULL,
plan_version_id TEXT NOT NULL,
status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
started_at TEXT NOT NULL,
finished_at TEXT,
execution_fingerprint_json TEXT NOT NULL,
warnings_json TEXT NOT NULL DEFAULT '[]',
errors_json TEXT NOT NULL DEFAULT '[]'
```
Drops `pending`/`skipped` (D10). Adds CHECK on status.

### `artifacts`
```
artifact_id TEXT PRIMARY KEY,
artifact_type TEXT NOT NULL,
role TEXT NOT NULL,
storage_key TEXT NOT NULL,   -- relative to objects/ root, e.g. "ab/cdef...fullhash"
physical_hash TEXT NOT NULL,
logical_hash TEXT NOT NULL,
media_type TEXT NOT NULL,
schema_version TEXT NOT NULL DEFAULT '',
created_at TEXT NOT NULL,
metadata_json TEXT NOT NULL DEFAULT '{}',
UNIQUE(physical_hash)
```
Changes: `path` → `storage_key` (content-addressed; points into `objects/`). Adds `UNIQUE(physical_hash)` explicit (was enforced by dedup logic only). Adds `schema_version` first-class column (was in metadata).

### `artifact_lineage`
```
lineage_id TEXT PRIMARY KEY,
run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
run_step_id TEXT NOT NULL REFERENCES run_steps(run_step_id) ON DELETE CASCADE,
plan_version_id TEXT NOT NULL REFERENCES plan_versions(plan_version_id) ON DELETE CASCADE,
step_id TEXT NOT NULL,
branch_id TEXT,
artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
direction TEXT NOT NULL CHECK (direction IN ('input','output')),
created_at TEXT NOT NULL,
UNIQUE(run_step_id, artifact_id, direction)
```
Unchanged except CHECK on direction.

### `evidence_edges`
```
evidence_edge_id TEXT PRIMARY KEY,
run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
run_step_id TEXT NOT NULL REFERENCES run_steps(run_step_id) ON DELETE CASCADE,
plan_version_id TEXT NOT NULL,
step_id TEXT NOT NULL,
parent_step_id TEXT NOT NULL,
source_run_id TEXT NOT NULL,
source_run_step_id TEXT NOT NULL REFERENCES run_steps(run_step_id) ON DELETE CASCADE,
policy TEXT NOT NULL,
source_label TEXT NOT NULL,
is_reused INTEGER NOT NULL CHECK (is_reused IN (0,1)),
is_stale INTEGER NOT NULL CHECK (is_stale IN (0,1)),
stale_reason TEXT,
created_at TEXT NOT NULL,
UNIQUE(run_step_id, parent_step_id, source_run_step_id)
```
Unchanged except CHECK constraints.

### `evidence_artifacts`
```
evidence_artifact_id TEXT PRIMARY KEY,
evidence_edge_id TEXT NOT NULL REFERENCES evidence_edges(evidence_edge_id) ON DELETE CASCADE,
artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
role TEXT NOT NULL,
created_at TEXT NOT NULL,
UNIQUE(evidence_edge_id, artifact_id)
```
Unchanged.

### Governance tables: `plan_branches`, `branch_step_map`, `branch_comparisons`, `comparison_challenger_branches`, `branch_comparison_snapshots`, `comparison_snapshot_plan_versions`
Unchanged from v2 (governance-gated, created only when `governance_enabled`).

### Annotation/review tables: `step_annotations`, `champion_assignments`, `diagnostics`, `manual_binning_reviews`
Unchanged. Add CHECK on `manual_binning_reviews.status IN ('pending','approved','rejected')` (currently free-form string per domain).

### `exports`
```
export_id TEXT PRIMARY KEY,
run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
export_type TEXT NOT NULL,
path TEXT NOT NULL,
size_bytes INTEGER NOT NULL DEFAULT 0,
created_at TEXT NOT NULL
```
Unchanged. Note: `path` here is a user-facing export path (audit pack, report), not an object-store key.

### Indexes
Preserved from v2 `INDEXES_SQL` plus:
```
CREATE INDEX IF NOT EXISTS idx_runs_cancel_requested ON runs(cancel_requested) WHERE cancel_requested = 1;
CREATE INDEX IF NOT EXISTS idx_artifacts_logical_hash ON artifacts(logical_hash);
```

## Unit-of-work behaviour

```python
class UnitOfWork(Protocol):
    @property
    def conn(self) -> sqlite3.Connection: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(self, *exc) -> None: ...
```

`UnitOfWorkFactory(Protocol)`:
```python
class UnitOfWorkFactory(Protocol):
    def for_project(self, project_id: str) -> UnitOfWork: ...
    def read_only(self, project_id: str) -> UnitOfWork: ...
```

`SqliteUnitOfWork` (in `adapters/sqlite/connection.py`):
- Owns a single `sqlite3.Connection` opened against `<project_root>/project.sqlite`.
- `for_project` opens connection, issues `BEGIN IMMEDIATE` (write) — actually lazy: `BEGIN` only on first write. `read_only` opens connection without `BEGIN`.
- Provides `conn` for query objects.
- `commit()` / `rollback()` / `__exit__` (rollback on exception, commit on success if begun).
- **Not shared across threads.** Each thread/dispateched run gets its own `UnitOfWork` from the factory.
- Connection settings: `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, `row_factory=sqlite3.Row`, `isolation_level=None` (driver autocommit; explicit BEGIN/commit managed by UoW).

**No `ProjectStore`.** The UoW owns only the connection + transaction. Path resolution (`project_root`, `objects/`, `manifests/`, `exports/`) is done by `ArtifactStore` (filesystem adapter) and `ProjectRegistryPort` (root resolution), not the UoW.

## Transaction ownership

- **Only use cases open `UnitOfWork`s.** Routes call use cases; use cases call query objects on `uow.conn`; query objects issue SQL but never commit.
- **Query objects (repositories) do not commit.** They take `conn` and issue `conn.execute(...)`. The UoW commits.
- **No autocommit for multi-statement operations.** The current pattern of single-statement autocommit in repos (e.g. `RunRepository.heartbeat`, `ArtifactRepository.register`) is replaced: each such operation runs inside a UoW opened by the calling use case. For trivial single-statement updates (heartbeat), the use case opens a tiny UoW.
- **Heartbeat exception:** the heartbeat watchdog (if retained) opens its own UoW per tick via the factory — same pattern as today but through the port, not raw `ProjectStore(root)`.

## Connection ownership

- `UnitOfWorkFactory` owns a connection pool per project (or opens on demand; SQLite connection pool is cheap). 
- One connection per UoW. UoWs are short-lived (one use case or one step finalization).
- The executor's main thread opens one UoW per step finalization; the heartbeat watchdog opens its own UoW per tick. No shared connections across threads.

## Row mapping

- Query objects return domain dataclasses (`Project`, `Plan`, `PlanVersion`, `StepSpec`, `Run`, `RunStep`, `EvidenceEdge`, `EvidenceArtifact`, `ArtifactRef`, `Branch`, `Comparison`, etc.) — not `sqlite3.Row` or `dict`.
- `_row_to_*` static methods live in the adapter query objects (e.g. `adapters/sqlite/artifact_repo.py:_row_to_artifact_ref`).
- The domain layer never sees `sqlite3.Row`.

## Query adapter separation

| Port (application/ports/) | SQLite adapter (adapters/sqlite/) | Tables |
|---------------------------|-----------------------------------|--------|
| `ProjectRegistryPort` | `adapters/system/ProjectRegistry` (JSON file, not SQLite) | — |
| `ProjectProvisionerPort` | `adapters/sqlite/ProjectProvisioner` + `adapters/filesystem/ProjectInitializer` | creates project.sqlite + dirs |
| (no port — query objects are use-case-private) | `adapters/sqlite/ProjectRepo`, `PlanRepo`, `StepRepo`, `RunRepo`, `RunStepRepo`, `ArtifactRepo`, `EvidenceRepo`, `BranchRepo`, `ComparisonRepo`, `ChampionRepo`, `ManualBinningRepo` | as named |

Query objects are *not* ports — they're adapter-internal. Use cases depend on `UnitOfWork` + construct query objects via `uow.projects`, `uow.plans`, `uow.runs`, etc. (convenience properties on the UoW that return query objects bound to `uow.conn`). This avoids a port-per-repository explosion while keeping SQL inside adapters.

```python
class SqliteUnitOfWork:
    @property
    def projects(self) -> ProjectRepo: return ProjectRepo(self.conn)
    @property
    def plans(self) -> PlanRepo: return PlanRepo(self.conn)
    # ...
```

Use cases access `uow.plans.get_version(...)` — the `UnitOfWork` protocol in `application/ports/unit_of_work.py` declares these properties returning `Protocol` types (so application doesn't import the SQLite adapter). This is a pragmatic compromise: the UoW *is* a port that exposes typed query handles. The query handle types are defined in `application/ports/` as Protocols; the SQLite adapter provides concrete classes.

## Concurrency expectations

- One writer at a time (SQLite `IMMEDIATE` txn). Multiple readers OK (WAL).
- Runs execute single-threaded per project (one `ThreadRunDispatcher` with `max_workers=1` default, as today).
- Cross-project parallelism OK (separate SQLite files).
- Stale-run recovery: `SubmitRun` sweeps before inserting; same as today.
- Heartbeat watchdog: separate connection, separate UoW per tick.

## Initialization strategy

`ProjectProvisionerPort.initialize(root)`:
1. Create `<root>/` (mkdir parents).
2. Create `<root>/project.sqlite`.
3. Execute clean schema SQL.
4. Insert `store_meta` rows.
5. Create `<root>/objects/`, `<root>/manifests/runs/`, `<root>/exports/`.

`Open` (via `UnitOfWorkFactory.for_project(project_id)`): resolve root via registry, open connection, verify `store_meta.schema_family == "cardre-v3"` and `schema_version == "1"`. No migration runner — if version mismatches, raise `SchemaVersionError`.

## When schema versioning becomes mandatory

At first real deployment (per ADR-0003 roadmap). Until then, the schema is recreatable. When the first real project exists, introduce `adapters/sqlite/migrations.py` with a `migrate(conn, from_version)` runner and increment `schema_version` for every breaking change. This is a post-launch concern; out of scope for this sprint.

## Artifact object model

```
project.cardre/
├── project.sqlite
├── objects/
│   └── {physical_hash[:2]}/
│       └── {physical_hash}/      # full 64-char hex; no extension (media_type in DB)
├── manifests/
│   └── runs/
│       └── {run_id}.json
└── exports/
    ├── report-{run_id}/
    └── audit-pack-{branch_id}/
```

- **Artifact identity**: `artifact_id` (UUID, DB PK) + `physical_hash` (content address, UNIQUE).
- **Logical hash**: canonical content hash (JSON canonical form or `v2:`-prefixed Arrow IPC). Stored in `artifacts.logical_hash`. Used for reproducibility/staleness, not for storage path.
- **Physical hash**: SHA-256 of raw bytes. Storage key = `objects/{hash[:2]}/{hash}`.
- **Media type**: `application/json`, `application/vnd.apache.parquet`, `text/csv`, etc. DB column, not file extension.
- **Artifact kind**: derived from `artifact_type` + `schema_version` + `role`; matched by `EvidenceAdapter` profiles to typed evidence.
- **Role**: declared by the node's output contract; validated by `OutputPublisher`.
- **Schema version**: `cardre.<kind>.v1` constant; stored in `artifacts.schema_version` first-class.
- **Metadata**: free-form JSON (training params, feature counts, target column, etc.).

## Publication lifecycle (atomic)

```
node produces payload/dataframe
        |
        v
OutputPublisher.stage(role, kind, payload|frame, metadata)
        |  writes to staging dir: <root>/.staging/{uuid}
        |  computes logical_hash + physical_hash
        |  validates against declared output contract (role, kind, schema_version)
        |  returns StagedArtifact handle (not yet visible)
        v
(StepRunner returns StepExecutionResult to ExecuteRun)
        |
        v
ExecuteRun finalization UoW:
        with uow_factory.for_project(project_id) as uow:
            for staged in result.staged_artifacts:
                artifact_store.publish(staged)   # os.replace staging → objects/{h[:2]}/{h}
                artifact_id = uow.artifacts.register(...)  # INSERT, dedup by physical_hash
                uow.lineage.register_lineage(run_step_id, artifact_id, "output")
            uow.run_steps.insert(run_step)
            uow.evidence.insert_edges(...)
            uow.evidence.insert_artifacts(...)
            uow.runs.heartbeat(run_id)
            uow.commit()
```

- **Staging** is filesystem-only, outside any UoW. A crash leaves orphan staging files (gc'd by a startup sweep).
- **Publish** is `os.replace(staging, objects/{h[:2]}/{h})` — atomic.
- **Register + lineage + evidence + run_step + heartbeat** are all in one `IMMEDIATE` txn. If any fails, the txn rolls back — but the published file remains in `objects/`. This is acceptable: orphan objects are unreachable from DB and gc'd by a hash-sweep. The invariant is: **if a run_step is committed, its artifacts are published and registered together.**

## Failure recovery

| Failure point | State | Recovery |
|---------------|-------|----------|
| Crash during staging | orphan in `.staging/` | startup sweep deletes `.staging/*` |
| Crash after publish, before commit | orphan in `objects/{h[:2]}/{h}` (no DB row) | periodic gc: for each file in `objects/`, if no `artifacts` row, delete (after grace period) |
| Crash during commit (txn rollback) | published file remains; DB unchanged | same gc |
| Commit succeeds, then crash | run_step committed, artifacts registered + lineage + evidence consistent | normal; run is `running`, heartbeat stale → sweep on next submit |
| Manifest write fails | run not finalised (still `running`); manifest file may be partial | `FinalizeRun` retries; if still fails, run finalises as `failed` with `RUN_FINALISATION_FAILED` diagnostic; partial manifest overwritten on retry |
| Status transition fails (compare-and-set lost) | another finalizer already transitioned | re-read actual status, rewrite manifest with actual status, raise `RUN_ALREADY_FINALISED` (preserved behaviour) |

## Garbage collection

- `.staging/` swept on bootstrap (delete all).
- `objects/` gc: periodic (on project open or explicit `gc` command) scan of `objects/` vs `artifacts.physical_hash`; delete unreferenced files older than a grace period. Not in scope for the sprint; document as follow-up.

## Temporary files

- Staging files: `<root>/.staging/{uuid}` (or OS temp dir if outside project root is acceptable). Deleted on publish or by startup sweep.
- Manifest temp: `<root>/manifests/runs/.{run_id}.tmp` → `os.replace` to `{run_id}.json`.
- Export temp: `<root>/exports/.{export_name}.tmp/` → `os.replace` to `{export_name}/`.

## User-facing exports

- Audit packs: `exports/audit-pack-{branch_id}/` (zipped or directory).
- Reports: `exports/report-{run_id}/report_bundle.json` + `report.html`.
- Scoring exports: produced as artifacts (role `report`, kind `scoring_export_python`/`scoring_export_sql`) under `objects/`, then copied to a user-facing path on demand. (Current behaviour: scoring export nodes write JSON artifacts; the "export" is the artifact itself.)

## Canonical manifest publication

- Path: `manifests/runs/{run_id}.json` (D15).
- Built by `FinalizeRun` use case: `build_manifest_payload` → set `manifest_hash=""` → `json_logical_hash(payload)` → set `manifest_hash` → validate `RunManifest` pydantic → atomic temp+`os.replace`.
- Manifest hash covers the entire payload including `steps[]` and `diagnostics[]`.
- `assert_run_audit_integrity` (preserved test) verifies: run terminal, no phantom run_steps, every evidence_edge has ≥1 evidence_artifact, manifest file exists + valid JSON + matches run_id/plan_version_id/status + `manifest_hash` recomputes correctly.

## Schema versioning policy

- Until first real deployment: no migration runner. Schema version is `1`. Breaking changes are free (recreate project).
- At first real deployment: introduce `adapters/sqlite/migrations.py`, increment `schema_version` per change, write a new ADR. Out of scope for this sprint.

## Mapping existing artifact types to the proposed model

| Current `artifact_type` | Current path | New `storage_key` | Notes |
|--------------------------|--------------|-------------------|-------|
| `dataset` | `datasets/{hash[:16]}-{stem}.parquet` | `objects/{h[:2]}/{h}` | role `train`/`test`/`oot`/`input` |
| `model` | `artifacts/{hash[:16]}-{stem}.json` | `objects/{h[:2]}/{h}` | schema_version `cardre.model_artifact.v1` |
| `definition` | `artifacts/{hash[:16]}-{stem}.json` | `objects/{h[:2]}/{h}` | bin/selection/sample/modelling-metadata |
| `report` | `artifacts/{hash[:16]}-{stem}.json` | `objects/{h[:2]}/{h}` | WOE/IV, validation, cutoff, etc. |
| `scorecard` | `artifacts/{hash[:16]}-{stem}.json` | `objects/{h[:2]}/{h}` | score scaling, frozen bundle |
| `manifest` | `artifacts/{hash[:16]}-{stem}.json` | `objects/{h[:2]}/{h}` | technical manifest |
| (manifest run file) | `exports/manifest-{run_id}/manifest.json` | `manifests/runs/{run_id}.json` | canonical, not an artifact |

## Unresolved design decisions (carried from 00)

- D5 sharding (`objects/{hash[:2]}/{hash}/`) — recommended, pending human confirmation.
- D15 manifest path — recommended.
- Whether to keep `exports/manifest-{run_id}/` as a symlink to `manifests/runs/{run_id}.json` for backwards familiarity — recommended: no, clean cut.