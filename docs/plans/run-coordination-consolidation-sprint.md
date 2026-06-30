# Run Coordination Consolidation Sprint

Resolve the main architectural friction in Cardre: run coordination
ownership is split across `RunService`, `RunWorker`, `run_orchestrator`,
`PlanExecutor`, `RunLifecycle`, `ProjectStore`, sidecar routes, and frontend
polling. The goal is **not** a cosmetic refactor. The goal is to make run
lifecycle behaviour explicit, testable, and consistent across sync and async
execution.

## The Problem In One Sentence

Sync runs go through `RunService._execute_sync`; async runs go through
`RunWorker` → `run_orchestrator.execute_run`. Both implement branch/to-node
short-circuit + placeholder cancellation independently, and they have
previously diverged. The worker must stop calling `run_orchestrator` as an
independent execution authority.

## Target Architecture

```
sidecar route
  -> RunService.run_plan(...)
      -> validates / creates / reuses / short-circuits run
      -> dispatches sync or async
      -> RunDispatcher.dispatch(...)
          -> RunWorker.execute(...)
              -> RunService.execute_created_run(...)
                  -> EvidencePolicyService (short-circuit decisions)
                  -> PlanExecutor (step execution)
                  -> RunLifecycle (final status + manifest)
```

- `RunService` owns **which** run is executed and the run coordination boundary.
- `RunWorker` owns **process/thread failure capture**, not execution policy.
- `PlanExecutor` owns **how** steps are executed.
- `RunLifecycle` owns **final status + manifest write**.
- `RunDispatcher` owns the **dispatch substrate** (thread / process / queue).
- `run_orchestrator.py` remains as a **compatibility shim** only — no independent policy.

## Design Principles

- **TDD.** Every behaviour change is locked by a characterization test
  *before* the refactor. RED first, GREEN second.
- **Smallest safe refactor.** Do not rewrite `PlanExecutor`. Do not touch
  step execution. Only consolidate the run coordination seam.
- **Behaviour stable unless a test proves it wrong.** The one deliberate
  behaviour change (approved by the maintainer) is: branch short-circuit
  placeholders now get a `cancelled` manifest via `finalise_run`, aligning
  with ADR 0004 atomic finalisation (to-node placeholders already do).
- **Frontend is additive only.** No response shape changes. Polling fields
  preserved: `run_id`, `plan_version_id`, `status`, `started_at`,
  `finished_at`, `step_count`, `branch_id`, `executed_step_ids`,
  `diagnostics`, `latest_error`, `heartbeat_at`, `is_stale`.
- **One PR at the end**, raised via `scripts/pr-gate.sh` per `AGENTS.md`.

## Pre-Requisites (must hold before Phase 1)

- `make preflight` passes on `main`.
- The venv is bootstrapped: `. .venv/bin/activate && pip install -e ".[sidecar,dev,test]"`.
- Branch `feat/run-coordination-consolidation` exists off `main`.
- Governance tests can run: `CARDRE_GOVERNANCE=1 pytest -m governance -q` is green on `main` (or skipped if env unset).

## Phase Sequence

| Phase | Title                                                  | Depends on | Behaviour change? |
|-------|--------------------------------------------------------|------------|-------------------|
| 1     | Characterization contract tests (RED where applicable) | —          | No (tests only)   |
| 2     | Introduce `RunService.execute_created_run`            | 1          | No (extract)      |
| 3     | Switch `RunWorker` to delegate to `RunService`        | 2          | No (seam change)  |
| 4     | Unify placeholder cancellation via `finalise_run`      | 3          | **Yes** (branch placeholders now write manifest) |
| 5     | Demote `run_orchestrator` to a pure shim              | 4          | No (shim only)    |
| 6     | Update existing tests to the new seam                  | 5          | No (test rewrites) |
| 7     | Frontend + route verification                          | 6          | No (additive)     |

Each phase has a dedicated document in `docs/plans/run-coordination/`:
- `phase-1-contract-tests.md`
- `phase-2-execute-created-run.md`
- `phase-3-worker-delegation.md`
- `phase-4-placeholder-cancellation.md`
- `phase-5-orchestrator-shim.md`
- `phase-6-test-migration.md`
- `phase-7-frontend-verification.md`

## Definition Of Done

The sprint is resolved only when **all** of the following hold:

- [ ] `RunService` owns run coordination. `RunService.execute_created_run` is the single execution entrypoint for an already-created run.
- [ ] `RunWorker._invoke_executor` calls `RunService.execute_created_run`, not `run_orchestrator.execute_run`.
- [ ] Sync (`sync=True`) and async dispatch share the same execution method (`_execute_sync` builds a `RunRequest` and calls `execute_created_run`).
- [ ] Branch, to-node, and full-plan runs share one contract in `_execute_existing_running_run`.
- [ ] Short-circuit behaviour is identical across sync and async — locked by `test_branch_short_circuit_returns_existing_run_for_sync_and_worker_paths` and the to-node parity test.
- [ ] Placeholder run cancellation is deliberate, tested, and always goes through `finalise_run` (manifest written).
- [ ] Worker exceptions still produce `RUN_WORKER_FAILED` diagnostics and a terminal run status.
- [ ] Dispatch startup failures still produce `RUN_DISPATCH_FAILED` diagnostics and a terminal run status.
- [ ] Stale heartbeat recovery has one normal policy owner (`RunService._maybe_recover_stale_run` / `_is_stale`).
- [ ] Existing sidecar route responses are preserved (field-for-field).
- [ ] Existing frontend polling assumptions still hold (verified by `npm run test -- src/api src/hooks src/components/__tests__/ProjectView`).
- [ ] `run_orchestrator.execute_run` contains no independent execution policy — it delegates to `RunService`.
- [ ] All focused tests green: `pytest tests/test_run_worker.py tests/test_run_orchestrator.py tests/test_run_lifecycle.py tests/test_run_coordination_contract.py tests/test_run_diagnostics.py tests/test_branch_consistency.py -q`.
- [ ] `make preflight` green.
- [ ] `ruff check --fix` clean.
- [ ] PR raised via `scripts/pr-gate.sh` and CI green.

## Out Of Scope (Deliberate)

- Rewriting `PlanExecutor`. It still calls `RunLifecycle.start`/`finalise`. A
  follow-up issue is filed in the sprint summary: *"Move
  `RunLifecycle.start` ownership from `PlanExecutor` to `RunService` so
  `PlanExecutor` only owns step execution."*
- Process/queue-based dispatch. `ThreadRunDispatcher` remains the default.
- Frontend refactor. Only verification.
- New progress endpoints. Additive only — none added in this sprint.
- Changing `EvidencePolicyService`. It remains the single short-circuit policy owner.

## Risks

1. **Test patch churn.** Six existing tests patch
   `run_orchestrator.execute_run` / `run_orchestrator.PlanExecutor`. Phase 6
   rewrites them to patch the new seam. This is the largest mechanical risk.
2. **Branch placeholder manifest is a behaviour change.** Locked by a new
   test in Phase 4. If a downstream consumer breaks, the fix is to relax the
   test, not to revert `finalise_run`.
3. **`_execute_sync` exception translation** (`ValueError`→`CardreError`,
   generic→`RUN_EXECUTION_FAILED`) must be preserved in
   `_execute_existing_running_run` or route error envelopes change.
4. **`run_plan` preflight placeholders.** Preflight still creates+cancels
   placeholders for async short-circuit. After consolidation, preflight must
   use the same `_cancel_placeholder_run` helper for manifest consistency.
5. **`PlanContainsUnavailableNodesError`** is raised pre-create in
   `run_plan` — must remain exactly where it is.

## How To Run This Sprint (Auto Phase Orchestrator)

This sprint is designed for the `auto-phase-orchestrator` skill. Each phase
document is self-contained and follows the same structure so a smaller LLM
can execute it without architectural guesswork:

1. **Goal** — one sentence.
2. **Files** — exact files to read, modify, create.
3. **Tests to write first (RED)** — concrete test names + assertions.
4. **Implementation** — the minimal change to pass tests.
5. **Verification commands** — exact shell commands to run.
6. **Definition of done for this phase** — checkbox list.
7. **Failure mode** — what to do if tests fail unexpectedly.

The orchestrator should:
- Run one phase at a time, in order.
- After each phase, run `ce-code-review` against the phase base.
- Fix P0/P1 findings before proceeding.
- Commit with `feat(run-coord-N): <title>`.
- Do **not** push or open a PR until Phase 7 is complete.
- At the end, run `scripts/pr-gate.sh` per `AGENTS.md`.

## Reference: Current Flow Map

```
POST /runs (sync? or default)
  sidecar/routes/runs.py:run_plan
    -> RunService.run_plan(...)
        - validate plan_version, governance gate, node availability
        - preflight short-circuit checks (async-only: branch/to_node)
        - recover stale runs (_maybe_recover_stale_run, _is_stale)
        - store.create_run(...)
        - sync: _execute_sync(...)         <-- path A
        - async: _dispatch_async -> RunDispatcher.dispatch -> RunWorker.execute
                                              -> _invoke_executor -> run_orchestrator.execute_run  <-- path B

Path A: RunService._execute_sync
  - branch: prepare_branch_evidence; short-circuit -> finish_run(cancelled) + return existing
            else: executor.run_branch(..., branch_ctx=ctx)
  - to_node: executor.run_to_node(...)
  - full: executor.run_plan_version(...)
  - if result_id != run_id: finish_run(cancelled) + return existing

Path B: run_orchestrator.execute_run
  - branch: prepare_branch_evidence; short-circuit -> finish_run(cancelled) + return existing
             else: executor.run_branch(...); _handle_short_circuit
  - to_node: executor.run_to_node(...); _handle_short_circuit
  - full: executor.run_plan_version(...); _handle_short_circuit
```

The two paths duplicate branch/to-node short-circuit handling and placeholder
cancellation. This sprint converges them into `_execute_existing_running_run`.