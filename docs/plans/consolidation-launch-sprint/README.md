# Consolidation Launch Sprint — Evidence, Lifecycle, and API Surface

## Purpose

Consolidate the duplicated, divergent backend primitives that decide
"which evidence counts", "is this run current", "what should the UI show",
and "what error did the user actually get" before launch. The sprint is not
abstraction for neatness — it is a correctness boundary: today the same
branch/step can be current for execution and unavailable for comparison,
report, export, or manual-binning.

Target outcome: a single resolution path for evidence, step IDs, run
currentness, and API errors, with cross-service parity tests proving the
launch journey cannot silently diverge.

## Why now

`cardre/evidence_locator.py` already exists and documents the intended
branch-scoped → full-plan → across-plan-version policy. Several important
paths still bypass it:

- `BranchEvidenceResolver._find_shared_evidence` re-implements the chain with
  diagnostics but a different search order.
- `ManualBinningService._resolve_upstream_defs._find_run_step` uses
  branch-exact → latest full-plan run → latest plan run, and reads only the
  first output artifact.
- `comparison_service._find_typed_artifact` scans the branch step map and
  same-version branch/full-plan run-steps, but drops the across-plan
  fallback.
- `export_service` shared-upstream lookup ignores source branch evidence.
- `step_id.resolve_run_step` has its own exact-vs-ancestor policy.

Each consumer can return a different `RunStepRecord` (or none) for the same
branch/step. The riskiest case is inherited source-branch evidence: branch
execution uses source-branch-aware lookup, while export and comparison use
variants that can miss it.

## Scope boundary

This sprint does **not** add new modelling nodes, new evidence kinds, or new
scorecard functionality. It does not rewrite the executor or the run store.

Allowed changes are limited to:

- Extracting and consolidating resolution/currentness/lookup primitives.
- Migrating existing consumers onto the consolidated primitives.
- Converting service `ValueError` codes to `CardreError` subclasses.
- Frontend query string and error display helpers.
- Cross-service parity tests.

If a change tempts you into `cardre/nodes/`, new evidence schemas, or a new
orchestration abstraction over `ReportGenerationService`, stop and re-scope.

## Validation context (read before starting)

The plan was validated against the repo on 2026-06-26. Confirmed facts that
shape the work:

- `cardre/evidence_locator.py:45` `latest_successful_run_step` implements the
  intended branch → full-plan → plan-level run fallback. It is not used by
  `BranchEvidenceResolver._find_shared_evidence`, manual binning, comparison,
  or export shared-upstream lookup.
- `cardre/services/branch_evidence.py:254` `_find_shared_evidence` searches
  across-plan with `source_branch_id` first, then baseline, then latest plan
  run. It emits diagnostics. The central locator does neither.
- `cardre/services/manual_binning_service.py:546` `_find_run_step` is a
  private closure: branch-exact → latest full-plan run for this version →
  latest plan run scan. It does not consult the central locator and does not
  fall back across plan versions.
- `cardre/services/comparison_service.py:130` `_find_typed_artifact` scans the
  branch step map, then same-version branch run-step, then same-version
  full-plan run-step. No across-plan fallback. Legacy `logistic-regression`
  fallback is handled locally at `:196-199`.
- `cardre/services/export_service.py:178` shared-upstream lookup uses
  `branch_id=None` and a latest plan run scan. It ignores
  `source_branch_id` from the branch step map.
- `cardre/step_id.py:95` `resolve_run_step` returns `None` immediately for
  `resolution == "exact"` after the run-specific check; only ancestor
  resolution gets the broader fallback.
- `cardre/staleness.py:44` `compute_staleness` collects a same-version run-step
  map, while `step_is_stale:75` can substitute across-plan evidence with
  fingerprint matching. `staleness_detail:186` reasons are computed from the
  collected map, which may not match the evidence `step_is_stale` actually
  used. `_staleness_reason:148` does not check across-plan fallback.
- `sidecar/routes/runs.py:59` `_is_branch_current` and `:76`
  `_is_to_node_current` are route-level preflight helpers.
  `_is_branch_current` swallows all non-`CardreError` exceptions at `:71`.
  `_is_to_node_current` returns any existing successful run for the plan
  version when the closure is non-stale, not necessarily a run matching the
  requested branch/to-node scope.
- `sidecar/routes/runs.py:218-234` the route owns placeholder run creation and
  background thread creation. `run_orchestrator.dispatch_run_async:82` owns
  async failure diagnostics, but thread-start failure at `:235` marks the run
  failed with no diagnostic.
- `cardre/services/run_orchestrator.py:46-60` short-circuit handling cancels
  the placeholder run with a `RUN_SHORT_CIRCUITED` diagnostic when the executor
  returns a different run id. The route's preflight short-circuit at
  `:202-211` returns the existing run without creating a placeholder, so sync
  and async branch no-op paths can produce different lifecycle histories.
- `sidecar/error_handling.py:98` provides the central `CardreError` envelope.
  Routes still catch `ValueError` and flatten codes:
  `comparisons.py:33` (`COMPARISON_FAILED`), `comparisons.py:91`
  (`REFRESH_FAILED`), `exports.py:36` (`EXPORT_FAILED`), `reports.py:73`
  (`READINESS_FAILED`), `champion.py:29` (`CHAMPION_FAILED`),
  `projects.py:42` (path validation). Service `ValueError` messages carry the
  real code (e.g. `BASELINE_BRANCH_NOT_FOUND: ...`) but the route discards it.
- `cardre/readiness/check.py:121` and `cardre/reporting/collector.py:137` both
  resolve branch, step map, required steps, and evidence independently.
  `export_service.py:271` resolves the latest report run itself before calling
  `ReportGenerationService`, so export can choose a different run than the
  report route would use.
- `cardre/services/manual_binning_service.py:87` `get_editor_state` blocks on
  stale upstream via `compute_staleness`. `:330` `preview_overrides` repeats
  step/branch/nearest-source lookup but does **not** re-check staleness.
  `:407` `validate_overrides` uses `_find_mb_step_id_for_validation:593`,
  which scans all steps by canonical ID and prefers branch-owned only if
  `branch_id` matches — not the same nearest-upstream selection as the editor.
- `frontend/src/api/client.ts:92` `formatApiError` already exists and
  `useRunProgress` already uses it. `frontend/src/utils/errors.ts:10`
  `renderApiError` also exists. However `ManualBinningEditor.tsx:43`,
  `ArtifactBrowser.tsx:100`, `ArtifactSummaryInline.tsx:12`, and
  `ArtifactPreviewPane.tsx:21` still drop or undersurface API error
  code/request ID details.
- `frontend/src/api/client.ts` mixes `URLSearchParams` (`:250`, `:269`,
  `:317`, `:408`) with manual interpolation (`:245`, `:297`, `:300`, `:326`,
  `:370`, `:405`, `:419`, `:423`). `getReportServeUrl:427` correctly uses
  `encodeURIComponent` for the path segment.
- `cardre/services/artifact_service.py:33` `build_json_summary_preview` has
  no callers other than its own definition. `sidecar/routes/artifacts.py:25`
  `_shape_value` and `:61` `_json_artifact_preview` are route-local; the
  evidence route at `sidecar/routes/evidence.py:26` builds its own semantic
  summary with a separate `_to_item`.
- Cross-project ID scans are inconsistent:
  `artifact_service.find_artifact:18`, `runs.get_run:253`,
  `comparisons.get_branch_comparison:52`, `branches.get_branch:60`,
  `plans.get_plan:43`, `plans.get_workflow_guidance:128`. Some skip missing
  project paths (`runs.py:257`, `:271`); others do not
  (`comparisons.py:54`, `branches.py:71`). None detect duplicate IDs across
  stores.
- `cardre/services/workflow_guidance_service.py:232` repeats staleness,
  `:261` repeats `resolve_required_steps`, `:296` repeats
  `check_report_readiness`, and `:387/:427` repeats manual-binning editor
  state lookup. This is a missed instance not enumerated in the source
  report.
- `sidecar/routes/method_summary.py:64` is an explicit evidence-readiness
  stub with its own branch artifact scan. `:101` returns
  `evidence_readiness.status = "not_implemented"`. This is a missed instance
  not enumerated in the source report.
- CI enforces a **600-line limit per `.tsx` file**
  (`scripts/check-line-counts.py`, job `check-line-counts`). New frontend
  helpers/components must stay under it.
- `check-api-contracts` CI job regenerates `frontend/src/api/schema.d.ts`
  and fails on uncommitted diff. Any backend model change must commit the
  regenerated types in the same PR.

## Batch sequence

| Batch | Title | Wave | Main outcome |
|-------|-------|------|--------------|
| A | Evidence and step resolution foundations | 1 | `EvidenceResolver` + `StepResolutionService` with diagnostics, replacing `evidence_locator.py` and `step_id.resolve_run_step` |
| B | Manual-binning context unification | 2 | `ManualBinningContextResolver` shared by editor, preview, validation, and save review |
| C | Report, comparison, export, and method-summary evidence consumers | 3 | `ReportEvidencePlan` consumed by readiness, collector, comparison, export, and method-summary |
| D | Run currentness and orchestrator-owned submission | 2 | `RunCurrentnessService` + `submit_run` owning preflight, placeholder creation, dispatch, diagnostics |
| E | Service-level API errors | 3 | `CardreError` subclasses raised by services; route-local `ValueError` wrappers removed |
| F | Artifact presentation and resource locator | 2 | `ArtifactPresentationService` + `ResourceLocator` standardizing cross-route read/lookup |
| G | Frontend query and error surfaces | 1 | `withQuery` + `ErrorNotice` used across the API client and artifact/manual-binning components |
| H | Integration consistency tests | 4 | Cross-service parity tests proving the consolidated primitives are actually used |

Detailed LLM instructions live in:

- `batch-a-evidence-step-resolution-foundations.md`
- `batch-b-manual-binning-context-unification.md`
- `batch-c-report-comparison-export-method-summary.md`
- `batch-d-run-currentness-orchestrator-submission.md`
- `batch-e-service-level-api-errors.md`
- `batch-f-artifact-presentation-resource-locator.md`
- `batch-g-frontend-query-error-surfaces.md`
- `batch-h-integration-consistency-tests.md`

## Parallelisation plan

```
Wave 1 (parallel):
  Batch A — Evidence and step resolution foundations
  Batch G — Frontend query and error surfaces
  (no shared files; frontend can proceed while backend foundations are built)

Wave 2 (parallel, after Batch A):
  Batch B — Manual-binning context unification
  Batch D — Run currentness and orchestrator-owned submission
  Batch F — Artifact presentation and resource locator
  (disjoint primary files; all consume the new resolver contracts)

Wave 3 (after B/D/F; coordinate C before E on shared service files):
  Batch C — Report, comparison, export, and method-summary evidence consumers
  Batch E — Service-level API errors
  (Batch E sweeps routes/services that Batch C also touches; land C first or
  split E by service if true parallel work is required)

Wave 4 (sequential, after all backend migrations):
  Batch H — Integration consistency tests

Wave 5 (sequential):
  Full verification and launch gate
```

## Cross-cutting rules for all batches

1. **No new modelling/evidence/scorecard scope.** If a change tempts you into
   `cardre/nodes/`, `cardre/executor.py` modelling logic, or new evidence
   schemas, stop and re-scope.
2. **Extend, do not reinvent, the error framework.** Services raise
   `CardreError` subclasses; routes stop catching `ValueError` except at
   legacy boundaries. Never add a second error envelope.
3. **One resolution path per concern.** Evidence, step ID, currentness,
   manual-binning context, and report evidence plan each have exactly one
   owning module. Consumers delegate; they do not re-implement.
4. **Diagnostics travel with the resolution.** When consolidating, preserve
   the diagnostic capability of `BranchEvidenceResolver._find_shared_evidence`
   (inherited baseline warning, reuse-not-found warning). The new primitives
   must emit at least as much signal as the code they replace.
5. **Compatibility wrappers are temporary.** `evidence_locator.py` may remain
   as a compatibility shim during migration and must be deleted in the
   integration batch once all call sites move.
6. **No new handwritten TS types for API shapes.** Per ADR 0006, API response
   shapes come from `frontend/src/api/schema.d.ts`. If a backend model changes,
   regenerate types with `python3 scripts/generate-openapi-types.py` and
   commit the diff in the same PR.
7. **Every new frontend test uses MSW.** Do not mock `api` modules directly.
   The `server` in `frontend/src/test/server.ts` is the only network seam.
8. **Do not leave TODOs that gate safety.** If a guard cannot be implemented,
   either implement the prerequisite or remove the guard — do not ship a TODO
   that implies safety the code does not provide.
9. **Preserve protected artifacts.** Per `ce-code-review` convention, never
   flag `docs/brainstorms/`, `docs/plans/`, or `docs/solutions/` for deletion.
   This sprint's plan files live under `docs/plans/consolidation-launch-sprint/`
   and are decision artifacts, not stale code.
10. **Stay under the 600-line `.tsx` ceiling.** Extract before approaching
    it. Reusable helpers go in `frontend/src/utils/` or
    `frontend/src/hooks/`, not inline.

## Definition of done for the sprint

1. One `EvidenceResolver` resolves run-step/artifact evidence for branch
   execution, comparison, export, report, and manual-binning; a table-driven
   parity test proves identical `run_step_id` for the same branch/step.
2. One `StepResolutionService` resolves canonical step IDs for readiness,
   collector, comparison, validation, and workflow guidance; a shared fixture
   test proves identical resolved refs.
3. One `RunCurrentnessService` evaluates branch/to-node currentness and feeds
   `submit_run`; sync and async branch no-op paths produce equivalent status
   and diagnostics.
4. Services raise `CardreError` subclasses; routes return `detail.code`
   domain codes (e.g. `BRANCH_NOT_FOUND`, `BASELINE_BRANCH_NOT_FOUND`,
   `REPORT_BLOCKED`) not flattened wrappers.
5. One `ReportEvidencePlan` is produced by readiness and consumed by
   collector, export, and method-summary; readiness and collector agree on
   every resolved `run_step_id`.
6. One `ManualBinningContextResolver` backs editor, preview, validation, and
   save review; preview refuses stale source evidence and validation uses
   the same binning artifact ID as editor state.
7. `ArtifactPresentationService` and `ResourceLocator` standardize artifact
   summary/preview/evidence presentation and cross-project lookup; the unused
   `build_json_summary_preview` is deleted.
8. `withQuery` is used for every optional frontend query string; `ErrorNotice`
   surfaces API error code/request ID in artifact and manual-binning UI.
9. Cross-service parity tests in Batch H pass, proving the consolidated
   primitives are actually used everywhere.
10. `evidence_locator.py` compatibility wrapper is deleted (or explicitly
    retained with a documented reason) after all call sites migrate.
11. `pytest tests/` and `npm run test -- src/api src/hooks src/components/__tests__/ProjectView`
    are green on the integration branch.

## Priority

This sprint is a launch prerequisite. Do it before any new evidence UI polish,
manual-binning redesign, or additional modelling nodes. Without it, every new
feature inherits the divergent resolution paths and adds another way to be
wrong about the same logical question.