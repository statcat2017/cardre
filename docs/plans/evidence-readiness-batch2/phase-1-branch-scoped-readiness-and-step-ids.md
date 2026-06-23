# Phase 1 — Branch-scoped readiness with step_id attribution

## Goal

Make readiness evaluate the correct branch/run/step instead of an
incidental first matching step, and make every blocker navigable by
populating `step_id`. The response must self-describe the context it was
checked against.

## Context you must read first

- `cardre/readiness/check.py` (post-PR-0 path; was
  `cardre/reporting/readiness.py`) — focus on `check_report_readiness`
  at the file's bottom and the **manual-binning scan at
  `:241-254`** (line numbers will shift post-PR-0). This is the
  branch-unaware scan:
  ```python
  for s in store.get_plan_version_steps(plan_version_id):
      if s.canonical_step_id == "manual-binning" or s.node_type == "cardre.manual_binning":
          manual_binning_step = s
          break
  ```
- `cardre/step_id.py:77` — `resolve_required_steps(branch_id, canonical_step_ids, branch_step_map)`.
  Returns `{canonical_step_id: ResolvedStepRef | None}`. Already
  imported by readiness.py for the WOE/IV checks at `:174-217`.
- `cardre/step_id.py:21-29` — `ResolvedStepRef` carrying `step_id`,
  `resolved_branch_id`, `resolution` (`"exact"` / `"ancestor"`).
- `cardre/reporting/evidence_contract.py:18-49` — the
  `REQUIRED_STEPS_*` lists. `manual-binning` is in
  `REQUIRED_STEPS_COLLECTOR` only.
- `cardre/services/manual_binning_service.py:210-258` — WOE/IV
  warnings (`VARIABLE_SUMMARY_UNAVAILABLE`) emitted at `:245, :253`.
  These are editor-level warnings, not readiness-level. **Readiness
  talks about the `final-woe-iv` step for WOE/IV-missing, not the
  manual-binning step.** Keep this separation.
- `cardre/nodes/build/bins.py:462-502` — `reviewed` and
  `accept_automated` params on `ManualBinningNode`, mutual-exclusion
  enforced at `:501-502`.
- `sidecar/models.py:558-574` — `ReportReadinessResponse`. Will gain
  context echo fields in this PR.
- `cardre/services/workflow_guidance_service.py:249-253` — the
  canonical resolution call already used elsewhere in guided workflow.
- `tests/test_reporting.py:526-645` — readiness regression tests to
  extend.
- `tests/test_reporting_acceptance.py:98-110` — `_review_manual_binning`
  helper. Understand how the existing acceptance scenarios assert
  branch-scoping.
- `frontend/src/components/__tests__/ReadinessPanel.test.tsx` — already
  handles `step_id`; will need assertions updated for new echo fields.

## Changes

### 1. Branch-scope the manual-binning check

In `cardre/readiness/check.py` (post-PR-0), replace the linear scan
with the same `resolve_required_steps` call already used for WOE/IV.

```python
# Resolved together with other required steps, once per branch
resolved = resolve_required_steps(
    branch_id=target_branch_id,
    canonical_step_ids=["manual-binning"],
    branch_step_map=branch_step_map,
)
mb_ref = resolved.get("manual-binning")

if mb_ref is None:
    # The plan version has no manual-binning step at all, or only on
    # a different branch lineage.
    warnings.append(ReadinessWarning(
        LimitationCode.MANUAL_BINNING_NOT_REVIEWED,
        "No manual-binning step found on this branch.",
        step_id=None,
    ))
else:
    params = store.get_step_params(mb_ref.step_id)  # or equivalent
    if not params.get("reviewed", False) and not params.get("accept_automated", False):
        blockers.append(ReadinessBlocker(
            LimitationCode.MANUAL_BINNING_NOT_REVIEWED,
            "Manual binning has not been reviewed on this branch. ...",
            step_id=mb_ref.step_id,
        ))
```

Reuse the `branch_step_map` already built earlier in the function
(`readiness.py:148-217` constructed one) — do **not** rebuild it.

Target behaviour:

- branch report checks the target branch's manual-binning step;
- champion report checks the champion branch's manual-binning step;
- "no manual-binning step on this branch" becomes a warning with
  `step_id=None` (not a silent pass, not a hard blocker — the
  branch may legitimately rely on automated binning alone, but the
  user should know);
- "manual-binning step present but unreviewed" is a blocker with the
  resolved `step_id`.

### 2. Populate `step_id` on every blocker/warning with a target

Audit every `blockers.append(ReadinessBlocker(code, message))` in
`check_report_readiness`. For each, decide the resolved `step_id`:

| Blocker / warning source | Step target |
|---|---|
| `MANUAL_BINNING_NOT_REVIEWED` | resolved manual-binning step (branch-scoped) |
| `MISSING_WOE_IV_EVIDENCE_V1` | resolved `final-woe-iv` step — *not* manual-binning. The blocker answers "why is the report missing WOE/IV?" → final-woe-iv is the cause. |
| `MISSING_VALIDATION_ARTIFACT` | resolved `validation-metrics` step |
| `MISSING_SCORECARD_MODEL_ARTIFACT` | resolved `model-fit` step |
| `MISSING_SCORE_SCALING_ARTIFACT` | resolved `score-scaling` step |
| `MISSING_TARGET_DEFINITION` | resolved `target-definition` step |
| `CHAMPION_ASSIGNMENT_MISSING`, `NO_CHAMPION_ASSIGNMENT`, `TARGET_BRANCH_NOT_CHAMPION` | `None` — these are project-level, not step-level |

Use the same `resolve_required_steps` call (extend its
`canonical_step_ids` list to include every step for which you need
resolved IDs). One call, many resolutions.

If a step is missing entirely on the branch and the blocker code refers
to a step that should exist, set `step_id=None` and a message that says
"Step X not present on this branch." The frontend's "Go to step" button
must not render when `step_id` is `None` — `ReadinessPanel.tsx:135`
already gates on this.

### 3. Add context echo fields to `ReportReadinessResponse`

In `sidecar/models.py`:

```python
class ReportReadinessResponse(BaseModel):
    ready: bool = False
    status: str = ""
    blockers: list[ReadinessItem] = Field(default_factory=list)
    warnings: list[ReadinessItem] = Field(default_factory=list)
    # New context echo:
    project_id: str = ""
    target_branch_id: str = ""
    run_id: str = ""
    report_mode: str = "branch"
    plan_version_id: str = ""
    checked_at: str = ""  # ISO-8601 UTC, e.g. datetime.now(timezone.utc).isoformat()
```

`checked_at` is a **string** (not `datetime`) because the frontend cache
key needs a stable, comparable representation. Populate from the route
(`sidecar/routes/reports.py:49-68`), not from `check_report_readiness`
itself — the readiness function returns a `ReportReadinessResult` which
should stay pure over the store; the route decorates with echo context.

Populate the echo fields in the route handler:

```python
response = ReportReadinessResponse(
    **result.to_dict(),
    project_id=request.project_id,
    target_branch_id=request.target_branch_id,
    run_id=run_id,
    report_mode=request.report_mode,
    plan_version_id=plan_version_id,
    checked_at=datetime.now(timezone.utc).isoformat(),
)
```

The route already has `project_id`, `run_id`, `target_branch_id`,
`report_mode` from the request; fetch `plan_version_id` from the run.

Do **not** add echo fields to `WorkflowReportReadiness`. The
workflow-guidance route's `report_readiness` is a sub-shape embedded in
`WorkflowGuidance`; `WorkflowGuidance` already carries
`branch_id`, `run_id`, etc. at its top level. Echoing in both shapes
redundantly risks drift. The frontend reads context from
`WorkflowGuidance` directly.

### 4. Update frontend types

`frontend/src/api/schema.d.ts` is regenerated from OpenAPI. After
extending the models, run:

```
python3 scripts/generate-openapi-types.py
cd frontend && npx tsc --noEmit
```

Commit the regenerated `schema.d.ts` in this PR.

## Tests

### Backend (extend `tests/test_reporting.py::TestReadinessRegression`)

Add:

1. **`test_manual_binning_reviewed_on_other_branch_blocks_target`**
   - Create two branches A and B off the same plan version.
   - Mark manual-binning reviewed on branch A's step only.
   - `check_report_readiness(target_branch_id=B)` returns blocked with
     `MANUAL_BINNING_NOT_REVIEWED` and `step_id` pointing at **B's**
     manual-binning step, not A's.
   - `check_report_readiness(target_branch_id=A)` returns ready (no
     blocker for this code).

2. **`test_branch_specific_manual_binning_step_id_returned`**
   - Assert the blocker's `step_id` is exactly the branch-owned step id
     (e.g. `manual-binning__br_<branchB>`), not the plan-version step id
     (e.g. `manual-binning`).

3. **`test_champion_mode_uses_champion_branch`**
   - Champion branch = C; target = some other branch; set reviewed on
     C only.
   - `check_report_readiness(target_branch_id, report_mode="champion")`
     resolves the champion assignment via
     `store.get_champion_assignment(plan_id, target_branch_id)` and
     evaluates manual-binning against the champion branch's step.
   - Assert the blocker (if any) carries the champion branch's step id.

4. **`test_no_champion_assignment_blocks_champion_mode_warns_branch_mode`**
   - No champion assignment set.
   - Champion mode → blocker `CHAMPION_ASSIGNMENT_MISSING`,
     `step_id=None`.
   - Branch mode → warning `NO_CHAMPION_ASSIGNMENT`, `step_id=None`.

5. **`test_response_includes_context_fields`**
   - Issue the readiness check via the sidecar route (or via
     `ReportGenerationService.check_readiness` with stub response).
   - Assert all six echo fields are populated and `checked_at` parses
     as ISO-8601.

6. **`test_blocker_step_ids_populated_for_known_codes`**
   - Drive a full-blocker scenario (target definition missing,
     manual-binning unreviewed, WOE/IV missing, validation missing,
     model missing, scaling missing).
   - Assert each blocker's `step_id` resolves to the expected canonical
     step on the target branch, except `CHAMPION_ASSIGNMENT_MISSING`
     (must be None).

### Frontend

Update existing `ReadinessPanel.test.tsx` assertions:

- Assert `target_branch_id`, `run_id`, `report_mode`, `checked_at` are
  rendered in the freshness copy (the existing test exercises the
  freshness; extend its assertions).
- The "Go to step" button tests at `ReadinessPanel.test.tsx:105-130`
  already prove the wiring; no change needed beyond ensuring the mocked
  blocker carries the now-expected `step_id: "step-manual-binning-brB"`.

## Acceptance criteria

- `MANUAL_BINNING_NOT_REVIEWED` readiness cannot be satisfied by a
  different branch's manual-binning step.
- Readiness response (`ReportReadinessResponse`) echoes
  `project_id`, `target_branch_id`, `run_id`, `report_mode`,
  `plan_version_id`, `checked_at`.
- Every readiness blocker/warning with a step target carries a
  non-null `step_id` matching the branch-owned step id.
- Blockers without a step target (`CHAMPION_ASSIGNMENT_MISSING`) use
  `step_id=None` and the frontend does not render "Go to step" for
  them.
- `cardre/readiness/check.py` is no larger than `readiness.py` was
  pre-PR-0; expect ~+15 lines for the manual-binning change minus the
  linear scan.
- `pytest tests/test_reporting.py` passes.
- Regenerated `schema.d.ts` committed.
- `npx tsc --noEmit` and `npm test` pass in `frontend/`.

## Out of scope for this phase

- Removing the disclaimer at `ReadinessPanel.tsx:114-116` — PR 4.
- Adding test assertions that readiness and `EvidenceTab` agree — PR 4.
- Touching the collector's own limitation emission — PR 4.
- New backend evidence summaries — PR 2.