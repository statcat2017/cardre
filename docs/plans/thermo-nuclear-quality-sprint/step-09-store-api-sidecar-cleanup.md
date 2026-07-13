# PR9 — Store / API / sidecar cleanup

**Findings:** A1, A2, A3 (scoped), A4, A5 (scoped), A6, A8, A9
**Deferred:** A7 (schema migration — separate PR), A5 full typed hydration
(follow-up), A3 speculative services (excluded)
**Batch:** G (parallel: PR9a with PR9b)
**Depends on:** PR8 (needs `RunStatus` enum for repo return-type
consistency)
**Behaviour change:** No

## Reassessment summary (2026-07-13)

The original plan covered A1–A9. After tracing the current code, three
items are revised:

- **A7 (active_step_id column) → DEFERRED.** The store has no migration
  infrastructure (`schema.py:1-6` explicitly disclaims migrations;
  `_check_schema_version` does a hard-equality check at `db.py:174`).
  Adding a column requires either building a migration runner from
  scratch or a hard schema-version bump that rejects existing stores.
  Both are schema/migration changes, not structure-only refactors.
  Sprint rule §2 says a PR may change behaviour OR refactor structure,
  not both unless labelled as a migration PR. PR9 is labelled "No
  behaviour change." A7 belongs in its own labelled migration PR. The
  current implementation (`run_repo.py:87-106`, read-modify-write of
  `metadata_json`) has 3 call sites and no reported bugs.
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
  `RunCoordinator.list_for_project`.

## Goal

Delete the `ProjectStore` delegate API. Collapse repository boilerplate
with a small `Repository` base + `_branch_filter` helper (avoid a
mini-ORM — just enough to dedup). Extract `ChampionRepository`, dedup
`get_comparison`, and move comparison-snapshot accessors to
`ComparisonRepository`. Move 3 route handlers' inline business logic to
existing repos/services. Centralise 3 inline response mappers. Dedup
`errors.py` (delete 35 shadowing constants). Fix `__version__` hardcode.
Clean up sidecar argv. Delete the `_value` polymorphic helper. No schema
changes. No API response-shape changes.

## Tasks (parallel agents)

### PR9a — Store layer

**Files:** `cardre/store/db.py`, all `cardre/store/*_repo.py`,
`cardre/store/schema.py` (no change), new `cardre/store/_base.py`,
new `cardre/store/champion_repo.py`

#### A1 — Delete `ProjectStore` delegate block

1. Delete lines 272-334 of `cardre/store/db.py` (16 delegate methods +
   the comment header at 268-270).
2. Move callers to `XRepository(store).method(...)`. There are 54 live
   caller sites (5 delegates have zero callers and need no migration).
    See the [implementation guide](./step-09-implementation-guide.md) for
    the full caller list.
3. `ProjectStore` becomes: connection + transaction + raw execute +
   `artifact_path` + schema version check. ~271 lines (the `<80` target
   is unrealistic — the remainder is legitimate connection/transaction
   infrastructure).

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

#### A5 (scoped) — Delete `_value` polymorphic helper

1. Delete `_value(obj, key, default)` in
   `cardre/api/routes/_run_mappings.py:32-35`.
2. Change `plan_to_response` and `plan_version_to_response` to accept
   `Mapping[str, Any]` only (not `Plan | Mapping`). Replace `_value(obj,
   key, default)` with `obj.get(key, default)` / `obj[key]`.
3. Update `tests/test_api_mappers.py:17,27,33` to pass dicts (use
   `.to_dict()` on the `Plan`/`PlanVersion` dataclasses) instead of
   typed objects. Both have `to_dict()` methods (`domain/plan.py:22,45`).
4. Verify all callers of `plan_to_response(`/`plan_version_to_response(`
   pass dicts (repos return dicts). The callers are in `plans.py` and
   `projects.py` — all pass repo results (dicts). The only typed-object
   callers are in the test.

### PR9b — API + sidecar

**Files:** `cardre/api/routes/runs.py`, `exports.py`, `reports.py`,
`champion.py`, `artifacts.py`, `manual_binning.py`,
`cardre/api/routes/_run_mappings.py`, `cardre/api/errors.py`,
`cardre/api/dependencies.py`, `cardre/services/run_coordinator.py`,
`cardre/store/evidence_repo.py`, new
`cardre/services/export_listing.py`, `sidecar/__main__.py`

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

**Excluded:** `node_types.py` fallback (7 lines — `NodeTypeRegistry` is
over-engineering), `list_projects` (`ProjectResolver` already exists),
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
   log_level="info")`. ~4 lines.
3. Update `tests/test_sidecar_entrypoint.py`: the test currently calls
   `sidecar_main.main(["cardre-api", "18000"])` and asserts
   `captured["port"] == 18000`. Rewrite to assert that `main()` uses
   `CardreConfig.from_env().api_port` (the test already monkeypatches
   `CardreConfig.from_env` to return `api_port=8752` — assert port 8752).

## Acceptance criteria

- [ ] `rg 'def get_branch\b|def get_run\b|def get_artifact\b'
  cardre/store/db.py` returns 0.
- [ ] `rg 'store\.get_branch\(|store\.get_run\(|store\.get_artifact\('
  cardre/ sidecar/` returns 0 (outside `db.py`).
- [ ] `class Repository` exists in `cardre/store/_base.py`.
- [ ] `rg 'branch_id IS NULL' cardre/store` returns 1 (the helper) or 0
  (if fully encapsulated).
- [ ] `rg 'def get_comparison' cardre/store/branch_repo.py` returns 0.
- [ ] `cardre/store/champion_repo.py` exists.
- [ ] `rg 'store\.root' cardre/api/routes/exports.py
  cardre/api/routes/reports.py` returns 0.
- [ ] `rg 'RunSummary\(' cardre/api/routes/runs.py` returns 0.
- [ ] `rg '"0.2.0"' cardre/api/routes/projects.py` returns 0.
- [ ] `rg 'GOVERNANCE_DISABLED = ErrorCode' cardre/api/errors.py`
  returns 0.
- [ ] `rg 'def main\(argv' sidecar/__main__.py` returns 0.
- [ ] `rg 'def _value' cardre/api/routes/_run_mappings.py` returns 0.
- [ ] `rg '_review_to_response' cardre/api/routes/manual_binning.py`
  returns 0.
- [ ] `ruff check` clean; `make preflight` green.
- [ ] Golden report bundle diff passes.
- [ ] `wc -l cardre/store/db.py` < 275 (revised from the unrealistic
  `<80` — the remainder is legitimate connection/transaction code).

## Do not

- Do not change API response shapes — only the construction site moves.
- Do not invent a full ORM. The `Repository` base is small (get, list,
  `_row_to_obj`). If genuine logic differs, leave it in the subclass.
- Do not add the `active_step_id` column or any schema change (A7 is
  deferred).
- Do not create `NodeTypeRegistry`, `ProjectListService`, `ExportService`
  class, or `ReportService` class (excluded from scope).
- Do not rename `_run_mappings.py` to `_mappings.py`.
- Do not add `_row_to_obj` typed hydration to dict-returning repos
  (deferred to follow-up).

## Follow-up tickets (create after PR9 merges)

1. **A7 — `active_step_id` column migration.** Label as migration PR.
   Requires building a migration runner or loosening the hard-equality
   version check. 3 call sites: `executor.py:84,96`,
   `run_coordinator.py:478`.
2. **A5 full — typed-domain hydration for dict-returning repos.** Add
   `_row_to_obj` to `RunRepository`, `PlanRepository`,
   `BranchRepository`, `ProjectRepository`, `ComparisonRepository`;
   create `Branch` domain class; migrate all `r["field"]` → `r.field`
   callers.
3. **`finish()` legacy wrapper removal.** `run_repo.py:156-161` is a
   deprecated delegator left by PR8; safe to delete once all callers use
   `transition()`.
4. **`RunScope` dataclass→StrEnum audit.** PR8 silently changed
   `RunScope` from a dataclass with fields to a `StrEnum`. Verify no
   caller relied on `.plan_version_id`/`.branch_id`/`.target_step_id`/
   `.force`.