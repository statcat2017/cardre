# Storage & Migrations

## SQLite Metadata Store

All metadata is stored in a single SQLite database per project. The schema is defined in `cardre/adapters/sqlite/schema.py` and accessed through specialized repository classes in `cardre/adapters/sqlite/`:

| Repository | File | Responsibility |
|------------|------|----------------|
| `ProjectRepo` | `project_repo.py` | Project records |
| `PlanRepo` | `plan_repo.py` | Plans, plan versions, steps |
| `StepRepo` | `step_repo.py` | Plan steps and edges |
| `RunRepo` | `run_repo.py` | Runs, run steps, status |
| `BranchRepo` | `branch_repo.py` | Branches, branch step maps |
| `ArtifactRepo` | `artifact_repo.py` | Artifact records, hashes, paths |

## Storage Model

- **SQLite**: metadata only — step records, plan versions, run records, artifact references (paths + hashes), user annotations, override reasons. No tabular data or binary blobs.
- **Parquet artifacts**: all tabular data — imported datasets, transformed datasets, metric tables, IV rankings, prediction tables.
- **JSON artifacts**: small non-tabular reports, configuration blobs, definition artifacts (bin maps, model parameters, scorecard specs).

This keeps SQLite lean, queryable, and easy to backup while Parquet handles columnar data efficiently.

## Schema

The database schema is defined in `cardre/adapters/sqlite/schema.py` and includes tables for:
- Projects, plans, plan versions, plan steps
- Runs, run steps
- Artifacts, artifact references
- Branches, branch step maps
- Comparisons, comparison snapshots
- Champions, champion assignments

Branch-related tables are created separately via `BRANCH_TABLES_SQL` and are only present when governance features are enabled.

## Migrations

Schema migrations are handled by `cardre/adapters/sqlite/schema.py` which includes version checks and migration logic. The store checks the schema version on open and applies any pending migrations.
