# Batch A — Evidence and Step Resolution Foundations

## Goal

Create the two consolidated primitives that unblock most of the sprint:
`EvidenceResolver` (run-step/artifact evidence lookup with diagnostics) and
`StepResolutionService` (canonical step ID → branch-scoped step ID). Migrate
the first consumers and leave `evidence_locator.py` as a compatibility shim.

This batch is the foundation for Batches B, C, D, and H. Do not start those
until this batch lands.

## Context you must read first

- `cardre/evidence_locator.py` — the existing central helpers. Note
  `latest_successful_run_step:45` (branch → full-plan → plan-level run) and
  `latest_successful_run_step_across_plan:75`.
- `cardre/services/branch_evidence.py:254` — `_find_shared_evidence`. This is
  the diagnostic-capable variant: across-plan with `source_branch_id`, then
  baseline, then latest plan run, emitting `INHERITED_BASELINE_EVIDENCE` and
  `REUSE_EVIDENCE_NOT_FOUND` diagnostics.
- `cardre/step_id.py:31` — `resolve_step_for_branch` and
  `:95` `resolve_run_step` (exact-vs-ancestor policy).
- `cardre/reporting/evidence_contract.py:81` —
  `find_evidence_for_canonical_step`, which wraps the central locator with
  canonical alias lookup.
- `cardre/services/manual_binning_service.py:546` — the private
  `_find_run_step` closure (do not migrate here; that is Batch B).
- `cardre/services/comparison_service.py:130` — `_find_typed_artifact` (do
  not migrate here; that is Batch C).
- `tests/test_evidence_locator.py` — existing characterization tests. They
  only cover the central helper and a few fallbacks, not cross-consumer
  parity.
- `docs/plans/consolidation-launch-sprint/README.md` — sprint-level
  validation context and cross-cutting rules.

## Changes

### 1. Create `EvidenceResolver` with a typed policy enum

New file `cardre/services/evidence_resolver.py`.

```python
from typing import Literal
from dataclasses import dataclass

from cardre.audit import RunStepRecord, StepSpec
from cardre.errors import Diagnostic
from cardre.store import ProjectStore


@dataclass(frozen=True)
class EvidenceLookupRequest:
    plan_version_id: str
    step_id: str
    branch_id: str | None = None
    source_branch_id: str | None = None
    run_id: str | None = None
    canonical_step_id: str | None = None
    aliases: bool = True
    require_fingerprint_match: StepSpec | None = None
    policy: Literal[
        "run_only",
        "branch_then_full_then_plan",
        "source_branch_then_full_then_plan",
        "across_plan",
    ] = "branch_then_full_then_plan"


@dataclass(frozen=True)
class EvidenceResolution:
    run_step: RunStepRecord | None
    source: Literal["run", "branch", "full_plan", "across_plan",
                     "latest_plan_run", "missing"]
    diagnostics: list[Diagnostic]


class EvidenceResolver:
    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def resolve(self, request: EvidenceLookupRequest) -> EvidenceResolution:
        ...
```

Behavior by policy:

- `run_only` — look only inside `request.run_id`. Source `run` or `missing`.
- `branch_then_full_then_plan` — the current
  `latest_successful_run_step` chain: branch-scoped, then same-version
  full-plan (`branch_id=None`), then latest plan-level run scan. Source
  `branch` / `full_plan` / `latest_plan_run` / `missing`.
- `source_branch_then_full_then_plan` — the
  `_find_shared_evidence` chain: across-plan with `source_branch_id`, then
  across-plan baseline (`branch_id=None`), then latest plan-level run scan.
  Emit `INHERITED_BASELINE_EVIDENCE` when falling back to baseline and
  `REUSE_EVIDENCE_NOT_FOUND` when nothing is found. Source `across_plan` /
  `latest_plan_run` / `missing`.
- `across_plan` — the `latest_successful_run_step_across_plan` chain. Source
  `across_plan` / `latest_plan_run` / `missing`.

When `require_fingerprint_match` is set, validate `params_hash`,
`node_type`, and `node_version` against the candidate; drop and continue
on mismatch (mirrors `staleness.step_is_stale:83-86`).

When `aliases` is true and `canonical_step_id` is set, run
`canonical_alias_candidates` and return the first hit (mirrors
`evidence_contract.find_evidence_for_canonical_step:92`).

### 2. Migrate `BranchEvidenceResolver._find_shared_evidence`

In `cardre/services/branch_evidence.py`, replace the body of
`_find_shared_evidence:254` with a call to
`EvidenceResolver.resolve` using
`policy="source_branch_then_full_then_plan"`. Preserve the diagnostics it
already appends by passing the resolver-returned diagnostics list through.

The existing call sites at `:132` (pre-collect shared evidence) and `:233`
(resolve_parent_evidence) must behave identically. Keep the
`INHERITED_BASELINE_EVIDENCE` and `REUSE_EVIDENCE_NOT_FOUND` codes.

### 3. Migrate `step_id.resolve_run_step`

In `cardre/step_id.py`, make `resolve_run_step:95` delegate to
`EvidenceResolver`:

- `resolution == "exact"` with a `run_id` → `policy="run_only"`.
- `resolution == "exact"` without a `run_id` → return `None` (preserve
  current behavior; exact resolution does not get broader fallback).
- `resolution == "ancestor"` → `policy="across_plan"` with
  `branch_id=resolved_branch_id`.

Do not change `resolve_step_for_branch` or `resolve_required_steps` — those
are pure branch-step-map functions and stay in `step_id.py`.

### 4. Create `StepResolutionService`

New file `cardre/services/step_resolution_service.py`.

```python
from typing import Literal
from cardre.step_id import ResolvedStepRef
from cardre.store import ProjectStore


class StepResolutionService:
    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def resolve_canonical(
        self,
        branch_id: str,
        plan_version_id: str,
        canonical_step_id: str,
        mode: Literal["exact", "ancestor", "nearest_upstream"] = "ancestor",
        from_step_id: str | None = None,
    ) -> ResolvedStepRef | None: ...

    def resolve_required(
        self,
        branch_id: str,
        plan_version_id: str,
        canonical_step_ids: list[str],
        mode: Literal["exact", "ancestor", "nearest_upstream"] = "ancestor",
    ) -> dict[str, ResolvedStepRef | None]: ...
```

`exact` and `ancestor` delegate to `resolve_step_for_branch` /
`resolve_required_steps` after loading the branch step map. `nearest_upstream`
delegates to `cardre.services.step_topology.find_nearest_binning_source` /
`find_nearest_ancestor_by_canonical_step_id` (used today only by manual
binning — Batch B will consume this).

Centralize the legacy alias fallback that today lives inline in
`readiness/check.py:129-136`: when a canonical step is missing from
`resolved`, try `canonical_alias_candidates` and copy the first present
candidate ref. The service owns this; readiness and collector stop doing it
locally in Batch C.

### 5. Leave `evidence_locator.py` as a compatibility shim

Keep `cardre/evidence_locator.py` importable. Its public functions
(`latest_successful_run_step`, `latest_successful_run_step_across_plan`,
`collect_run_steps_for_plan_version`, `resolve_output_artifacts`) become
thin wrappers over `EvidenceResolver`. This lets unmigrated consumers
(`comparison_service`, `export_service`, `manual_binning_service`) keep
working until Batches B and C migrate them.

Do not delete `evidence_locator.py` in this batch. Batch H deletes it once
all call sites move.

## Tests

### New: `tests/test_evidence_resolver.py`

Table-driven policy tests, one fixture per row:

- branch-owned evidence exists → source `branch`, no diagnostics.
- branch evidence absent, full-plan evidence exists → source `full_plan`,
  no diagnostics.
- inherited source-branch evidence exists only in an older plan version →
  source `across_plan`, no diagnostics.
- source branch has no evidence, baseline across-plan exists → source
  `across_plan`, one `INHERITED_BASELINE_EVIDENCE` diagnostic.
- no evidence anywhere → source `missing`, one
  `REUSE_EVIDENCE_NOT_FOUND` diagnostic.
- stale same-step evidence exists but `require_fingerprint_match` does not
  match → skip and continue; if nothing else matches, source `missing`.
- typed evidence exists in a non-first output artifact → resolver returns
  the run-step (the consumer then reads artifacts; resolver does not pick
  artifacts).
- aliases: `logistic-regression` resolves to `model-fit` evidence when
  `canonical_step_id="model-fit"` and `aliases=True`.

### New: `tests/test_step_resolution_service.py`

- `resolve_canonical(mode="exact")` returns the branch-owned step.
- `resolve_canonical(mode="ancestor")` returns shared upstream resolved to
  `source_branch_id`.
- `resolve_canonical(mode="nearest_upstream")` returns the nearest binning
  ancestor for a manual-binning step.
- `resolve_required` applies the legacy alias fallback centrally: a plan
  with only `logistic-regression` in the step map resolves
  `model-fit` to the same ref.

### Update: `tests/test_evidence_locator.py`

Keep the existing characterization tests green against the shim. Add one
assertion that `latest_successful_run_step` and
`EvidenceResolver.resolve(policy="branch_then_full_then_plan")` return the
same `RunStepRecord` for the same inputs.

### New: `tests/test_branch_evidence_resolver_migration.py`

- `prepare_branch_run` with inherited source-branch evidence emits the same
  `INHERITED_BASELINE_EVIDENCE` diagnostic as before migration.
- `resolve_parent_evidence` finds shared evidence via the resolver and
  populates `step_outputs`.

## Verification

```bash
pytest tests/test_evidence_resolver.py \
       tests/test_step_resolution_service.py \
       tests/test_evidence_locator.py \
       tests/test_branch_evidence_resolver_migration.py \
       tests/test_branch_consistency.py \
       tests/test_evidence_contract.py
```

## Definition of done

1. `EvidenceResolver` exists with all four policies and diagnostics.
2. `BranchEvidenceResolver._find_shared_evidence` delegates to it; diagnostic
   codes unchanged.
3. `step_id.resolve_run_step` delegates to it for ancestor resolution.
4. `StepResolutionService` exists with `exact`, `ancestor`, and
   `nearest_upstream` modes, plus centralized alias fallback.
5. `evidence_locator.py` is a compatibility shim over `EvidenceResolver`.
6. All listed tests are green; no existing characterization test regresses.

## Files touched

- `cardre/services/evidence_resolver.py` (new)
- `cardre/services/step_resolution_service.py` (new)
- `cardre/evidence_locator.py` (shim)
- `cardre/services/branch_evidence.py`
- `cardre/step_id.py`
- `tests/test_evidence_resolver.py` (new)
- `tests/test_step_resolution_service.py` (new)
- `tests/test_evidence_locator.py` (updated)
- `tests/test_branch_evidence_resolver_migration.py` (new)

## Depends on

none (foundation batch)

## Unblocks

Batch B, Batch C, Batch D, Batch H.