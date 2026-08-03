# Execution & Staleness

## Plan Executor

The `StepRunner` (`cardre/application/execution/step_runner.py`) is the single execution seam.

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

The `FinalizeRun` use case (`cardre/application/runs/finalize_run.py`) owns generic run mechanics:

- Run creation and `run_id` resolution.
- Final status setting and manifest artifact writing, combined into one atomic `finalise_run()` call. The terminal status is written via `RunRepository.transition(run_id, RunStatus.X, expected_from=(RunStatus.RUNNING,))` — the single atomic terminal-status writer. Run statuses are modelled by the `RunStatus(StrEnum)` in `cardre/domain/run.py`; callers pass enum members, not bare strings.
- Manifest payload construction (`build_manifest_payload`) and labelling (`step_action`).

`StepRunner` still owns execution semantics: topological ordering, node execution, role and leakage enforcement, and run-step evidence recording. It returns a typed `StepExecutionResult` (carrying `status`, `input_artifact_ids`, `output_artifact_ids`, and staged artifacts) so `ExecuteRun` does not re-query `RunStepRepository.get_for_run` after execution.

### Run-step writer seam

The run persistence loop in `cardre/application/runs/execute_run.py` coordinates transaction-scoped persistence for ``run_steps``, ``evidence_edges``, ``evidence_artifacts``, and ``artifact_lineage`` rows. Persistence is delegated to the repository layer (`RunStepRepo`, `EvidenceRepo`, `ArtifactRepo`); the executor focuses on orchestration.

## Staleness Detection

Staleness is computed by `cardre/application/evidence/explain_staleness.py`. A step is stale if its latest run does not reference the latest upstream run steps. This is a computed property, not a stored status, so it can be recomputed on the fly as plan versions change.

The staleness check compares `logical_hash` values of upstream step outputs. If an upstream step was re-run with different parameters, all downstream steps become stale regardless of their stored status.
