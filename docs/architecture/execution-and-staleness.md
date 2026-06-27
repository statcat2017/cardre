# Execution & Staleness

## Plan Executor

The `PlanExecutor` (`cardre/executor.py`) is the single execution seam for all run modes:

- **Full-plan run**: executes all steps in a plan version in topological order.
- **Branch run**: executes only branch-owned steps, reusing evidence from the baseline for shared upstream steps. **Branch evidence policy (validation, staleness, short-circuit, shared/branch-owned evidence seeding, and parent evidence resolution) is owned by `cardre/services/evidence_policy.py` (`EvidencePolicyService`) — the single source of truth.** `PlanExecutor.run_branch` is a pure consumer: it requires a `BranchRunEvidence` prepared upstream and does not resolve policy itself. Both sync (`RunService._execute_sync`) and async (`run_orchestrator.execute_run` → `RunWorker`) paths prepare evidence via `EvidencePolicyService` and pass it as `branch_ctx`.
- **To-node run**: executes the ancestor closure of a target step, reusing non-stale upstream evidence.
- **Replay**: re-executes steps with modified parameters, reusing unchanged upstream evidence.

### Execution Flow

1. **Action planning**: builds a list of `_StepAction` instances (execute, reuse, or skip) based on the run mode and staleness.
2. **Action execution**: walks actions in order, executing nodes or reusing prior evidence.
3. **Finalisation**: writes the run manifest and transitions the run to its final status.

### Role Enforcement

The executor enforces role-based access for artifacts:
- Fitting nodes can only consume `train` artifacts.
- Apply/transform nodes can consume `test` and `oot` artifacts.
- Leakage rules prevent fitting nodes from accessing holdout data.

## Run Lifecycle

The `RunLifecycle` class (`cardre/run_lifecycle.py`) owns generic run mechanics:

- Run creation and `run_id` resolution.
- Final status setting and manifest artifact writing, combined into one atomic `finalise_run()` call.
- Manifest payload construction (`build_manifest_payload`) and labelling (`step_action`).

`PlanExecutor` still owns execution semantics: topological ordering, node execution, role and leakage enforcement, parent evidence resolution, and run-step evidence recording.

## Staleness Detection

Staleness is computed by `cardre/staleness.py`. A step is stale if its latest run does not reference the latest upstream run steps. This is a computed property, not a stored status, so it can be recomputed on the fly as plan versions change.

The staleness check compares `logical_hash` values of upstream step outputs. If an upstream step was re-run with different parameters, all downstream steps become stale regardless of their stored status.
