# PR8 — Introduce RunStatus enum and atomic transitions

**Findings:** SE1, SE2, SE3, SE4, SE5, SE7
**Batch:** F (sequential, after Batch D)
**Depends on:** PR4 (needs reuse-subsystem deleted so the executor is
simplified)
**Behaviour change:** Migration (labelled) — the observable run-status
transitions don't change, only the mechanism (string literals → enum +
transition function)

## Goal

Introduce a `RunStatus` enum and a single
`RunRepository.transition(run_id, to_status, *, expected_from=...)`
function that is the only writer of terminal statuses. Make the executor
return a typed `PlanExecutionResult` so the coordinator stops
re-querying. Delete the `to_node` executor branch. Dedup stale-recovery.
Make `refresh_comparison` atomic. Resolve `branch_id` once.

This is a **migration PR** — it changes the run-status writer from
scattered string literals to an enum + transition function. The
observable behaviour (which status a run ends in) must not change; only
the mechanism does.

## Tasks

### SE3 — `RunStatus` enum + single transition

1. Define `RunStatus(StrEnum)` in `cardre/domain/run.py`:
   ```python
   class RunStatus(StrEnum):
       PENDING = "pending"
       RUNNING = "running"
       SUCCEEDED = "succeeded"
       FAILED = "failed"
       INTERRUPTED = "interrupted"
       CANCELLED = "cancelled"
   ```
2. Add `RunRepository.transition(run_id, to_status: RunStatus, *,
   expected_from: Iterable[RunStatus] | None = None) -> bool` — the only
   writer of terminal statuses. Validates the transition.
3. Replace the 4+ `finish(run_id, "failed")` / `finish(run_id, "succeeded")`
   call sites with `transition(...)`.
4. Replace bare string comparisons (`run["status"] != "running"`,
   `status not in ("succeeded", "failed", ...)`) with `RunStatus` enum
   comparisons.

### SE4 — Executor returns `PlanExecutionResult`

1. Make `run_plan_version` return a typed `PlanExecutionResult`:
   ```python
   @dataclass
   class PlanExecutionResult:
       run_id: str
       has_failure: bool
       outputs: dict[...]
       records: dict[...]
       executed_step_ids: list[str]
       def status(self) -> RunStatus:
           return RunStatus.FAILED if self.has_failure else RunStatus.SUCCEEDED
   ```
2. Delete the dead `compute_final_status` helper.
3. In `run_coordinator.py:_execute_existing_running_run`:
   - Stop re-querying `RunStepRepository.get_for_run` twice. Use
     `result.has_failure` and `result.executed_step_ids`.
   - Call `lifecycle.finalise(status=result.status())`.
   - Delete the post-`with` re-query.
   - Replace the `execution_mode` identity-map dict with a typed
     `RunScope` enum → `execution_mode` property.

### SE2 — Delete `to_node` executor branch

1. Delete the `to_node` branch in
  `cardre/services/run_coordinator.py:298-301` (the non-atomic
  write-then-raise). Scope validation is owned at `run()` /
  `_plan_decision`.
2. Confirm `executor.run_to_node` was already deleted by PR4.

### SE1 — Stale-recovery dedup

1. Delete the dead `_maybe_recover_stale_run`
   (`run_coordinator.py:489-511`).
2. Extract the live inline sweep (444-462) into
   `_sweep_stale_running_runs(plan_version_id) -> list[str]`.
3. The sweep uses `RunRepository.transition(run_id, RunStatus.FAILED,
   expected_from=(RunStatus.RUNNING,))`.

### SE5 — `refresh_comparison` atomicity

1. In `comparison_service.py:486-542`, wrap the whole
   `refresh_comparison` in a single transaction.
2. Delete the per-iteration `UPDATE branch_comparisons SET
  latest_snapshot_id=...`. One `latest_snapshot_id` UPDATE at the end.
3. If the third challenger fails, the whole transaction rolls back.

### SE7 — `branch_id` single-read

1. Resolve `run_branch_id` once per run (cached) and pass it into
   `write_run_step`.
2. Delete the inline `SELECT branch_id FROM runs WHERE run_id = ?` at
   395-398 and the `_get_branch_for_run` helper.
3. Assert the `branch_id` kwarg and run-row `branch_id` match (make it
   an invariant).

## Acceptance criteria

- [ ] `RunStatus` enum exists in `cardre/domain/run.py`.
- [ ] `RunRepository.transition` exists and is the only writer of
  terminal statuses.
- [ ] `rg '"running"|"failed"|"succeeded"|"interrupted"|"cancelled"'
  cardre/services cardre/execution --type py -g '!test*'` — bare string
  status literals replaced by `RunStatus.X`.
- [ ] `run_plan_version` returns `PlanExecutionResult`.
- [ ] `rg 'compute_final_status' cardre/execution/executor.py` returns 0.
- [ ] `rg 'get_for_run' cardre/services/run_coordinator.py` returns ≤1.
- [ ] `rg '_maybe_recover_stale_run' cardre` returns 0.
- [ ] `rg 'to_node' cardre/execution/executor.py` returns 0.
- [ ] `rg 'with store.transaction\(\) as conn: UPDATE branch_comparisons'
  cardre/services/comparison_service.py` returns 0.
- [ ] `rg 'SELECT branch_id FROM runs WHERE run_step_id'
  cardre/execution/executor.py` returns 0.
- [ ] Run lifecycle tests pass with the new enum (no behaviour change).
- [ ] `ruff check` clean; `pytest tests/ -q` green.

## Do not

- Do not change which status a run ends in — only the mechanism. The
  migration is structure-only from the observer's perspective.
- Do not touch store/API layer (that's PR9).