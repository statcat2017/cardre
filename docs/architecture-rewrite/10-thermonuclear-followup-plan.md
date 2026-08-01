# 10 — Thermonuclear Followup: Implementation Plan

Scoped from the thermonuclear review comparing pre-refactor (`a130608`) to
current HEAD (`e09f9d6`). Three blockers (B1–B3) and four follow-ups (U1–U4).
Each section is self-contained: goal, exact files, code shape, and the tests
that pin the behaviour. A smaller LLM can implement each section independently.

**Order:** B3 → B2 → B1. B3 is a pure addition (safest first); B2 is a small
extract; B1 is the largest restructure and benefits from B2's canonical helper
already being in place.

**Before every push:** `ruff check --fix && make preflight`.
**Before every PR:** `scripts/pr-gate.sh`.
**Do not change behaviour.** Every existing test in `tests/application/runs/`,
`tests/application/execution/`, `tests/application/governance/`, and the parity
oracles (`test_scoring_export_parity`, `test_logistic_regression_known_input`,
`test_golden_fixtures_roundtrip`, `test_golden_report_bundle`,
`test_run_audit_integrity`) must stay green.

---

## B3 — Add the `._conn` architecture test (R5 missing guard)

### Goal
R5 removed every `uow._conn` access from `cardre/application/**` but never added
the guard test the plan mandated (`09b-review-remediation-plan.md`,
`09a-tidy-up-sprint-verification.md` §Finding 8). Import-linter catches
*imports* of `cardre.adapters` from application, but not runtime attribute
access. Add an AST scan so the regression door closes.

### Files
- **New:** `tests/test_application_no_conn_access.py`

### Code shape

```python
"""Architecture guard: cardre/application/** must never touch ``uow._conn``.

R5 pushed all persistence SQL behind typed repository operations on the
adapter. import-linter forbids *importing* ``cardre.adapters`` from
``cardre.application``, but a runtime ``uow._conn.execute(...)`` reach-through
would slip past import-linter. This test AST-scans every application module
and fails on any ``AttributeAccess`` whose attribute is ``_conn``.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_ROOT / "cardre" / "application"


def _application_python_files() -> list[Path]:
    return [p for p in APP_ROOT.rglob("*.py") if p.is_file()]


def _uses_conn_access(tree: ast.AST) -> list[str]:
    """Return a list of ``file:line`` locations accessing ``._conn``."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_conn":
            hits.append(f"{node.lineno}")
    return hits


def test_application_never_accesses_conn() -> None:
    offenders: list[tuple[str, str]] = []
    for path in _application_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for line in _uses_conn_access(tree):
            offenders.append((str(path.relative_to(REPO_ROOT)), line))
    assert not offenders, (
        "cardre/application/** must not access ``._conn`` (R5 invariant). "
        "Offenders:\n  " + "\n  ".join(f"{f}:{l}" for f, l in offenders)
    )
```

### Tests that pin it
- `test_application_never_accesses_conn` — passes on clean tree.
- **Negative proof (add as a second test):** parse a known-bad snippet and
  assert the helper *would* flag it, so the guard cannot silently rot:

```python
def test_conn_detector_flags_known_bad() -> None:
    bad = ast.parse("uow._conn.execute('SELECT 1')")
    assert _uses_conn_access(bad), "detector must flag ._conn access"

def test_conn_detector_ignores_unrelated() -> None:
    ok = ast.parse("uow.runs.list_for_plan_version()")
    assert not _uses_conn_access(ok)
```

### Acceptance
- `pytest tests/test_application_no_conn_access.py` green.
- `make preflight` green.
- Temporarily add `uow._conn.execute("SELECT 1")` to any file under
  `cardre/application/` → the test must fail. Revert.

---

## B2 — One canonical `is_stale` helper, single threshold source

### Goal
Stale-heartbeat logic is duplicated in `cardre/api/mappers.py:59-75`
(`_is_stale`, hard-coded default `300`) and
`cardre/application/runs/submit_run.py:198-224` (`_sweep_stale`, uses
`self._stale_heartbeat_seconds` from `Settings`). Two implementations of the
same rule with two threshold sources. Extract one pure helper into
`cardre/domain/diagnostics.py` (already the home of `utc_now_iso`/`parse_iso`)
and have both callers pass the threshold explicitly.

### Files
- **Edit:** `cardre/domain/diagnostics.py` — add `is_run_stale`.
- **Edit:** `cardre/api/mappers.py` — delete `_is_stale` + `_STALE_HEARTBEAT_SECONDS`; call `is_run_stale`.
- **Edit:** `cardre/application/runs/submit_run.py` — `_sweep_stale` calls `is_run_stale`.
- **New:** `tests/domain/test_is_run_stale.py`.

### Code shape

`cardre/domain/diagnostics.py` — append:

```python
from cardre.domain.run import Run, RunStatus


def is_run_stale(
    run: Run,
    *,
    stale_heartbeat_seconds: int,
    now_ts: float | None = None,
) -> bool:
    """A run is stale only if it is running AND its persisted heartbeat is
    older than the staleness threshold (or absent/malformed).

    A healthy running run with a recent heartbeat is fresh; a running run
    with no heartbeat is stale; a non-running run is never stale.

    ``now_ts`` is injectable for deterministic tests; defaults to now.
    """
    if str(run.status) != RunStatus.RUNNING.value:
        return False
    hb = run.heartbeat_at
    if hb is None:
        return True
    if now_ts is None:
        now_ts = datetime.now(UTC).timestamp()
    try:
        hb_ts = datetime.fromisoformat(hb).replace(tzinfo=UTC).timestamp()
    except (ValueError, TypeError):
        return True
    return (now_ts - hb_ts) > stale_heartbeat_seconds


__all__ = ["JsonDict", "is_run_stale", "parse_iso", "utc_now_iso"]
```

`cardre/api/mappers.py` — replace lines 56-75 with:

```python
from cardre.domain.diagnostics import is_run_stale  # add to imports


def run_to_response(
    run: Run,
    *,
    step_count: int = 0,
    executed_step_ids: list[str] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    stale_heartbeat_seconds: int,
) -> RunResponse:
    # ... unchanged body ...
    is_stale=is_run_stale(run, stale_heartbeat_seconds=stale_heartbeat_seconds),
```

Make `stale_heartbeat_seconds` **required** (no default) so no caller can
silently fall back to 300. The one call site (`routes/runs.py:35`) already
passes `container.settings.stale_heartbeat_seconds`.

`cardre/application/runs/submit_run.py` — `_sweep_stale` becomes:

```python
def _sweep_stale(self) -> None:
    from datetime import UTC, datetime

    from cardre.domain.diagnostics import is_run_stale
    from cardre.domain.run import RunStatus

    now_ts = datetime.now(UTC).timestamp()
    stale_candidates: list[tuple[str, str | None]] = []
    uow = self._uow_factory()
    try:
        for run in uow.runs.list_for_plan_version():
            if run.status != RunStatus.RUNNING.value:
                continue
            if is_run_stale(run, stale_heartbeat_seconds=self._stale_heartbeat_seconds, now_ts=now_ts):
                stale_candidates.append((run.run_id, run.heartbeat_at))
    finally:
        uow.close()

    from cardre.application.runs.finalize_run import FinalizeDiagnostic

    for run_id, hb in stale_candidates:
        self._finalize_run(
            run_id, "interrupted",
            diagnostic=FinalizeDiagnostic(code="RUN_STALE", message="Run was stale and has been interrupted"),
            stale_heartbeat_at=hb,
        )
```

### Tests that pin it

`tests/domain/test_is_run_stale.py`:

```python
"""Pin the single canonical staleness rule used by both SubmitRun and the
API mapper. All edge cases live here; the callers only thread the threshold."""
from __future__ import annotations

from cardre.domain.diagnostics import is_run_stale
from cardre.domain.run import Run, RunStatus


def _run(status: str = RunStatus.RUNNING.value, heartbeat_at: str | None = None) -> Run:
    return Run(run_id="r", plan_version_id="pv", status=status, heartbeat_at=heartbeat_at)


def test_non_running_is_never_stale():
    assert is_run_stale(_run(RunStatus.SUCCEEDED.value), stale_heartbeat_seconds=300) is False

def test_running_no_heartbeat_is_stale():
    assert is_run_stale(_run(heartbeat_at=None), stale_heartbeat_seconds=300) is True

def test_running_recent_heartbeat_is_fresh():
    from datetime import UTC, datetime, timedelta
    hb = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    assert is_run_stale(_run(heartbeat_at=hb), stale_heartbeat_seconds=300) is False

def test_running_old_heartbeat_is_stale():
    from datetime import UTC, datetime, timedelta
    hb = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
    assert is_run_stale(_run(heartbeat_at=hb), stale_heartbeat_seconds=300) is True

def test_malformed_heartbeat_is_stale():
    assert is_run_stale(_run(heartbeat_at="not-a-date"), stale_heartbeat_seconds=300) is True

def test_now_ts_is_injectable_and_deterministic():
    from datetime import UTC, datetime, timedelta
    hb = (datetime.now(UTC) - timedelta(seconds=400)).isoformat()
    # same heartbeat, a huge now_ts => stale; a tiny now_ts => fresh
    assert is_run_stale(_run(heartbeat_at=hb), stale_heartbeat_seconds=300, now_ts=1e12) is True
    assert is_run_stale(_run(heartbeat_at=hb), stale_heartbeat_seconds=300, now_ts=0.0) is False
```

Also extend `tests/application/runs/test_run_submission_contract.py` with one
test confirming `mappers.run_to_response` raises `TypeError` if
`stale_heartbeat_seconds` is omitted (proves the default is gone):

```python
def test_run_to_response_requires_stale_threshold():
    import pytest
    from cardre.api.mappers import run_to_response
    from cardre.domain.run import Run, RunStatus
    with pytest.raises(TypeError):
        run_to_response(Run(run_id="r", plan_version_id="pv", status=RunStatus.RUNNING.value))
```

### Acceptance
- `tests/domain/test_is_run_stale.py` green.
- Existing `test_run_submission_contract.py` (P1-1 stale-sweep tests) green —
  behaviour unchanged.
- `grep -rn "_is_stale\|_STALE_HEARTBEAT_SECONDS" cardre/` returns nothing.
- `make preflight` green.

---

## B1 — Decompose `ExecuteRun.__call__` (the 300-line god-method)

### Goal
`execute_run.py:40-343` is one method with 11 hand-rolled
`self._uow_factory()` try/commit/rollback/close blocks and a
`self._run_summary_ref` instance-state side-channel. Extract a fenced-UoW
context manager and a RunSummary step hook so the main loop reads as
orchestration, not inline plumbing. **Behaviour must not change** — the lease
fences, outbox ordering, and cancellation re-reads all stay.

### Files
- **Edit:** `cardre/application/runs/execute_run.py` — extract helpers, slim `__call__`.
- **New:** `tests/application/runs/test_execute_run_decomposition.py` — pins the structural invariants and the RunSummary hook contract.

### Step 1 — Extract `fenced_persist_uow` context manager

The repeated pattern (lines 168-294, 443-481) is: open UoW → assert lease →
do writes → commit / rollback / close. Extract:

```python
from contextlib import contextmanager
from cardre.domain.errors import LeaseLost


@contextmanager
def _fenced_persist(uow_factory, run_id: str, worker_generation: int):
    """Open a mutation UoW, assert the lease, commit on success.

    Raises ``LeaseLost`` (after rollback) if the run was cancelled or the
    lease was lost between the node finishing and this transaction. The
    caller decides whether ``LeaseLost`` means 'finalize cancelled' or 'raise'.
    """
    uow = uow_factory()
    try:
        uow.runs.assert_running_lease(run_id, worker_generation)
        yield uow
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()
```

A *read-only* sibling for the read blocks (lines 44-64, 130-134, 324-328,
372-416):

```python
@contextmanager
def _read_uow(factory):
    """Open + close a read-only UoW; rolls back on error (a no-op for reads)."""
    uow = factory()
    try:
        yield uow
    finally:
        uow.close()
```

### Step 2 — Extract `_persist_step_outputs` method

Move lines 168-294 (the per-step persist block) into:

```python
def _persist_step_outputs(
    self, command, step, pv_id, run, result, step_outputs,
    run_step_records, worker_generation,
) -> tuple[list[ArtifactRef], list[str]]:
    """Register artifacts, run-step, lineage, evidence edges, and outbox rows
    inside one fenced transaction. Returns (output_refs, outbox_ids)."""
    artifact_store = self._artifact_store
    with _fenced_persist(self._uow_factory, command.run_id, worker_generation) as uow:
        output_refs, staged_by_artifact = self._register_artifacts(uow, artifact_store, result, command, pv_id)
        run_step = self._insert_run_step(uow, command, step, pv_id, result)
        run_step_records[step.step_id] = run_step
        self._register_lineage(uow, command, step, pv_id, run, output_refs, staged_by_artifact, result, step_outputs, run_step_records)
        outbox_ids = self._enqueue_outbox(uow, command, pv_id, run_step, output_refs, staged_by_artifact, artifact_store)
    return output_refs, outbox_ids
```

### Step 3 — Extract `RunSummaryHook` (remove the special-case branch + instance state)

The `step.node_type == "cardre.technical_manifest_export"` branch at line 144
and the `self._run_summary_ref` side-channel at 153/277 are one specific node
type leaking into the general loop. Replace with a hook the loop calls
generically:

```python
class _RunSummaryHook:
    """Publishes the RunSummary before the technical-manifest step runs and
    remembers the ref so its lineage can be registered with that step."""

    def __init__(self, execute_run: "ExecuteRun") -> None:
        self._execute_run = execute_run
        self._summary_ref: ArtifactRef | None = None

    def before_step(self, step, step_outputs, run_step_records, command, pv_id, run, worker_generation) -> None:
        if step.node_type != "cardre.technical_manifest_export" or not step_outputs:
            return
        self._summary_ref = self._execute_run._publish_run_summary(
            command, pv_id, run, step_outputs, run_step_records, worker_generation,
        )
        if self._summary_ref is not None:
            step_outputs.setdefault(step.step_id, []).append(self._summary_ref)

    def register_own_lineage(self, uow, command, step, pv_id, run, input_id_set) -> None:
        sr = self._summary_ref
        if sr is not None and sr.artifact_id in input_id_set:
            uow.artifacts.register_lineage(
                run_id=command.run_id, run_step_id=f"{command.run_id}-{step.step_id}",
                plan_version_id=pv_id, step_id=step.step_id,
                artifact_id=sr.artifact_id, direction="input",
                branch_id=run.branch_id if hasattr(run, "branch_id") else None,
            )
```

Wire it in `__call__`:

```python
summary_hook = _RunSummaryHook(self)
# ... in the loop, before heartbeat:
summary_hook.before_step(step, step_outputs, run_step_records, command, pv_id, run, worker_generation)
# ... inside _persist_step_outputs, after the normal input-lineage loop:
summary_hook.register_own_lineage(uow, command, step, pv_id, run, input_id_set)
```

This deletes `self._run_summary_ref` instance state entirely — the hook owns
it and is constructed per `__call__`, so `ExecuteRun` becomes reentrant.

### Step 4 — The slimmed `__call__` (target shape, ~80 lines)

```python
def __call__(self, command: ExecuteRunCommand) -> None:
    self._artifact_store = self._artifact_store_factory()
    with _read_uow(self._uow_factory) as uow:
        run = uow.runs.get(command.run_id)
    if run is None or run.status not in ("created", "queued"):
        return
    pv_id = run.plan_version_id

    with _read_uow(self._uow_factory) as uow:
        pv = uow.plans.get_version(pv_id)
        steps = uow.plans.get_version_steps(pv_id) if pv is not None else None
    if pv is None:
        return

    try:
        from cardre.application.execution.topology import validate_topology
        validate_topology(steps)
        self._assert_nodes_available(steps)
        worker_generation = self._claim_run(command)
    except Exception:
        self._finalize_after_pre_exec_failure(command)
        return

    from cardre.application.execution.heartbeat import HeartbeatWatchdog
    watchdog = HeartbeatWatchdog(self._uow_factory, command.run_id, self._heartbeat_interval_seconds)
    watchdog.start()
    try:
        self._execute_steps(command, pv_id, run, steps, worker_generation)
    except Exception as exc:
        self._finalize_run(command.run_id, "failed", diagnostic=FinalizeDiagnostic(code="RUN_EXECUTION_FAILED", message=str(exc)))
    finally:
        watchdog.stop()


def _execute_steps(self, command, pv_id, run, steps, worker_generation) -> None:
    step_outputs: dict[str, list[Any]] = {}
    run_step_records: dict[str, RunStep] = {}
    summary_hook = _RunSummaryHook(self)
    for step in steps:
        if self._is_cancelled(command):
            self._finalize_run(command.run_id, "cancelled"); return
        summary_hook.before_step(step, step_outputs, run_step_records, command, pv_id, run, worker_generation)
        self._heartbeat(command)
        result = self._step_runner.run_step(pv_id, command.run_id, step, step_outputs, run_step_records)
        try:
            output_refs, outbox_ids = self._persist_step_outputs(
                command, step, pv_id, run, result, step_outputs, run_step_records, worker_generation,
            )
        except LeaseLost as exc:
            if "cancellation" in str(exc):
                self._finalize_run(command.run_id, "cancelled")
            return
        self._finalize_artifacts(self._artifact_store, output_refs, outbox_ids)
        if result.status == RunStepStatus.FAILED:
            self._finalize_run(command.run_id, "failed"); return
    if self._is_cancelled(command):
        self._finalize_run(command.run_id, "cancelled"); return
    self._finalize_run(command.run_id, "succeeded", worker_generation=worker_generation)
```

### Tests that pin it

`tests/application/runs/test_execute_run_decomposition.py`:

```python
"""Pin the structural invariants of the decomposed ExecuteRun.

These tests do NOT re-prove the R3 lease/cancellation behaviour (that lives in
test_dispatch_fencing_concurrency.py); they prove the decomposition preserved
the same observable contracts through a cleaner structure.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

EXEC = Path("cardre/application/runs/execute_run.py")


def _read() -> str:
    return EXEC.read_text()


# --- structural guards ---

def test_no_run_summary_ref_instance_state():
    """The _run_summary_ref side-channel must be gone (moved into the hook)."""
    src = _read()
    assert "_run_summary_ref" not in src, "instance state side-channel must be removed"

def test_no_inline_node_type_special_case_in_call():
    """__call__ must not special-case 'cardre.technical_manifest_export'."""
    tree = ast.parse(_read())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "__call__")
    src_segment = ast.get_source_segment(_read(), call) or ""
    assert "technical_manifest_export" not in src_segment, (
        "node-type special case must live in _RunSummaryHook, not __call__"
    )

def test_fenced_persist_helper_exists():
    assert "_fenced_persist" in _read(), "fenced-persist context manager must be extracted"

def test_call_body_under_100_lines():
    tree = ast.parse(_read())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "__call__")
    length = call.end_lineno - call.lineno + 1
    assert length <= 100, f"__call__ must stay under 100 lines (got {length})"

def test_uow_factory_call_count_in_call_dropped():
    """__call__ must not hand-roll 11 uow blocks; reads go through _read_uow."""
    tree = ast.parse(_read())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "__call__")
    count = sum(
        1 for n in ast.walk(call)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_uow_factory"
    )
    assert count <= 2, f"__call__ must not open raw UoWs directly (got {count}); use _read_uow/_fenced_persist"
```

Plus **behaviour-preservation** tests (run the existing composed-execution
suite as the oracle — do not duplicate it). Add one focused test proving the
RunSummary hook still fires for the manifest step:

```python
def test_run_summary_hook_publishes_before_manifest_step(monkeypatch, tmp_path):
    """The hook must publish RunSummary and inject it into the manifest step's
    inputs — the same observable behaviour as before the decomposition."""
    # Build a minimal ExecuteRun with a fake step_runner whose manifest step
    # records its input artifact ids; assert the RunSummary id is among them.
    # Reuse the _provision helper from test_uow_ownership.py for a real DB.
    ...
```

### Acceptance
- All existing tests in `tests/application/runs/` green (no behaviour change).
- `test_execute_run_decomposition.py` green.
- `execute_run.py` `__call__` ≤ 100 lines; `_run_summary_ref` gone; the
  `technical_manifest_export` string appears only in `_RunSummaryHook`.
- `make preflight` green.

---

## U1 — Restore the `score_scaling_known_input` parity oracle

### Goal
`06-sprint-plan.md:102` lists `test_score_scaling_known_input` as a preserved
parity oracle. It existed at `a130608` but is absent now. Either restore a
focused oracle or document that `test_golden_report_bundle` / the acceptance
pathway subsumes it.

### Files
- **Investigate:** `git show a130608:tests/test_score_scaling_known_input.py`
- **Decision:** if the golden bundle covers score scaling, add a one-line note
  to `06-sprint-plan.md` §"parity oracles" recording the subsumption and close
  this item. If not, restore the file adapted to the new node import path
  (`cardre/nodes/build/models.py` `ScoreScalingNode`).

### Test that pins it (if restored)
```python
def test_score_scaling_known_input(tmp_path):
    """ScoreScalingNode with known coefficients produces known scores."""
    # Adapt from a130608 version; assert exact score vector.
```

### Acceptance
- Either a restored focused test, or a documented subsumption note in the
  sprint plan. No silent drop.

---

## U2 — Type the manifest publisher port (`Any` → port)

### Goal
`report_queries.py:47,121` use `Any` for `manifest_publisher_factory`. R5's
typed-repository push should extend here.

### Files
- **New:** `cardre/application/ports/manifest_publisher.py`
- **Edit:** `cardre/application/reporting/report_queries.py`
- **Edit:** `cardre/bootstrap/container.py` (wire the port)

### Code shape

```python
# cardre/application/ports/manifest_publisher.py
from __future__ import annotations
from typing import Any, Protocol


class ManifestPublisherPort(Protocol):
    def list_manifests(self) -> list[dict[str, Any]]: ...
    def read(self, run_id: str) -> dict[str, Any] | None: ...


class ManifestPublisherFactoryPort(Protocol):
    def __call__(self, project_id: str) -> ManifestPublisherPort: ...
```

Then `report_queries.py`:
```python
from cardre.application.ports.manifest_publisher import ManifestPublisherFactoryPort

class ListReports:
    def __init__(self, uow_factory: UnitOfWorkFactory, manifest_publisher_factory: ManifestPublisherFactoryPort) -> None: ...
```

### Tests that pin it
- Existing `test_manifest_discovery.py` stays green (behaviour unchanged).
- Add `mypy` check: `mypy cardre/application/reporting/report_queries.py`
  passes with no `Any` on the factory param.

### Acceptance
- `make preflight` (runs mypy) green.

---

## U3 — Register a manifest descriptor row at finalization (remove FS scan from `ListReports`)

### Goal
`report_queries.py:77-88` scans the filesystem inside a query use case to
synthesize manifest entries. Cleaner: write a lightweight row to
`publication_outbox` (or a `manifests` view) at finalization so `ListReports`
is a pure DB query.

### Scope
This is a larger change touching the outbox schema and `FinalizeRun`. **Defer
unless the FS scan becomes a correctness or performance problem.** Document as
a known follow-up in `09b-review-remediation-plan.md` §"Not Fixed" so it is
tracked.

### Acceptance (if implemented)
- `ListReports` no longer calls `manifest_publisher_factory(...).list_manifests()`.
- A new test proves a finalized run appears in `ListReports` via a DB row only.

---

## U4 — `ListExports` manifest entries use `created_at=""`

### Goal
`report_queries.py:87` synthesizes manifest `ReportItem` with `created_at=""`.
If U3 is not done, at least derive a real `created_at` from the manifest file's
mtime or the run's `finished_at` so consumers aren't forced to handle empty
strings.

### Files
- **Edit:** `cardre/application/reporting/report_queries.py:77-88`

### Acceptance
- `test_manifest_discovery.py` asserts `created_at` is non-empty for manifest
  entries.

---

## Implementation order & dependency

```
B3 (additive, no risk) ──> B2 (small extract) ──> B1 (big restructure, uses B2's is_run_stale)
U1 (investigate + restore/note) — independent, do anytime
U2 (type port) — independent
U3 (defer; document first)
U4 (small; only if U3 not done)
```

Each item is one PR. Run `scripts/pr-gate.sh` per item; do not batch.

## Status

| Item | Status | Notes |
|------|--------|-------|
| B3 | **done** | `tests/test_application_no_conn_access.py`; 3 tests |
| B2 | **done** | `Run.is_stale` on `cardre/domain/run.py`; `mappers.py` + `submit_run.py` updated; oracle tests in `tests/test_domain_run.py` (circular-import fix: `is_run_stale` lives on `Run`, not `diagnostics.py` — `diagnostics` is imported by `run` and cannot import back) |
| B1 | **done** | `_read_uow`/`_fenced_persist` context managers, `_RunSummaryHook`, slimmed `__call__` (46 lines); `test_execute_run_decomposition.py` (9 tests) |
| U1 | **done** | `tests/nodes/test_score_scaling_known_input.py` restored against the new node contract |
| U2 | **done** | `cardre/application/ports/manifest_publisher.py`; `report_queries.py` typed |
| U3 | **deferred** | documented in `09b-review-remediation-plan.md` §Not Fixed |
| U4 | **done** | manifest entries carry run `finished_at`; pinned in `test_manifest_discovery.py` |