# Phase 4 — StepInspector Next action + Evidence tabs

You are implementing **Phase 4** of the Guided Workflow Sprint
(`docs/plans/guided-workflow-sprint.md`). Phases 1, 2, and 3 are merged.

Read first:
- `frontend/src/components/StepInspector.tsx` (current single-pane inspector)
- `sidecar/routes/artifacts.py` (existing `summarise_artifact` route)
- `cardre/evidence.py` (`ArtifactEvidenceReader.summarise_step_outputs`,
  `summarise_run_artifacts`)
- `docs/architecture/artifact-evidence-access.md` (especially the
  "Writing Sidecar Artifact Previews" section)

## Goal

Reorganise `StepInspector` from a metadata panel into a modelling assistant
with five tabs. The first tab is the default, populated entirely from
`workflowGuidance.step_guidance[step_id]`. The Evidence tab uses **typed
sidecar endpoints** that wrap `ArtifactEvidenceReader` — the frontend never
imports the reader and never reads raw artifacts.

This is more than a UI PR. Two new backend evidence routes are required
because `summarise_step_outputs` and `summarise_run_artifacts` are not
currently exposed.

## Inspector Tabs

1. **Next action** (default)
   - `step_guidance[canonical_id].readiness` rendered as a status.
   - `explanation` — why this step matters (governance framing).
   - `primary_action` — the action label.
   - `evidence_kinds` — the list this step produces/expects.
   - If `isManualBinning`, the manual-binning readiness block (Phase 5a)
     integrates here as a feature card inside the tab. Phase 4 only needs to
     render the **existing** manual-binning readiness block unchanged.
2. **Configure**
   - Existing params editor (`SchemaDrivenParamsEditor`). Identical UX to
     today's collapsible editor, just promoted to a tab.
3. **Evidence**
   - Per-artifact card with `kind`, summary preview shape, logical hash.
   - Sourced from `GET /runs/{run_id}/steps/{step_id}/evidence` (new route,
     see below). If no run resolves for this branch, the tab shows "No run
     evidence yet — run the pathway to produce evidence."
4. **Warnings**
   - Tightened blocker/warning list. If the step is referenced in
     `guidance.blockers` (matched by `step_id`) those blockers render here.
   - If the step has its own `status == "failed"`, the failure detail from
     the latest run step renders here.
   - Source: `guidance.blockers` for matching `step_id`; plus
     `step.status == "failed"` → fetch the latest run step error message via
     `api.getRunSteps(runId)` (no new route). Cache minimally.
5. **Run history**
   - Compact list of past run-step records for this step across all runs of
     the current `branch.head_plan_version_id`. Each entry: run id (short),
     status, started/finished, carried-forward indicator. Source:
     `api.getRunSteps` per run listing, joined client-side with run metadata.
     Use the existing `api.getProjectRuns(projectId)` and the existing
     `api.getRunSteps(runId)` — no new route.
   - This is a *modeller's* view: short, date-stamped, with the artefacts
     produced (artifact IDs short). Click-through to the Artifacts browser
     is acceptable.

Tabs 1, 2, 4, and 5 are pure frontend given Phase 1 guidance. **Tab 3
requires the new evidence routes below.**

## Backend Work (Required)

Two new sidecar routes under `sidecar/routes/evidence.py` (scaffolded in
Phase 0), now registered in `sidecar/main.py`:

```
GET /runs/{run_id}/steps/{step_id}/evidence
GET /runs/{run_id}/evidence
```

Both return `RunStepEvidenceResponse` (new model in `sidecar/models.py`):

```python
class RunStepEvidenceItem(BaseModel):
    artifact_id: str
    artifact_type: str
    role: str | None
    media_type: str
    evidence_kind: str | None
    summary: dict  # whatever reader.summarise_artifact returns, opaque to the route
    logical_hash: str | None

class RunStepEvidenceResponse(BaseModel):
    run_id: str
    step_id: str | None  # None for the /runs/{id}/evidence aggregate
    items: list[RunStepEvidenceItem]
```

Implementation in the route handler:

```python
from cardre.evidence import ArtifactEvidenceReader
from cardre.services.project_registry import get_store_for_project

reader = ArtifactEvidenceReader(store)
# For the per-step route:
for rs in store.get_run_steps(run_id):
    if rs.step_id == step_id:
        items = [
            _to_item(reader, aid)
            for aid in rs.output_artifact_ids
        ]
        return RunStepEvidenceResponse(run_id=run_id, step_id=step_id, items=items)
raise HTTPException(404, ...)

# For the per-run route:
items = []
for rs in store.get_run_steps(run_id):
    for aid in rs.output_artifact_ids:
        items.append(_to_item(reader, aid))
return RunStepEvidenceResponse(run_id=run_id, step_id=None, items=items)
```

`_to_item` calls `reader.summarise_artifact(artifact_id)` and packages it.

`project_id` is required as a query parameter so `get_store_for_project`
works (consistent with `reports.py`).

**Guardrail compliance:** the new routes must use the reader's
`summarise_artifact`. Do not call `store.artifact_path` in this route except
where the byte-download suppression applies (it does not here). The audit at
`tests/test_artifact_guardrail.py` will flag any direct file read.

Augment `docs/architecture/artifact-evidence-access.md` to mention the two
new routes in the "Approved Read Paths" section's sidecar-previews
header.

## Frontend

Replace `StepInspector`'s single-pane layout with a tab bar at the top,
tabs below. Default tab: **Next action**. Width stays at 320px (current);
use compact tab affordances (icon + label). If text overflows on small viewports,
truncate labels rather than widening the inspector.

```tsx
// frontend/src/components/StepInspector.tsx
type InspectorTab = "next_action" | "configure" | "evidence" | "warnings" | "history";
const [tab, setTab] = useState<InspectorTab>("next_action");
```

When `step` changes, reset `tab` to `"next_action"` via `useEffect` on
`step?.step_id` (so selecting a new step always opens on the assistant).

Existing logic stays largely intact inside the Configure tab. The
manual-binning readiness block (Phase 4 inclusion) stays as-is in the
Next-action tab until Phase 5a reworks it.

## Files

| File                                              | Action | Content                                                                                          |
|---------------------------------------------------|--------|--------------------------------------------------------------------------------------------------|
| `sidecar/routes/evidence.py`                      | Replace scaffold | Implement both routes. Thin delegate to `ArtifactEvidenceReader`. |
| `sidecar/main.py`                                 | Edit   | Register `evidence.router`. |
| `sidecar/models.py`                               | Edit   | Add `RunStepEvidenceItem`, `RunStepEvidenceResponse`. |
| `docs/architecture/artifact-evidence-access.md`   | Edit   | Mention the two new routes. |
| `frontend/src/api/schema.d.ts`                    | Regen  | `python3 scripts/generate-openapi-types.py`. |
| `frontend/src/api/client.ts`                      | Edit   | One-liner `getStepEvidence(runId, stepId, projectId)` and `getRunEvidence(runId, projectId)`. |
| `frontend/src/components/StepInspector.tsx`       | Edit   | Tab-bar refactor. Each tab a subcomponent for clarity. Reuse `useQuery` for evidence + warnings. |
| `frontend/src/components/inspector/NextActionTab.tsx` | Create | Renders `guidance.step_guidance[canonical_id]`. Includes inline manual-binning readiness block (legacy). |
| `frontend/src/components/inspector/ConfigureTab.tsx` | Create | Wraps `SchemaDrivenParamsEditor`. |
| `frontend/src/components/inspector/EvidenceTab.tsx` | Create | Calls `getStepEvidence`, list of `RunStepEvidenceItem`. |
| `frontend/src/components/inspector/WarningsTab.tsx` | Create | Renders matching blockers + step failure detail. |
| `frontend/src/components/inspector/RunHistoryTab.tsx` | Create | Lists run-step records for this step across runs of the current branch head. |
| `frontend/src/components/ProjectView.tsx`          | Edit   | Pass `guidance` and current `runId` into `<StepInspector>` so it can fetch evidence. |
| `tests/test_sidecar_api.py`                       | Edit   | Add coverage for the two new routes. |
| `tests/test_artifact_guardrail.py`                | Edit if needed | If the new routes accidentally trigger guardrail flags, fix before merge. |

## Sequence

1. Implement the two backend routes + DTOs.
2. Register `evidence.router` in `sidecar/main.py`.
3. Augment `docs/architecture/artifact-evidence-access.md`.
4. Add backend tests; run guardrail test.
5. Regenerate `schema.d.ts`.
6. Add the two one-liner client methods.
7. Split `StepInspector` into the five tabs and the five tab subcomponents.
8. Wire `ProjectView` to pass guidance + `runId`.
9. Run `npx tsc --noEmit` and `python3 -m pytest tests/ -q`.

## Acceptance Criteria

For every launch step, the inspector answers:
- What this step does — `explanation`.
- Why it matters in scorecard governance — `explanation` (same field; backend
  drafts governance-framed copy in Phase 1's localisation constants).
- What inputs/evidence it needs — `evidence_kinds` + the Evidence tab.
- What it produced — Evidence tab.
- What the user should do next — Next action tab `primary_action`.
- What warning/blocker exists — Warnings tab.

Mechanical:
- The two new routes are documented in
  `docs/architecture/artifact-evidence-access.md`.
- `tests/test_artifact_guardrail.py` passes (no direct file reads added).
- Switching steps always lands the user on the Next action tab.
- The 320px width holds all tabs without horizontal scroll. Verify with at
  least one long step name (e.g., `woe_transform__br_specific`).
- `npx tsc --noEmit` clean. `python3 -m pytest tests/ -q` green.

## Non-Goals

- Phase 5's manual-binning tab upgrades (DTO enrichment + review-complete).
  Phase 4's manual-binning block is the legacy block unchanged.
- Charts in the Evidence tab — text-only summaries from the reader.
- Exporting evidence from the inspector.
- Replacing `ArtifactBrowser`. It remains the only way to see non-step
  artifacts (notably `__import__` plan outputs).

## Drop-Dead Notes

- Do **not** fetch evidence on mount of `StepInspector` for every step
  change. Only the Evidence tab fetches. Use `useQuery` `enabled` keyed on
  `tab == "evidence" && !!runId`.
- Do **not** expose a "Download artifact" button in the inspector. Downloads
  go via the existing `/artifacts/{id}/preview` endpoint through
  `ArtifactBrowser`.
- `summarise_artifact` may return `None` for untyped JSON artifacts. The
  frontend renders "Unsupported evidence kind for preview." Do not attempt
  raw JSON interpretation on the client.
- If `runId` is unknown (no run yet for the branch), the Evidence tab shows
  the deterministic placeholder noted above. No grey spinner forever.