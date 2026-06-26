# Batch C — Report, Comparison, Export, and Method-Summary Evidence Consumers

## Goal

Make report readiness, report collection, comparison, export, and
method-summary share one evidence plan and one resolution path. Today
readiness and the collector resolve branch/run/step/evidence independently,
export resolves its own latest run, and comparison and method-summary have
their own typed-artifact scans that miss across-plan fallback.

## Context you must read first

- `cardre/readiness/check.py:37` — `check_report_readiness`. Resolves
  branch, step map, required steps (`:121`), legacy alias fallback
  (`:129-136`), and per-step evidence (`:138-149`).
- `cardre/reporting/collector.py:92` — `ReportCollector.collect`. Independently
  resolves branch (`:122`), step map (`:132`), required steps (`:137`),
  and evidence via `_resolve_run_step:779`.
- `cardre/services/report_generation_service.py:51` — the pipeline wrapper.
  `generate_and_write:72` checks readiness then collects.
- `cardre/services/export_service.py:270` — export resolves
  `latest_run_id` itself (`:271-277`) before calling
  `ReportGenerationService`.
- `cardre/services/comparison_service.py:22` — `_check_branch_readiness`
  builds its own `canon_to_actual` map (`:39-42`).
- `cardre/services/comparison_service.py:130` — `_find_typed_artifact`,
  missing across-plan fallback.
- `cardre/services/comparison_service.py:196-199` — local legacy
  `logistic-regression` fallback.
- `sidecar/routes/method_summary.py:37` — the MVP stub with its own branch
  artifact scan at `:64` and `evidence_readiness.status = "not_implemented"`
  at `:101`.
- `cardre/reporting/evidence_contract.py:81` —
  `find_evidence_for_canonical_step` (wraps central locator with aliases).
- `docs/plans/consolidation-launch-sprint/README.md` — cross-cutting rules.

## Prerequisite

Batch A must land first (for `EvidenceResolver` and
`StepResolutionService`). Batch B should land first or in parallel with
coordination, since both touch manual-binning-adjacent readiness — but the
files are disjoint, so parallel is safe.

## Changes

### 1. Create `ReportEvidencePlan`

New file `cardre/reporting/report_evidence_plan.py`.

```python
from dataclasses import dataclass
from cardre.reporting.evidence_contract import REQUIRED_STEPS_BRANCH, \
    REQUIRED_STEPS_CHAMPION, REQUIRED_STEPS_COLLECTOR
from cardre.services.evidence_resolver import EvidenceResolution
from cardre.step_id import ResolvedStepRef
from cardre.readiness.dto import ReadinessBlocker, ReadinessWarning


@dataclass
class ReportEvidencePlan:
    branch: dict
    run: dict
    plan_version_id: str
    plan_id: str | None
    resolved_steps: dict[str, ResolvedStepRef | None]
    resolved_run_steps: dict[str, EvidenceResolution | None]
    blockers: list[ReadinessBlocker]
    warnings: list[ReadinessWarning]


def build_report_evidence_plan(
    store, project_id, run_id, target_branch_id, report_mode,
) -> ReportEvidencePlan: ...
```

`build_report_evidence_plan` does once what readiness and collector each do
today:

1. Resolve branch, run, plan_version_id, plan_id.
2. Load branch step map (with the `head_pv` fallback at
   `readiness/check.py:96-98`).
3. Use `StepResolutionService.resolve_required` (mode `ancestor`, with
   centralized alias fallback) for the mode's required steps.
4. Use `EvidenceResolver` (policy `branch_then_full_then_plan`) for each
   resolved step, keyed by canonical step ID.
5. Run the WOE/IV v1 artifact check (`readiness/check.py:152-166`), champion
   checks (`:168-188`), manual-binning review check (`:190-229`), and OOT
   check (`:231-236`) — these become warnings/blockers on the plan.

### 2. Migrate `check_report_readiness`

`check_report_readiness` becomes a thin function that builds the plan and
maps `plan.blockers` / `plan.warnings` onto `ReportReadinessResult`. The
branch-not-found and run-not-found early returns at `:48-82` stay as
short-circuits before plan building.

The inline alias fallback at `:129-136` is removed —
`StepResolutionService.resolve_required` owns it now.

### 3. Migrate `ReportCollector.collect`

`ReportCollector` takes a `ReportEvidencePlan` in its constructor (or builds
one if not supplied, for backward compatibility). `collect` reads
`plan.resolved_steps` and `plan.resolved_run_steps` instead of calling
`resolve_required_steps:137` and `_resolve_run_step:779`.

The `INHERITED_BRANCH_EVIDENCE` limitation at `collector.py:788-793` is now
sourced from `EvidenceResolution.diagnostics` on the plan, so the collector
stops re-deriving it.

### 4. Migrate export report run selection

In `export_service.py:270-315`, replace the local `latest_run_id` resolution
with a call to `ReportGenerationService.latest_reportable_run(project_id,
branch_id, report_mode)`. Add that method to `ReportGenerationService` — it
returns the run id the report route would use (branch-scoped, then full-plan
fallback), so export and report never diverge.

The readiness + generate calls at `:281-294` stay, but they consume the same
plan via `ReportGenerationService`.

### 5. Migrate comparison readiness and typed-artifact lookup

In `comparison_service.py`:

- `_check_branch_readiness:22` uses `StepResolutionService.resolve_required`
  (mode `ancestor`, alias fallback) instead of the local `canon_to_actual`
  map at `:39-42`. It then uses `EvidenceResolver` to check evidence presence
  per required step.
- `_find_typed_artifact:130` is replaced by `EvidenceResolver` (policy
  `branch_then_full_then_plan`) plus `ArtifactEvidenceReader.read_optional`
  over the resolved run-step's output artifacts. The across-plan fallback
  is now automatic.
- The local legacy `logistic-regression` fallback at `:196-199` is removed —
  `canonical_alias_candidates` in the resolver handles it.

### 6. Migrate method-summary

In `sidecar/routes/method_summary.py:37`, replace the branch artifact scan
at `:64` with `EvidenceResolver` resolving `model-fit` (aliases on) for the
branch, then `ArtifactEvidenceReader.read_optional` on the output artifacts.
Replace `evidence_readiness.status = "not_implemented"` at `:101` with the
result of `build_report_evidence_plan`-style readiness for the model step
(or a lighter `StepResolutionService` + `EvidenceResolver` check if a full
plan is overkill for this endpoint).

The endpoint stays an MVP in scope (no new metrics), but it no longer lies
about evidence readiness.

## Tests

### New: `tests/test_report_evidence_plan.py`

- Readiness and collector agree on every resolved `run_step_id` for a branch
  with all-branch-owned steps.
- Readiness and collector agree for a branch with inherited source-branch
  evidence — the plan carries `INHERITED_BASELINE_EVIDENCE` diagnostics and
  both surfaces report it.
- Export with `include_report=True` uses the same run as direct report
  generation.
- A report that passes readiness produces a collector bundle whose
  `source_step_refs` match the plan's `resolved_steps`.

### Update: `tests/test_reporting.py` and `test_reporting_acceptance.py`

- Assert readiness blockers reference the same `step_id` the collector would
  have resolved.
- Assert a legacy `logistic-regression`-only plan passes readiness for
  `model-fit` via the centralized alias fallback.

### New: `tests/test_comparison_evidence_resolver.py`

- Comparison readiness resolves the same actual step IDs as report
  readiness for baseline and challenger branches.
- `_build_comparison_content` finds inherited source-branch model evidence
  that the old `_find_typed_artifact` would have missed.
- Legacy `logistic-regression` evidence is found via resolver aliases, not
  the local fallback.

### New: `tests/test_method_summary_evidence_readiness.py`

- Method summary selects the same model artifact as report/comparison for a
  branch with inherited evidence.
- `evidence_readiness.status` is no longer hardcoded to
  `"not_implemented"`.

## Verification

```bash
pytest tests/test_report_evidence_plan.py \
       tests/test_reporting.py \
       tests/test_reporting_acceptance.py \
       tests/test_comparison_evidence_resolver.py \
       tests/test_evidence_route.py \
       tests/test_evidence_summaries.py \
       tests/test_method_summary_evidence_readiness.py
```

## Definition of done

1. `ReportEvidencePlan` is produced once by readiness and consumed by
   collector, export, and method-summary.
2. Export uses `ReportGenerationService.latest_reportable_run`, not a local
   run selection.
3. Comparison readiness and typed-artifact lookup use
   `StepResolutionService` and `EvidenceResolver`; the local
   `canon_to_actual` map and `logistic-regression` fallback are deleted.
4. Method-summary no longer reports `evidence_readiness.status =
   "not_implemented"`.
5. All listed tests are green.

## Files touched

- `cardre/reporting/report_evidence_plan.py` (new)
- `cardre/readiness/check.py`
- `cardre/reporting/collector.py`
- `cardre/services/report_generation_service.py`
- `cardre/services/export_service.py`
- `cardre/services/comparison_service.py`
- `sidecar/routes/method_summary.py`
- `tests/test_report_evidence_plan.py` (new)
- `tests/test_reporting.py` (updated)
- `tests/test_reporting_acceptance.py` (updated)
- `tests/test_comparison_evidence_resolver.py` (new)
- `tests/test_method_summary_evidence_readiness.py` (new)

## Depends on

Batch A (EvidenceResolver, StepResolutionService)

## Unblocks

Batch H (parity tests include report/comparison/export/method-summary).