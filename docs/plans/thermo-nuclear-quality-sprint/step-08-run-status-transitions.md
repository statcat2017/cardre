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
    - Delete the post-`with` re-query (run_coordinator.py:346-348).
    - Replace the `execution_mode` identity-map dict (lines 294-297) with a
      `RunScope` enum → `execution_mode` property mapping.

> **`RunScope` name-collision note (audit revision):** `cardre/domain/run.py:58-64`
> already defines `RunScope` as a frozen dataclass (fields: `plan_version_id`,
> `branch_id`, `target_step_id`, `force`). It is exported in `__all__` but
> **never instantiated in production logic** (verified — only imported and
> re-exported; its fields are redundant with `Run`). PR8 should **delete the
> dead `RunScope` dataclass and reuse the name for the `StrEnum`** (with
> `FULL_PLAN`, `BRANCH`, `TO_NODE` members). Alternatively rename the enum to
> `RunScopeKind`; the former is cleaner since the dataclass is dead. Update
> `cardre/domain/__init__.py:34,60` accordingly.

### SE2 — Make `to_node` safety-net atomic (revised — do NOT delete)

**Revised after pre-implementation audit of the current repo.** The
original plan called for deleting the `to_node` branch in
`cardre/services/run_coordinator.py:298-301`. The audit found:

- `run_coordinator.py:146-147` only guards *new* runs created via
  `run()`. The safety net at lines 299-302 (`_execute_existing_running_run`)
  is load-bearing for **legacy `to_node` rows already in the DB** — e.g.
  rows written by a direct DB insert or older code path.
- `tests/test_run_coordinator.py:296-317`
  (`test_to_node_in_column_raises`) asserts that a `to_node` row is
  rejected *and* raises `RunScopeNotAvailableForLaunch`. Deleting the
  safety net would leave such a row stuck in `running` while raising —
  strictly worse and a behaviour change.

1. Keep the `RunScopeNotAvailableForLaunch` raise at lines 299-302.
2. Replace the non-atomic `RunRepository(...).finish(run_id, "failed")`
   with `RunRepository(...).transition(run_id, RunStatus.FAILED,
   expected_from=(RunStatus.RUNNING,))` so the write is atomic with the
   enum and uses the single transition writer.
3. Confirm `executor.run_to_node` was already deleted by PR4 (verified:
   zero hits in `cardre/execution/executor.py`).
4. Full deletion of the safety-net branch is a **follow-up** requiring a
   product decision on legacy `to_node` rows + an update to
   `test_to_node_in_column_raises`. Not in this PR.

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
- [ ] `RunScope` is an enum (dead dataclass removed) in `cardre/domain/run.py`.
- [ ] `RunRepository.transition` exists and is the only writer of
  terminal statuses.
- [ ] `rg '"running"|"failed"|"succeeded"|"interrupted"|"cancelled"'
  cardre/services cardre/execution --type py -g '!test*'` — bare string
  status literals replaced by `RunStatus.X` (≤2 residual unavoidable hits
  such as manifest payload keys / log messages, not comparisons).
- [ ] `run_plan_version` returns `PlanExecutionResult`.
- [ ] `rg 'compute_final_status' cardre/execution/executor.py` returns 0.
- [ ] `rg 'get_for_run' cardre/services/run_coordinator.py` returns ≤1.
- [ ] `rg '_maybe_recover_stale_run' cardre` returns 0.
- [ ] `rg '_get_branch_for_run' cardre` returns 0.
- [ ] `rg 'SELECT branch_id FROM runs WHERE run_id'
  cardre/execution/executor.py` returns 0.
- [ ] `rg 'to_node' cardre/execution/executor.py` returns 0 (executor has
  no such method — verified by PR4).
- [ ] `to_node` safety-net branch in `run_coordinator.py` still raises
  `RunScopeNotAvailableForLaunch` and uses `transition(...)` atomically.
- [ ] `rg 'with store.transaction\(\) as conn: UPDATE branch_comparisons'
  cardre/services/comparison_service.py` returns 0 (per-iteration
  transaction gone); one outer transaction wraps the snapshot-build loop.
- [ ] `tests/test_run_coordinator.py::test_to_node_in_column_raises`
  passes unchanged.
- [ ] Run lifecycle, worker, audit-integrity, stale-recovery tests pass
  with the new enum (no behaviour change).
- [ ] New tests added: `transition` (4 cases), `PlanExecutionResult`
  status, `refresh_comparison` rollback + happy path, `branch_id`
  invariant, `_sweep_stale_running_runs` returns, coordinator-does-not-
  requery spy.
- [ ] `ruff check` clean; `pytest tests/ -q` green; `make preflight`
  green.

## Do not

- Do not change which status a run ends in — only the mechanism. The
  migration is structure-only from the observer's perspective.
- Do not touch store/API layer (that's PR9).
- Do not delete the `to_node` safety-net raise in `run_coordinator.py`
  (it is load-bearing for legacy DB rows — see SE2 revision above).

## Documentation updates (must include)

The following docs reference run status / lifecycle mechanisms and must
be updated as part of this PR. The audit confirmed they currently
describe the pre-PR8 string-based state machine.

1. `docs/architecture/execution-and-staleness.md` — the "Run Lifecycle"
   section: already updated in the planning phase to reference
   `RunRepository.transition` + `RunStatus` enum + `PlanExecutionResult`.
   Verify the prose matches the final implementation and the module path
   (`cardre/execution/run_lifecycle.py`, not `cardre/run_lifecycle.py`
   — the doc had a stale path which the planning phase corrected).
2. `docs/architecture/domain-model.md` — add a "Run Status" subsection
   (separate from the existing "Step Status") describing `RunStatus` and
   `RunScope` enums. Already drafted in the planning phase; verify it
   matches the final member set.
3. `docs/adr/0004-single-run-lifecycle-atomic-finalisation.md` — the
   "Historical note" already references PR8's `transition` writer. Verify
   the "Decision" section's mention of `store.finish_run` is still
   accurate (it is now `RunRepository.transition`; the ADR's intent is
   preserved — no decision-text change needed, only the historical note
   which is already updated).
4. `docs/risk/crash-corruption-risk-register.md` — references
   `recover_interrupted_runs`, `finalise()`, and run status strings in
   several rows. These describe *risk* mitigations, not the writer
   mechanism. **No change required** unless a row's "mitigated by"
   column cites a deleted symbol (`_maybe_recover_stale_run`,
   `compute_final_status`). The audit found no such citations — rows
   cite `run_lifecycle.py:308-323` finalisation and
   `recover_interrupted_runs`, both of which survive PR8 (the former via
   `transition`, the latter is unrelated). Leave as-is.
5. `docs/plans/thermo-nuclear-quality-sprint/README.md` and
   `sprint-execution.md` — the PR8 row / Batch F description already
   describe the enum + transition goal. No change needed unless the
   scope deviates (it does not, beyond the SE2 revision which is
   documented in this step-08 file).
6. `docs/prd/cardre-v2-big-bang-refactor-prd.md:33` — user story lists
   run states as strings ("created, queued, running, succeeded, failed,
   cancelled, and interrupted"). This is a product requirement, not a
   code reference. **No change required** — the enum members use the
   same string values.

If the implementing agent discovers additional doc references to the old
`finish(...)` writer or bare-string run statuses during implementation,
update them in the same PR.
