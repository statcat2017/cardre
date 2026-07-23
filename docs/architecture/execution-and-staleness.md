# Execution & Staleness

## Plan Executor

The `PlanExecutor` (`cardre/execution/executor.py`) is the single execution seam.

- **Full-plan run**: executes all steps in a plan version in topological order.
- **Branch launch**: the run metadata may be branch-scoped, but step execution still uses the same execute-all-steps loop. The only branch-specific pre-execution policy that survives is a short-circuit check via `cardre/application/evidence/evidence_resolver.py`.
- **To-node execution is not supported at launch.** `RunCoordinator` rejects `run_scope="to_node"` before execution begins.

### Execution Flow

1. **Action planning**: builds a list of `_StepAction` instances. The only supported action is `execute`.
2. **Action execution**: walks actions in order and executes nodes.
3. **Finalisation**: writes the run manifest and transitions the run to its final status.

### Role Enforcement

The executor enforces role-based access for artifacts:
- Fitting nodes can only consume `train` artifacts.
- Apply/transform nodes can consume `test` and `oot` artifacts.
- Leakage rules prevent fitting nodes from accessing holdout data.

## Run Lifecycle

The `RunLifecycle` class (`cardre/execution/run_lifecycle.py`) owns generic run mechanics:

- Run creation and `run_id` resolution.
- Final status setting and manifest artifact writing, combined into one atomic `finalise_run()` call. The terminal status is written via `RunRepository.transition(run_id, RunStatus.X, expected_from=(RunStatus.RUNNING,))` — the single atomic terminal-status writer. Run statuses are modelled by the `RunStatus(StrEnum)` in `cardre/domain/run.py`; callers pass enum members, not bare strings.
- Manifest payload construction (`build_manifest_payload`) and labelling (`step_action`).

`PlanExecutor` still owns execution semantics: topological ordering, node execution, role and leakage enforcement, and run-step evidence recording. `run_plan_version` returns a typed `PlanExecutionResult` (carrying `has_failure`, `executed_step_ids`, and a `status() -> RunStatus` property) so `RunCoordinator` does not re-query `RunStepRepository.get_for_run` after execution.

### Run-step writer seam

The `cardre/execution/run_step_writer.py` module coordinates transaction-scoped persistence for ``run_steps``, ``evidence_edges``, ``evidence_artifacts``, and ``artifact_lineage`` rows. Extracted from ``PlanExecutor._record_run_step``, it keeps the executor focused on orchestration while the writer handles persistence. The writer owns raw ``INSERT`` SQL for ``run_steps`` and ``artifact_lineage``; evidence edge/artifact inserts are delegated to ``EvidenceRepository.insert_edge`` / ``insert_artifact`` to avoid duplicating the insert SQL owned by the repository layer. The writer exposes one function: ``write_run_step``. It requires an active ``IMMEDIATE`` connection and uses ``INSERT OR IGNORE`` for lineage de-duplication.

## Staleness Detection

Staleness is computed by `cardre/staleness.py`. A step is stale if its latest run does not reference the latest upstream run steps. This is a computed property, not a stored status, so it can be recomputed on the fly as plan versions change.

The staleness check compares `logical_hash` values of upstream step outputs. If an upstream step was re-run with different parameters, all downstream steps become stale regardless of their stored status.
