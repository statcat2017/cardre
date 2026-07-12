# PR9 — Store / API / sidecar cleanup

**Findings:** A1, A2, A3, A4, A5, A6, A7, A8, A9
**Batch:** G (parallel: PR9a with PR9b)
**Depends on:** PR8 (needs `RunStatus` enum for repo return-type
consistency)
**Behaviour change:** No

## Goal

Delete the `ProjectStore` delegate API. Collapse repository boilerplate
with a small `Repository` base + `_branch_filter` helper (avoid a
mini-ORM — just enough to dedup). Move route business logic into services.
Dedup `errors.py`. Make repo return types consistent. Centralise API
mappings. Add `active_step_id` column. Fix `__version__` hardcode. Clean
up sidecar argv.

## Tasks (parallel agents)

### PR9a — Store layer

**Files:** `cardre/store/db.py`, all `cardre/store/*_repo.py`,
`cardre/store/schema.py`

#### A1 — Delete `ProjectStore` delegate block

1. Delete lines 272-334 of `cardre/store/db.py` (14 delegate methods).
2. Move callers to `XRepository(store).method(...)`.
3. `ProjectStore` becomes: connection + transaction + raw execute +
  `artifact_path` + schema version check. <80 lines.

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
   get/list pattern.
2. Refactor repos to inherit from `Repository`, overriding `_row_to_obj`
   where they hydrate domain objects.
3. Add `_branch_filter(branch_id) -> tuple[str, list]` helper. Use it in
   the 5 sites.
4. Move champion accessors from `BranchRepository` (139-191) to a new
  `cardre/store/champion_repo.py`.
5. Move comparison-snapshot accessors to `ComparisonRepository`. Delete
  the duplicate `get_comparison`.

#### A5 — Repo return-type consistency

1. Decide: **repos return typed domain objects.**
2. Add `_row_to_obj` overrides on `RunRepository`, `PlanRepository`,
   `BranchRepository`.
3. Delete the `_value(obj, key, default)` polymorphic helper in
   `_run_mappings.py:32-35`. Use direct attribute access.

#### A7 — `active_step_id` column

1. Add `active_step_id TEXT` to the `runs` table DDL. Bump
   `V2_STORE_SCHEMA_VERSION`.
2. Add a migration (`ALTER TABLE runs ADD COLUMN active_step_id TEXT`) for
   existing stores.
3. Replace `RunRepository.get_active_step`/`set_active_step` with column
   reads/writes.

### PR9b — API + sidecar

**Files:** `cardre/api/routes/runs.py`, `exports.py`, `reports.py`,
`node_types.py`, `projects.py`, `champion.py`, `artifacts.py`,
`manual_binning.py`, `_run_mappings.py`, `cardre/api/errors.py`,
`sidecar/__main__.py`

#### A3 — Move route business logic to services

1. `list_runs` → `RunCoordinator.list_for_project(project_id)` (or a new
   `RunQueryService`).
2. `list_run_evidence` → `EvidenceRepository.list_for_run_ordered(run_id)`
   (or a service method).
3. `list_exports` → `ExportService.list_for_project(project_id)`. Delete
   the filesystem walk.
4. `list_reports` → `ReportService.list_for_project` / `list_for_run`.
5. `node_types.py` fallback → `NodeTypeRegistry.default_node_types()`.
6. `list_projects` → `ProjectListService.list()` returning
   `(projects, unavailable)`.

#### A6 — Centralise mappings

1. Rename `_run_mappings.py` to `_mappings.py`.
2. Add `champion_to_response`, `artifact_to_response`,
   `manual_binning_review_to_response`.
3. Delete inline mapping in `champion.py:41-49`, `artifacts.py:31-39`,
   `manual_binning.py:35-47`.

#### A4 — `errors.py` dedup

1. Delete lines 67-101 of `cardre/api/errors.py` (35 module-level
   constants shadowing the enum).
2. Migrate callers to `ErrorCode.X`.

#### A8 — `create_project` `__version__` fix

1. Delete `cardre_version="0.2.0"` in `projects.py:145`. Let
   `project_to_response` fall back to `__version__`.

#### A9 — Sidecar argv cleanup

1. Delete the `argv` parameter and `if len(args) > 1: port = int(args[1])`
   branch in `sidecar/__main__.py:13-27`.
2. `main()` becomes 4 lines.

## Acceptance criteria

- [ ] `wc -l cardre/store/db.py` < 80.
- [ ] `rg 'def get_branch\b|def get_run\b|def get_artifact\b'
  cardre/store/db.py` returns 0.
- [ ] `class Repository` exists in `cardre/store/_base.py`.
- [ ] `rg 'branch_id IS NULL' cardre/store` returns 1 (the helper).
- [ ] `rg 'def get_comparison' cardre/store/branch_repo.py` returns 0.
- [ ] `cardre/store/champion_repo.py` exists.
- [ ] `rg 'store.root' cardre/api/routes/exports.py
  cardre/api/routes/reports.py` returns 0.
- [ ] `rg 'RunSummary\(' cardre/api/routes/runs.py` returns 0.
- [ ] `rg '"0.2.0"' cardre/api/routes/projects.py` returns 0.
- [ ] `rg 'GOVERNANCE_DISABLED = ErrorCode' cardre/api/errors.py`
  returns 0.
- [ ] `rg 'def main\(argv' sidecar/__main__.py` returns 0.
- [ ] `ruff check` clean; `pytest tests/ -q` green.
- [ ] Golden report bundle diff passes.

## Do not

- Do not change API response shapes — only the construction site moves.
- Do not invent a full ORM. The `Repository` base is small (get, list,
  _row_to_obj). If genuine logic differs, leave it in the subclass.