# Batch 02 — SQLite Persistence Layer + Clean Schema + Artifact Store

```text
You are implementing one bounded batch of the Cardre architecture rewrite.

Do not redesign the wider system.

Do not broaden the scope.

Inspect the current repository before editing because earlier batches may already have changed the paths referenced here.

Preserve validated mathematical and product behaviour, but do not preserve obsolete internal APIs or compatibility layers.

Complete this batch fully, including tests and deletion of code superseded within its scope.
```

## 1. Task objective

Build the complete SQLite persistence adapter (clean schema v1, `SqliteUnitOfWork` already from Batch 01, all query objects for every table) and the `ArtifactStore` filesystem adapter (staging → atomic publish → content-addressed `objects/{hash[:2]}/{hash}/`). This is the foundation every use case and node will build on.

## 2. Repository context

Read `docs/architecture-rewrite/03-persistence-and-artifacts.md` (full schema, UoW behaviour, artifact object model, publication lifecycle, failure recovery). Existing: `cardre/store/schema.py` (v2 schema v101), `cardre/store/*_repo.py` (11 repositories, all raw SQL), `cardre/store/db.py:ProjectStore`, `cardre/artifacts.py` (`write_*_artifact`). Batch 01 already created `adapters/sqlite/connection.py:SqliteUnitOfWork`, `adapters/sqlite/schema.py` (full clean schema), `adapters/sqlite/project_repo.py`.

## 3. Why the batch exists

Every use case (Batch 05–07) and every node output (Batch 03–05) depends on persistence + artifact storage. This batch must land before use cases and nodes can function. The artifact store's atomic publication (D8) is the core fix for Hypothesis 7.

## 4. Current relevant architecture

Repositories (`cardre/store/*_repo.py`) take `ProjectStore`, issue raw SQL via `store.execute()`, commit via autocommit. `EvidenceRepository.insert_edge/insert_artifact` accept an optional `conn` (transaction-aware). `ComparisonRepository.create_snapshot/add_snapshot_plan_version` accept `conn`. `PlanRepository.create_version` opens its own `IMMEDIATE` txn if no `conn`. `cardre/artifacts.py:_register_bytes_artifact` writes file (`temp_path.replace`), then `ArtifactRepository(store).register` (autocommit INSERT, dedup by `physical_hash`). No transaction wraps file+DB.

## 5. Target architecture after the batch

- `adapters/sqlite/` has all query objects: `ProjectRepo` (exists from 02), `PlanRepo`, `StepRepo`, `RunRepo`, `RunStepRepo`, `ArtifactRepo`, `EvidenceRepo`, `BranchRepo`, `ComparisonRepo`, `ChampionRepo`, `ManualBinningRepo`. Each takes `conn: sqlite3.Connection` in constructor; issues SQL on conn; returns domain dataclasses; never commits.
- `SqliteUnitOfWork` has convenience properties `projects`, `plans`, `steps`, `runs`, `run_steps`, `artifacts`, `evidence`, `branches`, `comparisons`, `champion`, `manual_binning` returning query objects bound to `self.conn`.
- `application/ports/unit_of_work.py:UnitOfWork` Protocol declares these properties returning query-handle Protocols (`ProjectRepoPort`, `PlanRepoPort`, etc.) so application doesn't import the SQLite adapter.
- `application/ports/artifact_store.py`: `StagedArtifactWriter` Protocol (`stage_json`, `stage_table`, `stage_bytes` → `StagedArtifact`; `publish(staged)` → moves to objects/) + `ArtifactReader` Protocol (`read_bytes(artifact)`, `resolve_path(artifact)` for adapters that need paths).
- `adapters/filesystem/artifact_store.py`: `FsArtifactStore` implementing both. Staging writes to `<root>/.staging/{uuid}`. Publish does `os.replace(staging, objects/{h[:2]}/{h})`. `read_bytes` reads from `objects/`. `resolve_path` returns the path.
- `StagedArtifact` dataclass: `staging_path: Path`, `provisional_artifact_id: str`, `physical_hash: str`, `logical_hash: str`, `media_type: str`, `schema_version: str`, `role: str`, `artifact_type: str`, `metadata: JsonDict`.
- Port contract tests for UoW + ArtifactStore (in-memory fakes + real adapters).
- Old `cardre/store/` and `cardre/artifacts.py` untouched (dormant; deleted in 09).

## 6. Exact scope

- Write all 10 new query objects in `adapters/sqlite/` (Plan, Step, Run, RunStep, Artifact, Evidence, Branch, Comparison, Champion, ManualBinning).
- Port SQL from existing `cardre/store/*_repo.py` but: (a) take `conn` not `ProjectStore`, (b) return domain dataclasses not `sqlite3.Row`/`dict`, (c) never commit, (d) use the clean schema (new `runs` columns `cancel_requested`, no `queued_at`/`target_step_id`; new `artifacts.storage_key`/`schema_version`; CHECK constraints).
- Write `application/ports/unit_of_work.py` query-handle Protocols (`ProjectRepoPort`, etc.) with the methods each use case needs.
- Write `application/ports/artifact_store.py` (`StagedArtifactWriter` + `ArtifactReader` Protocols, `StagedArtifact` dataclass).
- Write `adapters/filesystem/artifact_store.py:FsArtifactStore`.
- Add `SqliteUnitOfWork` properties.
- Tests: one per query object in `tests/adapters/sqlite/`; `tests/adapters/filesystem/test_artifact_store.py`; `tests/ports/test_artifact_store_contract.py` (in-memory fake + FsArtifactStore); extend `tests/ports/test_unit_of_work_contract.py` with all query-handle properties.

## 7. Files to inspect first

- `cardre/store/plan_repo.py`, `step_repo.py`, `run_repo.py`, `run_step_repo.py`, `artifact_repo.py`, `evidence_repo.py`, `branch_repo.py`, `comparison_repo.py`, `champion_repo.py`, `manual_binning_repo.py` (port SQL from each).
- `cardre/store/schema.py` (current schema — compare to clean schema in 03-persistence-and-artifacts.md).
- `cardre/artifacts.py` (current artifact write — port to FsArtifactStore).
- `cardre/domain/artifacts.py` (`ArtifactRef`, `physical_hash`, `logical_hash`, `table_logical_hash` — preserve).
- `cardre/domain/run.py`, `plan.py`, `evidence.py`, `manual_binning.py` (domain types query objects return).
- `cardre/adapters/sqlite/connection.py` (from Batch 01 — extend with properties).
- `cardre/adapters/sqlite/schema.py` (from Batch 01 — already has clean schema).

## 8. Files likely to change

- `cardre/application/ports/unit_of_work.py` (add query-handle Protocols + UoW properties)
- `cardre/application/ports/artifact_store.py` (new)
- `cardre/adapters/sqlite/__init__.py` (export query objects)
- `cardre/adapters/sqlite/connection.py` (add properties: `projects`, `plans`, `steps`, `runs`, `run_steps`, `artifacts`, `evidence`, `branches`, `comparisons`, `champion`, `manual_binning`)
- `cardre/adapters/sqlite/plan_repo.py` (new)
- `cardre/adapters/sqlite/step_repo.py` (new)
- `cardre/adapters/sqlite/run_repo.py` (new)
- `cardre/adapters/sqlite/run_step_repo.py` (new)
- `cardre/adapters/sqlite/artifact_repo.py` (new)
- `cardre/adapters/sqlite/evidence_repo.py` (new)
- `cardre/adapters/sqlite/branch_repo.py` (new)
- `cardre/adapters/sqlite/comparison_repo.py` (new)
- `cardre/adapters/sqlite/champion_repo.py` (new)
- `cardre/adapters/sqlite/manual_binning_repo.py` (new)
- `cardre/adapters/filesystem/__init__.py` (new)
- `cardre/adapters/filesystem/artifact_store.py` (new)
- `cardre/domain/artifacts.py` (add `StagedArtifact`? No — `StagedArtifact` is an application/adapter concept, put it in `application/ports/artifact_store.py` or `adapters/filesystem/artifact_store.py`)

## 9. Files likely to create

See "Files likely to change" — the `new` entries.

## 10. Files likely to delete

None. Old `cardre/store/` and `cardre/artifacts.py` stay dormant until Batch 07.

## 11. Required implementation sequence

1. Write `application/ports/artifact_store.py`: `StagedArtifact` dataclass, `StagedArtifactWriter` Protocol (`stage_json(role, kind, payload, metadata) -> StagedArtifact`, `stage_table(role, kind, frame, metadata) -> StagedArtifact`, `stage_bytes(role, kind, data, media_type, logical_hash, metadata) -> StagedArtifact`, `publish(staged) -> Path`), `ArtifactReader` Protocol (`read_bytes(artifact) -> bytes`, `resolve_path(artifact) -> Path`).
2. Write `application/ports/unit_of_work.py` query-handle Protocols: `ProjectRepoPort`, `PlanRepoPort`, `StepRepoPort`, `RunRepoPort`, `RunStepRepoPort`, `ArtifactRepoPort`, `EvidenceRepoPort`, `BranchRepoPort`, `ComparisonRepoPort`, `ChampionRepoPort`, `ManualBinningRepoPort`. Each declares the methods use cases call (get, list, insert, transition, heartbeat, etc.). `UnitOfWork` Protocol gets properties returning these ports.
3. Write `adapters/sqlite/project_repo.py` (already from 02 — extend to match `ProjectRepoPort`).
4. Write `adapters/sqlite/plan_repo.py` — port from `cardre/store/plan_repo.py`: `create_plan`, `get_plan`, `list_for_project`, `create_version(conn, plan_id, steps, description, is_committed)`, `get_version`, `get_version_steps`, `list_versions`, `get_latest_version_id`, `get_plan_id_for_version`, `update_version_description`, `commit_version`. Return `Plan`/`PlanVersion`/`StepSpec` dataclasses. Take `conn`. Use clean schema.
5. Write `adapters/sqlite/step_repo.py` — port from `cardre/store/step_repo.py`: `get_steps`, `insert_steps_and_edges(conn, plan_version_id, steps)`, `get_parent_edges`, `get_child_edges`, `get_all_edges`, `get_distinct_node_types`. Return `StepSpec` + edge rows.
6. Write `adapters/sqlite/run_repo.py` — port from `cardre/store/run_repo.py`: `create`, `get`, `transition`, `heartbeat`, `set_active_step`, `get_active_step`, `append_diagnostic`, `get_diagnostics`, `list_for_plan_version`, `list_for_project`, `get_latest_successful_id`, `get_latest_successful_id_for_plan`, `get_latest_successful_step_across_plan`, `set_cancel_requested`. Return `Run`/dict. Use clean schema (`cancel_requested` column; no `queued_at`).
7. Write `adapters/sqlite/run_step_repo.py` — port from `cardre/store/run_step_repo.py`: `insert`, `get`, `get_for_run`, `get_latest_successful_step`. Return `RunStep`.
8. Write `adapters/sqlite/artifact_repo.py` — port from `cardre/store/artifact_repo.py`: `register(conn, artifact)` (dedup by `physical_hash`), `get`, `list`, `get_for_project`, `list_for_project`, `register_lineage`, `get_lineage_for_run_step`, `output_artifact_ids_for_run_step`, `output_artifacts_for_run_step`, `output_artifact_ids_for_run`, `lineage_artifact_ids_for_run_step`. Return `ArtifactRef`. Use clean schema (`storage_key`, `schema_version` columns).
9. Write `adapters/sqlite/evidence_repo.py` — port from `cardre/store/evidence_repo.py`: `insert_edge(conn, edge)`, `insert_artifact(conn, artifact)`, `get_edges_for_run_step`, `get_edges_for_run`, `get_edges_for_plan_step`, `get_edges_for_plan_step_branch`, `get_edge_for_child_parent`, `get_artifacts_for_edge`, `get_artifacts_for_run_step`, `get_artifacts_for_run`, `list_for_run_ordered`. Return `EvidenceEdge`/`EvidenceArtifact`.
10. Write `adapters/sqlite/branch_repo.py` — port from `cardre/store/branch_repo.py`: `create_branch`, `get_branch`, `list`, `update_head`, `create_step_map`, `get_step_map`, `get_plan_version_ids`. Return `Branch`.
11. Write `adapters/sqlite/comparison_repo.py` — port from `cardre/store/comparison_repo.py`: `create_comparison`, `get_comparison`, `list_for_project`, `add_challenger_branch`, `get_challenger_branches`, `create_snapshot(conn, ...)`, `add_snapshot_plan_version(conn, ...)`, `get_snapshot_plan_versions`, `get_comparison_snapshot`, `get_comparison_snapshots`. Return `Comparison`.
12. Write `adapters/sqlite/champion_repo.py` — port from `cardre/store/champion_repo.py`: `get_champion_assignment_for_project`, `get_champion_assignment`, `get_champion_assignment_by_branch`, `insert_champion_assignment(conn, ...)`, `supersede_champion(conn, ...)`. Return `ChampionAssignment`.
13. Write `adapters/sqlite/manual_binning_repo.py` — port from `cardre/store/manual_binning_repo.py`: `create_review`, `get_review`, `list_for_project`, `get_reviews_for_step`, `update_review`. Return `ManualBinningReview`.
14. Extend `adapters/sqlite/connection.py:SqliteUnitOfWork` with properties returning each query object (`@property def plans(self) -> PlanRepo: return PlanRepo(self.conn)` etc.). The `UnitOfWork` Protocol in `application/ports/unit_of_work.py` declares the same properties returning the `*RepoPort` Protocols.
15. Write `adapters/filesystem/artifact_store.py:FsArtifactStore`:
    - `__init__(root: Path)`.
    - `stage_json(role, kind, payload, metadata)`: compute `logical_hash = json_logical_hash(payload)`, serialize, write to `<root>/.staging/{uuid}`, compute `physical_hash` from bytes, return `StagedArtifact`.
    - `stage_table(role, kind, frame, metadata)`: `logical_hash = table_logical_hash(frame)`, write parquet bytes to staging, `physical_hash` from bytes, return `StagedArtifact`.
    - `stage_bytes(...)`: write raw bytes to staging, `physical_hash` from bytes, return `StagedArtifact`.
    - `publish(staged)`: `dest = <root>/objects/{physical_hash[:2]}/{physical_hash}`; `dest.parent.mkdir(parents=True, exist_ok=True)`; `os.replace(staged.staging_path, dest)`; return `dest`.
    - `read_bytes(artifact)`: read from `<root>/objects/{physical_hash[:2]}/{physical_hash}` (resolve via `artifact.storage_key` or recompute from `physical_hash`).
    - `resolve_path(artifact)`: return `<root>/objects/{physical_hash[:2]}/{physical_hash}`.
    - `gc_staging()`: delete `<root>/.staging/*` (called on bootstrap).
16. Write `tests/adapters/sqlite/test_*.py` — one per query object, using a temp `SqliteUnitOfWork` (via `SqliteProjectProvisioner.initialize(tmp_root)` + `SqliteUnitOfWorkFactory.for_project`). Assert row mapping, constraints, dedup, transition compare-and-set.
17. Write `tests/adapters/filesystem/test_artifact_store.py` — stage, publish, read_bytes, orphan staging cleanup, hash correctness, dedup (publish same hash twice → same path).
18. Write `tests/ports/test_artifact_store_contract.py` — define contract; run against in-memory fake + `FsArtifactStore`.
19. Extend `tests/ports/test_unit_of_work_contract.py` with all query-handle properties.

## 12. Interfaces and invariants

- Query objects take `conn`, never commit, return domain dataclasses.
- `SqliteUnitOfWork` owns conn + txn; query objects are bound to `uow.conn`.
- `FsArtifactStore.stage_*` does not make artifacts visible; `publish` is atomic `os.replace`.
- `objects/{hash[:2]}/{hash}` sharding (D5).
- `StagedArtifact` carries `provisional_artifact_id` (UUID) — the final `artifact_id` may differ on dedup.
- `ArtifactRepo.register` dedups by `physical_hash` (UNIQUE constraint).
- `runs.status` CHECK constraint enforces the 5 states (D10).
- `run_steps.status` CHECK enforces `running`/`succeeded`/`failed` (D10).

## 13. Behaviour to preserve

- `ArtifactRepository.register` dedup by `physical_hash` (preserved).
- `RunRepository.transition` compare-and-set (preserved).
- `EvidenceRepository` edge/artifact uniqueness (preserved).
- `PlanRepository.create_version` version_number = max+1 (preserved).
- All hash functions (`json_logical_hash`, `physical_hash`, `table_logical_hash`) — preserved from `cardre/domain/artifacts.py`.

## 14. Intentional breaking changes

- `runs.queued_at`, `target_step_id` columns removed.
- `runs.status` CHECK constraint added (rejects `created`/`queued`).
- `artifacts.path` → `artifacts.storage_key`; `artifacts.schema_version` first-class column.
- `run_steps.status` CHECK rejects `pending`/`skipped`.
- `manual_binning_reviews.status` CHECK added.

## 15. Tests to add or update

See §11 steps 16–19. Plus: `tests/test_store_schema_no_queryable_json.py` — update table list for new schema (add `storage_key` to allowed columns; assert no `*_ids_json` in new tables).

## 16. Commands to run

```bash
. .venv/bin/activate
ruff check --fix
python3 -m importlinter --config .importlinter
make preflight
python3 -m pytest tests/adapters/sqlite tests/adapters/filesystem tests/ports -q
python3 -m pytest tests/test_store_schema_no_queryable_json.py -q
```

## 17. Acceptance criteria

- All 11 query objects work against a temp SQLite via `SqliteUnitOfWork`; row mapping returns domain types.
- `FsArtifactStore.stage_*` + `publish` + `read_bytes` round-trip; hashes match; dedup works.
- `UnitOfWork` Protocol + `*RepoPort` Protocols pass contract tests against both in-memory fakes and SQLite adapter.
- `make arch-check` passes (importlinter — `application` doesn't import `adapters`).
- `make preflight` passes (coverage ≥60%).
- No existing test breaks (old `cardre/store/` tests still pass — old code untouched).

## 18. Architecture rules

- `adapters/sqlite/**` imports only `application/ports/`, `domain/`, stdlib, `sqlite3`.
- `adapters/filesystem/**` imports only `application/ports/`, `domain/`, stdlib, `pathlib`, polars.
- `application/ports/**` imports only `domain/`, stdlib.
- No `ProjectStore` in new code.
- No `cardre/store/` imports from new code.
- No `cardre/artifacts.py` imports from new code.

## 19. Prohibited shortcuts

- Do not reuse `cardre/store/*_repo.py` — rewrite against `conn`.
- Do not call `store.execute()` or `store.transaction()` — use `conn.execute()` inside UoW.
- Do not commit inside query objects.
- Do not return `sqlite3.Row` or `dict` from query objects — return domain dataclasses.
- Do not skip the CHECK constraints in the clean schema.
- Do not skip the sharding in `objects/{hash[:2]}/{hash}/`.
- Do not make `publish` non-atomic (must be `os.replace`).
- Do not leave staging files visible (staging dir is `.staging/`, not `objects/`).

## 20. Explicit out-of-scope work

- Use cases (Batch 05–07).
- Node contracts (Batch 03).
- Node porting (Batch 04).
- API routes beyond health/projects (Batch 07).
- Deleting old `cardre/store/` (Batch 07).
- Artifact gc (document as follow-up; out of scope).
- Manifest publisher (Batch 05).

## 21. Expected final report format

1. List of query objects + their method counts.
2. `FsArtifactStore` stage/publish/read round-trip test results.
3. Contract test pass/fail (in-memory + sqlite/filesystem).
4. `make preflight` + `make arch-check` summary.
5. Coverage summary.
6. Files created/changed.

## Identity

- Sequence: 02
- Title: SQLite Persistence Layer + Clean Schema + Artifact Store
- Architectural objective: foundation persistence + atomic artifact publication
- Reason for position: every use case + node depends on this
- Difficulty: very high — large surface area, SQL porting, schema redesign

## Scope summary

- Created: 10 query objects, `FsArtifactStore`, port Protocols (`*RepoPort`, `StagedArtifactWriter`, `ArtifactReader`), `StagedArtifact`, tests.
- Changed: `application/ports/unit_of_work.py`, `adapters/sqlite/connection.py` (properties), `adapters/sqlite/schema.py` (already from 02).
- Deleted: nothing.
- Behaviour preserved: dedup, transition compare-and-set, hash algorithms, edge/artifact uniqueness.
- Behaviour changed: clean schema (new columns, CHECKs, dropped dead states).
- Exclusions: use cases, nodes, routes, manifest, dispatcher.

## Design decisions

- D5 (UoW), D7 (artifact addressing sharding), D8 (publication protocol), D10 (drop dead states), D18 (no ORM).

## Tests

See §15.

## Acceptance criteria

See §17.

## Risks

- R3 (hash divergence — algorithms preserved, only path changes), R18 (CHECK constraints reject test data), R23 (gc — out of scope), R6 (importlinter).

## Agent boundaries

Do not modify: `cardre/domain/`, `cardre/services/`, `cardre/store/`, `cardre/execution/`, `cardre/nodes/**`, `cardre/_evidence/**`, `cardre/api/**` (beyond Batch 01 state), `cardre/config.py`, `cardre/artifacts.py`, frontend, sidecar.

## Dependencies

- Required earlier: Batch 01 (`SqliteUnitOfWork`, schema, `ProjectRepo`, `bootstrap`).
- Optional parallel: **Batch 03 contract design overlaps this batch.** The `NodeDefinition`/`NodeContext`/`InputCollection`/`OutputPublisher` Protocols are pure interface work depending only on ports from Batch 01, not on Batch 02's SQLite implementation. Start Batch 03's contract design in a branch while Batch 02 implements; merge Batch 02 first, then Batch 03 lands on top. Saves the serial wait between the two "very high" batches.
- Open PRs: none.

## Estimated reasoning difficulty

very high.