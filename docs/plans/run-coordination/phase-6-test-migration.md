# Phase 6 — Migrate existing tests to the new seam

**Sprint:** `docs/plans/run-coordination-consolidation-sprint.md`
**Phase goal:** Rewrite the tests that patched `run_orchestrator.execute_run` / `run_orchestrator.PlanExecutor` so they patch the new seam (`RunService.execute_created_run` or `cardre.executor.PlanExecutor`) or assert delegation. Restore full suite green.

## Files

### Read first (do not edit)
- `tests/test_run_worker.py` — seven tests that patch `run_orchestrator.execute_run`.
- `tests/test_run_diagnostics.py::test_async_dispatch_failure_records_diagnostic` — patches `run_orchestrator.execute_run`.
- `tests/test_branch_consistency.py::TestRunToNodeBranchContext` — two tests patch `run_orchestrator.PlanExecutor`.
- `tests/test_run_orchestrator.py` — full file, patches `run_orchestrator.PlanExecutor` and `NodeRegistry`.
- `cardre/services/run_service.py` — `execute_created_run` (the new seam).
- `cardre/services/run_worker.py` — `_invoke_executor` now calls `RunService.execute_created_run`.

### Modify
- `tests/test_run_worker.py`
- `tests/test_run_diagnostics.py`
- `tests/test_branch_consistency.py`
- `tests/test_run_orchestrator.py`

## Tests to write first

No new tests. This phase rewrites existing tests to the consolidated seam.
The rewritten tests must preserve the *characterization* intent: they still
assert the same observable behaviour (diagnostic codes, run status, worker
naming, branch_id pass-through, short-circuit return value).

## Implementation

### General rule

Replace `monkeypatch.setattr("cardre.services.run_orchestrator.execute_run", X)`
with `monkeypatch.setattr("cardre.services.run_service.RunService.execute_created_run", X)`.

The fake signature changes from `def fake(*args, **kwargs)` to
`def fake(self, request)` because `execute_created_run` is a method. When the
test asserts the run was left in a particular state, the fake must call
`store.finish_run(request.run_id, "<status>")` itself (the old
`execute_run` sometimes did this; the new seam does not — the worker's
`_fail_run_if_running` handles failure, and `RunLifecycle` handles success).

### `tests/test_run_worker.py`

1. **`TestRunWorkerFailure.test_worker_exception_records_diagnostic_and_fails_run`**
   - Change patch target to `cardre.services.run_service.RunService.execute_created_run`.
   - Fake: `def _raise(self, request): raise RuntimeError("boom from executor")`.
   - The rest of the assertions (status `failed`, `RUN_WORKER_FAILED` diag) stay.

2. **`TestRunWorkerFailure.test_worker_heartbeats_before_execution`**
   - Change patch target.
   - Fake captures the heartbeat via `store.get_run(request.run_id)["heartbeat_at"]`
     then raises. Note `store` is not passed to the fake; the fake must
     reconstruct it: `from cardre.store import ProjectStore; store = ProjectStore(request.project_path)`.

3. **`TestRunWorkerFailure.test_worker_failure_does_not_leave_run_running`**
   - Change patch target. Fake raises. Assertions unchanged.

4. **`TestThreadRunDispatcher.test_dispatch_success_starts_named_thread`**
   - Replace the `import cardre.services.run_orchestrator as ro` + `ro.execute_run = ...`
     dance with `monkeypatch.setattr("cardre.services.run_service.RunService.execute_created_run", lambda self, req: store.finish_run(req.run_id, "succeeded"))`.
   - Keep `_join_named`.

5. **`TestSyncRunDispatcher.test_sync_dispatcher_runs_worker_inline`**
   - Change patch target. Fake appends to `called`. Assertions unchanged.

6. **`TestSyncRunDispatcher.test_sync_dispatcher_swallows_worker_exception`**
   - Change patch target. Fake raises. Assertions unchanged.

7. **`TestRunServiceDispatcherInjection.test_run_service_default_dispatcher_is_thread_backed`**
   - Same fix as (4): patch `RunService.execute_created_run` to a fast no-op
     that finishes the run.

### `tests/test_run_diagnostics.py`

8. **`test_async_dispatch_failure_records_diagnostic`**
   - Change patch target from `run_orchestrator.execute_run` to
     `RunService.execute_created_run`.
   - The fake `_raise_execute_run(self, request)` raises `RuntimeError`.
   - Assertions unchanged (`RUN_WORKER_FAILED` in diags, run `failed`).

### `tests/test_branch_consistency.py::TestRunToNodeBranchContext`

9. **`test_run_to_node_passes_branch_id_to_executor`**
   - These tests patch `run_orchestrator.PlanExecutor` to a `FakeExecutor` and
     call `run_orchestrator.execute_run`. After Phase 5, the shim delegates to
     `RunService`, which uses `cardre.executor.PlanExecutor`.
   - **Two options** (pick the one that preserves the test's intent):
     - **Option A (preferred):** Patch `cardre.executor.PlanExecutor` (the
       class `RunService` imports) so that `RunService._execute_existing_running_run`
       uses the fake executor. Then call `run_orchestrator.execute_run(...)` and
       assert the fake saw `branch_id`. This tests the full delegation chain.
     - **Option B:** Call `RunService(store).run_plan(...)` directly and
       patch `cardre.executor.PlanExecutor`. More direct, less of a shim test.
   - Use Option A. Replace `monkeypatch.setattr(run_orchestrator, "PlanExecutor", lambda r: FakeExecutor())`
     with `monkeypatch.setattr("cardre.executor.PlanExecutor", lambda r: FakeExecutor())`
     and `monkeypatch.setattr("cardre.executor.NodeRegistry", "with_defaults", staticmethod(lambda: object()))`.
   - `run_orchestrator.execute_run` now delegates to `RunService.run_plan` (no
     run_id given) which validates the plan version — so the test must use a
     real store with a real plan version, not `store=None`. Update the setup
     to build a minimal store + plan version (mirror `_init_store` /
     `_one_step_plan` from `test_run_worker.py`).
   - The fake's `run_to_node` returns `"run-1"`; assert `branch_id == "br-1"`.

10. **`test_run_to_node_without_branch_id_passes_none`** — same fix as (9).

### `tests/test_run_orchestrator.py`

This file is the largest rewrite. The tests previously asserted
`execute_run`'s internal behaviour (which executor methods were called, what
`branch_ctx` was passed). After Phase 5, `execute_run` is a shim. The tests
must now assert **delegation**, not internal behaviour.

11. **`test_execute_run_returns_created_run_id_for_sync_full_plan`**
    - Rewrite: monkeypatch `RunService.run_plan` to return a fake
      `RunResponse(run_id="delegated-full", ...)` when called with
      `run_scope="full_plan"`, `sync=True`, `run_id=None` (well, no run_id
      arg). Call `run_orchestrator.execute_run(DummyStore(), "pv", run_scope="full_plan")`.
      Assert return is `"delegated-full"` and that `RunService.run_plan` was
      called.
    - `DummyStore` is no longer sufficient (the shim calls `RunService(store)`
      which may touch the store). Use a real store with a one-step plan, or
      monkeypatch `RunService` so its constructor is a no-op. Simplest: patch
      `cardre.services.run_service.RunService` with a fake class whose
      `run_plan` returns the fake response and whose `__init__` accepts `store`.

12. **`test_execute_run_returns_created_run_id_for_sync_to_node`** — same pattern.

13. **`test_execute_run_returns_created_run_id_for_sync_branch`** (governance) — same pattern.

14. **`test_execute_run_preserves_precreated_async_run_id_on_branch_short_circuit`** (governance)
    - This test was the canonical pin for issue #168. After consolidation the
      short-circuit lives in `RunService._execute_existing_running_run`, not
      the shim. Rewrite to call `RunService(store).execute_created_run(request)`
      directly (with a real store, a real branch, and a monkeypatched
      `prepare_branch_evidence` returning a fake ctx with
      `short_circuit_run_id`). Assert the return is the existing run id and
      the placeholder is cancelled.
    - Move this test into `tests/test_run_coordination_contract.py` if it
      duplicates test 8 — or keep it in `test_run_orchestrator.py` as a shim
      test that asserts the shim returns the existing run id. The maintainer's
      intent is that the contract is locked; duplication across files is
      acceptable if the assertions are identical.

15. **`test_branch_short_circuit_worker_path_returns_existing_run_id`** (governance) — same as (14).

16. **`test_is_branch_current_returns_*`** — these test `sidecar/routes/runs.py`
    helpers, not the orchestrator. Leave them unchanged.

## Verification commands

```bash
. .venv/bin/activate
ruff check --fix tests/test_run_worker.py tests/test_run_diagnostics.py \
       tests/test_branch_consistency.py tests/test_run_orchestrator.py
pytest tests/test_run_worker.py tests/test_run_orchestrator.py \
       tests/test_run_lifecycle.py tests/test_run_coordination_contract.py \
       tests/test_run_diagnostics.py tests/test_branch_consistency.py -q
CARDRE_GOVERNANCE=1 pytest tests/test_run_orchestrator.py \
       tests/test_run_coordination_contract.py tests/test_branch_consistency.py -q
```

All must be green.

## Definition of done for this phase

- [ ] All seven `test_run_worker.py` tests patched to `RunService.execute_created_run`.
- [ ] `test_run_diagnostics.py::test_async_dispatch_failure_records_diagnostic` patched.
- [ ] `test_branch_consistency.py::TestRunToNodeBranchContext` uses `cardre.executor.PlanExecutor` + real store.
- [ ] `test_run_orchestrator.py` rewritten to assert delegation (or direct `RunService` calls for short-circuit tests).
- [ ] `test_is_branch_current_*` unchanged.
- [ ] Full focused suite green (commands above).
- [ ] `ruff check` clean.

## Failure mode

- If a fake signature mismatches: `execute_created_run(self, request)` — the
  `self` is the `RunService` instance. When using
  `monkeypatch.setattr("cardre.services.run_service.RunService.execute_created_run", fake)`,
  `fake` must accept `self` first. If you prefer to ignore it, use
  `lambda self, request: ...`.
- If `test_run_orchestrator.py` rewrite is too large: split it. The
  short-circuit tests can move to `test_run_coordination_contract.py` (where
  they belong after consolidation) and `test_run_orchestrator.py` keeps only
  the delegation tests. That is an acceptable outcome.
- If `DummyStore` no longer works: the shim's `RunService(store)` may call
  store methods. Use a real store built via `make_store()` /
  `ProjectStore(tmp_path / "test.cardre"); store.initialize()`.