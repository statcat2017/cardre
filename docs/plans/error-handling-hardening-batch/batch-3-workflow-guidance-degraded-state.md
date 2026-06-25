# Batch 3 — Workflow guidance degraded-state diagnostics

## Goal

Eliminate every silent `try/except: pass` and `try/except: return None`
in `workflow_guidance_service.py` by decomposing the 158-line `build()`
method into `Result`-returning helpers with explicit fail-hard-vs-degrade
policies. After this batch, workflow guidance never reports a pathway as
fresh when staleness failed, never hides a failed readiness check, and
always carries structured `diagnostics` when degraded.

This is the canonical demonstration of the `Result[T, Diagnostic]` refactor
from Batch 0 — the pattern other batches follow.

## Findings addressed

- **WG-1** — staleness failure becomes `STALENESS_UNAVAILABLE` blocker,
  not `{}` (which defaults to "fresh").
- **WG-2** — run-step loading failure fails hard when `run_id` is
  supplied; otherwise degrades with `RUN_STEPS_UNAVAILABLE`.
- **WG-3** — report readiness failure returns `report_readiness_status =
  "unavailable"`, not `None`.
- **WG-4** — manual-binning editor-state failure blocks manual-binning
  with `MANUAL_BINNING_STATE_UNAVAILABLE`.
- **WG-5** — optional action-target count failure degrades with a
  warning diagnostic (not a blocker).
- **WG-6** — `_derive_phase` no longer maps readiness failure to
  `"validate"`; returns `"report"` or `"diagnostics"` with a degraded
  warning.
- **WG-7** — fallback action uses `resolve_diagnostics` when degraded
  diagnostics exist.
- **PLAN-2** — carried-forward status response exposes
  `evidence_source_run_id` / `is_carried_forward` (touched here because
  `_build_canonical_status_map` is the status source).
- **ST-1** (partial) — `compute_staleness`/`step_is_stale` raise
  `GraphValidationError` instead of `KeyError`; the swallow is removed so
  the error propagates. Full topology/staleness typing lands in Batch 6.

## Context you must read first

- `cardre/services/workflow_guidance_service.py:163-321` — the `build()`
  method to decompose. Four `try/except` blocks: staleness (232-237),
  run-step loading (242-246), manual-binning editor state (354-371),
  action-target count (386-402).
- `cardre/services/workflow_guidance_service.py:297` and `:448` — two
  `check_report_readiness` calls per `build()`; consolidate to one.
- `cardre/services/workflow_guidance_service.py:412-459` — `_derive_phase`
  catches `Exception` and returns `"validate"`.
- `cardre/services/workflow_guidance_service.py:476-563` —
  `_derive_next_action` fallback at 556-563.
- `cardre/staleness.py:23-50` — `compute_staleness`; `step_is_stale` at
  53-125; `_find_spec` at 128-132 raises `KeyError`.
- `cardre/topology.py:12-58` — `validate_topology` raises `ValueError`.
- `sidecar/models.py` and `sidecar/routes/plans.py:127-196` — the
  `WorkflowGuidance` response model and route.
- `cardre/errors.py` — `Result`, `Ok`, `Degraded`, `Fail`,
  `unwrap_or_raise`, `unwrap_or_degrade`, `Diagnostic` (from Batch 0).
- `docs/plans/error-handling-hardening-batch/README.md` — cross-cutting
  rules (no `except: pass`; diagnostics carry context).

## Changes

### 1. `cardre/staleness.py` — typed graph errors (ST-1 partial)

`_find_spec` (line 128) raises `KeyError(step_id)`. Replace with a
`GraphValidationError` carrying parent/child context:

```python
from cardre.errors import GraphValidationError

def _find_spec(step_id, steps):
    for s in steps:
        if s.step_id == step_id:
            return s
    raise GraphValidationError(
        f"Missing parent step {step_id!r} referenced by staleness walk.",
        context={"missing_step_id": step_id, "known_step_ids": [s.step_id for s in steps]},
        status_code=500,
    )
```

`step_is_stale` already calls `_find_spec` at line 96; the error now
propagates as a typed `GraphValidationError` instead of `KeyError`.

### 2. `cardre/topology.py` — typed graph errors

`validate_topology` (line 12) raises `ValueError`. Convert each
`raise ValueError(...)` to `GraphValidationError(...)` with context
(`step_id`, `parent_step_id`, cycle info as applicable). This makes
branch-evidence's `validate_topology(steps)` call
(`branch_evidence.py:97`) raise a typed error that Batch 6 will route.

### 3. `cardre/services/workflow_guidance_service.py` — decompose `build()`

Split `build()` into four helpers, each returning a `Result`:

```python
def _gather_evidence(self, ..., head_pv_id, branch_id, run_id) -> Result[EvidenceBundle]:
    """Gather staleness, run-step status, and report readiness.

    Policy:
      - staleness failure -> Degraded(empty map, [STALENESS_UNAVAILABLE])
        so callers treat unknown steps as NOT fresh (handled in status).
      - run-step load failure with run_id supplied -> Fail([RUN_STEPS_UNAVAILABLE])
      - run-step load failure without run_id -> Ok({})  (no run context)
      - report readiness failure -> Degraded(None, [REPORT_READINESS_UNAVAILABLE])
    """

def _derive_status(self, evidence: EvidenceBundle, ...) -> Result[StatusMap]:
    """Derive per-canonical status. Staleness-degraded steps are 'unknown',
    not 'fresh'."""

def _derive_phase(self, status: StatusMap, ..., readiness: Result) -> Result[str]:
    """Phase from status. Readiness failure returns 'report' or 'diagnostics'
    with a degraded warning, NOT 'validate'."""

def _derive_next_action(self, phase, status, blockers, diagnostics) -> dict:
    """Next action. If degraded diagnostics exist and no specific action
    resolves, use 'resolve_diagnostics' kind."""
```

`build()` becomes a short orchestrator:

```python
def build(self, plan_id, project_id, branch_id=None, run_id=None) -> WorkflowGuidanceResult:
    # ... validation unchanged ...
    evidence_r = self._gather_evidence(...)
    status_r = self._derive_status(evidence_r, ...)
    readiness_r = evidence_r.readiness  # the Result from gather
    phase_r = self._derive_phase(status_r, ..., readiness_r)
    blockers = self._collect_blockers(status_r)
    next_action = self._derive_next_action(phase_r, status_r, blockers, diagnostics)
    diagnostics = _collect_diagnostics(evidence_r, status_r, phase_r)
    degraded = any(is_degraded(r) or is_fail(r) for r in (evidence_r, status_r, phase_r))
    return WorkflowGuidanceResult(
        phase=unwrap_or_degrade(phase_r, default="diagnostics"),
        ...,
        degraded=degraded,
        diagnostics=diagnostics,
    )
```

### 4. WG-1 — staleness failure blocks, never fresh

In `_gather_evidence`, replace:

```python
try:
    staleness_map = compute_staleness(...)
except Exception:
    staleness_map = {}
```

with:

```python
try:
    staleness_map = compute_staleness(self._store, head_pv_id, branch_id=...)
    staleness_r = Ok(staleness_map)
except CardreError as e:
    staleness_r = Degraded({}, [Diagnostic(
        code="STALENESS_UNAVAILABLE",
        message="Could not compute staleness; pathway freshness is unknown.",
        source="workflow_guidance.compute_staleness",
        exception_type=e.__class__.__name__,
        context={"plan_version_id": head_pv_id, "branch_id": branch_id},
    )])
```

In `_derive_status`, a step absent from a **degraded** staleness map is
**not** treated as `is_stale=False`. Use a sentinel: if the staleness
result is `Degraded`, mark each step's `staleness_status = "unknown"` and
treat unknown as a blocker (`readiness="blocked"` with a
`STALENESS_UNAVAILABLE` step-level diagnostic). Only an `Ok` staleness
map yields definitive fresh/stale.

This is the core correctness fix: `staleness_map.get(step_id, False)`
previously defaulted missing entries to `False` (fresh). After this
change, a degraded map yields `unknown`, never `fresh`.

### 5. WG-2 — run-step loading fail-hard vs degrade

```python
if run_id:
    try:
        run_step_status = {rs.step_id: rs.status for rs in self._store.get_run_steps(run_id)}
        run_steps_r = Ok(run_step_status)
    except Exception as e:
        # run_id was supplied by the user -> fail hard, the request is invalid.
        run_steps_r = Fail([Diagnostic(
            code="RUN_STEPS_UNAVAILABLE",
            message=f"Could not load run steps for run {run_id}: {e}",
            context={"run_id": run_id},
            exception_type=e.__class__.__name__,
        )])
else:
    run_steps_r = Ok({})
```

`build()` checks `is_fail(run_steps_r)` and raises a
`WorkflowGuidanceServiceError` carrying the diagnostic, which the route
(`plans.py:157`) maps to a 400 `GUIDANCE_FAILED` with the diagnostic
exposed.

### 6. WG-3 — report readiness unavailable, not None

In `_gather_evidence`, consolidate the **two** `check_report_readiness`
calls (lines 297 and 448) into one. Store the `Result` on
`EvidenceBundle.readiness`. On exception:

```python
readiness_r = Degraded(None, [Diagnostic(
    code="REPORT_READINESS_UNAVAILABLE",
    message="Could not check report readiness.",
    context={"run_id": run_id, "branch_id": branch_id},
)])
```

`WorkflowGuidanceResult.report_readiness` becomes a dict with
`status: "unavailable"` when degraded, not `None`. The route maps this
to `WorkflowReportReadiness(ready=False, status="unavailable",
blockers=[], warnings=[ReadinessItem(code="REPORT_READINESS_UNAVAILABLE",
message=...)])`.

### 7. WG-4 — manual-binning editor-state failure blocks

In `_step_guidance_for` for `manual-binning`, replace `except Exception:
pass` (line 370) with:

```python
try:
    state = self._manual_binning_service.get_editor_state(plan_id, step_id=actual_step_id)
    if not state.ready:
        readiness = "blocked"
        explanation = state.blocked_reason or explanation
        primary_action = "Resolve manual-binning blockers"
except Exception as e:
    readiness = "blocked"
    explanation = "Manual-binning state could not be loaded."
    primary_action = "Resolve manual-binning blockers"
    diagnostics.append(Diagnostic(
        code="MANUAL_BINNING_STATE_UNAVAILABLE",
        message=f"Could not load manual-binning editor state: {e}",
        context={"step_id": actual_step_id, "plan_id": plan_id, "branch_id": branch_id},
    ))
```

The step is `blocked`, not silently `ready`.

### 8. WG-5 — optional action-target count degrades with warning

The action-target count (`_step_guidance_for` lines 386-402) is UI
convenience. Keep `action_target = None` on failure but attach a
non-blocking warning diagnostic:

```python
except Exception as e:
    action_target = None
    diagnostics.append(Diagnostic(
        code="ACTION_TARGET_UNAVAILABLE",
        message=f"Could not compute selected-variable count: {e}",
        severity="warning",  # not a blocker
        context={"step_id": actual_step_id},
    ))
```

### 9. WG-6 — `_derive_phase` no longer maps readiness failure to `"validate"`

In `_derive_phase`, replace:

```python
try:
    result = check_report_readiness(...)
    if not result.ready: return "report"
    return "ready"
except Exception:
    return "validate"
```

with logic that consumes the `readiness_r` Result from `_gather_evidence`
(no second call):

```python
if is_fail(readiness_r): return Fail(readiness_r.diagnostics)
if is_degraded(readiness_r):
    return Degraded("report", [Diagnostic(
        code="REPORT_READINESS_UNAVAILABLE",
        message="Report readiness could not be verified; phase is 'report' (degraded).",
    )])
# Ok
if not readiness_r.value.ready: return Ok("report")
return Ok("ready")
```

### 10. WG-7 — fallback next-action uses `resolve_diagnostics`

In `_derive_next_action`, before the final fallback (lines 556-563):

```python
if diagnostics and not any_specific_action_resolved:
    return {
        "kind": "resolve_diagnostics",
        "label": "Resolve diagnostics",
        "description": "Some checks could not be completed. Review diagnostics before continuing.",
        "run_scope": None,
        "step_id": None,
        "action_target": "diagnostics",
    }
# Existing fallback only when no diagnostics exist
return {"kind": "run_pathway", "label": "Run pathway", ...}
```

### 11. `sidecar/models.py` — `WorkflowGuidance` gains `degraded` + `diagnostics`

Add:

```python
class WorkflowDiagnostic(BaseModel):
    code: str
    message: str
    severity: str = "blocker"
    source: str | None = None
    context: dict[str, Any] = {}

class WorkflowGuidance(BaseModel):
    # ... existing fields ...
    degraded: bool = False
    diagnostics: list[WorkflowDiagnostic] = []
```

Regenerate `frontend/src/api/schema.d.ts`.

### 12. `sidecar/routes/plans.py:127-196` — emit `degraded` + `diagnostics`

Map `WorkflowGuidanceResult.degraded` and `.diagnostics` into the
response.

### 13. PLAN-2 — carried-forward status provenance

In `_build_canonical_status_map` (lines 578-635), when a step's status is
sourced from a carried-forward run step (via `is_carried_forward` or
`cardre_step_carried_forward`), include `evidence_source_run_id` and
`is_carried_forward` in the status dict:

```python
result[cid] = {
    ...,
    "is_carried_forward": bool(getattr(plan_step, "is_carried_forward", False) or ...),
    "evidence_source_run_id": getattr(rs, "run_id", None) if rs else None,
}
```

Surface these on `WorkflowStepGuidance` (optional fields) so the UI can
show "status carried forward from run X".

## Tests

- Monkeypatch `compute_staleness` to raise `GraphValidationError`:
  response has `degraded=true`, a `STALENESS_UNAVAILABLE` diagnostic, and
  no step's `readiness` is `"complete"` due to a missing staleness entry.
- Monkeypatch `get_run_steps` to raise with a supplied `run_id`:
  response is 400 `GUIDANCE_FAILED` with a `RUN_STEPS_UNAVAILABLE`
  diagnostic in `detail.diagnostics`.
- Monkeypatch `get_run_steps` to raise with **no** `run_id`: response is
  200 `degraded=false` (run context absent is not degradation), empty
  run-step status.
- Monkeypatch `get_editor_state` to raise for manual-binning:
  `step_guidance["manual-binning"].readiness == "blocked"` with a
  `MANUAL_BINNING_STATE_UNAVAILABLE` diagnostic.
- Monkeypatch `check_report_readiness` to raise: `report_readiness`
  is a dict with `status == "unavailable"` and a
  `REPORT_READINESS_UNAVAILABLE` warning; `phase == "report"`.
- `_derive_phase` with degraded readiness returns `"report"`, never
  `"validate"`.
- Fallback next-action: when diagnostics exist and no specific action
  resolves, `next_action.kind == "resolve_diagnostics"`.
- `compute_staleness` is called exactly once per `build()` (no double
  call).
- `check_report_readiness` is called exactly once per `build()`.
- Carried-forward step status includes `evidence_source_run_id` and
  `is_carried_forward=true` when sourced from a prior run.

## Acceptance criteria

- `rg "except Exception:\s*$" cardre/services/workflow_guidance_service.py`
  returns zero matches.
- `rg "except Exception:\s*pass" cardre/services/workflow_guidance_service.py`
  returns zero matches.
- No step is treated as fresh due to a missing staleness map entry when
  staleness computation failed.
- `WorkflowGuidance` response carries `degraded` and `diagnostics`;
  frontend types regenerated.
- `compute_staleness` and `check_report_readiness` are each called at
  most once per `build()`.
- `_derive_phase` never returns `"validate"` due to a readiness failure.
- `make lint && make typecheck && make test` pass.

## Out of scope

- Manual-binning annotation diagnostics (Batch 4).
- Report metadata corruption vs missing (Batch 5).
- Branch-evidence typed errors (Batch 6 — completes ST-1 by routing
  `GraphValidationError` from `validate_topology` in the branch path).
- Frontend rendering of `degraded`/`diagnostics` (Batch 4 covers the
  manual-binning UI; a follow-up can render the guidance banner).