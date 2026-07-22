# Batch 01 — Bootstrap + API Skeleton + Composition Root + Architecture Enforcement

```text
You are implementing one bounded batch of the Cardre architecture rewrite.

Do not redesign the wider system.

Do not broaden the scope.

Inspect the current repository before editing because earlier batches may already have changed the paths referenced here.

Preserve validated mathematical and product behaviour, but do not preserve obsolete internal APIs or compatibility layers.

Complete this batch fully, including tests and deletion of code superseded within its scope.
```

## 1. Task objective

Build the working composition root (`bootstrap/container.py` + `build_app.py`), the `ProjectRegistryPort` + `ProjectProvisionerPort` + `UnitOfWork` skeleton, their first concrete adapters (`adapters/system/project_registry.py`, `adapters/sqlite/project_provisioner.py`, `adapters/sqlite/connection.py`), and a thin FastAPI app exposing `/health` + `/projects` (CreateProject, ListProjects, GetProject) end-to-end through use cases. **Also establish the package skeletons (`domain/` already correct, `application/ports/`, `nodes/contracts.py` placeholder, `bootstrap/`) and blocking architecture enforcement (`importlinter` + extended forbidden-symbol tests, xfail during migration).** This batch merges the original "skeleton + enforcement" batch with the bootstrap batch to save a PR cycle — enforcement starts the moment the new packages exist.

## 2. Repository context

Read `docs/architecture-rewrite/00-validation-report.md` (Workflow A — create project), `01-target-architecture.md` (package layout, allowed/prohibited imports, composition root), `02-domain-and-use-cases.md` (Projects use cases), `03-persistence-and-artifacts.md` (UoW, schema, project provisioner), `05-api-and-frontend-boundary.md` (endpoints, project identity). Existing code: `cardre/store/db.py` (`ProjectStore.initialize`), `cardre/store/project_registry.py`, `cardre/services/project_resolver.py`, `cardre/api/routes/projects.py`, `cardre/api/dependencies.py`, `cardre/config.py`. `pyproject.toml` (dev extras). `tests/test_canonical_contract.py` (existing AST bans). `Makefile` (preflight). `.github/workflows/ci.yml` (lint job).

## 3. Why the batch exists

This batch proves the hexagonal direction works: a route → use case → port → adapter → SQLite, with no `ProjectStore` and no `from_env()` outside `bootstrap/settings.py`. Once this slice is green, every later batch plugs into the same pattern.

## 4. Current relevant architecture

`POST /projects` (`api/routes/projects.py:107`) validates path → `ProjectStore(path).initialize()` → `ProjectRepository(store).create(name)` → `ProjectResolver(CardreConfig.from_env().registry_path).register_project(id, root)`. `GET /projects` lists via `ProjectResolver`. `GET /projects/{id}` resolves root + opens store + reads project row. `ProjectRegistry` (`cardre/store/project_registry.py`) is a JSON-file dict with atomic temp+replace. `CardreConfig.from_env()` reads env in routes.

## 5. Target architecture after the batch

- `bootstrap/settings.py:Settings` is constructed once in `build_app`; passed to `Container`.
- `bootstrap/container.py:Container` holds `settings`, `project_registry: ProjectRegistryPort`, `project_provisioner: ProjectProvisionerPort`, `uow_factory: UnitOfWorkFactory`, and use-case instances `create_project: CreateProject`, `list_projects: ListProjects`, `get_project: GetProject`.
- `bootstrap/build_app.py:build_app()` reads env via `Settings.from_env()`, builds `Container`, builds `FastAPI` via `api/app.py:create_app(container)`, returns `(app, shutdown)`.
- `api/app.py:create_app(container)` registers routers; routers resolve use cases via `Depends(get_create_project)` etc. reading from `request.app.state.container`.
- `api/dependencies.py` rewritten: `get_create_project`, `get_list_projects`, `get_get_project` pull from `app.state.container`. No `get_project_store`, no `X-Project-Id`/`X-Project-Path`, no `get_run_coordinator`.
- `application/ports/unit_of_work.py`: `UnitOfWork` Protocol + `UnitOfWorkFactory` Protocol.
- `application/ports/project_registry.py`: `ProjectRegistryPort` Protocol (`register`, `resolve_root`, `list_all`).
- `application/ports/project_provisioner.py`: `ProjectProvisionerPort` Protocol (`initialize(root)`).
- `application/projects/create_project.py`, `list_projects.py`, `get_project.py`: use-case classes taking ports.
- `adapters/system/project_registry.py`: `JsonProjectRegistry` implementing `ProjectRegistryPort` (port of `cardre/store/project_registry.py`).
- `adapters/sqlite/connection.py`: `SqliteUnitOfWork` implementing `UnitOfWork` (owns conn + txn). `SqliteUnitOfWorkFactory` implementing `UnitOfWorkFactory` (`for_project(project_id)` resolves root via `ProjectRegistryPort`, opens conn).
- `adapters/sqlite/project_provisioner.py`: `SqliteProjectProvisioner` implementing `ProjectProvisionerPort` (creates dirs + sqlite + schema).
- `adapters/sqlite/schema.py`: clean schema v1 SQL (from 03-persistence-and-artifacts.md).
- `adapters/sqlite/project_repo.py`: `ProjectRepo` query object (insert, get, list).
- `/health`, `POST /projects`, `GET /projects`, `GET /projects/{project_id}` work end-to-end via the new path. All other routes 404 (not registered yet).
- OpenAPI regenerated; `frontend/src/api/schema.d.ts` + `openapi.json` updated.
- `cardre/config.py` untouched (old code still uses it for non-project routes, which are 404/not registered).
- `cardre/services/project_resolver.py` untouched (old code path dormant).

## 6. Exact scope

- **Architecture enforcement (absorbed from old Batch 01):**
  - Add `importlinter>=2.0` to `pyproject.toml` `[project.optional-dependencies] dev`.
  - Create `.importlinter` with layered contracts per 01-target-architecture.md. During migration use `ignore_unmatched: true` so old packages (`cardre/services`, `cardre/store`, etc.) don't trip layering; tightened in Batch 07.
  - Add `make arch-check` target (`python3 -m importlinter --config .importlinter`); add to `preflight` and CI `lint` job.
  - Create `cardre/application/__init__.py`, `cardre/application/ports/__init__.py` (empty, docstrings).
  - Create `cardre/bootstrap/__init__.py` (empty) — done as part of bootstrap below.
  - Extend `tests/test_canonical_contract.py` with `test_forbidden_imports_outside_adapters` (AST walk banning `ProjectStore`, `context.store`, `store.root`, `CardreConfig.from_env`, `os.environ`, `sqlite3` outside `adapters/sqlite/`, `ArtifactEvidenceReader` outside `adapters/evidence/`, old repo class names outside `adapters/sqlite/`, FastAPI/Pydantic outside `api/`). Mark `@pytest.mark.xfail(strict=False, reason="Migration in progress; enforced after Batch 07")`.
  - Create `tests/test_architecture_boundaries.py` running `import-linter` CLI + asserting new packages importable.
- **Bootstrap + API skeleton (from old Batch 02):**
  - Create all port files listed in §5.
  - Create the adapter files listed above.
  - Create the three project use cases.
  - Rewrite `api/app.py`, `api/dependencies.py`, `api/routes/projects.py`, `api/routes/health.py`, `api/schemas.py` (only `HealthResponse`, `ProjectResponse`, `ProjectListResponse`, `ProjectCreateRequest`, `UnavailableProjectResponse` — other schemas stay in the old file or are added minimally).
  - Create `bootstrap/container.py:build_container(settings)` returning a populated `Container`.
  - Implement `bootstrap/build_app.py:build_app()`.
  - Update `sidecar/__main__.py` to call `build_app()` instead of importing `cardre.api.app.app` directly (or keep `app` module-level for uvicorn — see implementation sequence).
  - Add `adapters/sqlite/schema.py` with the full clean schema (all tables, even if unused yet — Batch 02 populates query objects).
  - Regenerate OpenAPI.
  - Tests: `tests/application/test_create_project.py`, `test_list_projects.py`, `test_get_project.py` (in-memory fakes for ports); `tests/adapters/system/test_project_registry.py`; `tests/adapters/sqlite/test_connection.py`, `test_project_provisioner.py`, `test_project_repo.py`; `tests/ports/test_unit_of_work_contract.py` (in-memory fake + sqlite); `tests/ports/test_project_registry_contract.py` (in-memory + json file); `tests/api/test_projects_new.py` (TestClient against `build_app`).
  - Delete: `cardre/api/dependencies.py:get_project_store`, `get_project_store_by_root`, `get_run_coordinator`, `require_governance` (the last two are recreated in later batches; for now routes that need them are not registered). Keep `cardre/services/project_resolver.py` and `cardre/store/project_registry.py` (dormant; deleted in Batch 07).

## 7. Files to inspect first

- `cardre/store/db.py` (ProjectStore.initialize pattern — replicate in ProjectProvisioner)
- `cardre/store/project_registry.py` (JSON registry — port to adapter)
- `cardre/store/schema.py` (current schema — clean schema is in 03-persistence-and-artifacts.md)
- `cardre/api/routes/projects.py` (current route logic — port to use cases)
- `cardre/api/dependencies.py` (current deps — rewrite)
- `cardre/api/app.py` (current app construction)
- `cardre/config.py` (Settings mirror)
- `cardre/domain/project.py`, `cardre/domain/errors.py` (Project, ErrorCode)
- `sidecar/__main__.py` (entrypoint)
- `tests/conftest.py` (existing fixtures — `registered_project` factory)
- `scripts/generate-openapi-types.py` (regen)

## 8. Files likely to change

- `cardre/application/ports/unit_of_work.py` (new)
- `cardre/application/ports/project_registry.py` (new)
- `cardre/application/ports/project_provisioner.py` (new)
- `cardre/application/projects/create_project.py` (new)
- `cardre/application/projects/list_projects.py` (new)
- `cardre/application/projects/get_project.py` (new)
- `cardre/adapters/__init__.py` (new)
- `cardre/adapters/system/__init__.py` (new)
- `cardre/adapters/system/project_registry.py` (new)
- `cardre/adapters/sqlite/__init__.py` (new)
- `cardre/adapters/sqlite/connection.py` (new)
- `cardre/adapters/sqlite/schema.py` (new — full clean schema)
- `cardre/adapters/sqlite/project_provisioner.py` (new)
- `cardre/adapters/sqlite/project_repo.py` (new)
- `cardre/api/app.py` (rewrite `create_app(container)`)
- `cardre/api/dependencies.py` (rewrite — use-case deps)
- `cardre/api/routes/projects.py` (rewrite — thin handlers)
- `cardre/api/routes/health.py` (rewrite — thin handler)
- `cardre/api/schemas.py` (trim to project/health schemas; other schemas added in Batch 07)
- `cardre/bootstrap/settings.py` (implement fully)
- `cardre/bootstrap/container.py` (implement `build_container`)
- `cardre/bootstrap/build_app.py` (implement `build_app`)
- `sidecar/__main__.py` (use `build_app`)
- `frontend/src/api/openapi.json` (regenerated)
- `frontend/src/api/schema.d.ts` (regenerated)
- `tests/conftest.py` (add `container` fixture, `build_app_client` fixture)
- `Makefile` (update `preflight` if openapi regen target changes)
- `tests/test_api_projects.py` (update or mark old tests xfail if they hit removed deps)

## 9. Files likely to create

See "Files likely to change" — the `new` entries.

## 10. Files likely to delete

- `cardre/api/dependencies.py:get_project_store*`, `get_run_coordinator`, `require_governance` (functions; file kept for remaining deps added later).
- Old `tests/test_api_projects.py` assertions that depend on `X-Project-Path` / `get_project_store` — rewrite for new path.

## 11. Required implementation sequence

**Enforcement first (absorbed from old Batch 01):**

0. Add `importlinter>=2.0` to `pyproject.toml` `[project.optional-dependencies] dev`. Create `.importlinter` with layered contracts per 01-target-architecture.md. During migration use `ignore_unmatched: true` so old packages don't trip layering; tightened in Batch 07. Add `make arch-check` target (`python3 -m importlinter --config .importlinter`); add to `preflight` + CI `lint` job. Create `cardre/application/__init__.py` + `cardre/application/ports/__init__.py` (empty, docstrings). Extend `tests/test_canonical_contract.py` with `test_forbidden_imports_outside_adapters` (AST walk, banned identifiers per §6, `@pytest.mark.xfail(strict=False, reason="Migration in progress; enforced after Batch 07")`). Create `tests/test_architecture_boundaries.py` running `import-linter` CLI + asserting new packages importable.

**Bootstrap + API skeleton:**

1. Implement `bootstrap/settings.py:Settings.from_env()` fully (mirror `CardreConfig.from_env`).
2. Write `application/ports/unit_of_work.py` (`UnitOfWork` + `UnitOfWorkFactory` Protocols per 03-persistence-and-artifacts.md).
3. Write `application/ports/project_registry.py` (`ProjectRegistryPort` Protocol: `register(project_id, root)`, `resolve_root(project_id) -> Path | None`, `list_all() -> dict[str,str]`).
4. Write `application/ports/project_provisioner.py` (`ProjectProvisionerPort` Protocol: `initialize(root: Path) -> None`).
5. Write `adapters/sqlite/schema.py` with the full clean schema (all tables from 03). This is a SQL string constant.
6. Write `adapters/sqlite/connection.py`: `SqliteUnitOfWork` (opens conn, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, `row_factory=sqlite3.Row`, `isolation_level=None`; `__enter__`/`__exit__` with commit/rollback; `conn` property). `SqliteUnitOfWorkFactory` (`for_project(project_id)` resolves root via registry, opens conn, returns UoW; `read_only(project_id)` opens conn without `BEGIN`).
7. Write `adapters/sqlite/project_provisioner.py`: `SqliteProjectProvisioner.initialize(root)` — creates root dir + `project.sqlite` + `objects/` + `manifests/runs/` + `exports/` + executes schema SQL + inserts `store_meta`.
8. Write `adapters/sqlite/project_repo.py`: `ProjectRepo(conn)` with `create(name)`, `get(project_id)`, `list_all()` returning `Project` dataclasses.
9. Write `adapters/system/project_registry.py`: `JsonProjectRegistry(path)` porting `cardre/store/project_registry.py` logic (atomic temp+replace).
10. Write `application/projects/create_project.py`: `CreateProject(provisioner, registry, uow_factory, id_generator, clock)`. `__call__(command)` validates path, calls `provisioner.initialize(root)`, opens UoW, `ProjectRepo(conn).create(name)`, commits, `registry.register(project_id, root)`, returns `Project`. Errors: `INVALID_PROJECT_PATH`, `STORE_ALREADY_EXISTS`.
11. Write `application/projects/list_projects.py`: `ListProjects(registry, uow_factory)`. `__call__()` calls `registry.list_all()`, for each resolves root + opens read-only UoW + `ProjectRepo.get(project_id)`. Returns `list[Project]` + unavailable list (root missing).
12. Write `application/projects/get_project.py`: `GetProject(registry, uow_factory)`. `__call__(query)` resolves root, opens read-only UoW, `ProjectRepo.get`. Returns `Project` or raises `PROJECT_NOT_FOUND`.
13. Write `api/schemas.py` with only `HealthResponse`, `ProjectResponse`, `ProjectListResponse`, `ProjectCreateRequest`, `UnavailableProjectResponse`. (Other schemas added in Batch 07; keep the old `cardre/api/schemas.py` contents for routes not yet rewritten — but since only health/projects routes are registered, only these schemas are needed. Move old schemas to a temporary `api/_legacy_schemas.py` if needed, or keep `api/schemas.py` with both old + new and just use the new ones. Simplest: keep `api/schemas.py` as-is, add new schemas, and only use new ones in new routes.)
14. Write `api/dependencies.py`: `get_container(request: Request) -> Container` reading `request.app.state.container`. `get_create_project`, `get_list_projects`, `get_get_project` pulling from container. Remove `get_project_store*`, `get_run_coordinator`, `require_governance`.
15. Write `api/routes/health.py`: `GET /health` returning `HealthResponse` with version, `launch_node_count` (from `container.node_catalogue` if present else 0), `governance_enabled`.
16. Write `api/routes/projects.py`: `POST /projects`, `GET /projects`, `GET /projects/{project_id}` as thin handlers calling use cases.
17. Write `api/app.py:create_app(container)` — builds FastAPI, sets `app.state.container = container`, registers `health` + `projects` routers, exception handlers (`cardre_error_handler`, `cardre_api_error_handler` preserved from `api/errors.py`), CORS (origins from `container.settings.cors_origins`).
18. Write `bootstrap/container.py:build_container(settings)` — constructs `JsonProjectRegistry(settings.registry_path)`, `SqliteProjectProvisioner`, `SqliteUnitOfWorkFactory(registry)`, `IdGeneratorPort` (uuid4), `ClockPort` (utc_now_iso), and the three use cases. Returns `Container`.
19. Write `bootstrap/build_app.py:build_app()` — `settings = Settings.from_env()`, `container = build_container(settings)`, `app = create_app(container)`, `return app, lambda: None` (no shutdown yet).
20. Update `sidecar/__main__.py` to call `build_app()[0]` and run uvicorn on it. Keep `cardre/api/app.py:app` module-level for `generate-openapi-types.py` compatibility (or update that script to call `build_app`).
21. Update `scripts/generate-openapi-types.py` to import from `bootstrap.build_app` (or keep `cardre.api.app:app` as a module-level singleton built via `build_app()`).
22. Regenerate OpenAPI: `python3 scripts/generate-openapi-types.py`.
23. Add `tests/conftest.py` fixtures: `settings` (Settings with tmp registry path), `container` (build_container(settings)), `app_client` (TestClient(create_app(container))).
24. Write all the test files listed in §8.
25. Run `make preflight` + `pytest tests/ -q` + `cd frontend && npm test`.

## 12. Interfaces and invariants

- `UnitOfWork` owns one conn + one txn; commit on success, rollback on exception.
- `UnitOfWorkFactory.for_project(project_id)` resolves root via `ProjectRegistryPort`, raises `PROJECT_NOT_FOUND` if missing.
- `ProjectProvisionerPort.initialize(root)` is idempotent-unsafe: raises `STORE_ALREADY_EXISTS` if `project.sqlite` exists.
- `CreateProject` transaction boundary: provisioner (filesystem + sqlite init, not a UoW) → UoW (project row insert) → registry (file write). Three operations, not one txn (registry is a file). Documented in 02.
- Routes never construct repos; use cases do via `uow.projects`.
- `Settings.from_env()` called once in `build_app`; never elsewhere.

## 13. Behaviour to preserve

- `POST /projects` validates absolute path + no `..` (same logic as current `projects.py:113-124`).
- `GET /projects` lists + separates unavailable (root missing).
- `GET /projects/{id}` returns 404 `PROJECT_NOT_FOUND` if missing.
- `HealthResponse` shape matches current (status, version, launch_node_count, deferred_node_count, governance_enabled).

## 14. Intentional breaking changes

- `X-Project-Id` / `X-Project-Path` headers removed from project routes (path param `{project_id}` is authoritative).
- Only `/health` + `/projects*` routes registered; all other routes 404 until later batches.
- `cardre/api/app.py:app` module-level singleton constructed via `build_app()` (if `generate-openapi-types.py` still imports `cardre.api.app:app`).

## 15. Tests to add or update

- `tests/application/test_create_project.py` — in-memory fakes for provisioner/registry/uow; assert path validation, `STORE_ALREADY_EXISTS`, project row created, registry registered.
- `tests/application/test_list_projects.py` — assert unavailable separation.
- `tests/application/test_get_project.py` — assert `PROJECT_NOT_FOUND`.
- `tests/adapters/system/test_project_registry.py` — atomic write, missing file → empty, resolve missing → None.
- `tests/adapters/sqlite/test_connection.py` — open, commit, rollback, conn property, WAL/FK pragmas.
- `tests/adapters/sqlite/test_project_provisioner.py` — initialize creates dirs + sqlite + schema; re-init raises `STORE_ALREADY_EXISTS`.
- `tests/adapters/sqlite/test_project_repo.py` — create/get/list.
- `tests/ports/test_unit_of_work_contract.py` — run against in-memory fake + `SqliteUnitOfWork`; assert commit/rollback semantics.
- `tests/ports/test_project_registry_contract.py` — run against in-memory dict + `JsonProjectRegistry`; assert register/resolve/list.
- `tests/api/test_projects_new.py` — TestClient against `build_app`; POST/GET/GET{id} end-to-end; error codes.
- Mark old `tests/test_api_projects.py` tests that depend on removed deps as `xfail` or rewrite them.

## 16. Commands to run

```bash
. .venv/bin/activate
ruff check --fix
python3 -m importlinter --config .importlinter
make preflight
python3 -m pytest tests/application tests/adapters tests/ports tests/api/test_projects_new.py -q
python3 -m pytest tests/test_api_projects.py -q   # mark xfail or rewrite as needed
cd frontend && npm test
cd frontend && npx tsc --noEmit
```

## 17. Acceptance criteria

- `build_app()` returns a FastAPI app + shutdown callable.
- `TestClient(build_app()[0]).get("/health")` returns 200 with correct shape.
- `TestClient.post("/projects", json={name, path})` returns 201; `GET /projects` lists it; `GET /projects/{id}` returns it.
- Invalid path → 400 `INVALID_PROJECT_PATH`; existing store → 409 `STORE_ALREADY_EXISTS`; missing project → 404 `PROJECT_NOT_FOUND`.
- `Settings.from_env()` is the only env reader (grep confirms no `CardreConfig.from_env()` in `api/`, `application/`, `adapters/`).
- `make arch-check` passes (importlinter).
- `make preflight` passes (coverage ≥60%).
- OpenAPI regenerated; `git diff --exit-code` on generated files clean.
- All new tests pass.

## 18. Architecture rules

- `application/**` may not import `adapters/**` or `api/**` or `bootstrap/**`.
- `api/**` may not import `adapters/**` or `nodes/**`.
- `bootstrap/**` is the only place wiring adapters to ports.
- `Settings.from_env()` only in `bootstrap/`.
- No `ProjectStore` in new code.

## 19. Prohibited shortcuts

- Do not reuse `cardre/store/db.py:ProjectStore` inside adapters — write a fresh `SqliteUnitOfWork`.
- Do not call `CardreConfig.from_env()` anywhere except `bootstrap/settings.py`.
- Do not register routes other than health + projects.
- Do not implement use cases other than the three project ones.
- Do not port `cardre/services/project_resolver.py` — it's dormant and deleted in 09.
- Do not skip OpenAPI regeneration.
- Do not leave old `tests/test_api_projects.py` failing — mark xfail or rewrite.

## 20. Explicit out-of-scope work

- Plan/run/evidence/governance/reporting routes + use cases (Batches 05–07).
- Node catalogue (Batch 03+).
- Artifact store (Batch 02).
- Heartbeat/dispatcher (Batch 05).
- Frontend component changes (Batch 07 — only OpenAPI regen here).
- Deleting `cardre/config.py`, `cardre/services/project_resolver.py`, `cardre/store/` (Batch 07).

## 21. Expected final report format

1. `build_app()` works; `TestClient` results for `/health`, `/projects`.
2. `make preflight` summary.
3. `make arch-check` output.
4. Grep confirming no `CardreConfig.from_env()` in `api/`/`application/`/`adapters/`.
5. OpenAPI regen diff summary.
6. Test pass/fail summary.
7. Files created/changed/deleted.

## Identity

- Sequence: 01
- Title: Bootstrap + API Skeleton + Composition Root + Architecture Enforcement
- Architectural objective: prove the hexagonal direction end-to-end with the smallest slice; establish blocking enforcement from the start
- Reason for position: first batch; every later batch plugs into this pattern
- Difficulty: high

## Scope summary

- Created: ports (UoW, ProjectRegistry, ProjectProvisioner), adapters (sqlite connection/provisioner/project_repo/schema, system project_registry), use cases (CreateProject, ListProjects, GetProject), rewritten api (app, dependencies, routes/health, routes/projects, schemas subset), bootstrap (settings, container, build_app) full implementation, sidecar entrypoint update, tests.
- Changed: api/app.py, api/dependencies.py, api/routes/health.py, api/routes/projects.py, api/schemas.py, bootstrap/*, sidecar/__main__.py, frontend/src/api/openapi.json, schema.d.ts, tests/conftest.py, Makefile, scripts/generate-openapi-types.py.
- Deleted: api/dependencies.py old functions (get_project_store*, get_run_coordinator, require_governance).
- Behaviour preserved: project create/list/get semantics, health shape.
- Behaviour changed: headers removed; only health+projects routes live.
- Exclusions: no plans/runs/evidence/governance routes; no nodes; no artifact store; no dispatcher.

## Design decisions

- D5 (UoW owns conn+txn), D6 (registry port), D11 (X-Project-Id removed), D16 (governance opt-in), D18 (no ORM), D20 (env read in build_app).

## Tests

See §15.

## Acceptance criteria

See §17.

## Risks

- R5/R6 (importlinter), R9 (openapi drift), R15 (tauri sidecar — main.rs unchanged), R20 (env timing), R25 (unresolved D11/D16 confirmed).

## Agent boundaries

Do not modify: `cardre/domain/`, `cardre/services/`, `cardre/store/`, `cardre/execution/`, `cardre/nodes/**`, `cardre/_evidence/**`, `cardre/reporting/`, `cardre/readiness/`, `cardre/modeling/`, `cardre/artifacts.py`, `cardre/config.py`, `cardre/capabilities.py`, `cardre/evidence_locator.py`, `cardre/branch_step_resolver.py`, `frontend/src/**` (only regenerated files), `frontend/src-tauri/**`.

## Dependencies

- Required earlier: none (this is the first batch).
- Optional parallel: none.
- Open PRs: none.

## Estimated reasoning difficulty

high — first end-to-end slice; many new files; composition root design.