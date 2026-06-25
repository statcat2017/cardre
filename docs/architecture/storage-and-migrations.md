# Storage & Migrations

## SQLite Metadata Store

All metadata is stored in a single SQLite database per project. The store is implemented as `ProjectStore` in `cardre/store/project_store.py` with specialized repository classes for focused access:

| Repository | File | Responsibility |
|------------|------|----------------|
| `ProjectStore` | `project_store.py` | Compatibility facade, top-level CRUD |
| `ArtifactRepository` | `artifact_repo.py` | Artifact records, hashes, paths |
| `PlanRepository` | `plan_repo.py` | Plans, plan versions, steps |
| `RunRepository` | `run_repo.py` | Runs, run steps, status |
| `BranchRepository` | `branch_repo.py` | Branches, branch step maps |
| `ProjectRepository` | `project_repo.py` | Project records |

## Storage Model

- **SQLite**: metadata only — step records, plan versions, run records, artifact references (paths + hashes), user annotations, override reasons. No tabular data or binary blobs.
- **Parquet artifacts**: all tabular data — imported datasets, transformed datasets, metric tables, IV rankings, prediction tables.
- **JSON artifacts**: small non-tabular reports, configuration blobs, definition artifacts (bin maps, model parameters, scorecard specs).

## Schema

The database schema is defined in `cardre/store/schema.py` and includes tables for projects, plans, plan versions, plan steps, runs, run steps, artifacts, artifact references, branches, branch step maps, comparisons, comparison snapshots, champions, and champion assignments. Branch-related tables are created separately via `BRANCH_TABLES_SQL` and are only present when governance features are enabled.

## Migrations

Schema migrations are handled by `cardre/store/schema.py` which includes version checks and migration logic. The store checks the schema version on open and applies any pending migrations.
