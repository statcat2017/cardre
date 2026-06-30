# Phase 1 — Characterization Contract Tests

**Sprint:** `docs/plans/run-coordination-consolidation-sprint.md`
**Phase goal:** Lock the run coordination contract with characterization tests *before* any refactor. Some tests will be GREEN immediately (current behaviour is correct); one will be RED (branch placeholder lacks a manifest — the intended consolidation target).

## Files

### Read first (do not edit)
- `cardre/services/run_service.py` — `RunService`, `run_plan`, `_execute_sync`, `_dispatch_async`, `_build_response`.
- `cardre/services/run_worker.py` — `RunRequest`, `RunWorker.execute`, `_invoke_executor`, `SyncRunDispatcher`, `ThreadRunDispatcher`, `WORKER_FAILED_CODE`, `DISPATCH_FAILED_CODE`.
- `cardre/services/run_orchestrator.py` — `execute_run`, `_handle_short_circuit`, `dispatch_run_async`.
- `cardre/services/evidence_policy.py` — `EvidencePolicyService`, `check_branch_current`, `check_to_node_current`, `prepare_branch_evidence`, `BranchRunEvidence`, `ShortCircuitResult`.
- `cardre/run_lifecycle.py` — `finalise_run`, `RunFinalisation`, `RunLifecycle`.
- `cardre/executor.py` — `PlanExecutor.run_plan_version`, `run_branch`, `run_to_node` (signatures only).
- `cardre/store/project_store.py` — `create_run`, `finish_run`, `get_run`, `get_run_diagnostics`, `get_run_steps`, `list_runs`.
- `tests/test_run_worker.py` — helpers `_init_store`, `_one_step_plan`, `_RecordingDispatcher`, `_ExplodingDispatcher`.
- `tests/helpers/__init__.py` — `make_store`.

### Create
- `tests/test_run_coordination_contract.py` (new file)

## Tests to write first

Create `tests/test_run_coordination_contract.py`. Use the helpers from
`tests/test_run_worker.py` (`_init_store`, `_one_step_plan`,
`_RecordingDispatcher`) by importing them, or copy minimal equivalents. Do
**not** duplicate `_init_store`/`_one_step_plan` — import them from
`tests.test_run_worker`.

Write these tests, in this order:

### 1. `test_async_dispatch_uses_precreated_run_id`
- Build store, one-step plan.
- Use `_RecordingDispatcher`.
- `service.run_plan(pv_id, sync=False)`.
- Assert `recorder.dispatched` is non-empty.
- Assert `req.run_id == resp.run_id`, `req.plan_version_id == pv_id`,
  `req.project_path == str(store.root)`, `req.run_scope == "full_plan"`.
- Assert `store.get_run(resp.run_id)["status"] == "running"`.
- **Expected: GREEN** (current behaviour).

### 2. `test_worker_delegates_to_run_service_execute_created_run`
- This test will **FAIL** until Phase 3 (it asserts the future seam). Mark it
  `@pytest.mark.xfail(reason="lands in phase 3")` so the suite stays green
  until then. The phase-3 document removes the xfail.
- Build store, one-step plan, `run_id = store.create_run(pv_id)`.
- Monkeypatch `cardre.services.run_service.RunService.execute_created_run`
  to a fake that appends the request to `calls` and calls
  `store.finish_run(request.run_id, "succeeded")`.
- `RunWorker().execute(RunRequest(project_path=str(store.root), plan_version_id=pv_id, run_id=run_id))`.
- Assert `len(calls) == 1`, `calls[0].run_id == run_id`,
  `store.get_run(run_id)["status"] == "succeeded"`.
- **Expected: RED (xfail)** until Phase 3.

### 3. `test_worker_failure_records_diagnostic_and_fails_run`
- Build store, one-step plan, `run_id = store.create_run(pv_id)`.
- Monkeypatch `cardre.services.run_service.RunService.execute_created_run`
  to raise `RuntimeError("executor exploded")`.
- `RunWorker().execute(RunRequest(...))`.
- Assert `run["status"] == "failed"`.
- Assert a diagnostic with `code == "RUN_WORKER_FAILED"`, severity `error`,
  category `execution`, `"executor exploded" in d["message"]`.
- **Expected: RED (xfail)** until Phase 3 (worker does not yet call
  `execute_created_run`). Mark `@pytest.mark.xfail(reason="lands in phase 3")`.

### 4. `test_dispatch_startup_failure_records_diagnostic_and_fails_run`
- Mirror `TestSidecarDispatchFailure` but at the service level: use
  `_ExplodingDispatcher(CardreError("boom", code=DISPATCH_FAILED_CODE))`.
- `service.run_plan(pv_id, sync=False)` raises `CardreError` with
  `code == DISPATCH_FAILED_CODE`.
- Assert run is `failed` and has a `RUN_DISPATCH_FAILED` diagnostic.
- **Expected: GREEN** (already covered by `test_run_worker.py`, lock it here
  too as a contract).

### 5. `test_execute_created_run_rejects_missing_run`
- Build store, one-step plan. Build a `RunRequest` with a non-existent
  `run_id`.
- Call `RunService(store).execute_created_run(request)` (this method does not
  exist yet — mark `@pytest.mark.xfail(reason="lands in phase 2")`).
- Assert it raises `CardreError` with `code == "RUN_NOT_FOUND"`.
- **Expected: RED (xfail)** until Phase 2.

### 6. `test_execute_created_run_rejects_plan_version_mismatch`
- Build store, two plan versions `pv_a`, `pv_b`. Create run on `pv_a`.
- Build `RunRequest` with `plan_version_id=pv_b` and the `pv_a` run id.
- Assert `CardreError` with `code == "RUN_PLAN_VERSION_MISMATCH"`.
- **Expected: RED (xfail)** until Phase 2.

### 7. `test_execute_created_run_rejects_non_running_status`
- Build store, one-step plan, `run_id = store.create_run(pv_id)`,
  `store.finish_run(run_id, "succeeded")`.
- `RunRequest` with the finished run id.
- Assert `CardreError` with `code == "RUN_NOT_RUNNING"`.
- **Expected: RED (xfail)** until Phase 2.

### 8. `test_branch_short_circuit_returns_existing_run_for_sync_and_worker_paths` (governance-gated)
- `@pytest.mark.governance` + skip-if `CARDRE_GOVERNANCE` unset (mirror the
  pattern in `tests/test_run_orchestrator.py`).
- Build store, one-step plan, a branch with `head_plan_version_id == pv_id`.
- Seed an existing successful branch run: `existing_run_id =
  store.create_run(pv_id, branch_id="branch-1")`, then save a successful run
  step and `store.finish_run(existing_run_id, "succeeded")`.
- Monkeypatch
  `cardre.services.evidence_policy.EvidencePolicyService.prepare_branch_evidence`
  to return a fake ctx with `short_circuit_run_id = existing_run_id` and
  empty `diagnostics`, `steps`, `branch_owned_step_ids`, `stale_branch_step_ids`,
  `step_outputs`, `run_step_records`. (Mirror `_FakeCtx` from
  `test_run_orchestrator.py`.)
- `sync = service.run_plan(pv_id, run_scope="branch", branch_id="branch-1", sync=True, force=False)`.
- `async_ = service.run_plan(pv_id, run_scope="branch", branch_id="branch-1", sync=False, force=False)`.
- Assert `sync.run_id == existing_run_id` and `async_.run_id == existing_run_id`.
- Assert a placeholder run exists with status `cancelled` (at least one).
- **Expected: GREEN** for the return-value parity (current behaviour already
  correct per `test_run_orchestrator.py`). The placeholder-manifest assertion
  belongs to Phase 4, not here.

### 9. `test_to_node_short_circuit_parity_sync_and_worker`
- Build store, one-step plan. Seed a prior successful full run with a run step
  for `source` (mirror `TestShortCircuitManifest.test_to_node_short_circuit_placeholder_has_manifest`
  setup).
- `sync = service.run_plan(pv_id, run_scope="to_node", target_step_id="source", sync=True)`.
- `async_ = service.run_plan(pv_id, run_scope="to_node", target_step_id="source", sync=False, dispatcher=_RecordingDispatcher())`.
- Assert both `run_id == prev_run_id`.
- **Expected: GREEN**.

### 10. `test_full_plan_executes_via_shared_path`
- Build store, one-step plan, register `SimpleSourceNode`.
- `RunService(store, dispatcher=SyncRunDispatcher()).run_plan(pv_id, sync=True)`.
- Assert status `succeeded`, `executed_step_ids == ["source"]`.
- **Expected: GREEN**.

### 11. `test_branch_placeholder_cancellation_writes_manifest` (governance-gated, RED)
- `@pytest.mark.governance` + skip guard.
- Same setup as test 8 (branch short-circuit).
- After `service.run_plan(..., sync=True, run_scope="branch", branch_id="branch-1")`,
  find the cancelled placeholder run.
- Assert it has exactly one `run_manifest` artifact with `status == "cancelled"`
  and `execution_mode == "branch"` (mirror the to-node assertion in
  `test_run_lifecycle.py:TestShortCircuitManifest`).
- **Expected: RED** — branch placeholders currently use `finish_run` with no
  manifest. This is the intended behaviour change, locked here so Phase 4
  turns it GREEN. Mark with a comment `# RED: lands in phase 4`.

### 12. `test_to_node_placeholder_cancellation_writes_manifest`
- Copy `TestShortCircuitManifest.test_to_node_short_circuit_placeholder_has_manifest`
  into the contract file (or import and re-run). Keep it GREEN.
- **Expected: GREEN** (preserved behaviour).

### 13. `test_run_orchestrator_shim_delegates_to_run_service`
- This will **FAIL** until Phase 5. Mark `@pytest.mark.xfail(reason="lands in phase 5")`.
- Monkeypatch `cardre.services.run_service.RunService.run_plan` to a fake
  returning a `RunResponse(run_id="delegated", plan_version_id="pv", status="succeeded", started_at="t", step_count=0)`.
- Call `run_orchestrator.execute_run(store, "pv", run_scope="full_plan")`.
- Assert the fake was called and the return is `"delegated"`.
- **Expected: RED (xfail)** until Phase 5.

## Implementation

No production code changes in this phase. Only create
`tests/test_run_coordination_contract.py`. The xfail markers protect the
suite from the not-yet-implemented seams.

## Verification commands

```bash
. .venv/bin/activate
ruff check tests/test_run_coordination_contract.py
pytest tests/test_run_coordination_contract.py -q
CARDRE_GOVERNANCE=1 pytest tests/test_run_coordination_contract.py -q
```

All non-xfail tests must pass. All xfail tests must xfail (not xpass — if an
xfail unexpectedly passes, that means a seam already exists and the phase
docs need revisiting).

## Definition of done for this phase

- [ ] `tests/test_run_coordination_contract.py` exists.
- [ ] Tests 1, 4, 8, 9, 10, 12 are GREEN.
- [ ] Tests 2, 3, 5, 6, 7, 11, 13 are `xfail` (not xpass).
- [ ] `ruff check tests/test_run_coordination_contract.py` clean.
- [ ] No production code changed.

## Failure mode

If a test you expected to be GREEN is RED, **stop**. That means the current
behaviour does not match the contract. Read the failing assertion, confirm
against the actual code, and either:
- Fix the test to match actual current behaviour (if the contract in this doc
  was wrong), OR
- File the discrepancy as a note in the phase summary — it may be a real bug
  that Phase 2/3/4 must preserve, not fix.

Do **not** change production code in Phase 1.