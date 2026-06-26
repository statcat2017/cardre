# Batch B — Manual-Binning Context Unification

## Goal

Make manual-binning editor, preview, validation, and save review share one
upstream context resolver. Today the editor blocks on stale upstream steps
but preview and validation do not, and validation can select a different
canonical step than the editor displayed. This is a governance/audit bug, not
just a UI inconsistency.

## Context you must read first

- `cardre/services/manual_binning_service.py:87` — `get_editor_state`. Note
  the staleness gate at `:153-168` and the upstream resolution at `:170-181`.
- `cardre/services/manual_binning_service.py:330` — `preview_overrides`.
  Repeats step/branch/nearest-source lookup at `:346-371` but does **not**
  re-check staleness.
- `cardre/services/manual_binning_service.py:407` — `validate_overrides`.
  Uses `_find_mb_step_id_for_validation:593`, a canonical scan unrelated to
  the editor's nearest-upstream selection.
- `cardre/services/manual_binning_service.py:538` — `_resolve_upstream_defs`
  and its private `_find_run_step:546` closure (branch-exact → latest full-plan
  run → latest plan run scan, first output artifact only).
- `cardre/services/manual_binning_service.py:593` —
  `_find_mb_step_id_for_validation`.
- `cardre/services/step_topology.py` — `find_nearest_binning_source` and
  `find_nearest_ancestor_by_canonical_step_id`.
- `cardre/readiness/manual_binning.py` — `compute_manual_binning_blockers`.
- `tests/test_manual_binning_source.py`,
  `tests/test_manual_binning_phase1.py`,
  `tests/test_manual_binning_phase3.py`,
  `tests/test_manual_binning_phase4.py`,
  `tests/test_manual_binning_gate.py` — existing coverage to preserve.
- `docs/plans/consolidation-launch-sprint/README.md` — cross-cutting rules.

## Prerequisite

Batch A must land first. This batch consumes `EvidenceResolver` and
`StepResolutionService`.

## Changes

### 1. Create `ManualBinningContextResolver`

New file `cardre/services/manual_binning_context.py`.

```python
from dataclasses import dataclass
from cardre.audit import StepSpec
from cardre.errors import Diagnostic
from cardre.services.evidence_resolver import EvidenceResolution
from cardre.services.step_resolution_service import StepResolutionService
from cardre.step_id import ResolvedStepRef
from cardre.store import ProjectStore


@dataclass
class ManualBinningContext:
    plan_id: str
    plan_version_id: str
    manual_step_id: str
    manual_spec: StepSpec | None
    branch_id: str | None
    branch_step_map: list[dict]
    binning_ref: ResolvedStepRef | None
    variable_selection_ref: ResolvedStepRef | None
    binning_stale: bool
    variable_selection_stale: bool
    binning_evidence: EvidenceResolution | None
    selection_evidence: EvidenceResolution | None
    binning_artifact_id: str | None
    selection_artifact_id: str | None
    bin_def: dict | None
    vs_def: dict | None
    selected_variables: list[str]
    diagnostics: list[Diagnostic]


class ManualBinningContextResolver:
    def __init__(self, store: ProjectStore) -> None: ...

    def resolve(
        self,
        plan_id: str,
        plan_version_id: str,
        manual_step_id: str = "manual-binning",
        *,
        require_current: bool = True,
    ) -> ManualBinningContext: ...
```

`require_current=True` enforces the staleness gate (used by editor and save
review). `require_current=False` skips staleness but still resolves evidence
(used by preview, which renders refined bins even when upstream is stale but
must not save).

The resolver:

1. Finds the manual-binning step spec (preferring `manual_step_id`, then any
   step with `canonical_step_id == "manual-binning"`).
2. Loads the branch step map.
3. Uses `StepResolutionService.resolve_canonical(mode="nearest_upstream")`
   for the binning source and variable-selection ancestor.
4. Computes staleness once via `compute_staleness`.
5. Uses `EvidenceResolver` (policy `branch_then_full_then_plan`) to resolve
   binning and variable-selection run-steps, reading the typed evidence
   artifacts via `ArtifactEvidenceReader`.
6. Populates `diagnostics` with any resolution warnings
   (`INHERITED_BASELINE_EVIDENCE`, `REUSE_EVIDENCE_NOT_FOUND`).

### 2. Migrate `get_editor_state`

Replace the manual lookup at `manual_binning_service.py:111-181` with a call
to `ManualBinningContextResolver.resolve(require_current=True)`. Map the
context onto the existing `ManualBinningEditorStateResponse` fields. When
`binning_stale or variable_selection_stale`, return the existing
`UPSTREAM_STEPS_STALE` blocked response with `required_steps`.

Preserve the WOE/IV variable-summary logic at `:245-317` — it reads
`final-woe-iv` evidence, not binning context, and stays as-is for now.

### 3. Migrate `preview_overrides`

Replace the lookup at `:346-371` with
`ManualBinningContextResolver.resolve(require_current=False)`. Preview must
not crash on stale upstream (it renders refined bins for inspection), but
the response must carry a `staleness` warning so the user knows they are
previewing against stale source bins.

Do not add a hard block here — the editor already blocks, and preview is a
read-only inspection step. But the warning is mandatory.

### 4. Migrate `validate_overrides` and `save_with_review`

Replace `_find_mb_step_id_for_validation:593` with the context resolver.
`validate_overrides` calls
`ManualBinningContextResolver.resolve(require_current=False)` and validates
against `context.bin_def` / `context.vs_def`.

`save_with_review:435` already calls `get_editor_state` at `:479` for the
review gate. After migration, that call returns the unified context, so the
gate uses the same `binning_artifact_id` the editor displayed. Remove the
separate `_find_mb_step_id_for_validation` path entirely.

### 5. Delete `_find_mb_step_id_for_validation` and the private `_find_run_step`

Both are replaced by the context resolver. Remove them and the
`_resolve_upstream_defs._find_run_step` closure. `_resolve_upstream_defs`
itself becomes a thin adapter that reads from `ManualBinningContext`
(`bin_def`, `vs_def`, `binning_artifact_id`, `selection_artifact_id`) — or is
deleted if all call sites now take the context directly.

## Tests

### New: `tests/test_manual_binning_context.py`

- Branch manual-binning step whose nearest upstream binning is branch-owned
  → `binning_ref.resolution == "exact"`, evidence from branch run.
- Branch manual-binning step whose binning source is shared upstream →
  `binning_ref.resolution == "ancestor"`,
  `binning_ref.resolved_branch_id == source_branch_id`.
- Shared upstream evidence inherited from an older plan version → context
  carries an `INHERITED_BASELINE_EVIDENCE` diagnostic.
- Stale binning source with `require_current=True` → context is still
  populated but `binning_stale=True`; editor maps it to
  `UPSTREAM_STEPS_STALE`.
- Stale binning source with `require_current=False` → context populated,
  `binning_stale=True`, no exception.

### Update: `tests/test_manual_binning_phase3.py` and `_phase4.py`

- Assert `preview_overrides` against a stale binning source returns a
  `staleness` warning in the response (new field or diagnostics entry).
- Assert `validate_overrides` uses the same `binning_artifact_id` that
  `get_editor_state` reported for the same branch/version/step. Add a
  fixture where `_find_mb_step_id_for_validation` would have picked a
  different step (branch-owned vs shared upstream) and prove they now match.

### New: `tests/test_manual_binning_review_gate_consistency.py`

- `save_with_review(reviewed=True)` against stale upstream raises
  `REVIEW_COMPLETION_BLOCKED` with `required_steps` matching the editor's
  blocked steps.
- `save_with_review(reviewed=True)` against current upstream succeeds and
  the committed annotation's `base_plan_version_id` matches the editor's
  `plan_version_id`.

## Verification

```bash
pytest tests/test_manual_binning_context.py \
       tests/test_manual_binning_source.py \
       tests/test_manual_binning_phase1.py \
       tests/test_manual_binning_phase3.py \
       tests/test_manual_binning_phase4.py \
       tests/test_manual_binning_gate.py \
       tests/test_manual_binning_review_gate_consistency.py
```

## Definition of done

1. `ManualBinningContextResolver` exists and is the single source of
   manual-binning upstream context.
2. Editor, preview, validation, and save review all consume it.
3. `_find_mb_step_id_for_validation` and the private `_find_run_step` closure
   are deleted.
4. Preview surfaces a staleness warning when upstream is stale.
5. Validation uses the same `binning_artifact_id` as editor state for a given
   branch/version/step; a dedicated test proves it.
6. All listed tests are green.

## Files touched

- `cardre/services/manual_binning_context.py` (new)
- `cardre/services/manual_binning_service.py`
- `tests/test_manual_binning_context.py` (new)
- `tests/test_manual_binning_phase3.py` (updated)
- `tests/test_manual_binning_phase4.py` (updated)
- `tests/test_manual_binning_review_gate_consistency.py` (new)

## Depends on

Batch A

## Unblocks

Batch H (parity tests include manual-binning).