# Phase 3 — Switch `RunWorker` to delegate to `RunService`

**Sprint:** `docs/plans/run-coordination-consolidation-sprint.md`
**Phase goal:** Change `RunWorker._invoke_executor` to call `RunService.execute_created_run` instead of `run_orchestrator.execute_run`. This is the seam change. No behaviour change for successful runs; worker failure diagnostics now come from the new seam.

## Files

### Read first (do not edit)
- `cardre/services/run_worker.py` — `RunWorker._invoke_executor` (lines 99-111), `RunWorker.execute`, `RunWorker._record_failure`, `WORKER_FAILED_CODE`.
- `cardre/services/run_service.py` — `execute_created_run` (added in Phase 2).
- `cardre/store/project_store.py` — `ProjectStore(root)` constructor.
- `tests/test_run_worker.py` — five tests that monkeypatch `cardre.services.run_orchestrator.execute_run`.
- `tests/test_run_coordination_contract.py` — tests 2, 3 (xfail) must turn GREEN.

### Modify
- `cardre/services/run_worker.py`
- `tests/test_run_coordination_contract.py` (remove xfails for tests 2, 3)

## Tests to write first (RED → GREEN)

The Phase-1 xfails `test_worker_delegates_to_run_service_execute_created_run`
and `test_worker_failure_records_diagnostic_and_fails_run` must now turn
GREEN. Remove their `@pytest.mark.xfail(reason="lands in phase 3")` markers.

## Implementation

### Step 1 — Rewrite `RunWorker._invoke_executor`

In `cardre/services/run_worker.py`:

Replace the body of `_invoke_executor` (currently lines 99-111):

```python
@staticmethod
def _invoke_executor(store: ProjectStore, request: RunRequest) -> None:
    from cardre.services.run_service import RunService

    RunService(store).execute_created_run(request)
```

Note: `RunService.__init__(store, dispatcher=None)` defaults to
`ThreadRunDispatcher`, which is irrelevant here because `execute_created_run`
does not dispatch — it executes synchronously in the current thread. The
dispatcher field is only used by `run_plan`'s async path.

### Step 2 — Update the class docstring

The `RunWorker` docstring currently says it "delegates actual step execution
to `cardre.services.run_orchestrator.execute_run`". Update it to say it
delegates to `RunService.execute_created_run`.

### Step 3 — Remove xfails

In `tests/test_run_coordination_contract.py`, remove the
`@pytest.mark.xfail(reason="lands in phase 3")` markers from tests 2 and 3.

## Verification commands

```bash
. .venv/bin/activate
ruff check --fix cardre/services/run_worker.py tests/test_run_coordination_contract.py
pytest tests/test_run_worker.py tests/test_run_orchestrator.py tests/test_run_lifecycle.py \
       tests/test_run_coordination_contract.py tests/test_run_diagnostics.py \
       tests/test_branch_consistency.py -q
CARDRE_GOVERNANCE=1 pytest tests/test_run_coordination_contract.py tests/test_run_orchestrator.py -q
```

### Expected fallout

The five tests in `tests/test_run_worker.py` that patch
`cardre.services.run_orchestrator.execute_run` will now **fail** because the
worker no longer calls that function:

- `TestRunWorkerFailure.test_worker_exception_records_diagnostic_and_fails_run`
- `TestRunWorkerFailure.test_worker_heartbeats_before_execution`
- `TestRunWorkerFailure.test_worker_failure_does_not_leave_run_running`
- `TestThreadRunDispatcher.test_dispatch_success_starts_named_thread`
- `TestSyncRunDispatcher.test_sync_dispatcher_runs_worker_inline`
- `TestSyncRunDispatcher.test_sync_dispatcher_swallows_worker_exception`
- `TestRunServiceDispatcherInjection.test_run_service_default_dispatcher_is_thread_backed`

`tests/test_run_diagnostics.py::test_async_dispatch_failure_records_diagnostic`
also patches `run_orchestrator.execute_run` and will fail.

`tests/test_branch_consistency.py::TestRunToNodeBranchContext` (two tests)
patch `run_orchestrator.PlanExecutor` — those will fail because
`execute_created_run` uses `cardre.executor.PlanExecutor` directly.

**Do not fix these in Phase 3.** Phase 6 is dedicated to migrating them. Phase
3 only verifies that the new seam works and the contract tests pass. To keep
the phase focused, run the contract file + the orchestrator + lifecycle + the
governance subset, and record the list of failing tests in the phase summary
for Phase 6 to address:

```bash
pytest tests/test_run_coordination_contract.py tests/test_run_orchestrator.py \
       tests/test_run_lifecycle.py -q
CARDRE_GOVERNANCE=1 pytest tests/test_run_coordination_contract.py -q
```

These must be green. The broader suite is allowed to be red in Phase 3 and
must be restored by Phase 6.

## Definition of done for this phase

- [ ] `RunWorker._invoke_executor` calls `RunService(store).execute_created_run(request)`.
- [ ] `RunWorker` docstring updated.
- [ ] Tests 2, 3 in the contract file are GREEN (xfail removed).
- [ ] `pytest tests/test_run_coordination_contract.py tests/test_run_orchestrator.py tests/test_run_lifecycle.py -q` is green.
- [ ] `CARDRE_GOVERNANCE=1 pytest tests/test_run_coordination_contract.py -q` is green.
- [ ] The list of tests broken by the seam change is recorded for Phase 6.
- [ ] `ruff check` clean on modified files.

## Failure mode

- If `test_worker_delegates_to_run_service_execute_created_run` does not pass:
  the monkeypatch target must be `cardre.services.run_service.RunService.execute_created_run`
  (the method on the class, not an instance). The fake signature is
  `fake_execute_created_run(self, request)` — note the `self`.
- If `test_worker_failure_records_diagnostic_and_fails_run` does not pass: the
  fake must raise, and `RunWorker._record_failure` must still append the
  `RUN_WORKER_FAILED` diagnostic. The monkeypatch must not swallow the
  exception before the worker's `try/except` sees it.