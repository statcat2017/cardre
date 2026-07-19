# Deepen Run Terminal Handling

## Purpose

This implementation guide is for an implementation agent. It deepens terminal
Run handling so every terminal outcome has one lifecycle implementation for its
diagnostic, manifest, and status transition.

Today `RunLifecycle` has useful depth for normal execution: it writes a Run
manifest before the terminal status transition and finalises a context-manager
body that raises. Four other paths bypass that seam:

- an unavailable persisted `to_node` Run;
- dispatcher startup failure;
- a worker exception that escapes execution;
- stale Run recovery.

Those modules write a diagnostic and/or terminal status directly. The result is
shallow terminal handling: callers must know the ordering, status precondition,
and whether a Run will receive an audit manifest.

The target is a deep `RunLifecycle` module. Callers supply an outcome and
path-specific diagnostic facts through its interface. The lifecycle
implementation owns the terminal writes. This concentrates locality and gives
every Run mode leverage from one test surface.

## ADR Constraints

This work implements ADR-0004 without reopening ADR-0002.

1. `PlanExecutor` remains the only public execution seam. Do not create a
   second executor, runner, or execution module tree.
2. `RunLifecycle` becomes the only external terminal-status writer.
3. The manifest is written before a normal terminal transition. A manifest
   write failure must leave a Run `failed`, never `succeeded` or `interrupted`.
4. A diagnostic, manifest, and normal terminal transition are lifecycle work.
5. Preserve current diagnostic codes and payload fields:
   - `RUN_BODY_EXCEPTION`
   - `RUN_DISPATCH_FAILED`
   - `RUN_WORKER_FAILED`
   - `RUN_RECOVERED_STALE`
   - `RUN_FINALISATION_FAILED`
6. No schema migration, Artifact format change, route change, or new domain
   term is required.

## Scope

Change these production modules:

- `cardre/execution/run_lifecycle.py`
- `cardre/services/run_coordinator.py`
- `cardre/execution/worker.py`

Extend these tests:

- `tests/test_run_lifecycle.py`
- `tests/test_run_lifecycle_errors.py`
- `tests/test_worker_lifecycle.py`
- `tests/test_run_coordinator.py`
- `tests/test_run_coordinator_edge_cases.py`, if its existing fixtures cover a
  dispatcher startup failure more directly

Do not change:

- `cardre/execution/executor.py` node execution semantics;
- `cardre/store/run_repo.py` persistence schema or transition rules;
- `cardre/domain/run.py` status values or state graph;
- `cardre/services/staleness_service.py` staleness computation;
- `CONTEXT.md` or ADRs.

## Current Terminal-Path Map

| Path | Current module | Current terminal write | Missing locality |
| --- | --- | --- | --- |
| Normal full-plan / Branch execution | `RunCoordinator._execute_existing_running_run` | `RunLifecycle.finalise` | Correct lifecycle path |
| Context-manager body exception | `RunLifecycle.__exit__` | diagnostic then `RunLifecycle.finalise` | Correct lifecycle path |
| Persisted unavailable `to_node` | `RunCoordinator._execute_existing_running_run` | direct `RunRepository.transition(...FAILED...)` | No manifest |
| Dispatcher startup failure | `RunCoordinator._dispatch_async` | diagnostic plus direct failed transition | No manifest |
| Thread startup exception | `ThreadRunDispatcher._record_dispatch_failure` | diagnostic plus `_fail_run_if_running` | Duplicates coordinator handling |
| Worker escape | `RunWorker._record_failure` | diagnostic plus `_fail_run_if_running` | No manifest |
| Stale Run recovery | `RunCoordinator._sweep_stale_running_runs` | direct interrupted transition plus diagnostic | No manifest |
| Manifest write failure | `RunLifecycle.finalise` | lifecycle diagnostic plus direct failed transition | Valid: this is inside lifecycle implementation |

After the change, only `cardre/execution/run_lifecycle.py` may call
`RunRepository.transition(... expected_from=(RunStatus.RUNNING,))` for terminal
Run statuses.

## Target Module Shape

The lifecycle interface should require callers to know only the terminal
outcome and optional diagnostic facts:

```text
caller outcome + diagnostic facts
             |
             v
      RunLifecycle.finalise(...)
             |
             +-- append diagnostic, if supplied
             +-- write manifest
             +-- transition Run from running to terminal status
```

The lifecycle constructor already holds `plan_version_id`, execution mode,
Branch context, target Step, and in-scope Steps. Do not make callers repeat
that context when finalising. The interface should get smaller, not larger.

## Production Changes

### 1. Let `RunLifecycle.finalise` own terminal diagnostics

File: `cardre/execution/run_lifecycle.py`

Import `JsonDict` at runtime, because the optional diagnostic is part of the
public lifecycle interface:

```python
from cardre.domain.diagnostics import JsonDict, utc_now_iso
```

Replace the current `finalise` shape, which repeats execution context at every
call site:

```python
def finalise(
    self,
    status: str,
    execution_mode: str,
    *,
    branch_id: str | None = None,
    target_step_id: str | None = None,
    in_scope_step_ids: list[str] | None = None,
) -> None:
```

with a context-capturing interface:

```python
def finalise(
    self,
    status: RunStatus | str,
    *,
    diagnostic: JsonDict | None = None,
) -> None:
    """Write one terminal Run outcome exactly once.

    The lifecycle owns diagnostic persistence, manifest writing, and the
    running-to-terminal transition. ``diagnostic`` describes why this caller
    reached the terminal outcome; it does not change lifecycle ordering.
    """
```

Implementation requirements:

1. Return immediately when `_finalised` is true, as today.
2. Normalize once with `terminal_status = RunStatus(status)`.
3. If `diagnostic` is not `None`, append it before writing the manifest.
4. Build `RunFinalisation` from constructor state only:

```python
finalise_run(
    self._store,
    RunFinalisation(
        run_id=self.run_id,
        plan_version_id=self.plan_version_id,
        status=terminal_status.value,
        execution_mode=self._execution_mode,
        finished_at=utc_now_iso(),
        branch_id=self._branch_id,
        target_step_id=self._target_step_id,
        in_scope_step_ids=self._in_scope_step_ids,
    ),
)
```

5. Retain the current failure behavior inside this module. If appending the
   diagnostic or writing the manifest fails, append a `RUN_FINALISATION_FAILED`
   diagnostic where possible, transition the still-running Run to `failed`, and
   re-raise. This is the one permitted direct terminal transition outside
   `finalise_run`, because it is the lifecycle implementation recovering from
   its own failed normal path.
6. Set `_finalised = True` only after `finalise_run(...)` succeeds.

Do not put dispatcher, worker, or stale-recovery branching in `RunLifecycle`.
They provide the outcome facts; the lifecycle implementation provides the
terminal mechanics.

### 2. Move context-manager exception diagnostics into `finalise`

File: `cardre/execution/run_lifecycle.py`

In `RunLifecycle.__exit__`, retain traceback construction but do not append the
diagnostic directly. Construct it and pass it through the lifecycle interface:

```python
if exc_val is not None:
    diagnostic = {
        "code": "RUN_BODY_EXCEPTION",
        "message": f"{type(exc_val).__name__}: {exc_val}",
        "severity": "error",
        "run_id": self.run_id,
        "plan_version_id": self.plan_version_id,
        "branch_id": self._branch_id,
        "traceback": ...,
        "created_at": utc_now_iso(),
    }
else:
    diagnostic = None

self.finalise(RunStatus.FAILED, diagnostic=diagnostic)
```

The method must still return `None` so the original exception propagates.

### 3. Simplify normal Run execution

File: `cardre/services/run_coordinator.py`

In `_execute_existing_running_run`, create the lifecycle with
`RunLifecycle.start(...)`, not a direct constructor. This validates the
existing `running` Run before execution and gives every terminal path one
factory.

Replace:

```python
with RunLifecycle(
    store=self._store,
    run_id=run_id,
    plan_version_id=plan_version_id,
    execution_mode=execution_mode,
    branch_id=branch_id,
    target_step_id=target_step_id,
) as lifecycle:
    ...
    lifecycle.finalise(
        status=result.status().value,
        execution_mode=execution_mode,
        branch_id=branch_id,
        target_step_id=target_step_id,
    )
```

with:

```python
with RunLifecycle.start(
    self._store,
    plan_version_id,
    run_id,
    execution_mode=execution_mode,
    branch_id=branch_id,
    target_step_id=target_step_id,
) as lifecycle:
    result = executor.run_plan_version(
        plan_version_id,
        run_id,
        force=force,
        branch_id=branch_id,
    )
    lifecycle.finalise(result.status())
```

Do not catch a `CardreError` inside the `with` body. Let `__exit__` write the
failure diagnostic and manifest before the error is re-raised.

### 4. Finalise persisted unavailable `to_node` Runs through the lifecycle

File: `cardre/services/run_coordinator.py`

`run()` rejects new `to_node` requests before persistence, but
`execute_created_run()` can load a persisted `to_node` Run. Replace the direct
failed transition in `_execute_existing_running_run` with:

```python
if run_scope == "to_node":
    lifecycle = RunLifecycle.start(
        self._store,
        plan_version_id,
        run_id,
        execution_mode="to_node",
        branch_id=branch_id,
        target_step_id=target_step_id,
    )
    lifecycle.finalise(RunStatus.FAILED)
    self._raise_run_scope_not_available(run_scope, target_step_id)
```

This path has no existing path-specific persisted diagnostic. Do not invent one
in this work. It must gain a failed manifest whose `execution_mode` is
`"to_node"`, then raise the existing `RunScopeNotAvailableForLaunch` error.

### 5. Finalise dispatcher startup failures through the lifecycle

File: `cardre/services/run_coordinator.py`

In `_dispatch_async`, keep dispatch ownership in the dispatcher. When dispatch
raises `CardreError`, construct the existing `RUN_DISPATCH_FAILED` diagnostic,
then finalise through the lifecycle:

```python
except CardreError:
    diagnostic: JsonDict = {
        "code": "RUN_DISPATCH_FAILED",
        "message": "Dispatch failed; run marked as failed.",
        "severity": "error",
        "run_id": run_id,
        "plan_version_id": plan_version_id,
        "created_at": utc_now_iso(),
    }
    RunLifecycle.start(
        self._store,
        plan_version_id,
        run_id,
        execution_mode=run_scope,
        branch_id=branch_id,
        target_step_id=target_step_id,
    ).finalise(RunStatus.FAILED, diagnostic=diagnostic)
    raise
```

Remove the surrounding `ProjectStore.transaction("IMMEDIATE")` block. The
lifecycle owns the diagnostic append, manifest write, and transition ordering.

### 6. Make the dispatcher report errors, not terminal state

File: `cardre/execution/worker.py`

`ThreadRunDispatcher.dispatch` currently has two startup-failure paths:

- known `CardreError` values are raised for the coordinator to handle;
- unknown exceptions call `_record_dispatch_failure`, then are raised for the
  coordinator to handle again.

This duplicates the terminal path. Remove
`ThreadRunDispatcher._record_dispatch_failure(...)` and its invocation. On an
unexpected startup exception, remove the tracked thread and raise the existing
`CardreError(code=DISPATCH_FAILED_CODE, ...)`. The coordinator is now the one
terminal caller for both known and unexpected dispatch failures.

Update the `RunDispatcher` protocol documentation: dispatchers raise an
appropriate `CardreError` when startup fails; they do not persist diagnostics
or terminal Run state.

### 7. Finalise worker escapes through the lifecycle

File: `cardre/execution/worker.py`

Replace `_fail_run_if_running(...)` with lifecycle finalisation. Keep the
existing `RUN_WORKER_FAILED` diagnostic payload unchanged.

```python
from cardre.execution.run_lifecycle import RunLifecycle

diagnostic = {
    "code": WORKER_FAILED_CODE,
    "message": f"{exc_type.__name__ if exc_type else 'Exception'}: {exc_value}",
    "severity": "error",
    "run_id": request.run_id,
    "plan_version_id": request.plan_version_id,
    "branch_id": request.branch_id,
    "traceback": tb,
    "created_at": utc_now_iso(),
}

try:
    RunLifecycle.start(
        store,
        request.plan_version_id,
        request.run_id,
        execution_mode=request.run_scope,
        branch_id=request.branch_id,
        target_step_id=request.target_step_id,
    ).finalise(RunStatus.FAILED, diagnostic=diagnostic)
except Exception:
    logger.exception("Run worker failure finalisation failed for run %s", request.run_id)
```

The worker remains best-effort and must still close its store. Delete
`_fail_run_if_running`, its imports, and every call site after the new lifecycle
path has direct tests.

### 8. Finalise stale recovery through the lifecycle

File: `cardre/services/run_coordinator.py`

In `_sweep_stale_running_runs`, construct the existing `RUN_RECOVERED_STALE`
diagnostic first, including the optional `active_step_id`. Then replace the
direct transition and diagnostic append with:

```python
RunLifecycle.start(
    self._store,
    existing_run["plan_version_id"],
    existing_run["run_id"],
    execution_mode=existing_run["run_scope"],
    branch_id=existing_run.get("branch_id"),
    target_step_id=existing_run.get("target_step_id"),
).finalise(RunStatus.INTERRUPTED, diagnostic=diag)
```

The stale Run must receive an `interrupted` manifest. Its manifest must contain
the same Run ID, PlanVersion, Branch context, target Step context, and terminal
status as the persisted Run.

## Required Tests

Use real `ProjectStore` rows for all manifest and terminal-status assertions.
Mock only the execution or dispatch action needed to force the path.

### Lifecycle module tests

File: `tests/test_run_lifecycle.py`

Add focused cases:

1. `finalise(... diagnostic=...)` persists the diagnostic, writes the manifest,
   and transitions a `running` Run to `failed`.
2. `finalise(RunStatus.INTERRUPTED, diagnostic=...)` writes a manifest with
   `status == "interrupted"` and persists the diagnostic.
3. A context-manager body exception persists `RUN_BODY_EXCEPTION`, marks the
   Run failed, and writes a failed manifest.
4. A manifest write failure leaves the Run failed, records
   `RUN_FINALISATION_FAILED`, and does not leave the Run `running` or
   `succeeded`.

Example diagnostic assertion:

```python
run = RunRepository(store).get(run_id)
diagnostics = RunRepository(store).get_diagnostics(run_id)
manifest = json.loads(
    (store.root / "exports" / f"manifest-{run_id}" / "manifest.json").read_text()
)

assert run["status"] == "failed"
assert manifest["status"] == "failed"
assert diagnostics[-1]["code"] == "RUN_DISPATCH_FAILED"
```

### Coordinator tests

File: `tests/test_run_coordinator.py`

1. Extend stale recovery to assert:
   - status is `interrupted`;
   - `RUN_RECOVERED_STALE` is persisted;
   - the stale Run's manifest exists and says `interrupted`.
2. Seed a `running` persisted Run with `run_scope="to_node"`, call
   `execute_created_run(run_id)`, assert the existing
   `RunScopeNotAvailableForLaunch` error, and then assert a failed manifest.
3. Use a fake dispatcher that raises `CardreError(code="RUN_DISPATCH_FAILED")`.
   Assert the created Run is failed, has `RUN_DISPATCH_FAILED`, and has a failed
   manifest.

### Worker tests

File: `tests/test_worker_lifecycle.py`

Extend `test_worker_exception_produces_failed_run_with_diagnostic` to assert:

```python
assert run["status"] == "failed"
assert any(d["code"] == "RUN_WORKER_FAILED" for d in diagnostics)
manifest_path = s.root / "exports" / f"manifest-{run_id}" / "manifest.json"
assert json.loads(manifest_path.read_text())["status"] == "failed"
```

Add a dispatcher startup test if the existing coordinator fixture cannot inject
a failing `RunDispatcher`. It must prove no second dispatcher-owned terminal
write occurs: one `RUN_DISPATCH_FAILED` diagnostic, one failed manifest, and a
terminal failed Run.

### Matrix

| Path | Terminal status | Required diagnostic | Manifest status |
| --- | --- | --- | --- |
| Normal successful execution | `succeeded` | none required | `succeeded` |
| Execution body exception | `failed` | `RUN_BODY_EXCEPTION` | `failed` |
| Persisted unavailable `to_node` | `failed` | none newly added | `failed` |
| Dispatcher startup failure | `failed` | `RUN_DISPATCH_FAILED` | `failed` |
| Worker escape | `failed` | `RUN_WORKER_FAILED` | `failed` |
| Stale recovery | `interrupted` | `RUN_RECOVERED_STALE` | `interrupted` |
| Manifest write failure | `failed` | `RUN_FINALISATION_FAILED` | absent or incomplete, never successful |

## Negative Checks

Before completing implementation, search production code for terminal direct
transitions:

```bash
rg '\.transition\(' cardre -g '*.py'
```

Expected result:

- normal and recovery transitions are in `cardre/execution/run_lifecycle.py`;
- `cardre/store/run_repo.py` retains its repository implementation;
- no terminal transition remains in `run_coordinator.py` or `worker.py`.

Also confirm `_fail_run_if_running` and
`ThreadRunDispatcher._record_dispatch_failure` are deleted, and no caller
imports them.

## Verification

Run after implementation:

```bash
. .venv/bin/activate
ruff check cardre/execution/run_lifecycle.py cardre/services/run_coordinator.py cardre/execution/worker.py tests/test_run_lifecycle.py tests/test_run_lifecycle_errors.py tests/test_worker_lifecycle.py tests/test_run_coordinator.py tests/test_run_coordinator_edge_cases.py
pytest tests/test_run_lifecycle.py tests/test_run_lifecycle_errors.py tests/test_worker_lifecycle.py tests/test_run_coordinator.py tests/test_run_coordinator_edge_cases.py
make preflight
```

## Review Checklist

- [ ] `RunLifecycle.finalise` accepts an optional diagnostic and uses captured
  execution context.
- [ ] Context-manager body exceptions route their diagnostic through
  `finalise`.
- [ ] Persisted unavailable `to_node` Runs get failed manifests.
- [ ] Dispatcher startup failures have one lifecycle terminal path.
- [ ] Worker escapes get failed manifests.
- [ ] Stale recovery gets an interrupted manifest.
- [ ] Current diagnostic codes and context fields are preserved.
- [ ] The lifecycle module is the only external terminal-status writer.
- [ ] Normal manifests are written before their status transition.
- [ ] Manifest failure cannot leave a Run running or successful.
