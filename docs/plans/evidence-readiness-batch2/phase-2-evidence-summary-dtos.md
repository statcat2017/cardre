# Phase 2 — Evidence summary DTOs and per-kind summarisers

## Goal

Give the frontend meaningful evidence summaries without making the
frontend parse raw artifacts. Generate summaries backend-side, attach
staleness and source-step attribution, and surface them via the existing
evidence route.

This is the PR where evidence stops being "artifact ID + hash" and starts
being "12 variables · IV range 0.18–0.42 · 2 warnings."

## Context you must read first

- `sidecar/routes/evidence.py` (68 LOC) — current evidence route.
  Note `_to_item` at `:24-32` and the two endpoints at `:35` and `:55`.
  This file must stay thin; new logic lives in `cardre/_evidence/`.
- `sidecar/models.py:752-766` — existing `RunStepEvidenceItem` and
  `RunStepEvidenceResponse`. The `summary: dict | None` field exists
  but is always an identifier blob.
- `cardre/_evidence/models.py:685-693` — `ArtifactEvidenceSummary`.
  Currently carries only `kind`, `schema_version`, `source_artifact_id`.
  The per-kind domain content (IV range, row counts, Gini/KS, etc.) is
  **new code**; this dataclass becomes the base, with per-kind
  subclasses or a discriminated return type from a summariser.
- `cardre/_evidence/reader.py:237-251` — `summarise_step_outputs` and
  `summarise_run_artifacts`. Reuse these for plumbing; they currently
  call `summarise_artifact` per item.
- `cardre/staleness.py:142` — `staleness_detail(store, plan_version_id, branch_id=None) -> list[StalenessDetail]`.
  Returns reasons `never_run` / `params_changed` / `node_version_changed`
  / `upstream_stale` / `upstream_artifact_changed`. **Reuse this.** Do
  not invent staleness inside the evidence route.
- `cardre/reporting/evidence_contract.py:18-49` — the
  `REQUIRED_STEPS_*` lists. PR 2 derives "partial evidence" from
  comparing present evidence against this contract; staleness does
  **not** mean partial.
- `cardre/step_id.py:77` — `resolve_required_steps`. Used to find the
  canonical step id for a step_id attached to an artifact.
- `frontend/src/components/inspector/EvidenceTab.tsx` (57 LOC) —
  today renders a flat list. PR 3 rebuilds the render; PR 2 only
  enriches the data it receives.
- `frontend/src/api/client.ts:257` — `getStepEvidence` (the TS client
  method). Regenerate types; don't hand-edit it.

## Changes

### 1. Extend `RunStepEvidenceItem` with structured fields

In `sidecar/models.py`:

```python
class EvidenceStatus(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"           # some expected evidence missing
    STALE = "stale"               # artifact present but upstream changed
    MISSING = "missing"           # contract expected evidence that is absent
    UNSUPPORTED = "unsupported"   # artifact kind has no summariser yet

class ReadinessItem(BaseModel):
    ...

class RunStepEvidenceItem(BaseModel):
    artifact_id: str
    artifact_type: str
    role: str | None = None
    media_type: str = ""
    evidence_kind: str | None = None
    logical_hash: str | None = None
    # New:
    created_at: str = ""
    is_stale: bool = False
    staleness_reason: str | None = None
    canonical_step_id: str | None = None
    source_step_id: str | None = None
    source_branch_id: str | None = None
    status: EvidenceStatus = EvidenceStatus.AVAILABLE
    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RunStepEvidenceResponse(BaseModel):
    items: list[RunStepEvidenceItem] = Field(default_factory=list)
    status: EvidenceStatus = EvidenceStatus.AVAILABLE
    checked_at: str = ""
    target_branch_id: str = ""
    run_id: str = ""
    canonical_step_id: str | None = None
```

The response-level `status` summarises the whole step (e.g.
`status=PARTIAL` if any expected artifact is missing; `status=STALE` if
all items stale; `status=MISSING` if items is empty but contract requires
this canonical step). Per-item `status` summarises the item.

**Do not add `physical_hash`.** Staleness does not consult it and the UI
has no present use for it. If a future audit feature needs it, add it
then with a justified UI requirement.

### 2. Create `cardre/_evidence/summaries.py`

This is the new module for per-kind domain summaries. Dispatch by
`evidence_kind` (or `artifact_type` when `evidence_kind` is absent).
Each summariser is a pure function taking the artifact (or its parsed
payload) and returning a `dict` plus a `list[str]` of warnings.

```python
def summarise(artifact_row, parsed_payload) -> tuple[dict, list[str]]:
    kind = artifact_row.evidence_kind or _infer_kind(artifact_row)
    fn = _SUMMARISERS.get(kind, _generic_summary)
    return fn(artifact_row, parsed_payload)
```

Launch-path summarisers (per the plan's table):

| `evidence_kind` (or artifact_type) | Summary dict keys |
|---|---|
| profile / import | `row_count`, `column_count`, `dataset_role` |
| target-definition | `target_column`, `good_label`, `bad_label`, `event_rate` |
| split / profile (split role) | `train_count`, `test_count`, `oot_count` |
| binning | `variable_count`, `bin_total`, `missing_handling`, `special_handling` |
| woe-iv | `selected_variable_count`, `iv_min`, `iv_max`, `top_variables: [{name, iv}]` (top 3) |
| logistic-model | `variable_count`, `coefficient_count`, `fit_status` |
| score-scaling | `score_min`, `score_max`, `pdo`, `base_odds`, `base_score` |
| validation-metrics | `gini`, `ks`, `auc`, `psi`, `calibration_status` (each key present only if the artifact carries it) |
| report-bundle | `ready`, `blocker_count`, `warning_count` |
| _generic | `{"schema_version": parsed_payload.schema_version, "unsupported_kind": true}` |

Do **not** overbuild. A summariser returns a small dict — at most ~8 keys.
Warnings are short English strings ("IV unavailable for 2 selected
variables.").

**Where the data comes from**: each summariser needs the *parsed*
artifact payload (e.g. the WOE/IV artifact's `variable_summaries`). Use
the existing artifact loaders in `cardre/_evidence/` — do not write a
second loader. If a loader does not exist for a kind, return the generic
summary; never raise.

**Unsupported kinds must still appear** in `items`, with
`status=UNSUPPORTED` and `summary={"unsupported_kind": true}`. Do not
silently drop them — PR 3's EvidenceTab renders them with a fallback
card.

### 3. Wire staleness, source attribution, and partial derivation into the route

In `sidecar/routes/evidence.py` (or a helper imported by it — keep the
route under 100 LOC):

1. Fetch `plan_version_id`, `branch_id` from the run.
2. Compute `staleness_detail(store, plan_version_id, branch_id)` once
   per request. Build a `{step_id: StalenessDetail}` map.
3. For each artifact attached to the requested step:
   - Resolve its `source_step_id` from the audit trail (the run step
     that produced it) and its `canonical_step_id` from the plan
     version step mapping.
   - Set `is_stale` / `staleness_reason` from the staleness map.
   - Call `cardre._evidence.summaries.summarise(...)` to get the
     summary dict and warnings.
   - Determine `status` per item:
     - `STALE` if `is_stale` true.
     - `UNSUPPORTED` if the summariser returned the generic dict with
       `unsupported_kind`.
     - else `AVAILABLE`.
4. After collecting all items, compute the response `status`:
   - No items, but the step's canonical id is in
     `REQUIRED_STEPS_BRANCH` for this branch → `MISSING`.
   - Some items present, but fewer than expected (the step's canonical
     id is in `REQUIRED_STEPS_*` and the contract implies more artifacts
     than found) → `PARTIAL`. Use the contract definition to decide
     "expected"; do not hard-code counts.
   - All items stale → `STALE`.
   - else match the worst per-item `status`.
5. Echo `target_branch_id`, `run_id`, `canonical_step_id` on the
   response. Echo `checked_at` as ISO-8601 UTC.

If the run has no run steps (never run), return
`items=[], status=MISSING, canonical_step_id=<resolved>`.

If the artifact / summary lookup raises, log the exception server-side
and return the item with `status=UNSUPPORTED` rather than failing the
whole request. The frontend uses the per-item status; only network
errors should surface as request-level failures (addressed in PR 3's
load-failed state).

### 4. Extend the bulk endpoint

The existing `GET /runs/{run_id}/evidence?project_id=...` route at
`sidecar/routes/evidence.py:55` should return a list of
`RunStepEvidenceResponse`, one per canonical step resolved on the
branch. This is what TopBar-style UIs will eventually use; PR 2 only
needs the schema and route plumbed, not a new UI consumer. Keep the
single-step endpoint (`:35`) as the primary one PR 3 consumes.

## Tests

### Backend

In `tests/test_evidence_summaries.py` (new file):

1. **`test_summary_profile_artifact`** — fixture produces a profile
   artifact; assert the summary dict has `row_count`, `column_count`,
   `dataset_role`.
2. **`test_summary_woe_iv_artifact`** — assert `selected_variable_count`,
   `iv_min`, `iv_max`, `top_variables` populated from a fixture
   WOE/IV evidence.
3. **`test_summary_validation_artifact`** — assert Gini/KS/AUC/PSI
   populated when present and omitted when absent (no `None` values in
   the dict).
4. **`test_summary_logistic_model`** — assert `coefficient_count` and
   `fit_status`.
5. **`test_summary_report_bundle`** — assert `ready`, `blocker_count`,
   `warning_count`. This summariser can call into `check_report_readiness`
   (don't re-derive) — pass through the readiness result for that
   branch/run and surface its summary.
6. **`test_unsupported_kind_returns_generic_summary`** — synthetic
   artifact with `evidence_kind="exotic-thing"`; assert item present with
   `status=UNSUPPORTED` and `summary={"unsupported_kind": true}`,
   **not** dropped.
7. **`test_missing_evidence_for_required_step_returns_no_evidence_status`**
   — request evidence for a canonical step in `REQUIRED_STEPS_BRANCH`
   when no artifact exists; assert `items=[]`, `status=MISSING`,
   `canonical_step_id` set.
8. **`test_stale_artifact_marked_stale`** — successful artifact, then
   mutate a parent step's params_hash; assert `is_stale=True`,
   `staleness_reason="upstream_stale"` or `"upstream_artifact_changed"`,
   per-item `status=STALE`.
9. **`test_partial_evidence_when_expected_evidence_absent`** —
   canonical step has one of two expected artifacts present; assert
   response `status=PARTIAL`.
10. **`test_route_error_returns_unsupported_not_request_failure`** —
    stub the summariser to raise; assert the item's status is
    `UNSUPPORTED` but the response is 200.

Reuse fixtures from `tests/test_evidence.py` for the artifact payloads.

### Frontend

Extend the MSW handler at `frontend/src/test/server.ts` (or add a
dedicated handler) to return one `RunStepEvidenceResponse` with items
carrying `summary`, `status`, `warnings`, `is_stale`,
`source_step_id`. No new frontend test files in this PR — PR 3 writes
`EvidenceTab.test.tsx`.

Regenerate `schema.d.ts`; commit the diff.

## Acceptance criteria

- `RunStepEvidenceItem` carries `summary` (populated dict), `warnings`,
  `is_stale`, `staleness_reason`, `created_at`, `canonical_step_id`,
  `source_step_id`, `source_branch_id`, `status`. No `physical_hash`.
- `RunStepEvidenceResponse` carries `status`, `checked_at`,
  `target_branch_id`, `run_id`, `canonical_step_id`.
- Per-kind summarisers live in `cardre/_evidence/summaries.py`,
  dispatch by `evidence_kind`, and cover the nine artefact types in the
  table above. Unsupported kinds fall back to a generic summary.
- The evidence route never raises into a 500 due to a summariser
  fault; failures degrade per-item to `UNSUPPORTED`.
- The report-bundle summariser reuses `check_report_readiness` rather
  than re-implementing the gate.
- `pytest tests/test_evidence_summaries.py` passes; existing
  `tests/test_evidence_*.py` still pass.
- `sidecar/routes/evidence.py` stays under 100 LOC. New logic lives
  in `cardre/_evidence/`.
- `cardre/_evidence/summaries.py` stays under 600 LOC. If approaches
  it, split by artifact family (e.g. `summary_model.py`,
  `summary_validation.py`).
- `schema.d.ts` regenerated and committed.

## Out of scope for this phase

- `EvidenceTab.tsx` render changes — PR 3.
- Frontend tests for the seven states — PR 3.
- Removing the disclaimer at `ReadinessPanel.tsx:114-116` — PR 4.
- Reconciling collector limitations — PR 4.
- New evidence kinds outside the nine in the table — explicitly
  out of scope for this batch.