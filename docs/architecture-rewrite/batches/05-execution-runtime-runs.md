# Batch 05 — Execution Runtime + Runs Use Cases

```text
You are implementing one bounded batch of the Cardre architecture rewrite.

Do not redesign the wider system.

Do not broaden the scope.

Inspect the current repository before editing because earlier batches may already have changed the paths referenced here.

Preserve validated mathematical and product behaviour, but do not preserve obsolete internal APIs or compatibility layers.

Complete this batch fully, including tests and deletion of code superseded within its scope.
```

## 1. Task objective

Build the execution runtime: `SubmitRun`, `ExecuteRun`, `CancelRun`, `GetRun`, `ListRuns`, `GetRunSteps`, `GetRunEvidence` use cases; `application/execution/StepRunner` (new, builds `NodeContext`, calls `node.run`, validates outputs); `adapters/dispatch/ThreadRunDispatcher` + `SyncRunDispatcher`; `FinalizeRun` (manifest write + status transition inside one UoW); port `TechnicalManifestExportNode` (with `RunSummary` input); cooperative cancellation. The execution path is restored (un-xfailing Batch 04's tests).

## 2. Repository context

Read `docs/architecture-rewrite/04-node-and-execution-runtime.md` (execution lifecycle, state machine, failure points, cancellation, manifest lifecycle), `02-domain-and-use-cases.md` (Runs use cases), `03-persistence-and-artifacts.md` (manifest path, UoW). Existing: `cardre/services/run_coordinator.py`, `cardre/execution/executor.py`, `step_runner.py`, `run_lifecycle.py`, `run_step_writer.py`, `worker.py`, `action_planner.py`, `fingerprints.py`, `failure_classification.py`, `topology.py`, `step_graph.py`. Batches 03–05 ported nodes + persistence + artifact store. Batch 04 broke the old execution path (xfail).

## 3. Why the batch exists

Execution is the core that ties nodes + persistence + dispatch together. It must follow 03 (persistence) + 04–05 (nodes). After this batch, the run lifecycle works end-to-end through the new architecture.

## 4. Current relevant architecture

`RunCoordinator.run` (submit), `RunCoordinator.execute_created_run` (execute), `PlanExecutor.run_plan_version` (topological step loop + heartbeat + persist), `RunLifecycle.finalise` (manifest + transition), `RunWorker`/`ThreadRunDispatcher` (async), `_HeartbeatWatchdog` (separate `ProjectStore` per tick). All take `ProjectStore`. Raw SQL in `RunCoordinator._create_persisted_run` and `PlanExecutor._resolve_run_branch_id`.

## 5. Target architecture after the batch

- `application/runs/submit_run.py:SubmitRun` — takes `uow_factory`, `plan_repo_port`, `run_repo_port`, `dispatcher`, `evidence_reader`. `__call__(command)` validates (version committed, governance, no concurrent run, branch evidence policy), sweeps stale, inserts run, dispatches (sync or async). No raw SQL; uses `uow.runs.create(...)`.
- `application/runs/execute_run.py:ExecuteRun` — takes `uow_factory`, `node_catalogue`, `step_runner`, `dispatcher`. `__call__(command)` loads run + version, validates topology + availability, runs steps via `StepRunner`, finalizes via `FinalizeRun`.
- `application/runs/cancel_run.py:CancelRun` — `__call__(command)` sets `cancel_requested=1` via `uow.runs.set_cancel_requested`.
- `application/runs/get_run.py`, `list_runs.py`, `get_run_steps.py`, `get_run_evidence.py` — read-only use cases via `uow`.
- `application/execution/step_runner.py:StepRunner` — takes `node_catalogue`, `artifact_store`, `evidence_reader`. `run_step(plan_version_id, run_id, spec, step_outputs, run_step_records, cancel_requested) -> StepExecutionResult`. Builds `StepInputCollection` + `StagingOutputPublisher`, constructs `NodeContext`, calls `node.run(context)`, validates declared outputs produced (required roles present), builds fingerprint (preserved from `execution/fingerprints.py`), returns `StepExecutionResult` with `staged_artifacts`. Does NOT persist (ExecuteRun does finalization).
- `application/execution/topology.py`, `step_graph.py`, `action_planner.py`, `fingerprints.py`, `failure_classification.py` — moved from `cardre/execution/` (pure; preserve logic).
- `application/runs/finalize_run.py:FinalizeRun` — takes `uow_factory`, `manifest_publisher`. `__call__(run_id, status, diagnostic)` opens UoW, writes manifest (atomic temp+replace to `manifests/runs/{run_id}.json`), `uow.runs.transition(run_id, status, expected_from=("running",))`, commits. On transition failure: re-read status, rewrite manifest, raise `RUN_ALREADY_FINALISED`.
- `application/ports/manifest_publisher.py:ManifestPublisherPort` Protocol (`publish(run_id, payload) -> Path`).
- `application/ports/run_dispatcher.py:RunDispatcherPort` Protocol (`dispatch(request)`, `get_status(run_id)`, `shutdown()`).
- `adapters/dispatch/thread_dispatcher.py:ThreadRunDispatcher` — ported from `execution/worker.py`; takes `uow_factory` + `execute_run` callable (not `project_path`). Worker opens UoW via factory, calls `execute_run(ExecuteRunCommand(run_id))`.
- `adapters/dispatch/sync_dispatcher.py:SyncRunDispatcher`.
- `application/execution/heartbeat.py:heartbeat(uow, run_id)` — `uow.runs.heartbeat(run_id)` (trivial; no separate `ProjectStore`).
- `TechnicalManifestExportNode` ported with a `manifest` input role: `ExecuteRun` produces a `RunSummary` dataclass (run_id, plan_version_id, steps with their outputs) and stages it as an artifact (kind `technical_manifest_input` or similar); the node reads it from `context.inputs.by_role("manifest")`. Alternatively, simpler: `ExecuteRun` passes the run's step outputs to the node via the normal `input_artifacts` mechanism (the node's parents are all prior steps; their outputs are in `step_outputs`). **Recommendation: keep the node reading from declared inputs (its parent steps' outputs); `TechnicalManifestExportNode` already declares `input_roles=["definition","report"]` — expand to include all upstream outputs it needs. The current implementation reads `RunStepRepository.get_for_run(run_id)` to iterate all steps; replace by having `ExecuteRun` pass the accumulated `step_outputs` dict to the node via a `RunSummary` input artifact. This is a design decision — implement the `RunSummary` approach.**
- Old `cardre/execution/executor.py`, `step_runner.py`, `run_lifecycle.py`, `run_step_writer.py`, `worker.py`, `action_planner.py`, `fingerprints.py`, `failure_classification.py`, `topology.py`, `step_graph.py` — moved/rewritten into `application/execution/` + `adapters/dispatch/`. Delete the old `cardre/execution/` package.
- Old `cardre/services/run_coordinator.py` — deleted (replaced by use cases).
- Execution-path tests un-xfailed and updated for the new path.

## 6. Exact scope

- Write `application/runs/submit_run.py`, `execute_run.py`, `cancel_run.py`, `get_run.py`, `list_runs.py`, `get_run_steps.py`, `get_run_evidence.py`.
- Write `application/execution/step_runner.py` (new — no store), `topology.py` (moved), `step_graph.py` (moved), `action_planner.py` (moved), `fingerprints.py` (moved), `failure_classification.py` (moved), `heartbeat.py` (new trivial).
- Write `application/runs/finalize_run.py`.
- Write `application/ports/manifest_publisher.py`, `run_dispatcher.py`.
- Write `adapters/dispatch/thread_dispatcher.py`, `sync_dispatcher.py`.
- Port `TechnicalManifestExportNode` (the deferred one from Batch 04).
- Delete `cardre/execution/` package (all moved/rewritten).
- Delete `cardre/services/run_coordinator.py`.
- Un-xfail execution-path tests; rewrite for new use cases.
- `RunSummary` dataclass in `domain/runs.py` or `application/execution/`.

## 7. Files to inspect first

- `cardre/services/run_coordinator.py` (submit logic — port to `SubmitRun`).
- `cardre/execution/executor.py` (execute logic — port to `ExecuteRun`).
- `cardre/execution/step_runner.py` (step run — port to new `StepRunner`).
- `cardre/execution/run_lifecycle.py` (manifest + transition — port to `FinalizeRun`).
- `cardre/execution/run_step_writer.py` (persistence — inline into `ExecuteRun` finalization via `uow.run_steps`/`uow.evidence`/`uow.artifacts`/`uow.lineage`).
- `cardre/execution/worker.py` (dispatch — port to `adapters/dispatch/`).
- `cardre/execution/topology.py`, `step_graph.py`, `action_planner.py`, `fingerprints.py`, `failure_classification.py` (move).
- `tests/test_run_coordinator.py`, `test_executor.py`, `test_run_lifecycle.py`, `test_worker_lifecycle.py`, `test_run_dispatch.py`, `test_run_audit_integrity.py`, `test_executor_characterization.py` (update).
- `cardre/nodes/build/export.py:TechnicalManifestExportNode` (port with RunSummary).

## 8. Files likely to change

- `cardre/application/runs/` (new package with all run use cases)
- `cardre/application/execution/` (new package with step_runner, topology, etc.)
- `cardre/application/ports/manifest_publisher.py`, `run_dispatcher.py` (new)
- `cardre/adapters/dispatch/` (new package)
- `cardre/nodes/build/export.py` (port `TechnicalManifestExportNode`)
- `cardre/domain/runs.py` (add `RunSummary` if placed here)
- Execution-path tests (un-xfail, rewrite)
- `cardre/execution/` (delete)
- `cardre/services/run_coordinator.py` (delete)

## 9. Files likely to create

See "Files likely to change" — the `new` entries.

## 10. Files likely to delete

- `cardre/execution/executor.py`, `step_runner.py`, `run_lifecycle.py`, `run_step_writer.py`, `worker.py`, `action_planner.py`, `fingerprints.py`, `failure_classification.py`, `topology.py`, `step_graph.py`, `context.py` (already gone in 05), `__init__.py`.
- `cardre/services/run_coordinator.py`.
- `cardre/services/__init__.py` re-exports of `RunCoordinator`/`RunSummary`.

## 11. Required implementation sequence

1. Move `cardre/execution/topology.py` → `application/execution/topology.py` (content unchanged). Same for `step_graph.py`, `action_planner.py`, `fingerprints.py`, `failure_classification.py`. Update imports.
2. Write `application/ports/manifest_publisher.py:ManifestPublisherPort` (`publish(run_id, payload: JsonDict) -> Path`).
3. Write `application/ports/run_dispatcher.py:RunDispatcherPort` (`dispatch(request: RunRequest)`, `get_status(run_id) -> str`, `shutdown()`). `RunRequest` moved to `application/runs/` or `domain/runs.py`.
4. Write `application/execution/heartbeat.py:heartbeat(uow, run_id)` — `uow.runs.heartbeat(run_id)`.
5. Write `application/execution/step_runner.py:StepRunner` — `__init__(node_catalogue, artifact_store_factory, evidence_reader_factory)`. `run_step(plan_version_id, run_id, spec, step_outputs, run_step_records, cancel_requested) -> StepExecutionResult`:
   - Resolve inputs from parent step outputs (preserved `_resolve_inputs`).
   - Instantiate node via catalogue.
   - Normalize + validate params (preserved).
   - Filter input artifacts by `node.__definition__.input_contract` (preserved `_filter_input_artifacts` extended for `ArtifactRoleSpec`).
   - Check required input roles present (NEW).
   - Build `StepInputCollection(input_artifacts, EvidenceReader(...))`.
   - Build `StagingOutputPublisher(node.__definition__.output_contract, artifact_store, step_id, run_id)`.
   - Build `NodeContext(...)`.
   - `node.run(context) -> NodeResult`.
   - Validate required output roles present in `node_result.staged_artifacts` (NEW).
   - Build fingerprint (preserved `build_execution_fingerprint`).
   - Return `StepExecutionResult(staged_artifacts=node_result.staged_artifacts, ...)`.
   - On `NodeFailedWithArtifacts`: capture staged artifacts, classify failure, return FAILED result with staged artifacts (preserved behaviour).
   - On other `Exception`: classify, return FAILED with empty staged.
6. Write `application/runs/execute_run.py:ExecuteRun` — `__init__(uow_factory, node_catalogue, step_runner, manifest_publisher)`. `__call__(command: ExecuteRunCommand) -> Run`:
   - Open read-only UoW; load run row; assert status="running"; load plan_version + steps.
   - Validate topology (`application/execution/topology.validate_topology`).
   - Probe availability for each step (`node_catalogue.availability`); raise `PlanContainsUnavailableNodesError` if any unavailable.
   - Resolve `run_branch_id` via `uow.runs.get(run_id)["branch_id"]` (no raw SQL).
   - Plan actions (`action_planner.plan_full_plan`).
   - For each action: check `cancel_requested` (read from `uow.runs.get(run_id)` or pass via command); if set, finalize CANCELLED, break. Heartbeat. `StepRunner.run_step(...)`. Open UoW (IMMEDIATE) for finalization: for each staged, `artifact_store.publish(staged)` + `uow.artifacts.register(...)` + `uow.lineage.register_lineage(...,"output")`; `uow.run_steps.insert(run_step)`; `uow.evidence.insert_edges(...)` + `insert_artifacts(...)`; `uow.runs.heartbeat(run_id)`; commit. Resolve output artifacts for next step. If step failed, break.
   - Build `RunSummary` (run_id, plan_version_id, steps with outputs) and stage as artifact (kind `technical_manifest_input`); publish + register so `TechnicalManifestExportNode` can read it. (Or: if `TechnicalManifestExportNode` is in the plan, its parent is the last build step; pass outputs through. Simplest: `ExecuteRun` doesn't special-case; the node's parents are its declared inputs; the plan author connects them. But `TechnicalManifestExportNode` currently reads ALL run_steps, not just declared parents. The `RunSummary` approach is cleaner. Implement it.)
   - `FinalizeRun(run_id, status, diagnostic)`.
7. Write `application/runs/finalize_run.py:FinalizeRun` — `__init__(uow_factory, manifest_publisher)`. `__call__(run_id, status, diagnostic=None)`:
   - Build manifest payload (preserved `build_manifest_payload`; moved to `application/execution/manifest.py` or inline).
   - `manifest_publisher.publish(run_id, payload)` (atomic temp+replace to `manifests/runs/{run_id}.json`).
   - Open UoW: if diagnostic, `uow.runs.append_diagnostic(run_id, diagnostic)`; `uow.runs.transition(run_id, status, expected_from=("running",))`; commit.
   - On transition failure (compare-and-set lost): re-read status, rewrite manifest with actual status, raise `RUN_ALREADY_FINALISED` (preserved).
8. Write `application/runs/submit_run.py:SubmitRun` — `__init__(uow_factory, dispatcher, evidence_reader)`. `__call__(command)`:
   - Open read-only UoW; `uow.plans.get_version(plan_version_id)`; assert committed; assert governance if branch scope.
   - `_plan_decision` (branch evidence policy via `evidence_reader` — preserved logic, ported from `RunCoordinator._check_branch_evidence_policy` using `EvidenceReaderPort`).
   - Open write UoW: `_sweep_stale_running_runs` (for each stale, `FinalizeRun(..., INTERRUPTED, diagnostic)`); check concurrent (preserved logic via `uow.runs.list_for_plan_version`); `uow.runs.create(...)`; commit.
   - If sync: call `ExecuteRun(ExecuteRunCommand(run_id))` directly.
   - If async: `dispatcher.dispatch(RunRequest(run_id, plan_version_id, ...))`; on dispatch failure, `FinalizeRun(..., FAILED, diagnostic=RUN_DISPATCH_FAILED)`.
9. Write `application/runs/cancel_run.py:CancelRun` — `__call__(command)`: open UoW, `uow.runs.set_cancel_requested(run_id)`, commit; return run.
10. Write `application/runs/get_run.py`, `list_runs.py`, `get_run_steps.py`, `get_run_evidence.py` — read-only via UoW.
11. Write `adapters/dispatch/thread_dispatcher.py:ThreadRunDispatcher` — `__init__(execute_run: ExecuteRun, uow_factory, max_workers=1)`. `dispatch(request)`: spawn thread calling `execute_run(ExecuteRunCommand(request.run_id))` (worker opens its own UoW via factory inside `ExecuteRun`). Preserve `get_status`, `shutdown`, duplicate-reject, max_workers (ported from `execution/worker.py:ThreadRunDispatcher`).
12. Write `adapters/dispatch/sync_dispatcher.py:SyncRunDispatcher`.
13. Port `TechnicalManifestExportNode`: `input_roles = ["manifest"]` (the `RunSummary` artifact produced by `ExecuteRun`); `run(context)`: read `RunSummary` from `context.inputs.by_role("manifest")`, assemble technical manifest dict, `context.outputs.publish_json(role="manifest", kind=TECHNICAL_MANIFEST_INDEX, payload=...)`.
14. Delete `cardre/execution/` package, `cardre/services/run_coordinator.py`.
15. Un-xfail execution-path tests; rewrite for `SubmitRun`/`ExecuteRun`/etc.
16. Update `test_run_audit_integrity.py` to use new manifest path + UoW.
17. Run all tests.

## 12. Interfaces and invariants

- `ExecuteRun` opens one UoW per step finalization (not during computation).
- `FinalizeRun` writes manifest + transition in one UoW (D8).
- `cancel_requested` checked between steps (D14).
- `StepRunner` does not persist; `ExecuteRun` does.
- `ThreadRunDispatcher` worker calls `ExecuteRun` (not `RunCoordinator`).
- Manifest path `manifests/runs/{run_id}.json` (D15).
- No `ProjectStore` anywhere in the new path.

## 13. Behaviour to preserve

- `test_run_coordinator.py`, `test_executor.py`, `test_run_lifecycle.py`, `test_worker_lifecycle.py`, `test_run_dispatch.py`, `test_run_audit_integrity.py`, `test_executor_characterization.py`, `test_run_plan_decision.py`, `test_run_step_writer.py`, `test_action_planning.py`, `test_run_lifecycle_errors.py`, `test_run_coordinator_edge_cases.py`, `test_run_repo_request_fields.py` — preserve behavioural assertions; update imports.
- Stale-run sweep → INTERRUPTED (preserved).
- Manifest hash self-consistency (preserved).
- Compare-and-set transition (preserved).
- `NodeFailedWithArtifacts` partial artifacts recorded (preserved).

## 14. Intentional breaking changes

- `RunCoordinator` → `SubmitRun` + `ExecuteRun` + `CancelRun`.
- `PlanExecutor` → `ExecuteRun`.
- `RunLifecycle` → `FinalizeRun`.
- `_HeartbeatWatchdog` → simple `heartbeat(uow, run_id)` between steps (no separate thread; the executor is single-threaded per run).
- `RunWorker` → `ThreadRunDispatcher` worker calling `ExecuteRun`.
- `TechnicalManifestExportNode` now reads `RunSummary` input artifact (not all run_steps directly).
- Manifest path `manifests/runs/{run_id}.json` (was `exports/manifest-{run_id}/manifest.json`).

## 15. Tests to add or update

- `tests/application/runs/test_submit_run.py`, `test_execute_run.py`, `test_cancel_run.py`, `test_finalize_run.py`, `test_get_run.py`, `test_list_runs.py`, `test_get_run_steps.py`, `test_get_run_evidence.py`.
- `tests/application/execution/test_step_runner.py` (build NodeContext, run node, validate outputs).
- `tests/adapters/dispatch/test_thread_dispatcher.py`, `test_sync_dispatcher.py`.
- `tests/ports/test_run_dispatcher_contract.py` (in-memory fake + ThreadRunDispatcher + SyncRunDispatcher).
- `tests/ports/test_manifest_publisher_contract.py`.
- Un-xfail + update `test_run_coordinator.py` → `test_submit_run.py` etc.
- `test_run_audit_integrity.py` updated for new manifest path.
- `test_executor_characterization.py` → `test_execute_run_characterization.py`.
- `test_golden_report_bundle.py` — if `TechnicalManifestExportNode` output shape changed, regenerate golden with `--update-golden` after confirming (R12).

## 16. Commands to run

```bash
. .venv/bin/activate
ruff check --fix
python3 -m importlinter --config .importlinter
make preflight
python3 -m pytest tests/application/runs tests/application/execution tests/adapters/dispatch tests/ports -q
python3 -m pytest tests/test_run_audit_integrity.py tests/test_scoring_export_parity.py -q
python3 -m pytest tests/ -q
```

## 17. Acceptance criteria

- `SubmitRun` + `ExecuteRun` work end-to-end (sync): create project → plan → commit → submit run → run succeeds → artifacts produced → manifest written.
- `CancelRun` sets `cancel_requested`; `ExecuteRun` finalizes CANCELLED.
- `test_run_audit_integrity.py` passes (manifest hash, evidence completeness).
- `test_scoring_export_parity.py` passes (full pathway including `TechnicalManifestExportNode`).
- No `ProjectStore` in `application/`, `adapters/dispatch/`.
- `cardre/execution/` deleted; `cardre/services/run_coordinator.py` deleted.
- `make arch-check` passes.
- `make preflight` passes (coverage ≥60%).
- Execution-path tests un-xfailed and passing.

## 18. Architecture rules

- `application/runs/**` imports only `domain/`, `application/ports/`, `application/execution/`.
- `application/execution/**` imports only `domain/`, `application/ports/`, `nodes.contracts` (for `NodeContext`/`NodeResult` types).
- `adapters/dispatch/**` imports only `application/ports/`, `domain/`, stdlib, `threading`.
- No `ProjectStore`, no `sqlite3`, no `os.environ` in `application/`.

## 19. Prohibited shortcuts

- Do not re-introduce `ProjectStore` or `_HeartbeatWatchdog` with separate connections (use UoW).
- Do not write manifest outside the finalization UoW.
- Do not skip the `cancel_requested` check.
- Do not let `StepRunner` persist (only `ExecuteRun`).
- Do not change manifest hash algorithm.
- Do not leave execution-path tests xfailed.

## 20. Explicit out-of-scope work

- Plans/evidence/governance/reporting use cases (Batch 06).
- Routes (Batch 07).
- Deleting old services other than `run_coordinator.py` (Batch 06/09).
- `cardre/services/staleness_service.py`, `evidence_locator.py` (Batch 06).
- Frontend (Batch 07).

## 21. Expected final report format

1. End-to-end run result (sync): run succeeded, artifacts count, manifest path.
2. Cancel run result.
3. `test_run_audit_integrity.py` + `test_scoring_export_parity.py` results.
4. Grep confirming no `ProjectStore` in `application/`/`adapters/dispatch/`.
5. `make preflight` + `make arch-check` summary.
6. Files created/deleted.

## Identity

- Sequence: 05
- Title: Execution Runtime + Runs Use Cases
- Architectural objective: restore execution through the new architecture; manifest inside UoW; cooperative cancel
- Reason for position: follows 03 (persistence) + 04–05 (nodes); precedes 07 (other use cases) + 08 (routes)
- Difficulty: very high — execution is the core integration point

## Scope summary

- Created: `application/runs/*`, `application/execution/*`, `adapters/dispatch/*`, `application/ports/manifest_publisher.py`, `run_dispatcher.py`, ported `TechnicalManifestExportNode`, tests.
- Changed: `cardre/nodes/build/export.py`, execution tests.
- Deleted: `cardre/execution/` package, `cardre/services/run_coordinator.py`.
- Behaviour preserved: run lifecycle, manifest hash, stale sweep, parity.
- Behaviour changed: manifest path, cancel via flag, `TechnicalManifestExportNode` input source.
- Exclusions: plans/evidence/governance/reporting use cases (07), routes (08).

## Design decisions

- D8 (publication inside UoW), D10 (state machine), D14 (cooperative cancel), D15 (manifest path), D9 (NodeContext).

## Tests

See §15.

## Acceptance criteria

See §17.

## Risks

- R2 (parity including `TechnicalManifestExportNode`), R4 (manifest atomicity), R7 (cancel never takes effect), R8 (stale recovery), R12 (golden report bundle regen), R14 (dispatcher thread regression).

## Agent boundaries

Do not modify: `cardre/services/` (other than `run_coordinator.py` deletion), `cardre/store/`, `cardre/api/**`, `cardre/nodes/**` (except `TechnicalManifestExportNode`), `cardre/domain/`, `cardre/config.py`, frontend, sidecar.

## Dependencies

- Required earlier: Batch 02 (persistence), Batch 04 (nodes ported).
- Optional parallel: Batch 06 use cases can be designed in parallel but need 06 for `SubmitRun`/`ExecuteRun` patterns.
- Open PRs: none.

## Estimated reasoning difficulty

very high.