# 01 — Target Architecture

## Dependency diagram

```
        FastAPI routes (api/routes/)  |  CLI  |  worker entry  |  Tauri desktop integration
                            |
                            v
                  Application use cases (application/**)
                    SubmitRun, ExecuteRun, CreateProject, CommitPlanVersion, ...
                            |
                  +---------+---------+
                  |                   |
                  v                   v
              Domain             Ports (application/ports/)
            (domain/**)            ^
                                    |
                        +----------+----------+
                        |                     |
                  SQLite adapters       Filesystem adapters
                  (adapters/sqlite/)    (adapters/filesystem/)
                        |                     |
                  Dispatch adapters     Rendering adapters
                  (adapters/dispatch/)   (adapters/rendering/)
                        |                     |
                  Evidence adapters      System adapters
                  (adapters/evidence/)   (adapters/system/)

                        ^
                        |
                  Bootstrap (bootstrap/)  — single composition root
                  builds Settings, NodeCatalogue, ProjectRegistryPort,
                  UoW factory, ArtifactStore, RunDispatcher, handlers, FastAPI app
```

Rule: **dependencies point inward toward domain and ports.** Domain depends on nothing. Ports depend on domain. Adapters depend on ports + domain. Application depends on domain + ports. API depends on application. Bootstrap depends on everything (the only place that wires concrete adapters to ports).

## Package structure

```
cardre/
├── domain/
│   ├── __init__.py
│   ├── common.py            # JsonDict, utc_now_iso, parse_iso
│   ├── errors.py             # CardreError, ErrorCode, typed exceptions
│   ├── artifacts.py          # ArtifactRef, physical_hash, logical_hash, table_logical_hash
│   ├── projects.py           # Project (entity)
│   ├── plans.py              # Plan, PlanVersion, StepSpec, PlanGraph (value objects)
│   ├── runs.py               # Run, RunStep, RunStatus, RunScope, RunStepStatus, transitions
│   ├── evidence.py           # EvidenceEdge, EvidenceArtifact, ResolvedEvidence
│   ├── governance.py         # Branch, Comparison, ChampionAssignment, ManualBinningReview
│   └── evidence/
│       ├── kinds.py          # EvidenceKind enum (from _evidence/kinds.py)
│       └── schemas.py        # SCHEMA_* constants (from _evidence/schemas.py)
│
├── application/
│   ├── __init__.py
│   ├── ports/
│   │   ├── __init__.py
│   │   ├── unit_of_work.py     # UnitOfWork, UnitOfWorkFactory
│   │   ├── project_registry.py # ProjectRegistryPort
│   │   ├── project_provisioner.py # ProjectProvisionerPort (initialize new project)
│   │   ├── artifact_store.py   # StagedArtifactWriter, ArtifactReader
│   │   ├── manifest_publisher.py # ManifestPublisherPort
│   │   ├── run_dispatcher.py   # RunDispatcherPort
│   │   ├── clock.py            # ClockPort
│   │   ├── id_generator.py    # IdGeneratorPort
│   │   ├── node_catalogue.py  # NodeCataloguePort
│   │   ├── report_renderer.py # ReportRendererPort
│   │   └── capability_probe.py # CapabilityProbePort
│   ├── projects/
│   │   ├── create_project.py
│   │   ├── list_projects.py
│   │   ├── get_project.py
│   │   └── resolve_project.py
│   ├── plans/
│   │   ├── create_plan.py
│   │   ├── get_plan.py
│   │   ├── list_plans.py
│   │   ├── get_plan_version.py
│   │   ├── list_plan_versions.py
│   │   ├── update_plan_version.py
│   │   ├── commit_plan_version.py
│   │   └── apply_manual_binning_edit.py
│   ├── runs/
│   │   ├── submit_run.py
│   │   ├── execute_run.py
│   │   ├── cancel_run.py
│   │   ├── get_run.py
│   │   ├── list_runs.py
│   │   ├── get_run_steps.py
│   │   └── get_run_evidence.py
│   ├── execution/
│   │   ├── step_runner.py     # builds NodeContext, calls node.run, validates outputs
│   │   ├── topology.py         # validate_topology (from execution/topology.py)
│   │   ├── step_graph.py       # descendant_closure, ancestor_closure
│   │   ├── action_planner.py
│   │   └── fingerprints.py
│   ├── evidence/
│   │   └── explain_staleness.py
│   ├── governance/
│   │   ├── create_branch.py
│   │   ├── create_comparison.py
│   │   ├── refresh_comparison.py
│   │   └── assign_champion.py
│   └── reporting/
│       ├── generate_report.py
│       └── export_audit_pack.py
│
├── nodes/
│   ├── __init__.py
│   ├── contracts.py          # NodeDefinition, NodeContext, NodeOutput, InputCollection, OutputPublisher, ArtifactContract
│   ├── parameters.py         # NodeParameterSchema, MethodOption, ParameterDefinition, ParameterConstraint, normalize_node_params
│   ├── catalogue.py          # NodeCatalogue (from registry.py, no env access)
│   ├── prep/
│   ├── build/
│   ├── validate/
│   └── selection/
│
├── adapters/
│   ├── __init__.py
│   ├── sqlite/
│   │   ├── connection.py      # SqliteUnitOfWork (owns conn + txn)
│   │   ├── schema.py         # clean schema (replaces store/schema.py)
│   │   ├── project_repo.py   # ProjectRepoPort impl
│   │   ├── plan_repo.py
│   │   ├── run_repo.py
│   │   ├── step_repo.py
│   │   ├── artifact_repo.py
│   │   ├── evidence_repo.py
│   │   ├── branch_repo.py
│   │   ├── comparison_repo.py
│   │   ├── champion_repo.py
│   │   └── manual_binning_repo.py
│   ├── filesystem/
│   │   ├── artifact_store.py # StagedArtifactWriter + ArtifactReader impl; objects/{hash[:2]}/{hash}/
│   │   └── exports.py         # audit pack / report writing
│   ├── dispatch/
│   │   ├── thread_dispatcher.py # ThreadRunDispatcher (from worker.py)
│   │   └── sync_dispatcher.py
│   ├── rendering/
│   │   ├── html_report.py
│   │   └── templates/
│   ├── evidence/
│   │   ├── profiles.py        # EVIDENCE_PROFILES (from _evidence/profiles.py)
│   │   └── parsers.py         # EVIDENCE_ADAPTERS (from _evidence/adapters/)
│   ├── system/
│   │   └── project_registry.py # ProjectRegistryPort impl (JSON file)
│   └── reporting/
│       └── collector.py       # ReportCollector (from reporting/collector.py) behind EvidenceReader+ArtifactReader
│
├── api/
│   ├── __init__.py
│   ├── app.py                # create_app(container) -> FastAPI
│   ├── dependencies.py       # FastAPI deps resolving use cases from container
│   ├── errors.py             # CardreApiError, ErrorCode, handlers
│   ├── schemas.py            # Pydantic request/response models (new shapes)
│   └── routes/
│       ├── health.py
│       ├── projects.py
│       ├── plans.py
│       ├── runs.py
│       ├── evidence.py
│       ├── artifacts.py
│       ├── governance.py     # branches + comparisons + champion + manual_binning
│       ├── reports.py
│       ├── exports.py
│       └── node_types.py
│
└── bootstrap/
    ├── __init__.py
    ├── settings.py           # Settings (frozen, from env once)
    ├── container.py          # Container: builds all adapters + use cases from Settings
    ├── node_catalogue.py     # builds NodeCatalogue from Settings + node classes
    └── build_app.py          # build_app() -> (FastAPI, shutdown_callable)
```

## Allowed imports

| Package | May import |
|---------|------------|
| `domain/` | stdlib, `domain/*` only. **No I/O, no FastAPI, no Pydantic, no SQLAlchemy, no env.** |
| `application/ports/` | `domain/`, stdlib. Ports are `Protocol`s or ABCs referencing domain types only. |
| `application/**` (use cases) | `domain/`, `application/ports/`, stdlib. **No adapter imports, no FastAPI, no sqlite3, no os.environ.** |
| `nodes/contracts.py`, `nodes/parameters.py` | `domain/`, stdlib. |
| `nodes/**` (implementations) | `nodes/contracts.py`, `nodes/parameters.py`, `domain/`, stdlib, third-party numerical (polars, sklearn, numpy, scipy). **No `application/`, no `adapters/`, no `store`, no `ProjectStore`, no FastAPI.** |
| `adapters/sqlite/` | `application/ports/`, `domain/`, stdlib, `sqlite3`. |
| `adapters/filesystem/` | `application/ports/`, `domain/`, stdlib, `pathlib`, polars. |
| `adapters/dispatch/` | `application/ports/`, `domain/`, stdlib, `threading`. |
| `adapters/rendering/` | `application/ports/`, `domain/`, stdlib, jinja2. |
| `adapters/evidence/` | `domain/evidence/`, `application/ports/` (ArtifactReader), stdlib, polars. |
| `adapters/system/` | `application/ports/`, `domain/`, stdlib. |
| `adapters/reporting/` | `application/ports/`, `domain/`, `adapters/evidence/`, stdlib. |
| `api/` | `application/`, `domain/`, `api/*`, FastAPI, Pydantic. **No `adapters/`, no `nodes/`, no `bootstrap/` direct imports except `Container` type.** |
| `bootstrap/` | everything. The only place wiring concrete adapters to ports. |

## Prohibited imports

- `domain/` ← anything outside stdlib. **Hard rule.**
- `application/` ← `adapters/`, `api/`, `bootstrap/`, `sqlite3`, `pathlib` (for paths as data is fine; for filesystem ops is not), `os.environ`, FastAPI, Pydantic.
- `nodes/` ← `application/`, `adapters/`, `api/`, `bootstrap/`, `store`, `ProjectStore`, `sqlite3`, `os.environ`, FastAPI.
- `api/routes/` ← `adapters/`, `nodes/`, `store`, `bootstrap/` (except the `Container` type passed via dependency).
- No file outside `adapters/sqlite/` may import `sqlite3`.
- No file outside `adapters/filesystem/` and `adapters/system/` may import `pathlib.Path` for filesystem mutation (domain may use `Path` as a value object).
- No file outside `bootstrap/settings.py` may read `os.environ`.
- No file outside `adapters/` may import `CardreConfig`/`Settings`.

## Composition root

`bootstrap/container.py` defines a `Container` dataclass:

```python
@dataclass
class Container:
    settings: Settings
    clock: ClockPort
    id_generator: IdGeneratorPort
    project_registry: ProjectRegistryPort
    project_provisioner: ProjectProvisionerPort
    uow_factory: UnitOfWorkFactory
    artifact_store: StagedArtifactWriter
    artifact_reader: ArtifactReader
    manifest_publisher: ManifestPublisherPort
    run_dispatcher: RunDispatcherPort
    node_catalogue: NodeCataloguePort
    capability_probe: CapabilityProbePort
    report_renderer: ReportRendererPort
    # use-case factories (closures capturing the above)
    create_project: CreateProject
    list_projects: ListProjects
    # ... one field per use case
```

`bootstrap/build_app.py`:
```python
def build_app() -> tuple[FastAPI, Callable[[], None]]:
    settings = Settings.from_env()  # the ONLY place env is read
    container = build_container(settings)
    app = create_app(container)
    return app, container.shutdown
```

`api/app.py:create_app(container)` builds the FastAPI app, registers routers, exception handlers, CORS. Routers receive use cases via `Depends` that pull from a request-scoped `Container` stored in `app.state.container`.

`bootstrap/settings.py`:
```python
@dataclass(frozen=True)
class Settings:
    launch_mode: bool
    governance_enabled: bool
    stale_heartbeat_seconds: int
    heartbeat_watchdog_interval_seconds: int
    api_host: str
    api_port: int
    registry_path: Path
    cors_origins: tuple[str, ...]
    max_workers: int

    @classmethod
    def from_env(cls) -> Settings: ...  # reads os.environ once
```

## Responsibility boundaries

| Layer | Owns | Does NOT own |
|-------|------|--------------|
| Domain | vocabulary, invariants, pure functions, enums, frozen dataclasses | I/O, transactions, dispatch, env, FastAPI, Pydantic |
| Application ports | interfaces to infrastructure | implementations |
| Application use cases | business rules, transaction boundaries (via UoW), orchestration | SQL, filesystem, threads, env, FastAPI |
| Nodes | parameter schemas, node execution, artifact *production* (via OutputPublisher) | persistence, dispatch, transactions, store, paths |
| Adapters | SQL, filesystem, threads, rendering, JSON registry | business rules, domain vocabulary |
| API | HTTP, request/response mapping, error mapping, FastAPI deps | business rules, repo construction, ownership checks, transactions |
| Bootstrap | wiring, env reading, app construction | business rules |

## Architecture enforcement

See 06-sprint-plan.md Batch 01 and the enforcement plan section below. Enforcement is blocking from Batch 01 onward via:

1. **`importlinter`** (new dep in `dev` extra) configured in `.importlinter` with layered contracts:
   - `domain` imports nothing internal.
   - `application` imports only `domain`.
   - `nodes` imports only `domain` + `nodes/contracts` + `nodes/parameters`.
   - `adapters` import only `application/ports` + `domain`.
   - `api` imports only `application` + `domain` + `api/*`.
   - `bootstrap` imports everything.
2. **Forbidden symbol tests** (extend `tests/test_canonical_contract.py`): `ProjectStore`, `context.store`, `store.root`, `from_env()` outside `bootstrap/settings.py`, raw `sqlite3` outside `adapters/sqlite/`, `os.environ` outside `bootstrap/`.
3. **Adapter contract tests**: each port has an in-memory test double and a SQLite adapter test; both must pass the same contract suite.
4. **Existing checks preserved**: `audit_artifact_reads.py`, `check-line-counts.py`, `test_store_schema_no_queryable_json.py`, `test_error_code_sync.py`, `check-sidecar-naming.py`.

## Global state / module-level construction to eliminate

- `cardre/api/app.py:83` `app = create_app()` — replaced by `bootstrap/build_app.py`.
- `cardre/services/run_coordinator.py:38-46` `_global_dispatcher` — replaced by `Container.run_dispatcher`.
- `CardreConfig.from_env()` calls outside `bootstrap/settings.py` — 11 sites.
- `ProjectResolver(CardreConfig.from_env().registry_path)` in routes — replaced by `Container.project_registry`.
- `NodeRegistry.with_defaults()` in `PlanExecutor.__init__` (`executor.py:132`) — replaced by `Container.node_catalogue`.
- Module-level `EVIDENCE_ADAPTERS` dict literal in `_evidence/adapters/__init__.py` — becomes `adapters/evidence/parsers.py` built once in bootstrap (or kept module-level but only imported by bootstrap/adapters).

## When each package is introduced

| Package | Introduced in batch |
|---------|---------------------|
| `domain/` | 01 (skeleton) — populated continuously |
| `application/ports/` | 01 (skeleton) — populated per use case |
| `application/**` (use cases) | 05+ (one batch per subsystem) |
| `nodes/contracts.py`, `nodes/parameters.py` | 01 (skeleton), 03 (full) |
| `nodes/catalogue.py` | 04 |
| `nodes/**` (implementations) | 03 (first node), 04 (remaining nodes) |
| `adapters/sqlite/` | 01 (connection + schema + project_repo), 02 (remaining query objects) |
| `adapters/filesystem/` | 02 |
| `adapters/dispatch/` | 05 |
| `adapters/evidence/` | 03 |
| `adapters/rendering/` | 06 |
| `adapters/system/` | 01 |
| `api/` (rewritten) | 01 (skeleton), 07 (full) |
| `bootstrap/` | 01 (skeleton + full) |

## Resolved decisions

D1 (clean rewrite) and D2 (preserve domain vocabulary) are resolved by [ADR-0014](../adr/0014-supersede-0002-authorise-hexagonal-re-encapsulation.md). The package layout and dependency direction described in this document are the authoritative target.

## Pending implementation decisions

None. All decisions (D1–D20) are Accepted as of 2026-07-21. See `00-validation-report.md` §Resolved implementation decisions for the evidence-based resolution of each.