# PR9 — Store / API / sidecar cleanup

**Findings:** A1, A2, A3 (scoped), A4, A5 (scoped), A6, A7, A8, A9
**Deferred to follow-up:** A5 full typed hydration, `finish()` wrapper
removal, `RunScope` audit
**Batch:** G (parallel: PR9a with PR9b)
**Depends on:** PR8 (needs `RunStatus` enum for repo return-type
consistency)
**Behaviour change:** No (schema migration is transparent — v100 stores
are upgraded on open)

## Reassessment summary (2026-07-13)

The original plan covered A1–A9. After tracing the current code, three
items are revised:

- **A7 (active_step_id column) → INCLUDED.** The store previously had no
  migration infrastructure and used a hard-equality version check. This
  PR adds a migration runner (`_schema_version.py`) that upgrades v100
  stores to v101 via `ALTER TABLE runs ADD COLUMN active_step_id TEXT`,
  then updates `store_meta.schema_version`. `V2_STORE_SCHEMA_VERSION`
  is bumped from 100 to 101. The version check now accepts
  `stored_version <= V2_STORE_SCHEMA_VERSION` and runs incremental
  migrations. `RunRepository.get_active_step()`/`set_active_step()` now
  read/write the column directly instead of the `metadata_json` blob.
  A regression test covers v100→v101 migration and active-step read/write.
- **A5 (repo return-type consistency) → REDUCED.** The plan says "repos
  return typed domain objects" and adds `_row_to_obj` to 3 repos.
  Reality: 5 repos return dicts (Run, Plan, Branch, Project, Comparison),
  no `Branch` domain class exists, and hydrating typed objects for all 5
  is a cross-cutting change that moves complexity (dict↔object conversion)
  rather than reducing it. The safe, complexity-reducing part is deleting
  the `_value(obj, key, default)` polymorphic helper
  (`_run_mappings.py:32-35`) which exists only because `plan_to_response`/
  `plan_version_to_response` accept `Plan | Mapping` unions while repos
  always return dicts. Full typed hydration → follow-up ticket.
- **A3 (move route business logic to services) → REDUCED.** The plan
  proposes 6 service relocations, but none of the target services exist
  (`RunCoordinator.list_for_project`, `ExportService`, `ReportService`,
  `ProjectListService`, `NodeTypeRegistry` — all absent). Creating
  `NodeTypeRegistry` for 7 lines of fallback tuples or `ProjectListService`
  to wrap the existing `ProjectResolver` adds indirection without
  removing complexity. Include only: (1) `list_run_evidence` grouping →
  `EvidenceRepository.list_for_run_ordered`, (2) the duplicated
  `store.root/"exports"` filesystem walk across 3 handlers → one listing
  helper, (3) `list_runs` `RunSummary(...)` inline construction →
  `RunCoordinator.list_for_project`. The hardcoded node-type fallback in
  `node_types.py` is deleted entirely (return empty list when no data).

## Goal

Delete the `ProjectStore` delegate API. Collapse repository boilerplate
with a small `Repository` base + `_branch_filter` helper (avoid a
mini-ORM — just enough to dedup). Extract `ChampionRepository`, dedup
`get_comparison`, and move comparison-snapshot accessors to
`ComparisonRepository`. Move 3 route handlers' inline business logic to
existing repos/services. Centralise 3 inline response mappers. Dedup
`errors.py` (delete 35 shadowing constants). Fix `__version__` hardcode.
Clean up sidecar argv. Delete the `_value` polymorphic helper. Delete
the hardcoded node-type fallback. Promote `active_step_id` from
`metadata_json` blob to a first-class column with a schema migration.
No API response-shape changes.

## Tasks (parallel agents)

### PR9a — Store layer

**Files:** `cardre/store/db.py`, all `cardre/store/*_repo.py`,
`cardre/store/schema.py`, new `cardre/store/_base.py`,
new `cardre/store/champion_repo.py`, new `cardre/store/_locked_cursor.py`,
new `cardre/store/_schema_version.py`

#### A1 — Delete `ProjectStore` delegate block

1. Delete lines 272-334 of `cardre/store/db.py` (16 delegate methods +
   the comment header at 268-270).
2. Move callers to `XRepository(store).method(...)`. There are 54 live
   caller sites (5 delegates have zero callers and need no migration).
   See the [implementation guide](./step-09-implementation-guide.md) for
   the full caller list.
3. `ProjectStore` becomes: connection + transaction + raw execute +
   `artifact_path` + schema version check via `_schema_version.py`.
   `_LockedCursor` extracted to `_locked_cursor.py`. db.py is 183 lines.

#### A2 — `Repository` base + `_branch_filter` + `ChampionRepository`

1. Add a small `Repository` base in `cardre/store/_base.py`:
   ```python
   class Repository:
       table: str
       pk: str
       def __init__(self, store): self._store = store
       def get(self, id) -> dict | None: ...
       def list(self, *, order_by=None) -> list: ...
       def _row_to_obj(self, row) -> Any: return dict(row)
   ```
   **Keep it small.** Do not invent a mini-ORM — just enough to dedup the
   `return None if row is None else dict(row)` idiom and the basic
   get/list pattern. Repos that already hydrate typed objects
   (`ArtifactRepository`, `EvidenceRepository`, `RunStepRepository`,
   `StepRepository`, `ManualBinningRepository`) override `_row_to_obj`.
2. Refactor repos to inherit from `Repository`, removing the duplicated
   `__init__`. Keep custom `get`/`list` where SQL differs (joins, WHERE
   clauses).
3. Add `_branch_filter(branch_id) -> tuple[str, list]` helper to
   `_base.py`. Use it in the 5 SQL sites: `run_repo.py:183,197,210`,
   `run_step_repo.py:69`, `evidence_repo.py:114`.
4. Move champion read accessors from `BranchRepository` (lines 143-170) to
   a new `cardre/store/champion_repo.py` with `ChampionRepository`.
   Update callers: `champion.py:24,33,35` (route),
   `champion_service.py:39,187,188` (service),
   `step_requirements.py:237,244` and `reporting/sections/champion.py:20`
   (via A1 delegate migration → `ChampionRepository(store).get_champion_assignment(...)`).
   Champion *writes* stay in `champion_service.py` (they use
   `ComparisonRepository` and direct SQL, not the read accessors).
5. Delete the duplicate `get_comparison` in `branch_repo.py:172` (the
   canonical copy is `comparison_repo.py:45`).
6. Move `get_comparison_snapshot` and `get_comparison_snapshots`
   (`branch_repo.py:179-191`) to `comparison_repo.py`. Update direct
   callers: `export_service.py:259`, `champion_service.py:83`.

#### A7 — `active_step_id` column + schema migration

1. Add `active_step_id TEXT` to the `runs` table DDL in
   `cardre/store/schema.py`.
2. Bump `V2_STORE_SCHEMA_VERSION` from 100 to 101.
3. Create `cardre/store/_schema_version.py` with `check_and_migrate(conn)`
   that:
   - Ensures `store_meta` exists.
   - Validates `schema_family == "cardre-v2"`.
   - Accepts `stored_version <= V2_STORE_SCHEMA_VERSION`.
   - Runs incremental migrations via `_run_migrations(conn, from_version)`.
   - Updates `store_meta.schema_version` to the current version.
4. Migration 100→101: `ALTER TABLE runs ADD COLUMN active_step_id TEXT`.
5. Update `db.py:open()` to call `check_and_migrate(conn)` instead of the
   old hard-equality check.
6. Update `RunRepository.get_active_step()`/`set_active_step()` to
   read/write the `active_step_id` column directly (no `metadata_json`
   read-modify-write).
7. Add regression test: create a v100 store manually, open it (triggers
   migration), verify `active_step_id` column works.

#### A5 (scoped) — Delete `_value` polymorphic helper

1. Delete `_value(obj, key, default)` in
   `cardre/api/routes/_run_mappings.py:32-35`.
2. Change `plan_to_response` and `plan_version_to_response` to accept
   `Mapping[str, Any]` only (not `Plan | Mapping`). Replace `_value(obj,
   key, default)` with `obj.get(key, default)` / `obj[key]`.
3. Update `tests/test_api_mappers.py:17,27,33` to pass dicts (use
   `.to_dict()` on the `Plan`/`PlanVersion` dataclasses) instead of
   typed objects. Both have `to_dict()` methods (`domain/plan.py:22,45`).
4. Update callers in `plans.py` that pass `PlanService` results (typed
   `Plan`/`PlanVersion` objects) to call `.to_dict()` before passing to
   the mapper.
5. Verify all callers of `plan_to_response(`/`plan_version_to_response(`
   pass dicts (repos return dicts). The callers are in `plans.py` and
   `projects.py` — all pass repo results (dicts) or `.to_dict()`.

### PR9b — API + sidecar

**Files:** `cardre/api/routes/runs.py`, `exports.py`, `reports.py`,
`node_types.py`, `champion.py`, `artifacts.py`, `manual_binning.py`,
`cardre/api/routes/_run_mappings.py`, `cardre/api/errors.py`,
`cardre/api/dependencies.py`, `cardre/services/run_coordinator.py`,
`cardre/store/evidence_repo.py`, new
`cardre/services/export_listing.py`, `sidecar/__main__.py`,
`.github/workflows/ci.yml`

#### A3 (scoped) — Move route business logic to repos/services

1. `list_run_evidence` → `EvidenceRepository.list_for_run_ordered(run_id)`
   — new method on the existing `EvidenceRepository`
   (`cardre/store/evidence_repo.py`). Encapsulates the grouping logic
   currently inline at `runs.py:124-145`. Returns
   `list[tuple[EvidenceEdge, list[EvidenceArtifact]]]` ordered by
   `run_step_id`. Route becomes ~3 lines.
2. `list_exports` / `list_reports` / `list_run_reports` — the 3 handlers
   share `store.root / "exports"` + `iterdir()` + name parsing. Add a
   module-level function `list_export_dirs` in a new
   `cardre/services/export_listing.py` (a function, not a class).
   Each route calls it and maps to its response model. Delete
   `store.root` from `exports.py` and `reports.py`.
3. `list_runs` → `RunCoordinator.list_for_project(project_id)` — add a
   `list_for_project` method to the existing `RunCoordinator`
   (`cardre/services/run_coordinator.py`). Moves the `RunSummary(...)`
   construction at `runs.py:43`. Route injects `RunCoordinator` via
   `Depends(get_run_coordinator)` and calls
   `coordinator.list_for_project(project_id)`. Satisfies
   `rg 'RunSummary\(' cardre/api/routes/runs.py returns 0`.
4. Delete the hardcoded node-type fallback in `node_types.py` (the 7
   default tuples). Empty projects return an empty `node_types` list.

**Excluded:** `list_projects` (`ProjectResolver` already exists),
`ProjectListService` (wraps an existing class without removing logic).

#### A6 — Centralise mappings

1. Add `champion_assignment_to_response`, `artifact_to_response`,
   `manual_binning_review_to_response` to `_run_mappings.py`.
2. Replace inline mapping in `champion.py:40-49`,
   `artifacts.py:31-39`, `manual_binning.py:35-47` (delete the local
   `_review_to_response` helper).
3. Do **not** rename `_run_mappings.py` → `_mappings.py` (cosmetic churn
   touching ~8 importers).

#### A4 — `errors.py` dedup

1. Delete lines 67-101 of `cardre/api/errors.py` (35 module-level
   constants shadowing the `ErrorCode` enum).
2. Migrate ~14 import sites to `from cardre.api.errors import ErrorCode`
   (or `from cardre.api.errors import ErrorCode, CardreApiError`).
3. Migrate ~123 bare-constant usages to `ErrorCode.X`. These include
   `code=RUN_NOT_FOUND` kwargs and `"code": GOVERNANCE_DISABLED` dict
   values in `dependencies.py`.
4. Update `__all__` in `errors.py` to export `ErrorCode` (not bare names).
5. `tests/test_error_code_sync.py` imports `ErrorCode` directly (line 13)
   and is unaffected. No test references the bare constants.

#### A8 — `create_project` `__version__` fix

1. Delete `cardre_version="0.2.0"` in `projects.py:145`. Change to
   `return project_to_response(project)`.
2. `ProjectRepository.create` already writes `__version__` to the row
   (`project_repo.py:22`), and `project_to_response` falls back to
   `__version__` (`_run_mappings.py:132`). The hardcode is fully
   redundant.

#### A9 — Sidecar argv cleanup

1. Delete the `argv` parameter and `if len(args) > 1: port = int(args[1])`
   branch in `sidecar/__main__.py:13-27`.
2. `main()` becomes: `config = CardreConfig.from_env()` +
   `uvicorn.run(app, host=config.api_host, port=config.api_port,
   log_level="info")`. ~8 lines.
3. Update `tests/test_sidecar_entrypoint.py`: assert that `main()` uses
   `CardreConfig.from_env().api_port` (the test monkeypatches
   `CardreConfig.from_env` to return `api_port=8752` — assert port 8752).
4. Update `.github/workflows/ci.yml` smoke test to use
   `CARDRE_API_PORT=18000 $BINARY &` instead of `$BINARY 18000 &`.

## Acceptance criteria

- [x] `rg 'def get_branch\b|def get_run\b|def get_artifact\b'
  cardre/store/db.py` returns 0.
- [x] `rg 'store\.get_branch\(|store\.get_run\(|store\.get_artifact\('
  cardre/ sidecar/` returns 0 (outside `db.py`).
- [x] `class Repository` exists in `cardre/store/_base.py`.
- [x] `rg 'branch_id IS NULL' cardre/store` returns 0 (encapsulated in
  helper).
- [x] `rg 'def get_comparison' cardre/store/branch_repo.py` returns 0.
- [x] `cardre/store/champion_repo.py` exists.
- [x] `rg 'store\.root' cardre/api/routes/exports.py
  cardre/api/routes/reports.py` returns 0.
- [x] `rg 'RunSummary\(' cardre/api/routes/runs.py` returns 0.
- [x] `rg '"0.2.0"' cardre/api/routes/projects.py` returns 0.
- [x] `rg 'GOVERNANCE_DISABLED = ErrorCode' cardre/api/errors.py`
  returns 0.
- [x] `rg 'def main\(argv' sidecar/__main__.py` returns 0.
- [x] `rg 'def _value' cardre/api/routes/_run_mappings.py` returns 0.
- [x] `rg '_review_to_response' cardre/api/routes/manual_binning.py`
  returns 0.
- [x] `ruff check` clean; `make preflight` green.
- [x] Golden report bundle diff passes (via CI).
- [x] `wc -l cardre/store/db.py` < 200 (revised from the unrealistic
  `<80` — `_LockedCursor` and schema versioning extracted to separate
  modules; the remainder is legitimate connection/transaction code).
- [x] `active_step_id TEXT` column exists in `runs` table DDL.
- [x] `V2_STORE_SCHEMA_VERSION` == 101.
- [x] v100→v101 migration exists and tested.
- [x] Hardcoded node-type fallback deleted from `node_types.py`.
- [x] `pytest tests/ -q` green (638 passed, 0 failed, 1 skipped).
- [x] All CI checks green.

## Do not

- Do not change API response shapes — only the construction site moves.
- Do not invent a full ORM. The `Repository` base is small (get, list,
  `_row_to_obj`). If genuine logic differs, leave it in the subclass.
- Do not create `ProjectListService`, `ExportService` class, or
  `ReportService` class (excluded from scope).
- Do not rename `_run_mappings.py` to `_mappings.py`.
- Do not add `_row_to_obj` typed hydration to dict-returning repos
  (deferred to follow-up).

## Follow-up tickets (create after PR9 merges)

1. **A5 full — typed-domain hydration for dict-returning repos.** Add
   `_row_to_obj` to `RunRepository`, `PlanRepository`,
   `BranchRepository`, `ProjectRepository`, `ComparisonRepository`;
   create `Branch` domain class; migrate all `r["field"]` → `r.field`
   callers.
2. **`finish()` legacy wrapper removal.** `run_repo.py:156-161` is a
   deprecated delegator left by PR8; safe to delete once all callers use
   `transition()`.
3. **`RunScope` dataclass→StrEnum audit.** PR8 silently changed
   `RunScope` from a dataclass with fields to a `StrEnum`. Verify no
   caller relied on `.plan_version_id`/`.branch_id`/`.target_step_id`/
   `.force`.