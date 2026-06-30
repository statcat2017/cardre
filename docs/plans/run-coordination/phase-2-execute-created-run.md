# Phase 2 — Introduce `RunService.execute_created_run`

**Sprint:** `docs/plans/run-coordination-consolidation-sprint.md`
**Phase goal:** Extract the body of `_execute_sync` into a shared execution method `execute_created_run(request)` that both sync and async paths will call. `_execute_sync` becomes a thin wrapper. No behaviour change.

## Files

### Read first (do not edit)
- `cardre/services/run_service.py` — full file.
- `cardre/services/run_worker.py` — `RunRequest` dataclass (fields: `project_path`, `plan_version_id`, `run_id`, `run_scope`, `branch_id`, `target_step_id`, `force`).
- `cardre/errors.py` — `CardreError` (constructor: `message`, `code`, `context`).
- `tests/test_run_coordination_contract.py` — tests 5, 6, 7 (xfail) must turn GREEN; tests 2, 3 (xfail) must remain xfail.

### Modify
- `cardre/services/run_service.py`

## Tests to write first (RED → GREEN)

The xfail tests from Phase 1 (`test_execute_created_run_rejects_missing_run`,
`test_execute_created_run_rejects_plan_version_mismatch`,
`test_execute_created_run_rejects_non_running_status`) must now turn GREEN.
Remove their `@pytest.mark.xfail` markers in
`tests/test_run_coordination_contract.py` as part of this phase.

Do **not** touch the worker-delegation xfails (tests 2, 3) — those land in
Phase 3.

## Implementation

### Step 1 — Add `execute_created_run` and `_execute_existing_running_run`

In `cardre/services/run_service.py`:

```python
def execute_created_run(self, request: "RunRequest") -> RunResponse:
    run = self._store.get_run(request.run_id)
    if run is None:
        raise CardreError(
            f"Run {request.run_id} not found",
            code="RUN_NOT_FOUND",
            context={"run_id": request.run_id},
        )
    if run["plan_version_id"] != request.plan_version_id:
        raise CardreError(
            "Run belongs to a different plan version.",
            code="RUN_PLAN_VERSION_MISMATCH",
            context={
                "run_id": request.run_id,
                "actual_plan_version_id": run["plan_version_id"],
                "expected_plan_version_id": request.plan_version_id,
            },
        )
    if run["status"] != "running":
        raise CardreError(
            f"Run {request.run_id} is not running.",
            code="RUN_NOT_RUNNING",
            context={"run_id": request.run_id, "status": run["status"]},
        )
    return self._execute_existing_running_run(request)
```

`_execute_existing_running_run` is the **extracted body of `_execute_sync`**,
adapted to take a `RunRequest` instead of positional args:

```python
def _execute_existing_running_run(self, request: "RunRequest") -> RunResponse:
    run_id = request.run_id
    plan_version_id = request.plan_version_id
    run_scope = request.run_scope
    branch_id = request.branch_id
    target_step_id = request.target_step_id
    force = request.force
    # ... exactly the current body of _execute_sync, unchanged ...
```

Preserve the exception translation exactly:
- `CardreError` re-raised unchanged.
- `ValueError` → split on `:` if present, else `code="RUN_VALIDATION_FAILED"`, wrapped in `CardreError`.
- generic `Exception` → `CardreError(code="RUN_EXECUTION_FAILED", context={...})`.

Preserve the post-exec short-circuit cancel:
```python
if result_id != run_id:
    self._store.finish_run(run_id, "cancelled")
    return self._build_response(result_id)
```
(Phase 4 replaces this `finish_run` with `_cancel_placeholder_run`.)

### Step 2 — Make `_execute_sync` a thin wrapper

```python
def _execute_sync(self, run_id, plan_version_id, run_scope, branch_id, target_step_id, force):
    request = RunRequest(
        project_path=str(self._store.root),
        plan_version_id=plan_version_id,
        run_id=run_id,
        run_scope=run_scope,  # type: ignore[arg-type]
        branch_id=branch_id,
        target_step_id=target_step_id,
        force=force,
    )
    return self.execute_created_run(request)
```

### Step 3 — Import `RunRequest`

`run_service.py` already imports `RunRequest` from `cardre.services.run_worker`
(line 19-23). Keep that import. Add the type annotation as a string forward
ref or ensure the import is available at runtime.

### Step 4 — Remove xfails

In `tests/test_run_coordination_contract.py`, remove the
`@pytest.mark.xfail(reason="lands in phase 2")` markers from tests 5, 6, 7.
They must now pass.

## Verification commands

```bash
. .venv/bin/activate
ruff check --fix cardre/services/run_service.py tests/test_run_coordination_contract.py
pytest tests/test_run_worker.py tests/test_run_orchestrator.py tests/test_run_lifecycle.py \
       tests/test_run_coordination_contract.py tests/test_run_diagnostics.py \
       tests/test_branch_consistency.py -q
CARDRE_GOVERNANCE=1 pytest tests/test_run_coordination_contract.py tests/test_run_orchestrator.py -q
```

All must be green. The worker-delegation xfails (tests 2, 3) and the
placeholder-manifest xfail (test 11) and the shim-delegation xfail (test 13)
must remain xfail.

## Definition of done for this phase

- [ ] `RunService.execute_created_run` exists with the three guards.
- [ ] `RunService._execute_existing_running_run` contains the body previously in `_execute_sync`.
- [ ] `_execute_sync` is a thin wrapper that builds a `RunRequest` and calls `execute_created_run`.
- [ ] Tests 5, 6, 7 are GREEN (xfail removed).
- [ ] Tests 2, 3, 11, 13 remain xfail.
- [ ] No other test regresses.
- [ ] `ruff check` clean.

## Failure mode

- If `_execute_sync` callers break: the wrapper must preserve the exact
  return shape. The exception translation in `_execute_existing_running_run`
  must be byte-for-byte identical to the old `_execute_sync`.
- If a test fails on the `RUN_NOT_FOUND` / mismatch / not-running guard: check
  that `store.get_run` returns a dict with key `"plan_version_id"` (it does —
  see `run_repo.RunRepository.get`). The guard strings must match the test
  assertions exactly.
- If `test_run_lifecycle.py::TestShortCircuitManifest` regresses: you changed
  the to-node short-circuit path. Re-read the original `_execute_sync` to-node
  branch and restore it verbatim.