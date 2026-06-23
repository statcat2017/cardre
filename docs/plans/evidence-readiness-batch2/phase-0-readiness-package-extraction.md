# Phase 0 — Readiness Package Extraction

## Goal

Make readiness have **one producer**. Today two code paths emit
readiness independently with two schemas; an explicit UI disclaimer
(`frontend/src/components/ReadinessPanel.tsx:114-116`) admits this. PR
4's stated acceptance ("readiness and evidence state cannot diverge
silently") cannot pass while the duplication stands. This phase extracts
a single readiness package and forces every consumer to call into it.

This is the radical refactor the rest of the batch depends on. Do it
first.

## Context you must read first

- `cardre/reporting/readiness.py` — current readiness module (263 LOC).
  Read all of it. Note `ReadinessBlocker` / `ReadinessWarning` (no
  `step_id`), `ReportReadinessResult`, and `check_report_readiness`.
- `cardre/reporting/limitation_codes.py` — blocker/warning code enum.
  This file does **not** move — it stays where both readiness and the
  collector can import it.
- `cardre/reporting/evidence_contract.py` — `REQUIRED_STEPS_*` lists and
  `find_evidence_for_canonical_step`. Already pure; only its import path
  will change for some callers.
- `cardre/services/workflow_guidance_service.py:294-317` — the
  **duplicate** producer. Note `report_mode="branch"` hard-coded at
  `:302` and `"step_id": None` hard-coded in the dict literal at
  `:308,312`. This is the divergence source.
- `cardre/services/report_generation_service.py:39-52` — ReadinessRoute
  service wrapper. Thin.
- `sidecar/routes/reports.py:49-68` — the readiness route.
- `sidecar/models.py:558-574` and `:799-811` — two readiness DTOs
  (`ReportReadinessResponse` and `WorkflowReportReadiness`).
- `frontend/src/components/ReadinessPanel.tsx:114-116` — the disclaimer
  that admits the two surfaces diverge. PR 0 should make this disclaimer
  obsolete; remove it as part of PR 4 once verification passes.

## Changes

### 1. Create the `cardre/readiness/` package

Move readiness logic out of `cardre/reporting/readiness.py` into a
dedicated package:

```
cardre/readiness/
    __init__.py        # re-exports public API
    check.py           # check_report_readiness (pure, store-bound)
    dto.py             # ReadinessBlocker, ReadinessWarning,
                       #   ReportReadinessResult (with step_id support)
    limitation_codes.py  # MOVED from cardre/reporting/limitation_codes.py
```

`limitation_codes.py` moves into the package because it is the readiness
contract, not a reporting concept. Re-export it from
`cardre/reporting/limitation_codes.py` as a deprecation shim for the
collector (the collector still emits collector-side limitations and must
keep importing it; see PR 4 for the collector-vs-readiness reduction).

### 2. Add `step_id` to the readiness DTO

In `cardre/readiness/dto.py`:

```python
@dataclass(frozen=True)
class ReadinessBlocker:
    code: str
    message: str
    step_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": str(self.code), "message": self.message,
                "step_id": self.step_id}
```

Do the same for `ReadinessWarning`. Update `ReportReadinessResult.to_dict`
to include `step_id`. Keep the class API compatible: existing callers
that construct `ReadinessBlocker(code, message)` without `step_id` still
work — `step_id` defaults to `None`. We will populate it in PR 1.

### 3. Make `WorkflowGuidanceService.build()` stop re-deriving readiness

Replace the body of `cardre/services/workflow_guidance_service.py:294-317`
with a call into `cardre.readiness.check.check_report_readiness` and
embed its `to_dict()` directly. Drop the manual dict construction at
`:304-315` (including the hard-coded `"step_id": None`).

```python
from cardre.readiness import check_report_readiness

# in build():
report_readiness = None
if run_id is not None and branch_id:
    try:
        result = check_report_readiness(
            store=self._store,
            project_id=project_id,
            run_id=run_id,
            target_branch_id=branch_id,
            report_mode="branch",
        )
        report_readiness = result.to_dict()
    except Exception:
        report_readiness = None
```

Note: `report_mode` here stays `"branch"` for now. **Do not change this
to champion mode.** Champion mode is the ExportPanel's job; the
workflow-guidance route's readiness badge is branch-scoped by design.
Add a one-line comment to that effect so the next reader doesn't
"helpfully" add a mode selector.

The `WorkflowReportReadiness` DTO (`sidecar/models.py:799-811`) must now
accept `step_id: str | None` on its blocker/warning items to match
`ReadinessItem`. Update the schema and regenerate
`frontend/src/api/schema.d.ts`.

### 4. Collapse the readiness sidecar DTOs

`ReportReadinessResponse` (`sidecar/models.py:558-574`) and
`WorkflowReportReadiness` (`sidecar/models.py:799-811`) currently differ
only by which route emits them. Make them share a single
`ReadinessItem` definition:

```python
class ReadinessItem(BaseModel):
    code: str
    message: str
    step_id: str | None = None

class ReportReadinessResponse(BaseModel):
    ready: bool = False
    status: str = ""
    blockers: list[ReadinessItem] = Field(default_factory=list)
    warnings: list[ReadinessItem] = Field(default_factory=list)
    # context echo fields added in PR 1; not yet populated here
```

Keep `WorkflowReportReadiness` as a thin subclass if the
`/workflow-guidance` route's shape needs the extra `ready` boolean at
the top level — but its blocker/warning items must be the same
`ReadinessItem`. No second code path.

### 5. Fix all import sites

Wholesale replacements:

- `from cardre.reporting.readiness import …` →
  `from cardre.readiness import …`
- `from cardre.reporting.limitation_codes import …` →
  `from cardre.readiness.limitation_codes import …` (or via the shim
  if you keep one in `cardre/reporting/`).

Files to audit:

- `cardre/services/workflow_guidance_service.py` (import +
  `:294-317` body).
- `cardre/services/report_generation_service.py` (import-only change).
- `sidecar/routes/reports.py` (no change needed; uses the service
  wrapper).
- `cardre/reporting/collector.py` — **does not import readiness**; only
  `limitation_codes`. Re-point its `limitation_codes` import through the
  shim or the new package; both work.
- All `tests/test_*.py` files importing `cardre.reporting.readiness` or
  `cardre.reporting.limitation_codes`.
- All `tests/test_*.py` files importing `cardre.reporting.readiness` or
  `cardre.reporting.limitation_codes`.

Use a global replace-and-run-tests cycle. Expect ~10 import sites.

### 6. Update `check-line-counts.py` exclusions (if needed)

If `scripts/check-line-counts.py` enumerates module paths, update paths.
If it uses discovery, no change needed.

## Tests

This PR adds **no new test logic** — it is pure refactor. The acceptance
gate is "all existing tests pass unchanged in behavior."

Add a single regression test:

- `tests/test_readiness_package.py::test_single_producer_shape` —
  asserts that `check_report_readiness(...).to_dict()` and the dict
  embedded in `WorkflowGuidance.report_readiness` have **the same keys
  and item structure** for a fixed scenario. Prove the two surfaces
  no longer diverge structurally.

Existing scenarios that must still pass unchanged:

- `tests/test_reporting.py::TestReadinessRegression` (`:526-645`):
  `target_branch_not_found`, `run_not_found`, champion/branch mode
  semantics, `to_dict` serialisation.
- `tests/test_reporting_acceptance.py`: `_review_manual_binning` helper
  (`:98-110`), `test_acceptance_1_full_champion_report`, branch/champion
  mode tests.
- `frontend/src/components/__tests__/ReadinessPanel.test.tsx` — all
  seven states still render.
- Any test asserting `ReportReadinessResponse` JSON shape.

Update test imports to the new package paths. No behavioral assertion
changes.

## Acceptance criteria

- `cardre/readiness/` exists with `check.py`, `dto.py`,
  `limitation_codes.py`, `__init__.py`.
- `cardre/reporting/readiness.py` is deleted (or reduced to a
  deprecation shim re-exporting `cardre.readiness.*`).
- `cardre/reporting/limitation_codes.py` is either deleted or a pure
  re-export shim.
- `cardre/services/workflow_guidance_service.py:304-315` no longer
  constructs readiness dicts by hand; it embeds
  `check_report_readiness(...).to_dict()`.
- `ReadinessBlocker` and `ReadinessWarning` carry `step_id: str | None`.
- `WorkflowReportReadiness` and `ReportReadinessResponse` share
  `ReadinessItem` (with `step_id`).
- `frontend/src/api/schema.d.ts` regenerated; diff committed.
- `pytest` passes.
- `npx tsc --noEmit` passes in `frontend/`.
- `npm test` passes in `frontend/`.
- `cardre/services/workflow_guidance_service.py` is **smaller** than
  before, ending the batch under 600 LOC if it does not already.
- `cardre/reporting/collector.py` is unchanged in line count (it only
  needed an import re-point).

## Out of scope for this phase

- Populating `step_id` on actual blockers — that is PR 1.
- Branch-scoping the manual-binning check — that is PR 1.
- Response context echo fields — that is PR 1.
- Removing `ReadinessPanel.tsx:114-116`'s disclaimer — that is PR 4
  (once consistency tests prove divergence is impossible).
- Reconciling collector-vs-readiness blocker codes — that is PR 4.