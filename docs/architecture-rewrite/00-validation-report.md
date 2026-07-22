# 00 — Validation Report

Status: PLANNING ONLY. No production code, tests, migrations, CI, dependencies, or files were modified to produce this report. Only new planning documents under `docs/architecture-rewrite/` were created.

## Executive conclusion

The proposed hexagonal rewrite is **architecturally validated with material modifications**. Every one of the ten core hypotheses is supported by concrete repository evidence. However, the proposal collides with a live, documented decision — **ADR-0002 "Extend PlanExecutor — Do Not Rewrite Execution Core"** — which rejected an earlier greenfield execution rewrite. The maintainers have since been running an incremental "deepening" programme (ADRs 0004–0008, 0013; the `deepen-*` and `pr*` branches, all merged to `main`) that treats symptoms but not the root structural issues this validation surfaced.

The task constraints explicitly permit a clean rewrite because Cardre has not launched. Reconciling the two:

- ADR-0002's rejection premise was "the existing core already delivers most acceptance criteria" — but the hypotheses below show the *current* architecture has real structural problems the deepening programme does not resolve: `ProjectStore` is an architectural load-bearing god-object referenced by 60 production files; ambient `CardreConfig.from_env()` is called from 11 sites including node registry and routes; artifact publication is not atomic with DB registration; node contracts are advisory and nodes freely access `context.store`; transactions span long-running computation in the executor; the worker reopens `ProjectStore` from a path; routes construct repositories and perform ownership checks.
- The deepening programme improved localized seams (manifest hashing, scoring IR, node module decomposition, frontend boundary) but did not alter the dependency direction: infrastructure (`ProjectStore`, SQLite, paths, env) still flows inward into nodes, services, and execution.
- ADR-0003 ("No Legacy Plan Accommodation") confirms there is no external compatibility constraint to honour: no production users, no released schema, no external API consumers.

**Conclusion: a clean cut is justified, but it must be a *different* clean cut than the one ADR-0002 rejected.** The rejected proposal invented competing vocabulary (`node instance`/`node run`/`execution run`, `execution_runs`/`node_runs` tables, single-hash artifacts) and dropped build/validate role enforcement. The validated target here **preserves the domain vocabulary** (`StepSpec`, `RunStep`, `PlanVersion`, `Run`, physical+logical dual hashing, build/validate streams, `RunStatus`/`RunScope` enums, canonical step IDs, evidence kinds) and **preserves all validated mathematical behaviour** — it only restructures the dependency direction and the ownership of I/O, transactions, dispatch, and composition. This is a hexagonal *re-encapsulation*, not a domain rewrite.

A new ADR superseding ADR-0002 was a prerequisite decision (now resolved — see ADR-0014), because the sprint plan depends on it.

## Repository baseline

- Branch: `main`, clean working tree.
- Commit: `a130608` (Node module decomposition), the latest in a series of merged deepening PRs.
- Stack: Python 3.11+, FastAPI, SQLite (WAL, autocommit driver-level), Polars, scikit-learn, React 19, TypeScript, Tauri v2, OpenAPI-generated frontend client.
- No ORM. Raw SQL throughout `cardre/store/` and in several services/execution files.
- Test suite: 96 backend test files + 5 frontend test files. Coverage floor 60% enforced via `make preflight` and CI.
- Architecture enforcement: bespoke AST/text scanners (`test_canonical_contract.py`, `test_evidence_adapters.py`, `test_store_schema_no_queryable_json.py`, `test_error_code_sync.py`, `scripts/audit_artifact_reads.py`, `scripts/check-sidecar-naming.py`, `scripts/check-line-counts.py`). **No `import-linter`** is configured.
- Open PRs: none open; several `refactor/slice-*` and `chore/*` remote branches have no matching squash in the visible main log and their merge state is unclear (see Open PRs section).

## Current architecture map

```
FastAPI routes (cardre/api/routes/)
        |  Depends(get_project_store)  -> constructs ProjectStore per request
        |  Depends(get_run_coordinator) -> RunCoordinator(store)
        v
Services (cardre/services/)
   RunCoordinator, PlanService, PlanMutationService, BranchService,
   ComparisonService, ChampionService, ManualBinningService,
   StalenessService, ExportService, ReportService, ProjectResolver
        |  take ProjectStore; construct repositories internally
        v
Repositories (cardre/store/*_repo.py)
   each takes ProjectStore, issues raw SQL via store.execute()
        |
        v
ProjectStore (cardre/store/db.py)
   owns sqlite3.Connection, threading.RLock, root Path, transaction(),
   execute(), artifact_path(); created per-request in API dependencies,
   per-tick in heartbeat watchdog, per-run in worker.
        |
Execution (cardre/execution/)
   PlanExecutor(store), StepRunner(store, registry), RunLifecycle(store),
   RunStepWriter, ActionPlanner, Worker/Dispatcher.
   _HeartbeatWatchdog opens fresh ProjectStore(root) per tick.
        |
Nodes (cardre/nodes/**)
   NodeType ABC; receive ExecutionContext(store, run_id, plan_version_id,
   step_spec, parent_run_steps, input_artifacts, validated_params,
   runtime_metadata). Nodes call write_json_artifact(store, ...),
   ArtifactEvidenceReader(store), ArtifactRepository(store), and in
   one case PlanRepository/RunStepRepository directly.
```

Key observations:

- `ProjectStore` is both a connection owner, a transaction boundary, a path resolver, a raw-SQL gateway, and a repository factory. 60 production files import it.
- The dependency direction is **outward-pointing**: nodes, services, execution, and routes all depend *inward* on `ProjectStore` (infrastructure). The domain package (`cardre/domain/`) is clean (no I/O, no store imports) — this is the one part of the current architecture that already matches the target.
- Configuration is ambient: `CardreConfig.from_env()` is called in 11 sites, including inside `RunCoordinator.__init__`, `PlanExecutor.__init__`, `NodeRegistry.availability`, route handlers, and `require_governance`.

## Workflow traces (A–F)

### Workflow A — Create or open a project

`POST /projects` (`cardre/api/routes/projects.py:107`) → validate absolute path, no `..` → `ProjectStore(path).initialize()` (creates `cardre.sqlite` + subdirs, executes `ALL_TABLES_SQL`, inserts `store_meta`) → `ProjectRepository(store).create(name)` → `ProjectResolver(CardreConfig.from_env().registry_path).register_project(project_id, root)` → response. The registry is `~/.cardre/projects.json` (atomic temp+replace).

`GET /projects/{project_id}` → `ProjectResolver(...).resolve_root(project_id)` → `ProjectStore(root).open()` (runs `_check_and_migrate`) → `ProjectRepository(store).get(project_id)` → response. The API layer constructs `ProjectStore` directly; there is no application/kernel layer between route and persistence.

### Workflow B — Create and commit a plan version

`POST /projects/{project_id}/plans` (`plans.py:80`) → `plan_belongs_to_project` ownership check (raw SQL JOIN) → `PlanRepository(store).create_plan(project_id, name)` → response.

`POST /projects/{project_id}/plan-versions/{version_id}/commit` (`plans.py:189`) → ownership check → `PlanService(store).commit_plan_version(version_id)` → rejects missing/already-committed (`PlanServiceError`) → `PlanRepository.commit_version` issues a single `UPDATE plan_versions SET is_committed=1` (autocommit; no explicit transaction). Graph validation does **not** occur at commit — `validate_topology` only runs in `PlanExecutor._load_and_validate` at execution time. Mutability is enforced by a service-level check, not a DB constraint.

`PlanMutationService.apply_manual_binning_edit` is the one path that creates a new draft version: it opens `store.transaction("IMMEDIATE")`, inserts `plan_versions` + `plan_steps` + `plan_step_edges` + `manual_binning_reviews` via `PlanRepository.create_version(conn=conn)` + `ManualBinningRepository.create_review`, then commits. Graph rules (acyclicity, parent existence) are NOT re-validated on mutation.

### Workflow C — Submit and execute a run

`POST /projects/{project_id}/runs` (`runs.py:61`) → `plan_version_belongs_to_project` → `RunCoordinator(store).run(plan_version_id, sync, force)`:

1. `PlanRepository(store).get_version` → existence + `is_committed` check (`PlanVersionNotCommittedError`).
2. Branch scope governance check via `CardreConfig.from_env()`.
3. `_plan_decision` → optional `_check_branch_evidence_policy` via `EvidenceLocator(store)` (only for branch scope, not force).
4. `_create_persisted_run`: `_sweep_stale_running_runs` (constructs `RunLifecycle` per stale run, finalises as INTERRUPTED) → `store.transaction("IMMEDIATE")` → concurrent-run guard via raw SQL `SELECT 1 FROM runs WHERE plan_version_id=? AND finished_at IS NULL` → `RunRepository.create`.
5. sync=True → `_execute_existing_running_run`: `RunLifecycle.start(store, ...)` context manager → `PlanExecutor(store).run_plan_version` → `lifecycle.finalise(result.status())`.
6. sync=False → `_dispatch_async`: builds `RunRequest(project_path=str(store.root), ...)`, `ThreadRunDispatcher.dispatch(request)`; on dispatch failure `RunLifecycle.start(...).finalise(FAILED)`.

`PlanExecutor.run_plan_version`:
- `_load_and_validate`: `PlanRepository.get_version_steps` + `validate_topology` (in-place Kahn's) + per-node availability probe → `PlanContainsUnavailableNodesError` if any unavailable.
- `_resolve_run_branch_id` via raw SQL `SELECT branch_id FROM runs WHERE run_id=?`.
- For each action: heartbeat → `_HeartbeatWatchdog` (spawns daemon thread opening fresh `ProjectStore(root)` per tick) → `_execute_and_persist` → heartbeat.

`_execute_and_persist`: `StepRunner.run_step` (resolves inputs, instantiates node, normalizes params, builds `ExecutionContext`, calls `node.run(context)`, builds fingerprint) → `_record_run_step_from_result` opens `store.transaction("IMMEDIATE")`, calls `write_run_step(conn, ...)` which inserts `run_steps` + `evidence_edges` + `evidence_artifacts` + `artifact_lineage` (input + output) on the passed connection, commits.

`RunLifecycle.finalise(status)`: writes manifest first (`write_manifest` builds `RunManifest` pydantic payload, hashes it, atomic temp+`os.replace` to `exports/manifest-{run_id}/manifest.json`) → `RunRepository.transition(run_id, status, expected_from=(RUNNING,))` (SQL-level compare-and-set). On transition failure, rewrites manifest with actual status and raises `RUN_ALREADY_FINALISED`.

### Workflow D — Execute a representative modelling node (LogisticRegression)

`LogisticRegressionNode.run(context)` (`cardre/nodes/build/models.py:33`):
1. `ArtifactEvidenceReader(context.store)` — constructs reader against the store.
2. `context.require_train_artifact()` — first input artifact with `role=="train"`.
3. `context.target_metadata()` — constructs another `ArtifactEvidenceReader(context.store)`, finds `MODELLING_METADATA`.
4. `reader.read_optional` for `SELECTION_DEFINITION`.
5. `reader.read_dataframe(train_artifact)` → `pl.read_parquet(store.artifact_path(art))`.
6. Select `*_woe` columns, build `TargetSpec`, fit `sklearn.linear_model.LogisticRegression`.
7. `write_json_artifact(store, artifact_type="model", role="model", payload=model, metadata={"schema_version": SCHEMA_MODEL_ARTIFACT, ...})` — writes to `store.root/artifacts/{hash[:16]}-{stem}.json`, registers via `ArtifactRepository(store).register` (dedup by `physical_hash`).
8. Returns `NodeOutput(artifacts=[artifact], metrics=...)`.

The node accesses: `context.store` (direct), `ArtifactEvidenceReader(context.store)` (twice), `context.input_artifacts`, `context.target_metadata()`. It reads only declared inputs. The artifact is published **outside** any DB transaction — `write_json_artifact` does `temp_path.replace(stored_path)` then `ArtifactRepository.register` as an autocommit INSERT. If the process crashes between file replace and INSERT, an orphan file exists with no DB row; if the INSERT succeeds but the executor's later `write_run_step` transaction fails, the file exists, the artifact row exists, but no `artifact_lineage`/`evidence_*` rows reference it.

### Workflow E — Generate scoring output

`PythonScoringExportNode.run` (`scoring_export.py:252`): finds frozen bundle via `context.find_frozen_bundle()` → finds `BIN_DEFINITION`, `WOE_TABLE`, `MODEL_ARTIFACT` by role → finds non-bundle `SCORE_SCALING` → reads typed evidence → `compile_scorecard(bin_def, woe_table, scorecard_dict, model_dict, feature_contract)` (scoring_export_ir.py) → `_build_python_scorer_source` emits standalone Python with `def score_cardre(record)` → `write_json_artifact(report, SCHEMA_SCORING_EXPORT_PYTHON)`.

`SqlScoringExportNode` does the same with SQL CTE output. `tests/test_scoring_export_parity.py` asserts Python and SQL outputs match `ApplyModelNode` reference output on train/test/oot. Parity is a first-class validated behaviour that must be preserved.

### Workflow F — Frontend project and run interaction

`App.tsx` holds `projectId` in `useState`; `WelcomeScreen` lists projects via `api.listProjects` and creates via `api.createProject({name, path})`. `ProjectView` builds `scope={projectId}` and calls `useProjectWorkspace(scope)`.

`useProjectWorkspace` issues parallel queries (`project`, `plans`, `planVersions`, `runs`, `run`, `runSteps`, `runEvidence`) via `openapi-fetch` typed client, attaching `X-Project-Id` header. A 1s `setInterval` refetches the four run-scoped queries while the selected run is non-terminal. Mutations: `createPlanMutation`, `runMutation` (POST `RunCreateRequest{plan_version_id, force:false, sync:false}`).

Tauri `main.rs` spawns `binaries/cardre-api-{triple}`, waits for `/health`, injects `window.__API_URL__` via `window.eval`, stores the child in `AppState`, kills on `WindowEvent::Destroyed`. Base URL read from `window.__API_URL__` falling back to `http://127.0.0.1:8752`.

## Evidence for and against each hypothesis

### Hypothesis 1 — `ProjectStore` is an over-broad architectural dependency — CONFIRMED

Evidence:
- `ProjectStore` is imported in 60 production files (rg count).
- `cardre/store/db.py:24-182`: `ProjectStore` owns (a) the sqlite3.Connection (`_db`), (b) the `threading.RLock`, (c) `root: Path`, (d) `transaction(mode)` context manager yielding the connection, (e) `execute(sql, params)` raw-SQL gateway, (f) `artifact_path(artifact)` path resolver, (g) `execute_script`/`executemany`, (h) `initialize()`/`open()` lifecycle, (i) schema migration trigger.
- Every repository (`artifact_repo.py:20`, `plan_repo.py:21`, `run_repo.py:23`, `evidence_repo.py:19`, `branch_repo.py:18`, `comparison_repo.py:21`, `champion_repo.py:16`, `manual_binning_repo.py:29`, `project_repo.py:19`, `run_step_repo.py:18`, `step_repo.py:18`) takes `ProjectStore` in its constructor and issues SQL via `self._store.execute(...)`.
- `ExecutionContext.store: ProjectStore` (`execution/context.py:38`) — nodes receive it directly.
- `RunCoordinator.__init__(store)` (`run_coordinator.py:91`), `PlanExecutor.__init__(store)` (`executor.py:130`), `StepRunner.__init__(store, ...)` (`step_runner.py:83`), `RunLifecycle` functions take `store` (`run_lifecycle.py:130,209,289,346`), `StalenessService(store)` (`staleness_service.py:38`), `EvidenceLocator(store)` (`evidence_locator.py:51`), `ReportGenerationService(store, ...)` (`report_service.py`), `ArtifactEvidenceReader(store)` (`_evidence/reader.py:40`), `_evidence/adapters/_base.py` (`match(artifacts, profile, store)`, `parquet_has_columns(art, cols, store)`).
- `cardre/artifacts.py:28-68`: `write_*_artifact(store, ...)` constructs `ArtifactRepository(store)` and calls `store.root` for paths.
- `_HeartbeatWatchdog` (`executor.py:53-108`) opens a fresh `ProjectStore(root)` per tick and per `__enter__`/`__exit__`.
- `RunWorker.execute` (`worker.py:78-88`) reopens `ProjectStore(request.project_path)`.

The proposal's six-listed responsibilities are all present in one class. No counter-evidence.

### Hypothesis 2 — Application use cases are fragmented — CONFIRMED

Evidence:
- Run lifecycle business rules live across: `RunCoordinator.run` (validation, decision, dispatch — `run_coordinator.py:107-177`), `_check_branch_evidence_policy` (`run_coordinator.py:220-250`), `_create_persisted_run` (concurrent-run guard, stale sweep — `run_coordinator.py:387-440`), `_execute_existing_running_run` (`run_coordinator.py:275-333`), `RunLifecycle` (terminal transition, manifest — `run_lifecycle.py:208-334`), `PlanExecutor` (topology, heartbeat, persistence — `executor.py:142-398`).
- Plan commit rules live in `PlanService.commit_plan_version` (`plan_service.py:71-97`) but the actual SQL is a single autocommit UPDATE in `PlanRepository.commit_version` — no transaction wraps "validate committed → update".
- Manual binning edit rules live in `PlanMutationService.apply_manual_binning_edit` (`plan_mutation_service.py:72-178`), which mixes: source-evidence structural validation, override merging, params_hash recomputation, and a transaction that writes plan_version + steps + edges + review.
- Branch creation rules live across `BranchService.create_branch` (orchestrator, `branch_service.py:29-65`), `BranchValidator` (rules, `branch_validator.py`), `branch_graph.py` (closure/remap), `branch_writer.py` (transaction).
- Comparison rules live across `comparison_service.create_comparison` / `refresh_comparison` (`comparison_service.py:119-330`) and four `comparison/*` builders.
- Champion rules live in `champion_service.assign_champion` (`champion_service.py:20-172`) with raw SQL for the final query.
- Export rules live in `export_service.export_branch_audit_pack` (`export_service.py:34-124`) including atomic tmp-dir→rename with backup/restore.
- No "use case" type exists. Business rules are methods on services that take `ProjectStore` and construct repositories inline.

### Hypothesis 3 — Infrastructure objects cross too far inward — CONFIRMED

Evidence:
- `ExecutionContext.store: ProjectStore` (`execution/context.py:38`) — the single most damaging inward leak: every node can call `store.execute("SELECT ...")`, `store.artifact_path(...)`, `ArtifactRepository(store)`, `ArtifactEvidenceReader(store)`, `PlanRepository(store)`, `RunStepRepository(store)`.
- `TechnicalManifestExportNode` (`build/export.py:19-247`) actually does this: it constructs `PlanRepository`, `ProjectRepository`, `RunStepRepository`, `ArtifactRepository` directly and iterates *all* run_steps for the run — not just `context.input_artifacts`.
- `CoefficientSignCheckNode` (`build/diagnostics.py:47-159`) reads a WOE evidence JSON via raw `store.artifact_path(...).read_text()` (`:77-79`, suppressed with `# cardre-allow-artifact-read: low-level-evidence-parser`).
- `ProfileDatasetNode` (`prep/profile.py`) reads parquet via `pl.read_parquet(store.artifact_path(...))` (suppressed `dataset-frame-input`).
- `ImportTabularDatasetNode` (`prep/import_.py`) reads from `params["source_path"]` — arbitrary filesystem path outside the project root — by design (ingest boundary), but it means a node touches the host filesystem.
- `RunCoordinator` issues raw SQL (`run_coordinator.py:423-426`).
- `PlanExecutor._resolve_run_branch_id` issues raw SQL (`executor.py:377-378`).
- `champion_service.get_champion` issues raw SQL (`champion_service.py:203-216`).
- `CardreConfig.from_env()` called in nodes/registry.py (`:110, :129`), capabilities.py (`:14, :19`), executor.py (`:134`) — environment access inside the node registry and executor, not just bootstrap.
- `X-Project-Path` header support (`api/dependencies.py:35-61`) — project-root path crosses the API boundary.

### Hypothesis 4 — Node contracts are advisory rather than enforceable — CONFIRMED

Evidence:
- `ArtifactContract` (`nodes/contracts.py:19-23`) only declares `input_roles`/`output_roles` as class attributes looked up via `getattr(cls, "input_roles", [])` (`contracts.py:58`). There is no schema validation, no output-kind validation, no required-output enforcement, no undeclared-output rejection.
- `StepRunner._filter_input_artifacts` (`step_runner.py:281-315`) filters by role — but a node can still reach *other* artifacts via `context.store` + `ArtifactRepository`.
- `NodeOutput` (`execution/context.py:81-85`) is a plain dataclass: `artifacts: list[ArtifactRef]`, `metrics`, `execution_fingerprint`, `warnings`. The runner does `isinstance(node_output, NodeOutput)` (`step_runner.py:172`) — that is the only output validation. Any artifact can be returned with any role/kind; the runner records them all in `artifact_lineage` and `evidence_artifacts`.
- `NodeFailedWithArtifacts` (`domain/errors.py:92-112`) lets a failing node return partial artifacts — useful, but no validation that those artifacts match declared output roles.
- `RolePolicy` (`contracts.py:27-32`) is defined but unused in the registry/execution path (grep finds no consumer).
- `TechnicalManifestExportNode` (see above) reads from the entire run's lineage, not its declared inputs.
- Node families most reliant on unrestricted store access: **export/manifest** (`TechnicalManifestExportNode`, `BuildSummaryReportNode`), **diagnostics** (`CoefficientSignCheckNode` raw path read), **freeze** (`FrozenScorecardBundleNode` constructs `ArtifactRepository(store).get(...)` to resolve source artifacts by id), **profile** (`ProfileDatasetNode` raw parquet read), **import** (`ImportTabularDatasetNode` reads arbitrary host path).

### Hypothesis 5 — Configuration is ambient — CONFIRMED

Evidence:
- `CardreConfig.from_env()` called in 11 sites: `run_coordinator.py:97`, `api/dependencies.py:23,91`, `api/routes/projects.py:40,89,137`, `nodes/registry.py:110,129`, `capabilities.py:14,19`, `execution/executor.py:134`.
- `ProjectResolver` is constructed per-request from `CardreConfig.from_env().registry_path` (`api/dependencies.py:24`, `routes/projects.py`).
- The dispatcher is a module-level singleton (`run_coordinator.py:38-46`): `_global_dispatcher` lazily built on first use.
- `require_governance` re-reads env every request (`dependencies.py:91`).
- `_raw_project_path_allowed()` reads `os.environ.get("CARDRE_ALLOW_RAW_PROJECT_PATH")` every request (`dependencies.py:75-79`).
- `PlanExecutor.__init__` reads the heartbeat interval from env (`executor.py:134`).

There is no bootstrap/composition root. Configuration is read wherever it's needed.

### Hypothesis 6 — Transaction ownership is unclear — CONFIRMED

Evidence:
- Commits occur in: `ProjectStore.initialize` (`db.py:76`), `ProjectStore.transaction` (commit on success, rollback on exception — `db.py:147-152`), `_check_and_migrate` (`_schema_version.py:69`), `PlanRepository.create_version` (when `conn is None`, `plan_repo.py:70`), `PlanMutationService` (one `IMMEDIATE` txn, `plan_mutation_service.py:151-172`), `RunCoordinator._create_persisted_run` (one `IMMEDIATE` txn, `run_coordinator.py:408`), `PlanExecutor._record_run_step_from_result` (one `IMMEDIATE` txn, `executor.py:320`), `BranchWriter.create_branch_with_graph` (one `IMMEDIATE` txn), `comparison_service.refresh_comparison` (one txn, `comparison_service.py:264-319`), `champion_service.assign_champion` (one txn, `champion_service.py:131-161`), `ProjectRegistry._write` (file replace).
- Repositories commit implicitly via autocommit for single statements (e.g. `ArtifactRepository.register`, `RunRepository.transition`, `RunRepository.heartbeat`, `StepRepository.insert_edge`, `BranchRepository.create_branch`, `ManualBinningRepository.create_review`).
- `RunRepository.transition` does a SQL-level compare-and-set (`run_repo.py:111-148`) — this is the run state machine's atomic guard, but it runs *outside* the manifest write transaction. `RunLifecycle.finalise_run` writes the manifest (filesystem) *then* calls `transition` (DB) — these are two separate operations; if the process dies between them, the manifest exists but the run row still says `RUNNING`.
- Transactions span long-running computation: `PlanExecutor._execute_and_persist` runs `node.run(context)` (which may take seconds for logistic regression, minutes for clustering) **before** opening `store.transaction("IMMEDIATE")`. This is actually correct (don't hold a write txn during computation), but the artifact publication inside `node.run` happens *outside* any transaction (see Hypothesis 7).
- Multiple connections participate in one logical operation: `_HeartbeatWatchdog` opens a *separate* `ProjectStore` per tick (`executor.py:82,94,101-103`) — a different SQLite connection writing `heartbeat_at` while the main connection is executing a node. The main `ProjectStore` is shared across threads (`check_same_thread=False` + `threading.RLock`). WAL mode + autocommit driver-level means these are real concurrent writes.
- Filesystem publication and DB registration diverge (see Hypothesis 7).

### Hypothesis 7 — Artifact publication is not sufficiently atomic — CONFIRMED

Evidence (lifecycle in `cardre/artifacts.py:28-68`):
1. `stored_path = store.root / directory / f"{logical_hash[:16]}-{stem}{extension}"`.
2. `temp_path = stored_path.with_name(f".{stored_path.name}.{uuid}.tmp")`.
3. `bytes_writer()` (in-memory).
4. `temp_path.write_bytes(data)` — OSError unlinks temp.
5. `temp_path.replace(stored_path)` — atomic file move.
6. `physical_hash(stored_path)`.
7. `ArtifactRepository(store).register(artifact)` — autocommit INSERT (or dedup SELECT+INSERT).
8. Later, `PlanExecutor._record_run_step_from_result` opens a *separate* `IMMEDIATE` transaction and calls `write_run_step(conn, ...)` which inserts `artifact_lineage` rows referencing `artifact_id`.

Partial-failure states:
- Crash between (5) and (7): orphan file on disk, no DB row.
- Crash between (7) and (8): file exists, `artifacts` row exists, no `artifact_lineage`/`evidence_*` rows. The artifact is unreachable from any run.
- (7) succeeds but (8) fails: `PlanExecutor._execute_and_persist` catches the recording failure and rewrites the step as FAILED with empty outputs (`executor.py:253-267`) — the artifact file and row remain, orphaned.
- `NodeFailedWithArtifacts`: the node writes artifacts (5,6,7) then raises; the executor records them as `output_artifact_ids` of a FAILED step (`step_runner.py:206-232`). The file/row exist but the step failed — this is intended but means artifacts can outlive a failed step.
- Dedup: `ArtifactRepository.register` dedups by `physical_hash` (`artifact_repo.py:28-33`). If two different logical payloads produce identical bytes (rare for JSON, possible for empty parquet), the second registration returns the first artifact_id — but the second node's `NodeOutput` still carries the *new* `ArtifactRef` with the *new* logical_hash, which never gets a DB row. Lineage then references an artifact_id that doesn't match the `ArtifactRef.logical_hash` the node produced. This is a latent inconsistency.

The proposal's content-addressed object store (staging → atomic publish → DB registration inside one transaction) resolves all of these.

### Hypothesis 8 — Run lifecycle ownership is fragmented — CONFIRMED

Evidence:
- Submission: `RunCoordinator.run` (`run_coordinator.py:107-177`).
- Dispatch: `RunCoordinator._dispatch_async` + `ThreadRunDispatcher.dispatch` (`run_coordinator.py:344-381`, `worker.py:183-231`).
- Queued state: `RunStatus.QUEUED` exists (`domain/run.py:42`) but is never written by any code path in launch mode — runs go CREATED? Actually `RunRepository.create` sets `status="running"` directly (no CREATED/QUEUED transition). `_VALID_TRANSITIONS` (`run.py:59-67`) defines `created→queued`, `queued→running` but neither is exercised. This is dead state machinery.
- Running state: set by `RunRepository.create` (autocommit INSERT with `status="running"`), heartbeat by `RunRepository.heartbeat` (autocommit UPDATE).
- Step state: `RunStepStatus` enum (`run.py:29-35`) — PENDING never written; SUCCEEDED/FAILED written by `write_run_step` inside the executor's `IMMEDIATE` txn; SKIPPED never written.
- Cancellation: `RunStatus.CANCELLED` is in `_VALID_TRANSITIONS` and `terminal()` but **no code path sets it**. There is no cancel endpoint. The proposal's `POST /runs/{run_id}/cancel` would be new.
- Interruption: `RunCoordinator._sweep_stale_running_runs` finalises stale runs as INTERRUPTED (`run_coordinator.py:446-483`); `RunWorker._record_failure` finalises as FAILED (`worker.py:96-132`).
- Failure finalization: `RunLifecycle.finalise(FAILED, diagnostic=...)` (`run_lifecycle.py:396`).
- Success finalization: `RunLifecycle.finalise(SUCCEEDED)` after `PlanExecutor` returns.
- Manifest creation: `RunLifecycle.build_final_manifest_payload` + `write_manifest` (`run_lifecycle.py:91-188`).
- Manifest publication: atomic `os.replace` to `exports/manifest-{run_id}/manifest.json`.
- Recovery after process death: `_sweep_stale_running_runs` (heartbeat-based), `RunWorker.execute` (re-entrant via `execute_created_run`).

Ownership is spread across `RunCoordinator`, `RunLifecycle`, `RunRepository`, `RunWorker`, `ThreadRunDispatcher`, `PlanExecutor`, `_HeartbeatWatchdog`. The lifecycle is *mostly* cohesive (ADR-0004 deepening helped), but the dispatch → worker → executor → lifecycle chain crosses four modules and two threads, each reopening `ProjectStore`.

### Hypothesis 9 — The API is too closely coupled to persistence — CONFIRMED

Evidence:
- `get_project_store` dependency (`api/dependencies.py:18-72`) yields a `ProjectStore` to every project-scoped route.
- Routes construct repositories directly: `runs.py:92` `RunStepRepository(store)`, `runs.py:110` `EvidenceRepository(store)`, `plans.py:87` `PlanRepository(store)`, `plans.py:112` `PlanRepository(store)`, `artifacts.py:24` `ArtifactRepository(store)`, `branches.py:31,55,91` `BranchRepository(store)`, `comparisons.py:24,39` `ComparisonRepository(store)`, `champion.py:25` `ChampionRepository(store)`, `manual_binning.py:42,57,76` `ManualBinningRepository(store)`, `evidence.py:44,83,91` `StepRepository(store)` + `EvidenceRepository(store)`, `node_types.py:22` `StepRepository(store)`.
- Routes perform ownership checks via raw SQL in `_project_scope.py` (`run_belongs_to_project`, `plan_belongs_to_project`, `plan_version_belongs_to_project`, `branch_belongs_to_project`, `step_belongs_to_project` — five JOIN queries).
- Routes access project paths: `projects.py:107-140` validates path and calls `store.initialize()`.
- Routes interpret persistence records: `runs.py:79-94` maps `RunStep` rows; `runs.py:97-113` maps evidence edges.
- `projects.py:137` calls `ProjectResolver(CardreConfig.from_env().registry_path).register_project` inside the route — env access + registry write in a route handler.
- `get_run_coordinator` (`dependencies.py:106-110`) constructs `RunCoordinator(store)` — application logic is constructed in a FastAPI dependency.

### Hypothesis 10 — A clean rewrite is cheaper than a compatibility refactor — CONFIRMED (with caveat)

Compatibility-refactor complexity that would be introduced:
- Dual schemas: new hexagonal schema + existing v2 schema 101, with a migration chain. But ADR-0003 says no legacy plans exist; no migration is needed.
- Dual API: new `/v2/...` routes alongside current routes, with response translation. But no external consumers exist; the frontend is generated from OpenAPI and can be regenerated in one step.
- Transitional node contexts: a wrapper `ExecutionContext` that has both `store` and the new restricted context, nodes migrated one at a time. This is the most expensive path — 51 node classes, many accessing `context.store` directly. A wrapper would have to expose `store` until every node is migrated, which defeats the contract.
- Legacy artifact readers: content-addressed `objects/sha256/` + existing `artifacts/{hash[:16]}-{stem}.{ext}`. But no project files exist; the layout can be replaced.
- Compatibility wrappers: `ProjectStore` delegating to the new unit-of-work. This preserves the 60-file dependency surface for months.
- Staged preservation of current project files: none exist.

No real constraint justifies any of this. ADR-0003 is explicit. The task constraints are explicit. **The caveat**: ADR-0002 rejected a *different* clean rewrite (one that changed vocabulary and dropped role enforcement). The validated rewrite preserves the domain vocabulary and validated behaviour, so ADR-0002's rejection rationale ("the existing core already delivers most acceptance criteria") does not apply — the hypotheses show it does not deliver the structural acceptance criteria (dependency direction, atomic publication, enforceable contracts, single composition root). ADR-0014 now supersedes ADR-0002 and authorises this rewrite.

## Active overlapping work

Merged to main (already in baseline):
- `ab3819a` Deepen branch evidence locator (ADR-0013).
- `86c38a7` Deepen run terminal handling (ADR-0004).
- `5e5d87e` Deepen supervised training preparation (ADR-0007).
- `a130608` Node module decomposition (PR4 — split feature_selection/validate/build/bins).
- `4892c26` Frontend and desktop boundary (PR3 — openapi-fetch, typed diagnostics, sidecar lifecycle).
- `808e528` Backend contract correctness (manifest hash, scoring IR, to_node removal).
- `2ccce5e` Trust the gates (CI repair).
- `f2403ec` PR11 thermo-nuclear quality sprint closeout.

Remote branches with unclear merge state (no matching squash in visible main log; may be merged earlier, abandoned, or still open):
- `refactor/extract-executor-and-branch-service` (7 commits) — executor/branch service extraction. Consistent with ADR-0002's "extend" path. **Supersede**: the rewrite extracts these into application use cases + ports; this branch's work becomes redundant.
- `refactor/slice-1-route-mappers` (2 commits) — route response mappers. **Supersede**: the rewrite moves mapping into application handlers / API schemas.
- `refactor/slice-2-run-step-writer` (5 commits) — run-step writer extraction. **Supersede**: the rewrite owns persistence in SQLite adapters.
- `refactor/slice-3-model-helpers` (2 commits) — model-node helper extraction. **Preserve as behavioural knowledge**: the helpers are ported into the new `nodes/build/` modules.
- `refactor/slice-4-constants` (1 commit) — heartbeat config consolidation. **Supersede**: config moves to bootstrap.
- `chore/fix-forward-heartbeat-coverage`, `chore/slice-5-coverage-bump` — coverage bumps. **Incorporate**: keep the coverage floor policy.
- `pr0-safety-net`, `pr0-followup-docs` — pre-refactor safety net + docs. **Preserve as behavioural knowledge** (golden fixture determinism).
- `pr7-followup-drop-bin-definition-forwarders` — drop dead bin forwarders. Likely already absorbed; verify before rewrite.

Recommendation: treat all `refactor/slice-*` branches as **superseded** — their value is captured by the rewrite's structural re-encapsulation. Do not merge them first; the rewrite deletes the code they refactor. The `chore/*` coverage policy and `pr0-safety-net` behavioural knowledge should be incorporated into the plan.

## Preserve / Port / Rewrite / Delete inventory

### Preserve largely as-is (validated behaviour, low coupling)

- `cardre/domain/` — `ArtifactRef`, `Plan`, `PlanVersion`, `Project`, `Run`, `RunStep`, `RunStatus`, `RunScope`, `RunStepStatus`, `StepSpec`, `EvidenceEdge`, `EvidenceArtifact`, `ResolvedEvidence`, `ManualBinningReview`, errors, diagnostics, hash functions (`json_logical_hash`, `physical_hash`, `table_logical_hash`, `params_hash`). These are pure, frozen, well-tested. Move to `domain/` package unchanged.
- `cardre/_evidence/kinds.py` — `EvidenceKind` enum (42 kinds). Move to `domain/evidence/` or `nodes/contracts.py`.
- `cardre/_evidence/schemas.py` — `SCHEMA_*` constants. Move with kinds.
- `cardre/_evidence/profiles.py` — `EVIDENCE_PROFILES`. Move to `nodes/contracts.py` or `application/evidence/`.
- `cardre/_evidence/adapters/__init__.py` — `EVIDENCE_ADAPTERS` registry + typed dataclass parsers. Move to `adapters/evidence/`. The `parse` callables currently take `ProjectStore`; they must be rewritten to take an `ArtifactReader` port (reads bytes/path) instead — **port with adaptation**.
- `cardre/nodes/build/scoring_export_ir.py` — `ScoringBin`, `ScoringVariable`, `compile_scorecard`, `compute_log_odds_and_direction`. Pure. Preserve.
- `cardre/nodes/build/_logit_helpers.py`, `_bin_counts.py`, `_fine_classing_numeric.py`, `_fine_classing_categorical.py`, `_metrics_calculation.py` — pure numerical helpers. Preserve.
- `cardre/node_parameters.py` — `NodeParameterSchema`, `MethodOption`, `ParameterDefinition`, `ParameterConstraint`, `normalize_node_params`. Pure. Preserve (move to `nodes/contracts.py` or `nodes/parameters.py`).
- `cardre/execution/topology.py`, `step_graph.py`, `fingerprints.py`, `failure_classification.py`, `action_planner.py` — pure. Preserve (move to `application/execution/` or `domain/plans/`).
- `cardre/engine/` (if present) — `cardre.engine.binning.woe` (WOE convention, `compute_iv`, `compute_woe`) used by `manual_binning_service.py`. Preserve.
- `cardre/modeling/families.py` (if present) — family registry. Preserve.
- `tests/fixtures/golden_*.json` — golden fixtures. Preserve.
- `tools/reference_extractors/extract_scorecard_r_german_credit.R` — parity reference. Preserve.
- `tests/test_scoring_export_parity.py`, `test_logistic_regression_known_input.py`, `test_score_scaling_known_input.py`, `test_calibrate_probabilities.py`, `test_golden_fixtures_roundtrip.py`, `test_golden_report_bundle.py`, `test_run_audit_integrity.py` — parity/characterization tests. **Preserve as behavioural oracles**, updating imports.
- `frontend/src/api/client.ts` transport (`ApiError`, `fetchResponse`, `fetchJson`, `typedTransport`, `requireData`, canonical error codes) — preserve; regenerate `openapi.json`/`schema.d.ts` from the new API.
- `frontend/src-tauri/src/main.rs` sidecar lifecycle (post-PR3) — preserve.

### Port with adaptation (valuable behaviour, coupled to old infrastructure)

- `cardre/nodes/build/models.py` — `LogisticRegressionNode`, `ScoreScalingNode`, `BuildSummaryReportNode`, `DummyFitNode`, `NoopNode`. Replace `context.store` + `write_json_artifact(store, ...)` with `context.outputs.publish(role, kind, payload)` / `context.outputs.publish_table(role, kind, frame)`. Replace `ArtifactEvidenceReader(context.store)` with `context.inputs.read(kind)`.
- `cardre/nodes/build/features.py` — `CalculateWoeIvNode`, `WoeTransformTrainNode`. Same port adaptation.
- `cardre/nodes/build/automatic.py`, `_fine_classing.py`, `_optbinning.py` — `AutomaticBinningNode`. Same adaptation.
- `cardre/nodes/build/manual.py` — `ManualBinningNode`. Same.
- `cardre/nodes/build/selection.py`, `selection_policy.py` — `VariableSelectionNode`. Same.
- `cardre/nodes/build/clustering.py` — `VariableClusteringNode` (770 lines). Same.
- `cardre/nodes/build/diagnostics.py` — `CoefficientSignCheckNode` (remove raw `store.artifact_path().read_text()`), `SeparationDiagnosticsNode`, `VifDiagnosticsNode`, `CalibrationDiagnosticsNode`. Same.
- `cardre/nodes/build/export.py` — `TechnicalManifestExportNode`. **Major port**: replace `PlanRepository`/`RunStepRepository`/`ArtifactRepository` direct construction with a declared `manifest` input role carrying the run's step summary; the node assembles the manifest from declared inputs only.
- `cardre/nodes/build/freeze.py` — `FrozenScorecardBundleNode`. Replace `ArtifactRepository(store).get(...)` with `context.inputs.read_artifact(artifact_id)`.
- `cardre/nodes/build/scoring_export.py` — `ScorecardTableExportNode`, `PythonScoringExportNode`, `SqlScoringExportNode`. Same adaptation.
- `cardre/nodes/prep/*` — `ImportTabularDatasetNode` (keep `source_path` param but route through a `SourceDatasetReader` port), `ProfileDatasetNode` (replace raw `pl.read_parquet(store.artifact_path(...))` with `context.inputs.read_dataframe(art)`), `ValidateBinaryTargetNode`, `SplitTrainTestOotNode`, `ApplyExclusionsNode`, `ExplicitMissingOutlierTreatmentNode`, `DefineModellingMetadataNode`, `DevelopmentSampleDefinitionNode`. Same.
- `cardre/nodes/validate/*` — `ApplyWoeMappingNode`, `ApplyModelNode`, `ValidationMetricsNode`, `CutoffAnalysisNode`. Same.
- `cardre/nodes/selection/*` — `FeatureSelectionFilterNode`, `FeatureSelectionEmbeddedNode`, `ResampleTrainingDataNode`, `SmoteTrainingDataNode`. Same.
- `cardre/nodes/boosting.py`, `ensembles.py`, `calibrate.py`, `explainability.py`, `fairness.py`, `ml_models.py`, `reject_inference.py`, `tuning.py` — deferred nodes. Same adaptation (when graduated).
- `cardre/_training_utils.py` — `prepare_supervised_training_data`. Port to take an `InputCollection` instead of `context.store`.
- `cardre/modeling/adapters.py` — `apply_logistic`, `apply_sklearn_estimator`, `apply_ensemble`. Replace `ProjectStore` params with `ArtifactReader` + `ArtifactWriter` ports.
- `cardre/modeling/serialization.py` — estimator save/load. Replace `ProjectStore` with `ArtifactReader`/`ArtifactWriter`.
- `cardre/services/comparison/woe_iv.py`, `model.py`, `validation.py`, `cutoff.py` — pure builders taking `ComparisonContext`. Port to take an `EvidenceReader` port instead of `store`.
- `cardre/reporting/collector.py`, `_resolve.py`, `schema.py`, `evidence_contract.py`, `renderer_html.py`, `sections/`, `templates/` — port to take `EvidenceReader` + `ArtifactReader` ports.
- `cardre/readiness/check.py`, `step_requirements.py` — port to take ports.
- `cardre/services/manual_binning_service.py` — pure WOE/IV extractors. Preserve as pure functions.
- `cardre/services/plan_dto.py` — DTOs. Replace with application result types.
- `cardre/evidence_locator.py` — `EvidenceLocator.resolve` fallback chain. Port to take `RunQueries` + `EvidenceQueries` ports; the 4-stage fallback logic is preserved.

### Rewrite (primary purpose is the current problematic architecture)

- `cardre/store/db.py` — `ProjectStore`. **Delete**, replaced by `SqliteUnitOfWork` (connection/transaction owner) + `adapters/sqlite/` repositories.
- `cardre/store/_locked_cursor.py`, `_schema_version.py`, `_base.py` — rewrite as SQLite adapter internals.
- `cardre/store/*_repo.py` (11 files) — rewrite as `adapters/sqlite/` query/mutation objects behind ports.
- `cardre/store/schema.py` — replace with clean schema (see 03-persistence-and-artifacts.md). Schema version 101 + migration 100→101 deleted (no projects to migrate).
- `cardre/store/project_registry.py` — rewrite as `adapters/system/ProjectRegistry` behind `ProjectRegistryPort`.
- `cardre/artifacts.py` — `write_*_artifact` helpers. Rewrite as `adapters/filesystem/ArtifactStore` behind `StagedArtifactWriter` port (staging → atomic publish → DB registration in one UoW).
- `cardre/execution/context.py` — `ExecutionContext` with `store`. Rewrite as restricted `NodeContext` with `inputs`, `outputs`, `params`, `runtime`, `logger` only.
- `cardre/execution/executor.py` — `PlanExecutor`, `_HeartbeatWatchdog`. Rewrite as `application/runs/ExecuteRun` use case orchestrating `RunDispatcher` + `StepRunner` + persistence via UoW. Heartbeat becomes a `RunRepository` concern inside the SQLite adapter.
- `cardre/execution/step_runner.py` — `StepRunner`. Rewrite to build `NodeContext` (no store), validate declared outputs, delegate persistence to the use case.
- `cardre/execution/run_lifecycle.py` — `RunLifecycle`. Rewrite as `application/runs/FinalizeRun` use case; manifest write + transition inside one UoW.
- `cardre/execution/run_step_writer.py` — rewrite as `adapters/sqlite/RunStepWriter` behind the persistence port.
- `cardre/execution/worker.py` — `RunWorker`, `ThreadRunDispatcher`. Rewrite as `adapters/dispatch/ThreadRunDispatcher` behind `RunDispatcher` port; worker takes a `UnitOfWorkFactory` not a path.
- `cardre/services/run_coordinator.py` — `RunCoordinator`. Rewrite as `application/runs/SubmitRun` + `application/runs/ExecuteRun` use cases; no global singleton dispatcher.
- `cardre/services/plan_service.py` — rewrite as `application/plans/GetPlan`, `ListPlans`, `CommitPlanVersion` use cases.
- `cardre/services/plan_mutation_service.py` — rewrite as `application/plans/ApplyManualBinningEdit` use case via UoW.
- `cardre/services/branch_service.py` + `branch_validator.py` + `branch_graph.py` + `branch_writer.py` — rewrite as `application/governance/CreateBranch` use case; graph logic moves to `domain/plans/`.
- `cardre/services/comparison_service.py` — rewrite as `application/governance/CreateComparison` + `RefreshComparison` use cases.
- `cardre/services/champion_service.py` — rewrite as `application/governance/AssignChampion` use case.
- `cardre/services/staleness_service.py` — rewrite as `application/evidence/ExplainStaleness` use case.
- `cardre/services/export_service.py` — rewrite as `application/reporting/ExportAuditPack` use case.
- `cardre/services/report_service.py` — rewrite as `application/reporting/GenerateReport` use case.
- `cardre/services/export_listing.py` — rewrite as adapter.
- `cardre/services/project_resolver.py` — rewrite as `application/projects/ResolveProject` using `ProjectRegistryPort`.
- `cardre/api/dependencies.py` — rewrite as `api/dependencies.py` constructing use cases via the composition root.
- `cardre/api/app.py` — rewrite; composition root builds the app.
- `cardre/api/routes/*` — rewrite as thin route handlers calling use cases; remove ownership checks (use cases enforce), remove repo construction, remove `X-Project-Path`.
- `cardre/api/schemas.py` — redesign to match new API (see 05-api-and-frontend-boundary.md).
- `cardre/api/routes/_project_scope.py` — delete (ownership in use cases).
- `cardre/api/routes/_run_mappings.py` — rewrite as API schema mappers.
- `cardre/config.py` — `CardreConfig.from_env()`. Rewrite as `bootstrap/settings.py` loaded once; pass frozen `Settings` to the composition root.
- `cardre/capabilities.py` — rewrite as `bootstrap/capabilities.py` probing against `Settings` + `NodeCatalogue`.
- `cardre/branch_step_resolver.py` — fold into `domain/plans/` + `application/governance/`.
- `cardre/nodes/registry.py` — rewrite as `bootstrap/node_catalogue.py` building a `NodeCatalogue` from `Settings`; availability probing against `Settings`, not `from_env()`.
- `sidecar/` — rewrite entrypoint to build the app via the composition root.

### Delete without replacement

- `cardre/store/_schema_version.py` migration machinery — no projects to migrate (ADR-0003). The new schema is version 1 (or unversioned until first release).
- `runs.target_step_id` column + all `to_node` plumbing — already removed per `808e528`; verify no residue.
- `runs.queued_at` / `RunStatus.QUEUED` — dead state, never written.
- `RunStepStatus.PENDING` / `SKIPPED` — never written.
- `RolePolicy` (`nodes/contracts.py:27-32`) — unused.
- `_global_dispatcher` singleton (`run_coordinator.py:38-46`) — replaced by composition root.
- `_raw_project_path_allowed()` + `X-Project-Path` header support — delete; `X-Project-Id` only.
- `RunCoordinator._dispatch_async` `type: ignore` for `run_scope` (`run_coordinator.py:356`) — gone with typed `RunScope`.
- `scripts/scan-direct-artifact-reads.py` + `.artifact-read-baseline.json` — already deleted per thermo-nuclear slice 0; verify.
- `scripts/v2-phase-check.sh` — phase-numbered history; replace with named suites (already noted in thermo-nuclear slice 0.3).
- `cardre/engine/` package — if it only contains binning/woe, fold into `domain/` or `nodes/build/`; if empty, delete.
- `cardre/workflows/` — inspect; likely unused.
- Dead `_lifecycle` forwarders on `BinDefinition` (if still present from `pr7-followup`).

## Major deviations from the original proposal

1. ~~**ADR-0002 reconciliation.** The proposal implicitly contradicts ADR-0002. The validated plan explicitly preserves ADR-0002's *intent* (don't invent competing vocabulary, don't drop role enforcement) while superseding its *conclusion* (the structural problems warrant a rewrite). A new ADR is required. This is the single most important modification.~~ **Resolved 2026-07-21: ADR-0014 supersedes ADR-0002 and carries forward its preserved design commitments unchanged.**
2. **Package layout.** The proposed `cardre/{domain,application,nodes,adapters,api,bootstrap}/` is validated with one change: `cardre/_evidence/` does not become `domain/evidence/` wholesale — the `EvidenceKind` enum and `SCHEMA_*` constants are domain (they're vocabulary), but `EVIDENCE_PROFILES` + `EVIDENCE_ADAPTERS` (typed parsers) are *adapters* (they parse bytes → typed objects, which is I/O). Split: `domain/evidence/kinds.py` + `domain/evidence/schemas.py` stay domain; `adapters/evidence/` holds profiles + parsers. This keeps `domain/` pure.
3. **No `Repository[T]`, no generic CRUD.** The proposal agrees. Confirmed: every port is Cardre-specific. The port catalogue (02-domain-and-use-cases.md) lists only meaningful ports.
4. **Node contract enforcement.** The proposal says nodes "must not receive ProjectStore". Confirmed necessary and sufficient. Added: the new contract also enforces declared output roles/kinds and rejects undeclared outputs at the `OutputPublisher` — the current `NodeOutput` is too permissive.
5. **Artifact atomicity.** The proposal's `objects/sha256/` content-addressed store is validated, but the path scheme is refined to `project.cardre/objects/{physical_hash[:2]}/{physical_hash}/` (sharded by first two hex chars to avoid single-dir-with-millions-of-files). Logical hash is metadata, not a path component.
6. **Manifest location.** Current `exports/manifest-{run_id}/manifest.json` → proposed `manifests/runs/{run_id}.json` (canonical). Exports (audit packs, reports) stay under `exports/`.
7. **Bootstrap.** The proposal's single composition root is validated. The module-level `app = create_app()` singleton in `api/app.py:83` must be replaced by `bootstrap/build_app.py` returning a configured app + `Shutdown` callable.
8. **No DI framework.** Confirmed. Direct handler injection in `api/dependencies.py` using a `Container` built once in `bootstrap/container.py`.
9. **Frontend regeneration.** The openapi-fetch + generated `paths`/`components` approach (PR3, merged) is preserved. The rewrite regenerates from the new API once.
10. **Cancellation.** The proposal adds `POST /runs/{run_id}/cancel`. This is new behaviour (no cancel path exists). It must be designed carefully: cooperative cancellation via a `cancel_requested` flag on the run row, checked by the executor's heartbeat loop.

## Rewrite-versus-refactor conclusion

**Rewrite.** The structural problems (Hypotheses 1, 3, 4, 5, 7) are not fixable by incremental extraction because they are *the dependency direction itself*. Every "fix" that keeps `ProjectStore` as the central object preserves the problem. The deepening programme proved this: it improved seams (manifest, scoring IR, modules) but did not change the direction. A compatibility refactor would require maintaining `ProjectStore` as a facade over the new UoW for months, across 60 files, while nodes still reach through it — a wrapper that defeats the contract.

The cost of a clean rewrite is: one new schema (no migration), one new API (no external consumers), one regenerated frontend client, ~51 node ports (mechanical: replace `context.store` with `context.inputs/outputs`), ~12 use cases (mechanical: move business rules from services), ~11 SQLite adapters (mechanical: move SQL from repos), one artifact store, one bootstrap. The cost of a compatibility refactor is: all of the above *plus* dual schemas, dual APIs, transitional contexts, wrappers, and months of coexistence.

**Clean cut.**

## Resolved implementation decisions (D3–D18 confirmed 2026-07-21)

All 16 implementation decisions are now Accepted. Each was resolved against concrete repository evidence gathered during validation. No batch agent should need to make or stall on these.

1. ~~ADR-0002 supersession~~ **Resolved: ADR-0014 supersedes ADR-0002.**
2. **`runs` table dead states: DROP `queued_at`, `CREATED`, `QUEUED`.** Evidence: `RunRepository.create` sets `status="running"` directly; `_VALID_TRANSITIONS` defines `created→queued`, `queued→running` but neither is exercised; `queued_at` column never written. The clean schema (03-persistence-and-artifacts.md) drops them and adds `CHECK (status IN ('running','succeeded','failed','cancelled','interrupted'))`. *Affects: Batch 02.*
3. **`RunStepStatus.PENDING`/`SKIPPED`: DROP.** Evidence: grep confirms neither is written by any code path. Re-add when scoped execution is designed (future). Clean schema adds `CHECK (status IN ('running','succeeded','failed'))`. *Affects: Batch 02.*
4. **Cancellation: COOPERATIVE only.** Evidence: no cancel path exists; preemptive thread interrupt is unsafe with sklearn C extensions. `runs.cancel_requested INTEGER NOT NULL DEFAULT 0` column; `ExecuteRun` checks between steps; `POST /runs/{run_id}/cancel` sets the flag. *Affects: Batch 05.*
5. **Artifact sharding: `objects/{hash[:2]}/{hash}/`.** Evidence: content-addressed store will hold thousands of files per project; flat dir is a filesystem performance hazard. Shard by first two hex chars. *Affects: Batch 02.*
6. **Manifest path: `manifests/runs/{run_id}.json`.** Evidence: current `exports/manifest-{run_id}/manifest.json` mixes canonical manifests with user-facing exports. Canonical path separates them. `RunManifestPublisherPort` writes to `manifests/`; exports stay under `exports/`. *Affects: Batch 02, 05.*
7. **`X-Project-Path` AND `X-Project-Id` headers: REMOVE BOTH.** Evidence: frontend `client.ts:269-271` only ever sends `X-Project-Id`; `X-Project-Path` is dev-only (`CARDRE_ALLOW_RAW_PROJECT_PATH=1`) and never sent by the TS client. Path param `{project_id}` is authoritative. *Affects: Batch 01.*
8. **`cardre/engine/` disposition: MOVE `binning/` to `domain/binning/`; MOVE `optbinning_adapter.py` to `nodes/build/`.** Evidence: `cardre/engine/binning/` contains `woe.py`, `definition.py`, `diagnostics.py`, `capabilities.py`, `optbinning_adapter.py`. The first four are pure (no I/O, no store) — they're domain logic imported by 10 sites (services, evidence, nodes, readiness). They belong in `domain/binning/`. `optbinning_adapter.py` imports the `optbinning` optional dep and is a node-support module → `nodes/build/_optbinning_adapter.py` (already co-located with `_optbinning.py`). Delete `cardre/engine/` after the move. *Affects: Batch 03.*
9. **`cardre/workflows/` disposition: MOVE `scorecard.py` to `domain/plans/scorecard_pathway.py`.** Evidence: `cardre/workflows/scorecard.py` provides `build_canonical_scorecard_steps` + `canonical_scorecard_step_ids` — the canonical 13-step scorecard build graph definition. It's imported by 5 tests. It's domain knowledge (the canonical pathway), not infrastructure. Move to `domain/plans/`; delete `cardre/workflows/`. *Affects: Batch 03.*
10. **Governance default: KEEP opt-in (`CARDRE_GOVERNANCE`).** Evidence: current opt-in; README roadmap says "Governance graduation — move governance from opt-in to default-on once the workflow is proven in real use." Graduate in a follow-up after the rewrite proves the workflow. `Settings.governance_enabled`. *Affects: Batch 01.*
11. **Coverage floor: KEEP 60% per-batch.** Evidence: `CONTRIBUTING.md` enforces 60% via `make preflight` + CI. Each batch adds enough tests to stay ≥60%. Don't suspend — keeps the quality bar. *Affects: all batches.*
12. **`pr7-followup` dead `_lifecycle` forwarders: ALREADY GONE (grep confirms).** Evidence: `rg "_lifecycle" cardre/` returns hits only in `services/run_coordinator.py`, `execution/__init__.py`, `execution/worker.py` — these are `run_lifecycle` references (the run lifecycle module), not `BinDefinition._lifecycle` forwarders. No `BinDefinition` forwarders remain. The rewrite deletes `run_coordinator.py`/`execution/` anyway. *Affects: none (no action needed).*

## Decision log

| # | Decision | Status | Repo evidence | Alternatives | Reason | Consequences | Batches affected |
|---|----------|--------|---------------|--------------|--------|--------------|-----------------|
| D1 | Clean rewrite, not compatibility refactor | Accepted (ADR-0014, 2026-07-21) | Hypotheses 1,3,4,5,7,9 confirmed; ADR-0003 (no legacy); task constraints; ADR-0014 supersedes ADR-0002 | Compatibility refactor with dual schemas/APIs | Structural problems are the dependency direction; deepening programme proved symptom-only fixes insufficient | 9-batch sprint; no migration; ADR-0002 marked Superseded | All |
| D2 | Preserve domain vocabulary | Accepted (ADR-0014, 2026-07-21) | `cardre/domain/` is clean; ADR-0002 rejected competing vocabulary; ADR-0014 carries forward ADR-0002's preserved design commitments | New vocabulary | Avoids gratuitous churn; preserves validated behaviour; honours ADR-0002 intent via ADR-0014 | `StepSpec`/`RunStep`/`PlanVersion`/`Run`/`RunStatus`/`RunScope`/evidence kinds/canonical step IDs unchanged | All |
| D3 | Package layout `cardre/{domain,application,nodes,adapters,api,bootstrap}/` | Accepted (2026-07-21) | Current `cardre/` has domain/nodes/services/store/execution/api/_evidence/reporting/readiness/modeling; no clean dependency direction | Keep services/ as application layer | Hexagonal direction requires ports + adapters; "services" is ambiguous | Move + split packages; see 01-target-architecture.md | All |
| D4 | Split `_evidence/` → `domain/evidence/` (kinds, schemas) + `adapters/evidence/` (profiles, parsers) | Accepted (2026-07-21) | `_evidence/kinds.py` + `schemas.py` are pure vocabulary; `profiles.py` + `adapters/` do I/O (parse bytes) | Keep `_evidence/` together | Domain must be pure; parsers are I/O | Two packages; adapters import domain | 01, 03 |
| D5 | Unit-of-work owns connection + transaction; no `ProjectStore` | Accepted (2026-07-21) | `ProjectStore` combines 9 responsibilities (H1); repos commit via autocommit; transactions span computation (H6) | Keep `ProjectStore` as facade | Atomicity requires single transaction owner | All persistence behind UoW port; repos become query objects taking `conn` | 02, 03, 04 |
| D6 | Project registry behind `ProjectRegistryPort`; not a singleton | Accepted (2026-07-21) | `project_registry.py` is file-based, constructed per-request from env | Module-level singleton | Composition root owns construction; no env access in handlers | `adapters/system/ProjectRegistry` | 01 |
| D7 | Artifact addressing: `objects/{hash[:2]}/{hash}/` sharded, physical hash = path, logical hash = metadata | Accepted (2026-07-21) | Current `artifacts/{hash[:16]}-{stem}.{ext}`; dual hashing already exists; non-atomic publication (H7); sharding needed for FS perf at scale | Single hash; flat dir | Sharding for FS perf; logical hash preserved for reproducibility | `StagedArtifactWriter` port; staging dir; atomic publish inside UoW | 02 |
| D8 | Publication protocol: stage → validate → publish (fs) → register (db) → lineage (db) all in one UoW | Accepted (2026-07-21) | Current 8-step lifecycle with partial-failure states (H7) | Keep separate | Atomicity | One UoW per step finalization | 04, 05 |
| D9 | Node I/O: `NodeContext` with `inputs`, `outputs`, `params`, `runtime`, `logger` only; no store | Accepted (2026-07-21) | `ExecutionContext.store` is the primary inward leak (H3, H4) | Wrapper context exposing store | Contract unenforceable with store access | 51 nodes ported; `OutputPublisher` validates declared roles/kinds | 03, 04 |
| D10 | Execution state machine: submitted→running→{succeeded|failed|cancelled|interrupted}; drop created/queued/pending/skipped | Accepted (2026-07-21) | Dead states never written (H8); `RunRepository.create` sets "running" directly; `_VALID_TRANSITIONS` created/queued never exercised | Keep dead states | Simplicity | New `runs` schema; `RunLifecycle` rewritten | 02, 05 |
| D11 | API identity: path param `{project_id}` only; remove `X-Project-Id` AND `X-Project-Path` headers | Accepted (2026-07-21) | Frontend `client.ts:269-271` only ever sends `X-Project-Id`; `X-Project-Path` is dev-only and never sent by TS client | Keep dev-only `X-Project-Path` | No real consumer; security; single source of truth | `api/dependencies.py` simplified | 01 |
| D12 | Frontend client regenerated from new OpenAPI; openapi-fetch + existing transport preserved | Accepted (2026-07-21) | PR3 (merged) established openapi-fetch + `ApiError` transport | Handwritten client | Drift; single source of truth | Regenerate `openapi.json`/`schema.d.ts` once | 01, 07 |
| D13 | Architecture enforcement: `import-linter` + AST checks + forbidden symbol tests | Accepted (2026-07-21) | Current bespoke AST checks work but are scattered; no `import-linter` | Keep bespoke only | Centralized, blocking, CI-enforced | `importlinter` dep added; `.importlinter` config; new tests | 01, 07 |
| D14 | Cancellation: cooperative via `cancel_requested` flag + heartbeat check | Accepted (2026-07-21) | No cancel path exists (H8); preemptive thread interrupt unsafe with sklearn C extensions | Preemptive thread interrupt | Unsafe with C extensions | `POST /runs/{run_id}/cancel` sets flag; executor checks between steps | 05 |
| D15 | Manifest canonical path: `manifests/runs/{run_id}.json` | Accepted (2026-07-21) | Current `exports/manifest-{run_id}/manifest.json` mixes canonical manifests with user-facing exports | Keep current | Canonical, queryable; separates from exports | `RunManifestPublisher` port | 02, 05 |
| D16 | Governance stays opt-in (`CARDRE_GOVERNANCE`) for now | Accepted (2026-07-21) | Current opt-in; README roadmap says "Governance graduation — move to default-on once proven in real use" | Default-on now | Graduate after rewrite proves workflow | `Settings.governance_enabled` | 01 |
| D17 | Coverage floor 60% maintained per-batch | Accepted (2026-07-21) | `CONTRIBUTING.md` 60% floor; `make preflight` + CI enforce | Suspend during rewrite | Keeps quality bar | Each batch must add tests to stay ≥60% | All |
| D18 | No ORM; raw SQL in SQLite adapters only | Accepted (2026-07-21) | No ORM currently; raw SQL throughout store | Introduce SQLAlchemy | No demonstrated value; adds dep | `adapters/sqlite/` query objects | 02 |
| D19 | `cardre/engine/binning/` → `domain/binning/` (pure modules) + `nodes/build/_optbinning_adapter.py` (optbinning dep); `cardre/workflows/scorecard.py` → `domain/plans/scorecard_pathway.py`; delete both old packages | Accepted (2026-07-21) | `cardre/engine/binning/` has 5 modules imported by 10 sites; `woe.py`/`definition.py`/`diagnostics.py`/`capabilities.py` are pure domain; `optbinning_adapter.py` imports optional dep → node-support; `cardre/workflows/scorecard.py` provides canonical 13-step pathway (domain knowledge) imported by 5 tests | Leave in place; move piecemeal | Domain logic must be in `domain/`; node-support in `nodes/`; `cardre/engine/` + `cardre/workflows/` are ambiguous legacy names | Move in Batch 03; delete old packages | 03 |
| D20 | Dead `_lifecycle` forwarders on `BinDefinition` already gone (no action) | Accepted (2026-07-21) | `rg "_lifecycle" cardre/` returns only `run_lifecycle` references in `run_coordinator.py`/`execution/` — no `BinDefinition._lifecycle` forwarders | n/a | n/a | None — rewrite deletes `run_coordinator.py`/`execution/` anyway | none |

(Decision log continues in each master document; this is the master log.)