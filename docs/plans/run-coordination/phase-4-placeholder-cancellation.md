# Phase 4 — Unify placeholder cancellation via `finalise_run`

**Sprint:** `docs/plans/run-coordination-consolidation-sprint.md`
**Phase goal:** Replace every `store.finish_run(run_id, "cancelled")` placeholder-cancellation site in `RunService` with a single `_cancel_placeholder_run` helper that appends the `RUN_SHORT_CIRCUITED` diagnostic and calls `finalise_run(..., status="cancelled")`. This makes branch placeholders write a manifest, aligning with ADR 0004 (to-node placeholders already do).

**This is the only deliberate behaviour change in the sprint.** It is
maintainer-approved and locked by test 11.

## Files

### Read first (do not edit)
- `cardre/services/run_service.py` — three sites that call `finish_run(..., "cancelled")`:
  - preflight branch short-circuit (async path, ~line 99-112)
  - preflight to-node short-circuit (already uses `finalise_run`, ~line 120-141) — this is the template
  - `_execute_existing_running_run` branch short-circuit (~line 170-182)
  - `_execute_existing_running_run` post-exec short-circuit (~line 188-190)
- `cardre/run_lifecycle.py` — `finalise_run`, `RunFinalisation` (fields: `run_id`, `plan_version_id`, `status`, `execution_mode`, `finished_at`, `branch_id`, `target_step_id`, `in_scope_step_ids`).
- `cardre/audit.py` — `utc_now_iso`.
- `tests/test_run_coordination_contract.py` — test 11 (xfail) must turn GREEN.
- `tests/test_run_lifecycle.py::TestShortCircuitManifest` — the to-node template.

### Modify
- `cardre/services/run_service.py`
- `tests/test_run_coordination_contract.py` (remove the xfail on test 11)

## Tests to write first (RED → GREEN)

`test_branch_placeholder_cancellation_writes_manifest` (test 11) is currently
`xfail(reason="lands in phase 4")`. Remove the xfail marker. It must turn
GREEN after the implementation.

Do not add new tests — the contract is already locked by test 11 and the
existing `test_to_node_short_circuit_placeholder_has_manifest` in
`test_run_lifecycle.py`.

## Implementation

### Step 1 — Add `_cancel_placeholder_run` helper

In `cardre/services/run_service.py`, add a private method:

```python
def _cancel_placeholder_run(
    self,
    run_id: str,
    *,
    plan_version_id: str,
    execution_mode: str,
    branch_id: str | None,
    target_step_id: str | None = None,
    existing_run_id: str,
    reason: str,
) -> None:
    """Append RUN_SHORT_CIRCUITED and finalise the placeholder as cancelled.

    Uses RunLifecycle.finalise_run so a manifest is written (ADR 0004 atomic
    finalisation). The placeholder run is left with status 'cancelled' and a
    run_manifest artifact.
    """
    from cardre.run_lifecycle import finalise_run, RunFinalisation

    self._store.append_run_diagnostic(run_id, {
        "code": "RUN_SHORT_CIRCUITED",
        "message": (
            f"Run {run_id} short-circuited {reason} "
            f"(existing run {existing_run_id})"
        ),
        "severity": "info",
        "category": "lifecycle",
        "run_id": run_id,
        "plan_version_id": plan_version_id,
        "branch_id": branch_id,
        "created_at": utc_now_iso(),
    })
    finalise_run(self._store, RunFinalisation(
        run_id=run_id,
        plan_version_id=plan_version_id,
        status="cancelled",
        execution_mode=execution_mode,
        finished_at=utc_now_iso(),
        branch_id=branch_id,
        target_step_id=target_step_id,
    ))
```

### Step 2 — Replace the branch preflight site (async)

In `run_plan`, the branch preflight short-circuit (~line 99-112) currently
does `append_run_diagnostic` + `finish_run(placeholder_id, "cancelled")`.
Replace both with:

```python
self._cancel_placeholder_run(
    placeholder_id,
    plan_version_id=plan_version_id,
    execution_mode="branch",
    branch_id=branch_id,
    existing_run_id=result.run_id,
    reason=f"because branch has no stale steps",
)
return self._build_response(result.run_id)
```

### Step 3 — Replace the to-node preflight site (async)

The to-node preflight (~line 120-141) already uses `finalise_run` but with a
hand-rolled diagnostic. Replace the diagnostic + `finalise_run` with a call
to `_cancel_placeholder_run` so the message format is uniform:

```python
self._cancel_placeholder_run(
    placeholder_id,
    plan_version_id=plan_version_id,
    execution_mode="to_node",
    branch_id=branch_id,
    target_step_id=target_step_id,
    existing_run_id=result.run_id,
    reason=f"for to-node {target_step_id}",
)
return self._build_response(result.run_id)
```

### Step 4 — Replace the `_execute_existing_running_run` branch site

The branch short-circuit inside `_execute_existing_running_run` (~line 170-182)
currently does `append_run_diagnostic` + `finish_run(run_id, "cancelled")`.
Replace with:

```python
self._cancel_placeholder_run(
    run_id,
    plan_version_id=plan_version_id,
    execution_mode="branch",
    branch_id=branch_id,
    existing_run_id=ctx.short_circuit_run_id,
    reason="because branch has no stale steps",
)
return self._build_response(ctx.short_circuit_run_id)
```

### Step 5 — Replace the `_execute_existing_running_run` post-exec site

The post-exec short-circuit (~line 188-190):

```python
if result_id != run_id:
    self._store.finish_run(run_id, "cancelled")
    return self._build_response(result_id)
```

Replace with a `_cancel_placeholder_run` call. The `execution_mode` here
depends on `run_scope`: `"branch"` for branch, `"to_node"` for to-node,
`"full_plan"` for full. Derive it:

```python
if result_id != run_id:
    execution_mode = {
        "branch": "branch",
        "to_node": "to_node",
        "full_plan": "full_plan",
    }[run_scope]
    self._cancel_placeholder_run(
        run_id,
        plan_version_id=plan_version_id,
        execution_mode=execution_mode,
        branch_id=branch_id,
        target_step_id=target_step_id,
        existing_run_id=result_id,
        reason="(executor returned existing run)",
    )
    return self._build_response(result_id)
```

### Step 6 — Remove the xfail

In `tests/test_run_coordination_contract.py`, remove the
`@pytest.mark.xfail(reason="lands in phase 4")` marker (or the `# RED: lands in phase 4` comment block) from test 11.

## Verification commands

```bash
. .venv/bin/activate
ruff check --fix cardre/services/run_service.py tests/test_run_coordination_contract.py
pytest tests/test_run_coordination_contract.py tests/test_run_lifecycle.py \
       tests/test_run_orchestrator.py -q
CARDRE_GOVERNANCE=1 pytest tests/test_run_coordination_contract.py \
       tests/test_run_lifecycle.py::TestShortCircuitManifest -q
```

All must be green.

## Definition of done for this phase

- [ ] `_cancel_placeholder_run` exists in `RunService`.
- [ ] All four cancellation sites use it.
- [ ] No direct `finish_run(..., "cancelled")` remains in `run_service.py` for short-circuit placeholders.
- [ ] Test 11 (`test_branch_placeholder_cancellation_writes_manifest`) is GREEN.
- [ ] `test_to_node_short_circuit_placeholder_has_manifest` still GREEN.
- [ ] Branch short-circuit parity test (test 8) still GREEN.
- [ ] `ruff check` clean.

## Failure mode

- If `finalise_run` raises `RunLifecycleError` for a placeholder with no run
  steps: that is expected — the placeholder has no run steps, so
  `build_manifest_payload` produces a manifest with an empty `steps` list.
  Verify the store returns `[]` for `get_run_steps` on a placeholder, which
  `build_manifest_payload` handles (it iterates the list). If it raises, the
  issue is in `write_manifest` reading the run record — the placeholder run
  record exists (it was created by `store.create_run`), so `get_run` returns
  it. Do not skip the manifest; fix the helper.
- If the to-node parity test regresses: you changed the diagnostic message
  format. The test asserts the run_id, not the message. If a test asserts the
  message, update it to match the new uniform format — but check first whether
  the message is asserted anywhere downstream (frontend `latest_error`).
  The frontend displays `latest_error.code` and `latest_error.message` only
  when `status` is `failed`/`interrupted`, not `cancelled`, so the message
  change is safe.