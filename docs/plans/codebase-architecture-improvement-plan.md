# Codebase Architecture Improvement Plan

Prioritized implementation plan for structural improvements identified by
thermo-nuclear code quality review.  Designed as parallelizable PR batches
to minimize merge conflicts.

## Key Constraints

- **ADR-0002** — Extend PlanExecutor, do not create a parallel execution stack.
  All executor changes must deepen the existing seam.
- **ADR-0003** — Pre-launch; backward compatibility is not required. Legacy
  branches can be removed, not just deprecated.

## Batch 1: Fast Correctness And Hygiene

Files barely overlap — can run in parallel.

1. **Frontend correctness**
   - Fix `StepInspector` hook ordering (move `useQuery` before early return).
   - Fix `SchemaDrivenParamsEditor` method initialization from `currentParams.method`.
   - Remove misleading "Auto-generated" banner from `frontend/src/types.ts`.

2. **Test collection and contracts**
   - Dedent `test_full_phase2a_pathway_import_through_manifest` into a class.
   - Add registry reconciliation to node contract tests: every registered
     public node must have a contract test or explicit exception.

3. **Packaging hygiene**
   - Keep `/build/` ignored (PR #1 already added).
   - Add package data for `cardre/reporting/templates/*.j2`.
   - Add `numpy` to explicit dependencies.
   - Stop ignoring `frontend/src-tauri/Cargo.lock` for reproducible builds.

4. **API contract drift**
   - CI diff both `frontend/src/api/schema.d.ts` and `frontend/src/api/openapi.json`.

## Batch 2: Guardrails Before Big Refactors

1. **Artifact-read guardrail** — Add a test banning direct
   `json.loads(store.artifact_path(...).read_text())` outside approved modules.

2. **Executor invariants** — Add characterization tests for full-plan, branch,
   to-node, force, cancellation, and role/leakage enforcement.

3. **API response contract tests** — Cover branch list fields, report generation
   options, and metadata fields. Decide whether ignored fields should be
   implemented or removed.

## Batch 3: Deepen Core Seams

1. **Evidence seam** — Introduce typed artifact/evidence access as the canonical
   module. Move raw parsing for model, scorecard, selection, validation, cutoff,
   and clustering artifacts behind this interface.

2. **Evidence locator** — One module for successful run-step/evidence lookup
   policies: branch-scoped, full-plan only, across plan versions, shared upstream
   fallback. Replace duplicated lookup loops in `staleness.py`,
   `branch_evidence.py`, `comparison_service.py`, `export_service.py`,
   `step_id.py`.

3. **Step graph module** — Centralize ancestors, descendants, canonical-to-actual
   resolution, closure logic. Replace duplicated code in `executor.py` and
   `branch_service.py`.

## Batch 4: PlanExecutor Internal Simplification

Depends on Batch 2; benefits from Batch 3.

1. **Internal ExecutionPlan** — `StepAction(step, action, evidence_source)` with
   actions `execute`, `reuse`, `skip`.

2. **Preserve public interface** — `run_plan_version`, `run_branch`,
   `run_to_node` signatures unchanged. Internally each builds an `ExecutionPlan`.
   One shared loop consumes actions.

3. **Move output artifact resolution** — Stop `BranchEvidenceResolver` calling
   executor private helpers. Put behind evidence/artifact module.

## Batch 5: Model Family Adapter Refactor

1. **ModelFamilyAdapter** — `fit`, `apply`, `summarize`, `limitations`.
   Register adapters by `model_family`.

2. **Move application logic** — Out of `ApplyModelNode` into logistic, sklearn,
   and ensemble adapters.

3. **Normalize model artifact construction** — Route logistic regression through
   the same modeling builder path as other classifiers.

## Batch 6: Store Decomposition

1. **Internal split** — `ArtifactRepository`, `PlanRepository`, `RunRepository`,
   `BranchRepository`, `ComparisonRepository`.

2. **Compatibility facade** — `ProjectStore` delegates initially.

3. **Gradual migration** — Services first, then executor, then routes.

## Batch 7: Large Node Domain Services

Per-node area, can run in parallel after evidence seam is available:
- Variable selection → `VariableSelectionPlanner` + policies.
- WOE/IV and binning → pure calculation modules.
- Validation metrics and clustering → extracted services.
- Reject inference → dedicated population/augmentation module.

## Batch 8: Frontend And Sidecar Architecture

- Replace handwritten API client with generated `paths`-typed operations.
- Extract `useRunProgress(runId)` hook from `ProjectView`.
- Fix Tauri sidecar lifecycle: store `Child`, check health body, avoid TOCTOU.

## Recommended Execution Order

1. Batch 1 (PR)
2. Batch 2
3. Batches 3 + 8 (parallel)
4. Batch 4
5. Batch 5
6. Batch 6
7. Batch 7 (parallel per-node)
