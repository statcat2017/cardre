# Phase 5 — Demote `run_orchestrator` to a pure shim

**Sprint:** `docs/plans/run-coordination-consolidation-sprint.md`
**Phase goal:** Rewrite `run_orchestrator.execute_run` so it contains **no independent execution policy**. It delegates to `RunService.run_plan` (when `run_id is None`) or `RunService.execute_created_run` (when `run_id` is given). Remove `_handle_short_circuit`.

## Files

### Read first (do not edit)
- `cardre/services/run_orchestrator.py` — full file.
- `cardre/services/run_service.py` — `RunService.run_plan`, `execute_created_run`, `RunResponse`.
- `cardre/services/run_worker.py` — `RunRequest`.
- `tests/test_run_orchestrator.py` — uses `DummyStore`, `FakeExecutor`, patches `run_orchestrator.PlanExecutor` and `run_orchestrator.NodeRegistry`.
- `tests/test_branch_consistency.py::TestRunToNodeBranchContext` — patches `run_orchestrator.PlanExecutor`.
- `tests/test_run_coordination_contract.py` — test 13 (xfail) must turn GREEN.

### Modify
- `cardre/services/run_orchestrator.py`
- `tests/test_run_coordination_contract.py` (remove the xfail on test 13)

## Tests to write first (RED → GREEN)

`test_run_orchestrator_shim_delegates_to_run_service` (test 13) is currently
`xfail(reason="lands in phase 5")`. Remove the xfail. It must turn GREEN after
the implementation.

## Implementation

### Step 1 — Rewrite `execute_run`

Replace the entire body of `execute_run` in `cardre/services/run_orchestrator.py`
with a pure delegation shim:

```python
def execute_run(
    store: ProjectStore,
    plan_version_id: str,
    run_id: str | None = None,
    run_scope: Literal["full_plan", "branch", "to_node"] = "full_plan",
    branch_id: str | None = None,
    target_step_id: str | None = None,
    force: bool = False,
) -> str:
    """Compatibility shim. Delegates to RunService — no independent policy.

    New code should call RunService.run_plan or RunService.execute_created_run
    directly. This exists so existing callers/tests that import
    run_orchestrator.execute_run keep working.
    """
    from cardre.services.run_service import RunService
    from cardre.services.run_worker import RunRequest

    if run_id is None:
        response = RunService(store).run_plan(
            plan_version_id=plan_version_id,
            run_scope=run_scope,
            branch_id=branch_id,
            target_step_id=target_step_id,
            force=force,
            sync=True,
        )
        return response.run_id

    request = RunRequest(
        project_path=str(store.root),
        plan_version_id=plan_version_id,
        run_id=run_id,
        run_scope=run_scope,
        branch_id=branch_id,
        target_step_id=target_step_id,
        force=force,
    )
    response = RunService(store).execute_created_run(request)
    return response.run_id
```

### Step 2 — Delete `_handle_short_circuit`

Remove the `_handle_short_circuit` function entirely. It is no longer
referenced.

### Step 3 — Keep `dispatch_run_async` as-is

`dispatch_run_async` already delegates to `RunWorker().execute(request)`. It
is a thin compat wrapper used by `test_run_diagnostics.py`. Leave it.

### Step 4 — Remove unused imports

After the rewrite, `PlanExecutor`, `NodeRegistry`, `utc_now_iso`, and the
`EvidencePolicyService` import inside the old branch block are no longer
needed at module top. Remove them. Keep `ProjectStore` and `Literal` (used by
the shim signatures).

### Step 5 — Remove the xfail

In `tests/test_run_coordination_contract.py`, remove the
`@pytest.mark.xfail(reason="lands in phase 5")` marker from test 13.

## Verification commands

```bash
. .venv/bin/activate
ruff check --fix cardre/services/run_orchestrator.py tests/test_run_coordination_contract.py
pytest tests/test_run_coordination_contract.py -q
```

### Expected fallout

`tests/test_run_orchestrator.py` will fail because it patches
`run_orchestrator.PlanExecutor` and `run_orchestrator.NodeRegistry`, which no
longer exist. **Do not fix these in Phase 5.** Phase 6 rewrites them to assert
delegation. Record the failures for Phase 6.

The contract file must be green:

```bash
pytest tests/test_run_coordination_contract.py -q
```

## Definition of done for this phase

- [ ] `execute_run` is a pure shim — no branch/to-node/full execution logic, no `_handle_short_circuit`.
- [ ] `_handle_short_circuit` deleted.
- [ ] Unused imports removed.
- [ ] Test 13 (`test_run_orchestrator_shim_delegates_to_run_service`) is GREEN.
- [ ] `dispatch_run_async` still exists and is unchanged.
- [ ] `pytest tests/test_run_coordination_contract.py -q` green.
- [ ] `ruff check` clean.

## Failure mode

- If `test_run_orchestrator_shim_delegates_to_run_service` does not pass: the
  monkeypatch target is `cardre.services.run_service.RunService.run_plan`. The
  fake returns a `RunResponse` — make sure the test constructs one with all
  required fields (`run_id`, `plan_version_id`, `status`, `started_at`,
  `step_count`). The shim extracts `.run_id`.
- If removing `PlanExecutor`/`NodeRegistry` imports breaks an `__init__` or
  re-export: grep for `from cardre.services.run_orchestrator import` across
  the repo. The only public symbols after this phase should be `execute_run`
  and `dispatch_run_async`.