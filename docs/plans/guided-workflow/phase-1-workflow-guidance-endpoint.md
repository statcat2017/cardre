# Phase 1 — Workflow guidance backend endpoint

You are implementing **Phase 1** of the Guided Workflow Sprint
(`docs/plans/guided-workflow-sprint.md`). Phase 0 must be merged.

Read first:
- `docs/adr/0008-workflow-guidance-seam-and-keys.md`
- `cardre/reporting/readiness.py` (`check_report_readiness`)
- `cardre/services/manual_binning_service.py` (`get_editor_state`)
- `cardre/staleness.py` (`compute_staleness`)
- `cardre/services/plan_service.py` (`get_plan_with_status`)
- `cardre/services/plan_dto.py`
- `sidecar/routes/plans.py`
- `docs/architecture/artifact-evidence-access.md`

## Goal

Implement `GET /plans/{plan_id}/workflow-guidance?branch_id=…&run_id=…`
that returns a single `WorkflowGuidance` object describing phase, next
action (with suggested `run_scope`), blockers, per-step readiness, and
report readiness. The route is a thin delegate to
`WorkflowGuidanceService`, which itself delegates to the four existing
readiness sources — **no re-implementation**.

## Endpoint

```
GET /plans/{plan_id}/workflow-guidance?branch_id=…&run_id=…
```

- At least one of `branch_id` / `run_id` is required. 400 if both absent.
- If only `run_id`: resolve `branch_id` from the run's `plan_version_id`
  against `plan_branches.head_plan_version_id`. If none, no branch context
  (single-branch/fallback project).
- If only `branch_id`: resolve `run_id` from the most recent successful run
  attached to `branch.head_plan_version_id` via `list_runs`. If none, phase
  is `setup` or `build` (no report readiness).
- If both: must satisfy `run.plan_version_id == branch.head_plan_version_id`
  (or a proven ancestor via `plan_versions` table). 400 otherwise.
- `project_id` query param optional, mirroring `getPlan`.

## Response

Pydantic in `sidecar/models.py`. Field names must match ADR 0008 exactly:

```python
class WorkflowNextAction(BaseModel):
    kind: Literal[
        "import_dataset", "configure_step", "run_pathway",
        "review_evidence", "edit_bins", "resolve_blocker", "export_report",
    ]
    label: str
    description: str
    run_scope: Literal["full_plan", "branch", "to_node"] | None
    step_id: str | None
    action_target: str | None  # e.g. "exports" | "manual_binning"

class WorkflowBlocker(BaseModel):
    code: str
    message: str
    step_id: str | None
    severity: Literal["blocker", "warning"]

class WorkflowStepGuidance(BaseModel):
    readiness: Literal["ready", "blocked", "needs_config", "stale", "complete"]
    primary_action: str
    explanation: str
    evidence_kinds: list[str]  # evidence kind names the step produces/expects

class WorkflowReportReadiness(BaseModel):
    ready: bool
    status: str
    blockers: list[ReadinessItem]  # reuse existing model; add step_id: str | None
    warnings: list[ReadinessItem]

class WorkflowGuidance(BaseModel):
    phase: Literal["setup", "build", "validate", "report", "ready"]
    next_action: WorkflowNextAction
    blockers: list[WorkflowBlocker]
    step_guidance: dict[str, WorkflowStepGuidance]  # keyed by canonical_step_id
    report_readiness: WorkflowReportReadiness | None
    branch_id: str | None
    run_id: str | None
```

**Add `step_id: str | None` to `ReadinessItem`** (not new model). Phase 6 uses
this structured field, not message parsing. This is a one-line, additive
schema change.

`step_guidance` is keyed by **canonical** step ID, not by the branch-owned
postfixed ID. The service resolves via `branch_step_map`. Frontend consumers
use `canonicalizeStepId` (landed in Phase 0) to look up.

## Phase Derivation

`phase` is backend-derived from a new module
`cardre/services/workflow_guidance_service.py`. Mirror of the frontend's
`SECTION_ORDER` + `STEP_DISPLAY_METADATA.sections` lives **in Python** under
`cardre/services/workflow_guidance_service.py` as `BUILD_STREAM_CANONICAL_IDS`
and `VALIDATE_STREAM_CANONICAL_IDS` constants. Do not import the frontend
file. The constants encode what `CONTEXT.md` already says:

- **BUILD_STREAM_CANONICAL_IDS**: population, target, sample-definition,
  exclusions, split, profile, fine-classing, woe-iv, clustering,
  variable-selection, manual-binning, woe-transform, logistic-regression,
  score-scaling.
- **VALIDATE_STREAM_CANONICAL_IDS**: apply-woe, apply-model,
  validation-metrics, cutoff-strategy.

**Algorithm (single function `_derive_phase`):**

1. If no `train`-role artifact is associated with the project's runs →
   `"setup"`. (Extend the `_check_oot_exists` pattern in `readiness.py` to a
   `_check_role_exists` helper on the store; do not import `_check_oot_exists`
   out of file — add a sibling.)
2. If any build-stream canonical step from `step_guidance` has
   `readiness in {"blocked", "needs_config", "stale"}` → `"build"`.
3. Else if any validate-stream canonical step has `readiness in
   {"blocked", "needs_config", "stale"}` → `"validate"`.
4. Else compute `report_readiness`:
   - If `report_readiness is None` (no run resolved) → `"build"`.
   - If `report_readiness.ready == False` → `"report"`.
   - Else → `"ready"`.

## Step Guidance Derivation

For each canonical step in `BUILD_STREAM` ∪ `VALIDATE_STREAM`:

1. Resolve the step instance via `branch_step_map` (Phase 0 server-side
   helper or `store.get_branch_step_map`).
2. Get `StepStatusItem` via `PlanService.get_plan_with_status`
   (`plan_dto.py`), filtered by the branch's `head_plan_version_id`.
3. Compute `readiness`:
   - `complete` if `status == "succeeded"` and `not is_stale`.
   - `stale` if `is_stale`.
   - `needs_config` if `status == "not_run"` and any required param is unset.
   - `blocked` if any blocker (below) maps to this step.
   - `ready` if `not_run` and upstream is complete and no config required.
4. `primary_action` and `explanation` are localised constants keyed by
   canonical step ID. Keep them as Python constants in the same module; do
   not externalise to i18n files yet.
5. `evidence_kinds` comes from `EvidenceKind` enum values the step's
   registered node type declares as outputs. Use the node registry's
   `output_evidence_kinds()` if it exists; otherwise derive from
   `EvidenceKind` strings hardcoded per canonical step in this module
   (acceptable for this sprint).

## Manual-Binning Readiness

Do **not** duplicate `ManualBinningService.get_editor_state`. Call it inside
`WorkflowGuidanceService._step_guidance_for("manual-binning", …)`:

```python
state = ManualBinningService(self._store).get_editor_state(plan_id, step_id=resolved_step_id)
if not state.ready:
    step_guidance["manual-binning"] = WorkflowStepGuidance(
        readiness="blocked" if state.blocked_reason else "needs_config",
        primary_action="Resolve manual-binning blockers",
        explanation=state.blocked_reason,
        evidence_kinds=["cardre.binning.v1", "cardre.woe_iv_evidence.v1"],
    )
```

`get_editor_state` may raise `PlanValidationError` if upstream is not ready —
catch and translate to `needs_config`.

## Report Readiness

If `run_id` is resolved:

```python
result = check_report_readiness(
    store=self._store,
    project_id=project_id,
    run_id=run_id,
    target_branch_id=branch_id or "",
    report_mode="branch",  # guidance always uses branch mode for the readiness pulse
)
```

Guidance uses **branch mode** for the passive readiness pulse. Champion mode
is a user-explicit action; do not surface champion-only blockers as journey
blockers. Champion-specific blockers are warnings here.

`report_readiness.blockers` and `warnings` carry over the existing
`ReadinessItem` shape plus the new optional `step_id` (see Phase 6).

## Next Action + Run Scope

`next_action.run_scope`:

- `"full_plan"` — phase is `setup` or `build` and there are multiple stale
  steps across the build stream.
- `"to_node"` — only one canonical step is stale; `step_id` populated.
- `"branch"` — only branch-owned steps are stale.
- `None` — action is not a run (e.g. `import_dataset`, `edit_bins`,
  `export_report`).

`next_action.kind` precedence:

1. `setup` phase → `import_dataset`.
2. Any `blocked` step → `resolve_blocker` (with that step's ID).
3. Manual-binning readiness `ready` (per Phase 5 runtime use) → `edit_bins`.
4. Any `needs_config` step → `configure_step`.
5. Any `stale` step → `run_pathway` (with the run_scope computed above).
6. `validate`/`report` phase with `report_readiness.ready == False` →
   `resolve_blocker` if blockers, else `run_pathway`.
7. `ready` phase → `export_report`.

`label`, `description`, `action_target` are localised constants keyed by
`kind + canonical_step_id`, kept in a private dict in the same module.

## Files

| File                                              | Action     | Content                                                                                       |
|---------------------------------------------------|------------|-----------------------------------------------------------------------------------------------|
| `cardre/services/workflow_guidance_service.py`    | Replace scaffold | Implement `WorkflowGuidanceService.build(plan_id, project_id, branch_id?, run_id?) -> WorkflowGuidanceResult`. Add `_derive_phase`, `_derive_step_guidance`, `_derive_next_action`, `_resolve_run_and_branch`. |
| `sidecar/models.py`                               | Edit       | Add `WorkflowGuidance`, `WorkflowNextAction`, `WorkflowBlocker`, `WorkflowStepGuidance`, `WorkflowReportReadiness`. Add `step_id: str \| None` to `ReadinessItem`. |
| `sidecar/routes/plans.py`                         | Edit       | Add `GET /{plan_id}/workflow-guidance` route. Thin delegate. Resolve `project_id` like `get_plan`. 400 on missing keys. |
| `sidecar/main.py`                                 | Edit if needed | Ensure `plans.router` is already registered (it is). |
| `frontend/src/api/schema.d.ts`                   | Regenerate | Run `python3 scripts/generate-openapi-types.py` after backend changes. |
| `frontend/src/api/client.ts`                      | Edit       | One-liner derived from generated operation: `getWorkflowGuidance: (planId, qs) => fetchJson<…>(\`/plans/${planId}/workflow-guidance?${qs}\`)`. Use the generated `paths["/plans/{plan_id}/workflow-guidance"]["get"]` response type via `components["schemas"]["WorkflowGuidance"]`. No inline duplicate. |
| `frontend/src/types.ts`                           | Edit       | Re-export `WorkflowGuidance` etc. from `./api/schema`. No inline shapes. |
| `tests/test_workflow_guidance_service.py`         | Create     | Unit tests: assert the service calls each delegate exactly once per query. Mock the four delegates. Assert key-resolution rules. Assert phase derivation for each branch. |

## Sequence

1. Define Pydantic models in `sidecar/models.py`.
2. Add `step_id` to `ReadinessItem` (additive — existing routes ignore it).
3. Implement `WorkflowGuidanceService.build` + helpers. Pure delegation.
4. Add the route in `sidecar/routes/plans.py`. Wire into `main.py` (already
   registered via `plans.router`).
5. Regenerate `frontend/src/api/schema.d.ts` via
   `python3 scripts/generate-openapi-types.py`. Commit the regen.
6. Add the one-liner `client.ts` method. Update `types.ts` to re-export.
7. Write `tests/test_workflow_guidance_service.py` with mocked delegates.
8. Run `python3 -m pytest tests/test_workflow_guidance_service.py tests/test_sidecar_api.py -q`
   and `cd frontend && npx tsc --noEmit`.

## Acceptance Criteria

The endpoint answers, for any plan/branch/run combination the project has:

- "What should the user do next?" — populated `next_action`. Verifiable
  with: no-dataset project → `kind=="import_dataset"`; ran-to-stale project →
  `kind=="run_pathway"` with a `run_scope`; ready project →
  `kind=="export_report"`.
- "Which step is blocking launch?" — `step_guidance[sid].readiness ==
  "blocked"` for the actual blocker; `next_action.kind ==
  "resolve_blocker"`; `next_action.step_id` populated.
- "Which evidence is missing?" — `step_guidance[sid].evidence_kinds` lists
  what is expected; `report_readiness.blockers` carry codes from
  `LimitationCode.MISSING_WOE_IV_EVIDENCE_V1` etc.
- "Is the report ready?" — `report_readiness.ready` is populated when
  `run_id` resolvable, else `report_readiness is None`.
- "Is manual binning ready?" — `step_guidance["manual-binning"].readiness`
  reflects the live `get_editor_state` result.

Mechanical:

- `tests/test_workflow_guidance_service.py` asserts each of
  `check_report_readiness`, `compute_staleness`,
  `ManualBinningService.get_editor_state`, and `PlanService.get_plan_with_status`
  is called exactly once per `build()` call. This is the
  no-duplication-of-logic guard ADR 0008 mandates.
- `python3 -m pytest tests/ -q` green. `cd frontend && npx tsc --noEmit`
  green.
- `git diff --exit-code` after `scripts/generate-openapi-types.py` passes
  in CI.

## Non-Goals

- Frontend consumption (Phase 2).
- Evidence routes (Phase 4).
- Champion-mode journey blockers (journey uses branch mode always).
- Per-step `primary_action` localisation (only English constants).

## Drop-Dead Notes

- **Never parse blocker messages for step IDs.** Add `step_id` to
  `ReadinessItem` and join `blocker.code` → canonical step mapping from
  `LimitationCode` directly inside `_derive_step_guidance`. See `cardre/reporting/limitation_codes.py`.
- **Never re-run the pathway from guidance.** Guidance is read-only.
- **Do not include `manual_review` as a phase.** ADR 0008 fixes this.
- The Phase 1 PR is **backend-only**. No `ProjectView` edits. Phase 2 adds
  the consumer.
- If `openapi-fetch` migration from ADR 0006 has not landed, add the one-line
  `fetchJson<>` method to `client.ts` — do not block on ADR 0006. The
  generated schema is still authoritative for the return type.