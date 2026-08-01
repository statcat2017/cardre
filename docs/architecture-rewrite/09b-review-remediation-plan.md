# Thermonuclear Review Remediation Plan

## Review: a7bd161..6eeb025 (post-merge)
## Findings: 2 P1, 3 P2, 2 P3

---

## P1-1: Stale sweep's `interrupted` finalization can silently no-op

### Problem
`SubmitRun._sweep_stale` (submit_run.py:190-224) reads runs in one UoW, determines staleness, then calls `FinalizeRun("interrupted")` in a separate transaction. If the run self-finalized (succeeded/failed) between the sweep-read and the transition, `RunAlreadyFinalised` propagates out and **aborts the entire `SubmitRun`** — the new run is never created.

Conversely, a run whose heartbeat was *renewed* between the sweep-read and the transition is still `running` (the transition only checks `status = 'running'`, not `heartbeat_at`), so a live worker gets killed.

### Fix (3 changes)

#### Change 1: `submit_run.py:215-224` — swallow `RunAlreadyFinalised` in `_sweep_stale`

Wrap the `_finalize_run` call in `try/except RunAlreadyFinalised: pass`. A concurrent finalization of the stale run is the desired outcome, not an error that should abort the new submission.

```python
# Before (submit_run.py:215-224):
if is_stale:
    self._finalize_run(run.run_id, "interrupted", ...)

# After:
if is_stale:
    try:
        self._finalize_run(run.run_id, "interrupted", ...)
    except RunAlreadyFinalised:
        pass  # run finalized concurrently — desired outcome
```

#### Change 2: `run_repo.py` — add `transition_interrupted(run_id, heartbeat_cutoff_iso)` that guards on heartbeat staleness

```python
def transition_interrupted(self, run_id: str, heartbeat_cutoff_iso: str) -> bool:
    """Transition a stale run to 'interrupted' only if its heartbeat is still expired."""
    from cardre.domain.diagnostics import utc_now_iso
    now = utc_now_iso()
    cursor = self._conn.execute(
        "UPDATE runs SET status = ?, finished_at = ? "
        "WHERE run_id = ? AND status = 'running' "
        "AND (heartbeat_at IS NULL OR heartbeat_at < ?)",
        (RunStatus.INTERRUPTED.value, now, run_id, heartbeat_cutoff_iso),
    )
    return bool(cursor.rowcount > 0)
```

#### Change 3: `submit_run.py` — call `transition_interrupted` atomically, not `FinalizeRun`

Replace the `_finalize_run` call in `_sweep_stale` with a direct `transition_interrupted` call inside the same UoW that reads the runs. If the transition returns `True` (run was truly stale), then call `_finalize_run` to publish the manifest. If `False` (heartbeat was renewed), skip.

```python
# After (submit_run.py _sweep_stale):
uow = self._uow_factory()
try:
    all_active = uow.runs.list_for_plan_version()
    for run in all_active:
        if run.status != RunStatus.RUNNING.value:
            continue
        hb = run.heartbeat_at
        is_stale = ...
        if is_stale:
            heartbeat_cutoff = (now_ts - stale_seconds).isoformat()
            transitioned = uow.runs.transition_interrupted(run.run_id, heartbeat_cutoff)
            if transitioned:
                uow.runs.begin_worker_generation(run.run_id)
    uow.commit()
finally:
    uow.close()
# After commit, finalize the interrupted runs to publish manifests
```

### Tests
- `test_sweep_stale_does_not_abort_new_submission`: create a run, mark it succeeded concurrently, call `SubmitRun` → new run created, no exception.
- `test_sweep_stale_does_not_interrupt_renewed_heartbeat`: start a run, let heartbeat expire, renew heartbeat, call `SubmitRun` → original run stays `running`.
- `test_sweep_stale_interrupts_truly_stale_run`: start a run, let heartbeat expire (no renewal), call `SubmitRun` → original run becomes `interrupted`.

---

## P1-2: `ExplainStaleness` opens a write UoW for a pure read

### Status: FALSE POSITIVE

`ExplainStaleness` is wired via `routes/evidence.py:27-28`:
```python
def factory():
    return container.uow_factory.read_only(project_id)
```

This returns a `SqliteReadOnlyUnitOfWork` (connection.py:127-198) which does NOT execute `BEGIN IMMEDIATE`. The reviewer's finding incorrectly assumed `self._uow_factory()` returns a `SqliteUnitOfWork`, but the route injects a `read_only` factory. No fix needed.

---

## P2-1: `transition_success` with `worker_generation=None` bypasses lease fencing

### Problem
`RunRepo.transition_success` (run_repo.py:122-146) has `worker_generation: int | None = None` — the `None` default skips the generation guard. `ExecuteRun` always passes the generation, but the API surface allows a future caller to skip the fence.

### Fix (1 change)

#### `run_repo.py:122` — make `worker_generation` required (remove `None` default)

```python
# Before:
def transition_success(self, run_id: str, worker_generation: int | None = None) -> bool:

# After:
def transition_success(self, run_id: str, worker_generation: int) -> bool:
```

Also remove the `worker_generation is None` branch (run_repo.py:133-138) — only the generation-guarded UPDATE remains.

### Tests
- `test_transition_success_requires_generation`: call `transition_success(run_id)` without generation → `TypeError`.
- Existing tests already pass the generation.

---

## P2-2: `RefreshComparison` finalize/mark-published not per-row isolated

### Problem
`RefreshComparison` (refresh_comparison.py:221-227) finalizes all staging files in a loop, then marks all outbox rows `published` in one batch. If one finalize fails, the loop aborts and the remaining artifacts' outbox rows stay `pending` with their staging files unreleased.

### Fix (1 change)

#### `refresh_comparison.py:221-227` — per-row finalize + mark-published with error isolation

```python
# After commit, finalize each comparison artifact and mark its outbox row.
# A failure on one artifact does not block the others.
for staged, outbox_id in pending_publishes:
    try:
        self._artifact_writer.finalize(staged)
        with self._uow_factory.for_project(command.project_id) as mark_uow:
            mark_uow.publications.mark_published(outbox_id)
            mark_uow.commit()
    except Exception:
        # Leave the outbox row pending for reconciliation to retry.
        pass
```

### Tests
- `test_refresh_comparison_one_finalize_failure_does_not_block_others`: inject a failing `finalize` for the second of three challengers → first and third finalized + marked `published`, second stays `pending`.

---

## P2-3: `_publish_run_summary` opens N+1 write UoWs in execution hot path

### Problem
`_publish_run_summary` (execute_run.py:326-459) opens a new `SqliteUnitOfWork` (with `BEGIN IMMEDIATE`) per run-step lineage read and per artifact get — S+A write-lock acquisitions for a run with S steps and A artifacts.

### Fix (1 change)

#### `execute_run.py:346-396` — replace per-iteration `self._uow_factory()` with a single read-only UoW

```python
# Before (execute_run.py:347-395):
pv_uow = self._uow_factory()  # write UoW for reads
...
lineage_ruow = self._uow_factory()  # N+1 write UoWs
...
line_ruow = self._uow_factory()  # N+1 write UoWs

# After:
summary_uow = self._uow_factory.read_only(command.run_id)
try:
    # All reads from the single read-only UoW
    for spec in summary_uow.plans.get_version_steps(pv_id): ...
    run_steps = summary_uow.run_steps.get_for_run(command.run_id)
    for rs in run_steps:
        lineage = summary_uow.artifacts.artifacts_for_run_step(rs.run_step_id)
        ...
finally:
    summary_uow.close()
```

But `ExecuteRun`'s `self._uow_factory` is `lambda: uow_factory.for_project(project_id)` — a callable, not a factory object with `.read_only`. Need to also inject the factory object or a `read_only_factory`.

### Fix detail
- Add `read_only_factory: Callable[[], ReadOnlyUnitOfWork]` to `ExecuteRun.__init__`.
- In `container.py`, wire it as `lambda: uow_factory.read_only(project_id)`.
- In `_publish_run_summary`, use `self._read_only_factory()` for all reads.

### Tests
- `test_run_summary_uses_read_only_uow`: spy on UoW creation; assert `_publish_run_summary` opens exactly 1 read-only UoW, not S+A write UoWs.
- Existing composed-execution and launch-pathway tests verify correctness.

---

## P3-1: `_row_to_run` does not populate `Run.metadata`

### Problem
`RunRepo._row_to_run` (run_repo.py:15-30) constructs `Run(...)` without `metadata`, so `Run.metadata` is always `{}`. The `runs.metadata_json` column (schema.py:87) is written nowhere (always `'{}'`), so this is inert.

### Fix (1 change — optional cleanup)

#### `run_repo.py:15-30` — parse `metadata_json` in `_row_to_run`

```python
import json

def _row_to_run(r: Any) -> Run:
    metadata = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
    return Run(
        ...,
        metadata=metadata,
    )
```

And in `RunRepo.create` (run_repo.py:50-56), write `metadata_json`:
```python
self._conn.execute(
    "INSERT INTO runs (..., metadata_json) VALUES (..., ?)",
    (..., json.dumps(command.metadata or {})),
)
```

### Tests
- `test_run_metadata_roundtrip`: create a run with metadata, read it back, assert `run.metadata` matches.

---

## P3-2: `ExecuteRun` re-instantiates `artifact_store` up to 3× per step

### Problem
`ExecuteRun` calls `self._artifact_store_factory()` multiple times per step (execute_run.py:169, 280, 413). `FsArtifactStore` is stateless and cheap, but the repeated construction is unnecessary.

### Fix (1 change — optional cleanup)

#### `execute_run.py:36-37` — construct one `artifact_store` at `__call__` entry, reuse for entire run

```python
def __call__(self, command: ExecuteRunCommand) -> None:
    artifact_store = self._artifact_store_factory()
    ...
```

Replace all subsequent `self._artifact_store_factory()` calls with `artifact_store`.

### Tests
- Existing composed-execution tests verify correctness.

---

## Implementation Order

1. **P1-1** (stale sweep) — highest priority, can wedge submissions
2. **P2-1** (required generation) — 1-line API change, prevents future bugs
3. **P2-2** (per-row finalize isolation) — small change, improves governance robustness
4. **P2-3** (N+1 read UoWs) — moderate change, needs new constructor param
5. **P3-1** (metadata roundtrip) — optional cleanup
6. **P3-2** (single artifact_store) — optional cleanup

## Not Fixed

- **P1-2** (`ExplainStaleness` write UoW) — **false positive**. The route injects `container.uow_factory.read_only(project_id)` which returns `SqliteReadOnlyUnitOfWork` (no `BEGIN IMMEDIATE`). Verified against `routes/evidence.py:27-28` and `connection.py:127-198`.

## Proof Tests Summary

| Finding | Test File | Test Name |
|---------|-----------|-----------|
| P1-1 | `test_sweep_stale` | `test_sweep_stale_does_not_abort_new_submission` |
| P1-1 | `test_sweep_stale` | `test_sweep_stale_does_not_interrupt_renewed_heartbeat` |
| P1-1 | `test_sweep_stale` | `test_sweep_stale_interrupts_truly_stale_run` |
| P2-1 | `test_transition_success` | `test_transition_success_requires_generation` |
| P2-2 | `test_governance_ports` | `test_refresh_comparison_one_finalize_failure_does_not_block_others` |
| P2-3 | `test_composed_execution` | `test_run_summary_uses_read_only_uow` |
| P3-1 | `test_run_repo` | `test_run_metadata_roundtrip` |
| P3-2 | — | verified by existing composed-execution tests |