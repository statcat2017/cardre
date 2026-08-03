# Execution & Staleness

## Plan Executor

The `StepRunner` (`cardre/application/execution/step_runner.py`) is the single execution seam.

- **Full-plan run**: executes all steps in a plan version in topological order.
- **Branch launch**: the run metadata may be branch-scoped, but step execution still uses the same execute-all-steps loop. The only branch-specific pre-execution policy that survives is a short-circuit check via `cardre/application/evidence/evidence_resolver.py`.
- **To-node execution is not supported at launch.** `RunCoordinator` rejects `run_scope="to_node"` before execution begins.

### Execution Flow

1. **Run creation**: `SubmitRun` (`cardre/application/runs/submit_run.py`) creates the run and enqueues a dispatch.
2. **Step execution**: `ExecuteRun` (`cardre/application/runs/execute_run.py`) claims the run and iterates the plan's steps directly in topological order, calling `StepRunner.run_step` for each. There is no separate action-planning phase.
3. **Finalisation**: `FinalizeRun` transitions the run to its terminal status and publishes the canonical manifest.

### Role Enforcement

The executor enforces role-based access for artifacts:
- Fitting nodes can only consume `train` artifacts.
- Apply/transform nodes can consume `test` and `oot` artifacts.
- Leakage rules prevent fitting nodes from accessing holdout data.

## Run Lifecycle

Run creation is owned by `SubmitRun` (`cardre/application/runs/submit_run.py`),
which atomically creates the run and enqueues a durable dispatch row. The
`FinalizeRun` use case (`cardre/application/runs/finalize_run.py`) owns the
terminal side:

- Terminal status transition and manifest publication outbox record, combined
  into one transaction. The terminal status is written via
  `RunRepository.transition(run_id, RunStatus.X, expected_from=(...))`.
  `FinalizeRun.__call__` accepts a status string (e.g. `"succeeded"`,
  `"failed"`, `"cancelled"`) and converts it internally with `RunStatus(status)`.
- Manifest payload construction (`_build_manifest` / `_build_manifest_steps`)
  and self-referential hashing (`compute_manifest_hash`, `compute_pathway_hash`).

`ExecuteRun` orchestrates step execution: it claims the run, iterates the plan's
steps in topological order, calls `StepRunner.run_step` for each, and persists
run-step records, evidence edges, artifacts and lineage. `StepRunner` returns a
typed `StepExecutionResult` (carrying `status`, `input_artifact_ids`,
`output_artifact_ids`, and staged artifacts) so `ExecuteRun` does not re-query
`RunStepRepository.get_for_run` after execution.

### Run-step writer seam

The run persistence loop in `cardre/application/runs/execute_run.py` coordinates transaction-scoped persistence for ``run_steps``, ``evidence_edges``, ``evidence_artifacts``, and ``artifact_lineage`` rows. Persistence is delegated to the repository layer (`RunStepRepo`, `EvidenceRepo`, `ArtifactRepo`); the executor focuses on orchestration.

## Staleness Detection

Staleness is computed by `cardre/application/evidence/explain_staleness.py`. A step is stale if its latest run does not reference the latest upstream run steps. This is a computed property, not a stored status, so it can be recomputed on the fly as plan versions change.

The staleness check compares `logical_hash` values of upstream step outputs. If an upstream step was re-run with different parameters, all downstream steps become stale regardless of their stored status.
