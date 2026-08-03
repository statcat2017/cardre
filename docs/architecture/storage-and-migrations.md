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
- Evidence edges and artifacts, reviews, publications, dispatch

Every project store is created by `SqliteProjectProvisioner.initialize()` running
the full `ALL_TABLES_SQL` script, which always includes the branch, evidence and
review tables. Governance is a capability gated at the application/API layer
(e.g. `CARDRE_GOVERNANCE`), not by omitting tables.

## Migrations

Cardre has not launched, so there is **no migration chain** before the first real
deployment. Each project store is created from the current `ALL_TABLES_SQL` with a
recorded `schema_family` / `schema_version` in `store_meta`.

Those values are currently **recorded but not yet enforced on open**:
`SqliteUnitOfWorkFactory` verifies only that the project root and
`project.sqlite` file exist before connecting. A future release will add a
schema-identity check that rejects stores whose recorded family/version differ
from the application, replacing in-place migration until a real compatibility
policy exists (see ADR 0015).
