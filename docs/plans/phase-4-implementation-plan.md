# Phase 4 Implementation Plan

Phase 4 turns Cardre's fixed Scorecard Pathway into a constrained branchable
modelling workspace with baseline/challenger branches, branch-scoped execution,
comparison snapshots, champion assignment, and selected-branch export.

This plan intentionally uses the fewest safe batches. Phase 4A0 is a hard
foundation gate because every later feature depends on branch-aware identity,
schema, and legacy migration. After that, implementation should run in two broad
parallel batches to maximise concurrent backend, sidecar, frontend, and test
work without violating evidence-lineage dependencies.

Source specification: `docs/plans/phase-4-technical-spec.md`.

## Batch Strategy

| Batch | Scope | Dependency | Parallelism Target |
|---|---|---|---|
| Batch 0 | Branch foundation and legacy migration | Starts from Phase 3-complete `main` | Backend/store/tests can run in parallel after contracts are agreed |
| Batch 1 | Branch read/create/edit/run, manual binning, and segment branch core | Batch 0 merged | Backend services, sidecar models/routes, frontend branch UX, and integration tests run concurrently |
| Batch 2 | Comparison, champion, selected export, audit manifest, and final hardening | Batch 1 branch evidence available | Comparison engine, champion/export services, frontend Compare/Champion/Export UX, and E2E tests run concurrently |

Do not split into the original 4A through 4F sequence unless coordination fails.
The only non-negotiable sequence is Batch 0 before everything else. Batching
4A/4B/4C/4F together is safe if contracts are frozen early, because all work uses
the same branch metadata model. Batching 4D/4E together is safe because champion
and export can be implemented against immutable comparison snapshot contracts
while the comparison content fills out.

## Batch 0: Foundation Gate

Goal: make existing Phase 3 projects branch-aware without changing historical
evidence.

This batch corresponds to Phase 4A0 in the technical specification and must be
merged before any user-facing branch creation, branch execution, comparison, or
champion work starts.

### Workstreams

1. Branch identity contract
   - Extend `StepSpec` with keyword-only `canonical_step_id` and `branch_id`.
   - Backfill `canonical_step_id` in `__post_init__`.
   - Update `to_dict()` and `from_dict()` to write/read branch fields while
     tolerating legacy records.
   - Update `replace_step_params()` to preserve branch fields.
   - Add focused unit tests before touching branch services.

2. SQLite schema migration
   - Add `plan_branches`.
   - Add `branch_step_map`.
   - Add `branch_comparisons`.
   - Add `branch_comparison_snapshots`.
   - Add `champion_assignments`.
   - Keep SQLite metadata-only; do not move artifacts into SQLite.
   - Add schema-version tests that open both fresh and legacy stores.

3. Baseline migration service
   - Find user-facing Scorecard Pathway plans and exclude hidden `__import__`
     plans.
   - Create one baseline branch per Scorecard Pathway.
   - Set baseline `base_plan_version_id` to the earliest plan version and
     `head_plan_version_id` to the latest plan version.
   - Populate `branch_step_map` for every historical plan version.
   - Make migration idempotent and fail loudly on partial/inconsistent maps.
   - Do not update `run_steps`, artifact records, artifact files, or execution
     fingerprints.

4. Pre-Phase-4 fixture
   - Add a deterministic legacy fixture-generation script or compressed fixture
     representing a completed Phase 3 project with no branch tables.
   - Ensure the fixture is not produced through current Phase 4 code paths.
   - Include run records, run steps, artifact records, and actual artifact files.

5. Compatibility read path
   - Ensure old projects can be opened before migration where the compatibility
     path is expected.
   - Ensure branch-aware APIs can query the migrated baseline after migration.

### Parallel Execution

After the `StepSpec` contract is agreed, split the work immediately:

- Engineer A: `StepSpec`, serialization, and `replace_step_params()` tests.
- Engineer B: SQLite branch-table migration and schema tests.
- Engineer C: legacy fixture and migration regression tests.
- Engineer D: baseline migration service and idempotency behavior.

Merge order inside the batch should be contract-first, schema-second,
migration-third, fixture-backed regression last. These can be reviewed as
separate PRs, but the batch is not complete until all acceptance criteria pass.

### Acceptance Criteria

- Existing `StepSpec(...)` call sites continue to work.
- Legacy steps deserialize with `canonical_step_id == step_id`.
- Legacy steps deserialize with `branch_id is None` before migration.
- All branch tables are created in fresh and migrated project stores.
- Migration creates one baseline branch per user-facing Scorecard Pathway.
- Migration maps every step in every historical plan version.
- Migration does not rewrite run records, run steps, artifacts, artifact files, or
  execution fingerprints.
- The migrated baseline branch can be listed and inspected through branch-aware
  read code.

### Verification

```bash
pytest tests
```

If frontend types are touched during this batch, also run:

```bash
cd frontend && npx tsc --noEmit
```

## Batch 1: Branchable Pathway Core

Goal: make branches visible, creatable, editable, executable, and usable for
manual-binning and segment experiments.

This batch combines the original Phase 4A, 4B, 4C, and the core of 4F. It is the
largest batch, but it has strong internal contracts and high parallelism. The
batch should start with response/request models and service interfaces so backend
and frontend work can proceed concurrently.

### Workstreams

1. Branch read model and API contracts
   - Implement `GET /projects/{project_id}/branches`.
   - Implement `GET /branches/{branch_id}`.
   - Implement `GET /plans/{plan_id}/branches` if useful for frontend data
     loading.
   - Add branch-aware plan response fields: `canonical_step_id`, `branch_id`, and
     `branch_label`.
   - Return backend-owned branch status, readiness, warnings, and champion flags
     where available; do not let React infer modelling truth.

2. Branch creation service
   - Implement `POST /plans/{plan_id}/branches`.
   - Validate permitted branch points and matching branch types.
   - Require non-empty branch name and creation reason.
   - Compute descendant closure from graph structure.
   - Generate stable opaque branch-owned step IDs.
   - Remap parents for duplicated downstream steps.
   - Preserve shared upstream links through `branch_step_map`.
   - Create a new plan version and update branch head atomically.
   - Do not copy run records or artifacts.

3. Branch-aware parameter editing
   - Extend `POST /plans/{plan_id}/steps/{step_id}/params` to accept generated
     branch step IDs.
   - Validate owning branch and active status.
   - Create a new plan version for branch-owned edits.
   - Preserve branch metadata across all steps.
   - Update only the owning branch's `head_plan_version_id`.
   - Stale only changed branch-owned steps and their branch-owned descendants.

4. Branch-aware manual binning
   - Generalise editor state loading to
     `GET /plans/{plan_id}/steps/{step_id}/editor-state`.
   - Generalise preview to
     `POST /plans/{plan_id}/steps/{step_id}/manual-binning/preview`.
   - Implement `find_nearest_ancestor_by_canonical_step_id()` using branch scope
     from `branch_step_map`.
   - Resolve fine-classing and variable-selection ancestors by canonical identity,
     not generated string construction.
   - Keep preview non-persistent: no artifacts, no run records, no plan version.

5. Branch-scoped execution
   - Extend `POST /runs` with `run_scope` values `full_plan`, `branch`, and
     `step_descendants`.
   - Add `branch_id` to run association where needed.
   - For branch runs, execute only stale/not-run branch-owned steps.
   - Reuse current shared upstream evidence without rerunning it.
   - Block branch execution when required shared upstream evidence is stale.
   - Do not create a plan version during normal branch execution.

6. Segment branch core
   - Support `segment_challenger` creation from `sample-definition`.
   - Reuse the Apply Exclusions rule validation/filter contract for segment
     filters.
   - Keep audit semantics distinct: exclusions remove rows, segment filters define
     a challenger population.
   - Record segment filter reasons.
   - Surface small-sample and low-bad-count warnings where data is available.

7. Frontend branch UX
   - Add navigation entries for Branches and Compare/Champion placeholders.
   - Build Branch Manager against branch list/detail endpoints.
   - Build Create Branch wizard with shared-upstream and duplicated-downstream
     review.
   - Add Single Branch View and Branch Lane View without freeform DAG editing.
   - Add branch-aware inspector identity section.
   - Show actual step IDs as copyable implementation details, not primary labels.
   - Keep actions wired to actual `step_id` values.

8. Integration tests
   - Add migrated-baseline branch list/detail tests.
   - Add branch creation tests for every permitted branch point.
   - Add rejection tests for forbidden branch points.
   - Add branch param edit and staleness tests.
   - Add branch manual-binning editor and preview tests.
   - Add branch run tests including shared-upstream stale blocker.
   - Add segment branch creation/filter validation tests.

### Parallel Execution

Start the batch with a one-day contract freeze:

- Pydantic request/response models.
- Branch service method signatures.
- Frontend TypeScript DTOs.
- Canonical error codes.

Then split aggressively:

- Engineer A: branch read model, plan response fields, branch status/readiness
  summaries.
- Engineer B: branch creation, descendant closure, generated step IDs, parent
  remapping.
- Engineer C: branch-aware params, staleness, branch head updates.
- Engineer D: branch-scoped execution and shared-upstream blockers.
- Engineer E: manual-binning ancestor resolution, editor-state, preview.
- Engineer F: segment filter validation reuse and segment branch tests.
- Engineer G: frontend Branch Manager, wizard, lane view, inspector identity.
- Engineer H: integration flow coverage and fixture reuse.

Avoid merging frontend string-splitting shortcuts. If an endpoint lacks canonical
identity, fix the backend contract instead of adding frontend inference.

### Acceptance Criteria

- Migrated projects show the baseline branch.
- Plan responses include canonical step IDs and branch IDs.
- Users can create challengers from `manual-binning`, `logistic-regression`, and
  every other permitted branch point.
- Forbidden branch points are rejected with structured diagnostics.
- Branch creation creates no copied evidence.
- Branch-owned param edits stale only branch-owned descendants.
- Baseline remains current after challenger edits.
- Manual-binning editor works for generated branch step IDs.
- Branch runs execute only needed branch-owned steps.
- Stale shared upstream evidence blocks branch runs clearly.
- Segment filters reuse exclusion operators and require reasons.
- Branch UI uses actual step IDs for API calls and displays branch identity
  without overwhelming the inspector.

### Verification

```bash
pytest tests
cd frontend && npx tsc --noEmit
cd frontend && npm run build
```

## Batch 2: Comparison, Champion, Export, And Final Hardening

Goal: make branch evidence useful for audit decisions: compare branches, record a
champion based on immutable comparison evidence, and export selected branch
lineage.

This batch combines the original Phase 4D and 4E plus final segment/export
hardening. It should start once Batch 1 can produce current branch evidence for a
baseline and at least one challenger.

### Workstreams

1. Comparison intent and readiness
   - Implement `POST /branch-comparisons`.
   - Implement `GET /branch-comparisons/{comparison_id}`.
   - Validate baseline/challenger branch membership.
   - Compute readiness from current successful evidence by canonical step ID.
   - Cache readiness only where safe and invalidate on branch head changes,
     branch runs, branch archival, and comparison spec changes.
   - Never trigger modelling execution from readiness checks.

2. Immutable comparison snapshots
   - Implement `POST /branch-comparisons/{comparison_id}/refresh`.
   - Implement `GET /branch-comparison-snapshots/{comparison_snapshot_id}`.
   - Create an immutable JSON comparison artifact on every ready refresh.
   - Create a `branch_comparison_snapshots` row for every ready snapshot.
   - Update latest snapshot pointers on comparison intent.
   - Return structured missing/stale evidence diagnostics when blocked.
   - Do not create run records during refresh.

3. Comparison content engine
   - Compare WOE/IV outputs and bin definitions.
   - Compare selected variables and model coefficients.
   - Compare score scaling outputs.
   - Compare validation metrics by role: train, test, OOT.
   - Compare cutoff/strategy outputs.
   - Surface warnings and errors explicitly, not only as raw JSON.
   - Keep comparison descriptive; do not declare a winner.

4. Champion assignment
   - Implement `POST /plans/{plan_id}/champion`.
   - Implement `GET /plans/{plan_id}/champion`.
   - Require active branch, current evidence, ready comparison snapshot, and
     non-empty rationale.
   - Supersede previous active champion assignment atomically.
   - Do not mutate artifacts, runs, or model evidence.

5. Selected branch export
   - Extend `POST /exports/audit-pack` to accept `branch_id`, comparison ID, and
     comparison snapshot ID.
   - Export selected branch only by default.
   - Include shared upstream lineage needed to explain the selected branch.
   - Include branch-owned evidence, hashes, params, warnings, errors, run IDs,
     run-step IDs, comparison snapshot, champion metadata, and technical manifest.
   - Exclude row-level data by default.
   - Return structured diagnostics for missing or corrupt artifacts.

6. Frontend Compare, Champion, and Export UX
   - Build comparison setup and refresh UI.
   - Show missing/stale evidence states with text labels.
   - Render WOE/IV, model, validation, cutoff, and warning comparison sections.
   - Add champion modal with required rationale and supersession warning.
   - Add champion badges in Branch Manager and branch views.
   - Add selected branch export flow and export diagnostics.
   - Keep the UI from claiming automatic winner selection.

7. End-to-end acceptance flows
   - Pre-Phase-4 baseline migration flow.
   - Manual-binning challenger flow.
   - Segment challenger flow.
   - Champion assignment persistence after close/reopen.
   - Selected champion branch export verification.

### Parallel Execution

Freeze comparison artifact JSON and champion/export request contracts first.
Then split:

- Engineer A: comparison intent, readiness, and missing/stale diagnostics.
- Engineer B: snapshot artifact persistence and snapshot read endpoints.
- Engineer C: WOE/IV, model, validation, cutoff, and warning comparison content.
- Engineer D: champion assignment and supersession.
- Engineer E: selected branch export and branch-aware technical manifest.
- Engineer F: frontend Compare view.
- Engineer G: frontend Champion and Export flows.
- Engineer H: E2E acceptance automation and regression hardening.

Champion and export services can proceed before comparison content is complete if
they validate against ready snapshot metadata and artifact references. Final
acceptance still requires full comparison content.

### Acceptance Criteria

- Comparison intent can be created without executing modelling nodes.
- Comparison refresh never creates run records.
- Ready refresh creates immutable comparison artifact and snapshot rows.
- Missing/stale evidence blocks comparison with actionable diagnostics.
- Train/test/OOT validation metrics are separated.
- Champion assignment requires ready comparison snapshot and rationale.
- Previous champion is superseded atomically.
- Champion assignment persists after close/reopen.
- Selected branch export includes lineage, shared upstream evidence,
  branch-owned evidence, comparison snapshot, champion assignment, hashes,
  warnings, and manifest evidence.
- Export excludes row-level data by default.
- UI never declares an automatic winner.

### Verification

```bash
pytest tests
cd frontend && npx tsc --noEmit
cd frontend && npm run build
```

## Cross-Batch Rules

- Backend is the source of truth for branch identity, canonical identity,
  staleness, comparability, lineage, and export content.
- React must not generate branch step IDs or infer lineage by splitting strings.
- Runs are evidence; plan versions are design state.
- Normal branch execution must not create plan versions.
- Comparison refresh is not a run and must not create run records.
- Branch creation and param edits must be transactional.
- Historical run evidence must not be rewritten.
- Do not copy artifacts to create branch evidence.
- Do not add arbitrary DAG editing, branch merging, plugin nodes, hosted
  execution, approval workflow, or governance-quality narrative reporting.

## Merge And Review Plan

Use as few release batches as possible, but avoid one unreviewable mega-PR.
Recommended PR shape:

1. Batch 0 PR group: contract, schema, migration, fixture, regression tests.
2. Batch 1 PR group: branch APIs/services, branch execution/manual-binning,
   segment core, frontend branch UX, integration tests.
3. Batch 2 PR group: comparison snapshots/content, champion/export, frontend
   decision UX, final E2E tests.

Each PR group may contain multiple parallel PRs, but the product should only move
through three acceptance gates. Do not start the next gate until the previous
gate's acceptance tests pass on `main` or the shared phase branch.

## Final End-to-End Gate

Phase 4 is complete only when this flow passes against a closed and reopened
project:

1. Open a completed pre-Phase-4 project.
2. Run Phase 4 migration.
3. Confirm baseline branch exists.
4. Confirm historical run records and artifacts still load.
5. Create a manual-binning challenger.
6. Confirm shared upstream and duplicated downstream steps are displayed.
7. Open branch manual-binning editor and resolve source bins by branch-aware
   ancestry.
8. Save a valid override with reason.
9. Confirm challenger head updates and challenger descendants are stale.
10. Confirm baseline remains current.
11. Run challenger branch.
12. Create and refresh comparison intent.
13. Confirm immutable comparison snapshot and artifact are created.
14. Inspect WOE/IV, model, train/test/OOT validation, cutoff, and warning
    comparisons.
15. Mark challenger champion with rationale.
16. Confirm previous champion is superseded.
17. Export selected champion branch.
18. Confirm export includes shared upstream lineage, branch-owned evidence,
    comparison snapshot, champion assignment, hashes, warnings, and technical
    manifest.
19. Close and reopen the project.
20. Confirm baseline, challenger, comparison snapshot, champion assignment, run
    history, artifacts, and export evidence persist.
