# 06 — Sprint Plan

## Prerequisite decision

**Resolved 2026-07-21.** [ADR-0014](../adr/0014-supersede-0002-authorise-hexagonal-re-encapsulation.md) supersedes ADR-0002 and authorises the hexagonal re-encapsulation. ADR-0002 is marked Superseded. The sprint may begin. ADR-0014 records D1 (clean rewrite) and D2 (preserve domain vocabulary) as Accepted, and carries forward ADR-0002's preserved design commitments (dual hashing, computed staleness, build/validate role enforcement, settled vocabulary, single execution path).

## Pre-sprint: implementation decisions (D3–D18) — RESOLVED

All 16 implementation decisions are confirmed as Accepted (2026-07-21) in `00-validation-report.md` §Resolved implementation decisions. Two additional decisions (D19 `cardre/engine/` + `cardre/workflows/` disposition, D20 `pr7-followup` forwarders) were resolved after inspecting `cardre/engine/binning/` (5 modules, 10 import sites) and `cardre/workflows/scorecard.py` (canonical 13-step pathway, 5 test import sites). No batch agent should need to make or stall on any decision. The sprint may begin immediately.

## Batches at a glance (revised for speed)

The original 9-batch plan is restructured for wall-clock speed via four levers: (1) merge the trivial skeleton batch into the first real batch, (2) overlap persistence implementation with node-contract design, (3) split the bulk node-porting batch into parallel family sub-PRs, (4) merge the final cleanup batch into the API batch. Result: ~6 serial steps with two parallel bursts, versus 9 fully serial.

| # | Title | Objective | Reason for position | Difficulty | Parallelizable |
|---|-------|-----------|---------------------|------------|----------------|
| 01 | Bootstrap + API skeleton + composition root + architecture enforcement | **Merged with old Batch 01.** `Settings`, `Container`, `build_app`, thin API (`/health` + `/projects`), `ProjectRegistryPort` + `ProjectProvisionerPort` + `UnitOfWork` skeleton + adapters; `importlinter` config + forbidden-symbol tests (xfail during migration); `domain/` `application/ports/` `nodes/contracts.py` `bootstrap/` skeletons. Regenerate OpenAPI. | First real batch; proves the composition root + dependency direction; enforcement blocking from the start | high | no (foundation) |
| 02 | SQLite persistence layer + clean schema + artifact store | Clean schema v1; `SqliteUnitOfWork`; all SQLite query objects; `adapters/filesystem/ArtifactStore` (staging+atomic publish); port contract tests (in-memory + sqlite) | Foundation every use case + node depends on; artifact atomicity is the core fix for H7 | very high | overlaps with 03-design (see below) |
| 03 | Domain moves + node contracts + port first node | Move `domain/evidence/`, `nodes/parameters.py`; introduce `NodeDefinition`/`NodeContext`/`InputCollection`/`OutputPublisher`/`NodeResult`; port `LogisticRegressionNode` (parity oracle); port `adapters/evidence/` behind `ArtifactReader` | Proves the node contract with the canonical fit node; evidence adapters become real adapters | very high | **design overlaps with 02** (see Parallelization) |
| 04 | Port remaining launch nodes (parallel family sub-PRs) | Port 30 launch nodes from `context.store` to `NodeContext`; port `modeling/adapters.py` + `serialization.py` + `_training_utils.py`; `bootstrap/node_catalogue.py`. **Split into 4–5 parallel sub-PRs by family:** prep (8), build-fit (15, incl. LogisticRegression done in 03), build-export (3), validate-apply (4). (`TechnicalManifestExportNode` deferred to 05.) | All launch nodes must be on the new contract before execution runs; mechanical work following the pattern 03 proved | high | **yes — 4-way parallel** |
| 05 | Execution runtime + runs use cases + `TechnicalManifestExportNode` | `SubmitRun`, `ExecuteRun`, `CancelRun`, `GetRun`, `ListRuns`, `GetRunSteps`, `GetRunEvidence`; `StepRunner` (new); `ThreadRunDispatcher`/`SyncRunDispatcher`; `FinalizeRun` (manifest inside UoW); port `TechnicalManifestExportNode` (needs `RunSummary` from `ExecuteRun`); cooperative cancellation; delete old `cardre/execution/` + `services/run_coordinator.py` | Ties nodes + persistence + dispatch; must follow 02+03+04 | very high | no (integration point) |
| 06 | Plans + evidence + governance + reporting use cases (parallel sub-PRs) | All remaining use cases: plans (8), evidence (1), governance (4), reporting (2); `adapters/rendering/`, `adapters/reporting/`; delete old `cardre/services/`, `cardre/reporting/`, `cardre/readiness/`, `cardre/evidence_locator.py`, `cardre/branch_step_resolver.py` | Use cases depend on 02+05; independent of each other → parallel | high | **yes — 4-way parallel** (plans, evidence, governance, reporting) |
| 07 | API routes + frontend regeneration + delete old architecture + finalize enforcement | **Merged with old Batch 09.** All remaining routes; full `api/schemas.py`; governance router; regenerate OpenAPI + `schema.d.ts`; update frontend `client.ts`/`useProjectWorkspace`/components; **then** delete `cardre/store/`, `cardre/config.py`, `cardre/artifacts.py`, `cardre/capabilities.py` (`cardre/engine/` + `cardre/workflows/` already moved/deleted in Batch 03 per D19); tighten `importlinter` + un-xfail forbidden-symbol tests; full product acceptance pathway | API is the consumer-facing layer; cleanup is small once API is live | high | no (final) |

**Total: 7 batches** (down from 9). Each batch is one PR; Batches 04 and 06 are sets of parallel sub-PRs merging together.

## Dependency graph

```
        ┌────────────────────────────────────────────────┐
        │                                                │
01 ──> 02 ──> 03 ──> 04 (4 parallel sub-PRs) ──> 05 ──> 06 (4 parallel sub-PRs) ──> 07
                ▲       │                                  │
                │       └── 03-design overlaps 02 ─────────┘
                │
        (03 contract design starts during 02 implementation)
```

Serial critical path: **01 → 02 → 03 → 04 → 05 → 06 → 07** (7 steps).
Wall-clock path with parallelism: **01 → 02 (overlapped with 03-design) → 03 → 04 (4-way parallel) → 05 → 06 (4-way parallel) → 07** (~6 serial steps + 2 parallel bursts).

## Parallelization opportunities (the four levers)

### Lever 1: Merge old Batch 01 into new Batch 01

Old Batch 01 was a trivial skeleton (empty packages + `importlinter` config + xfail tests). Folding it into the first commit of new Batch 01 (the bootstrap + API skeleton) loses one full PR cycle and loses nothing — enforcement starts the moment the new packages exist. The `importlinter` config and forbidden-symbol tests are part of the first commit.

### Lever 2: Overlap Batch 02 implementation with Batch 03 contract design

Batch 03's `NodeDefinition`/`NodeContext`/`InputCollection`/`OutputPublisher` Protocols are pure interface work depending only on ports from Batch 01, not on Batch 02's SQLite implementation. **Start Batch 03's contract design in a branch while Batch 02 implements.** Merge Batch 02 first, then Batch 03 lands on top. Saves the serial wait between the two "very high" batches.

Concretely: the agent for Batch 03 can begin writing `nodes/contracts.py` Protocols + `application/ports/artifact_store.py` + `application/ports/evidence_reader.py` while Batch 02 is in review. The port definitions don't import `adapters/sqlite/` or `adapters/filesystem/` — only `domain/`. When Batch 02 merges, Batch 03's contract branch rebases and fills in the implementations.

### Lever 3: Split Batch 04 into parallel family sub-PRs

Batch 04 is the wall-clock bottleneck: 30 nodes, mechanical, one proven pattern (from Batch 03's `LogisticRegressionNode`). **Split into 4 parallel sub-PRs landing concurrently after Batch 03 merges:**

| Sub-PR | Nodes | Approx. count |
|--------|-------|---------------|
| 04a — prep | `ImportTabularDatasetNode`, `ProfileDatasetNode`, `ValidateBinaryTargetNode`, `SplitTrainTestOotNode`, `ApplyExclusionsNode`, `ExplicitMissingOutlierTreatmentNode`, `DefineModellingMetadataNode`, `DevelopmentSampleDefinitionNode` | 8 |
| 04b — build-fit | `AutomaticBinningNode`, `CalculateWoeIvNode`, `WoeTransformTrainNode`, `ManualBinningNode`, `VariableClusteringNode`, `VariableSelectionNode`, `ScoreScalingNode`, `BuildSummaryReportNode`, `FrozenScorecardBundleNode`, `CoefficientSignCheckNode`, `SeparationDiagnosticsNode`, `VifDiagnosticsNode`, `CalibrationDiagnosticsNode`, `DummyFitNode`, `NoopNode` | 15 (LogisticRegression already in 03) |
| 04c — build-export | `ScorecardTableExportNode`, `PythonScoringExportNode`, `SqlScoringExportNode` | 3 |
| 04d — validate-apply | `ApplyWoeMappingNode`, `ApplyModelNode`, `ValidationMetricsNode`, `CutoffAnalysisNode` | 4 |

Plus shared work (ported once, in whichever sub-PR lands first, or in a tiny 04-shared pre-PR): `modeling/adapters.py`, `modeling/serialization.py`, `_training_utils.py`, `bootstrap/node_catalogue.py`.

Four agents in parallel cuts the critical-path time for this batch by ~4×. Sub-PRs merge into one batch; each must pass its own parity tests. The sub-PRs have minimal overlap (only the shared `modeling/` + catalogue — land that first in a 10-minute pre-PR, then the four family branches branch off it).

### Lever 4: Parallelize Batch 06 into four sub-PRs

After Batch 05 lands, the four use-case families are independent:

| Sub-PR | Use cases |
|--------|-----------|
| 06a — plans | `CreatePlan`, `GetPlan`, `ListPlans`, `GetPlanVersion`, `ListPlanVersions`, `UpdatePlanVersion`, `CommitPlanVersion`, `ApplyManualBinningEdit` |
| 06b — evidence | `ExplainStaleness` + `evidence_resolver.py` (4-stage fallback) |
| 06c — governance | `CreateBranch`, `CreateComparison`, `RefreshComparison`, `AssignChampion` |
| 06d — reporting | `GenerateReport`, `ExportAuditPack`, `adapters/rendering/`, `adapters/reporting/`, `readiness.py` |

Four agents in parallel; merge as one batch. Each deletes the old `cardre/services/*` files it replaces.

### Lever 5: Merge old Batch 09 into new Batch 07

Old Batch 09 (delete old code + tighten enforcement + acceptance test) is "moderate" and small — it's deletion + `importlinter` tightening + one test file. Tack it onto the tail of new Batch 07 (API routes + frontend regen) once the full API is live. Saves one full PR cycle. The acceptance pathway test is the gate that confirms the merge is safe to finalize.

## Review strategy

- **Run `make preflight` before every push.** It catches ruff, mypy, line-counts, artifact-reads, governance tests, openapi drift, frontend typecheck/build — most CI failures locally. The PR gate then only waits on jobs preflight can't run (sidecar build, tauri check, smoke test). Don't let agents push blind; a failed preflight is a wasted CI round.
- Each batch PR must pass the PR gate (`scripts/pr-gate.sh`).
- Each batch must include new tests proving the batch's invariants (see per-batch docs).
- Each batch must preserve the parity/characterization tests (`test_scoring_export_parity`, `test_logistic_regression_known_input`, `test_score_scaling_known_input`, `test_golden_fixtures_roundtrip`, `test_golden_report_bundle`, `test_run_audit_integrity`) — these are the behavioural oracles. Imports update; behaviour must not change.
- The product acceptance pathway (see 08-acceptance-and-test-strategy.md) is run as the gate for the merged Batch 07.

## Code-deletion milestones

| Batch | Deletes |
|-------|---------|
| 01 | `cardre/api/dependencies.py:get_project_store*`, `get_run_coordinator`, `require_governance` (old functions); `cardre/services/project_resolver.py` usage in routes (dormant, deleted in 06) |
| 02 | `cardre/store/db.py` `ProjectStore` (replaced by `SqliteUnitOfWork`); `cardre/store/_locked_cursor.py`, `_schema_version.py`, `_base.py`, `schema.py`; `cardre/store/*_repo.py` (replaced by `adapters/sqlite/*_repo.py`); `cardre/store/project_registry.py` (replaced by `adapters/system/project_registry.py`) |
| 03 | `cardre/_evidence/kinds.py`, `schemas.py` (moved to `domain/evidence/`); `cardre/_evidence/reader.py` (replaced by `InputCollection`); `cardre/_evidence/adapters/` (moved to `adapters/evidence/`); `cardre/node_parameters.py` (moved to `nodes/parameters.py`); `RolePolicy` (unused); `cardre/engine/binning/` (moved to `domain/binning/` + `nodes/build/_optbinning_adapter.py` per D19); `cardre/workflows/scorecard.py` (moved to `domain/plans/scorecard_pathway.py` per D19); `cardre/engine/` + `cardre/workflows/` packages deleted |
| 04 | `cardre/nodes/registry.py` (replaced by `bootstrap/node_catalogue.py`); `cardre/execution/context.py` (no consumers after all nodes ported); old node implementations (replaced by ported versions in `nodes/**`) |
| 05 | `cardre/execution/executor.py`, `step_runner.py`, `run_lifecycle.py`, `run_step_writer.py`, `worker.py`, `action_planner.py`, `fingerprints.py`, `failure_classification.py`, `topology.py`, `step_graph.py` (moved/rewritten into `application/execution/` + `adapters/dispatch/`); `cardre/services/run_coordinator.py` |
| 06 | `cardre/services/plan_service.py`, `plan_mutation_service.py`, `branch_service.py`, `branch_validator.py`, `branch_graph.py`, `branch_writer.py`, `comparison_service.py`, `comparison/*`, `champion_service.py`, `staleness_service.py`, `export_service.py`, `export_listing.py`, `report_service.py`, `manual_binning_service.py`, `plan_dto.py`; `cardre/evidence_locator.py`, `branch_step_resolver.py`; `cardre/reporting/` (moved to `adapters/rendering/` + `application/reporting/`); `cardre/readiness/` |
| 07 | `cardre/api/dependencies.py` (rewritten), `cardre/api/app.py` (rewritten), `cardre/api/schemas.py` (rewritten), `cardre/api/routes/*` (rewritten), `cardre/api/routes/_project_scope.py`, `_run_mappings.py` (deleted); `sidecar/__main__.py` (rewritten); `frontend/src/api/client.ts` `projectHeaders`; **then** `cardre/artifacts.py`, `cardre/capabilities.py`, `cardre/config.py`, `cardre/store/` (if any residue), `cardre/services/__init__.py` (if empty), `cardre/_evidence/` (if empty); tighten `importlinter`; un-xfail forbidden-symbol tests |

## Point at which old architecture disappears

After Batch 07 (which includes the old Batch 09 cleanup). Batches 01–06 keep old code coexisting (not dual-running — the old code is *not* on the request path once the new use case exists; it's just still importable). Batch 07 deletes it, tightens enforcement so it can't return, and runs the acceptance pathway.

**The application does not need to remain runnable after every intermediate batch.** Documented broken intermediate states:
- After 01: only `/health` + `/projects` work; all other routes 404.
- After 02: persistence layer exists but no use cases use it; old `ProjectStore` still in place for non-project routes (which are 404).
- After 03: one node ported; no execution path uses it yet.
- After 04: all nodes ported; old execution path intentionally broken (execution tests xfail).
- After 05: new execution path exists; old one deleted.
- After 06: all use cases exist; old services deleted.
- After 07: new API live; old routes + infra deleted; enforcement strict; acceptance pathway green.

## Open PRs and branches

Per 00-validation-report.md §Active overlapping work:
- All `refactor/slice-*` branches: **superseded** — do not merge. The rewrite deletes the code they refactor.
- `chore/fix-forward-heartbeat-coverage`, `chore/slice-5-coverage-bump`: **incorporate** the coverage floor policy into the plan (D17).
- `pr0-safety-net`, `pr0-followup-docs`: **preserve as behavioural knowledge** (golden fixture determinism). Verify golden fixtures still pass after the rewrite.
- `pr7-followup-drop-bin-definition-forwarders`: **verify** before Batch 01 that dead `_lifecycle` forwarders are gone; if not, the rewrite deletes them anyway.
- All merged deepening PRs: **absorbed** as the baseline; their behaviour is preserved by the parity tests.

## Acceptance pathway responsibility allocation

| Acceptance item | Responsible batch |
|-----------------|-------------------|
| 1. create a project | 01 |
| 2. import a supported dataset | 04 (ImportTabularDatasetNode ported) + 07 (route) |
| 3. profile the dataset | 04 (ProfileDatasetNode ported) + 07 |
| 4. create a plan | 06 (CreatePlan use case) + 07 |
| 5. edit the graph | 06 (UpdatePlanVersion — though graph editing is currently manual via params; full editor is future) + 07 |
| 6. commit an immutable plan version | 06 (CommitPlanVersion) + 07 |
| 7. submit a run | 05 (SubmitRun) + 07 |
| 8. execute the launch pathway | 05 (ExecuteRun) + 04 (all launch nodes) |
| 9. produce deterministic artifacts | 02 (artifact store) + 04 (nodes) + 05 (finalization) |
| 10. perform binning and WOE | 04 (AutomaticBinningNode, CalculateWoeIvNode, WoeTransformTrainNode) |
| 11. fit a logistic scorecard | 03 (LogisticRegressionNode) + 04 (ScoreScalingNode) |
| 12. scale scores | 04 (ScoreScalingNode) |
| 13. apply the model to test and OOT data | 04 (ApplyWoeMappingNode, ApplyModelNode) |
| 14. calculate validation metrics | 04 (ValidationMetricsNode, CutoffAnalysisNode) |
| 15. export scoring code | 04 (PythonScoringExportNode, SqlScoringExportNode) — parity test preserved |
| 16. generate an audit package | 06 (ExportAuditPack use case) + 07 |
| 17. replay a committed plan | 05 (SubmitRun on same version) |
| 18. verify scoring parity | 07 (test_scoring_export_parity.py passes) |
| 19. verify artifact hashes | 02 (artifact store hashing) + 07 (audit integrity test) |
| 20. verify canonical manifest consistency | 05 (FinalizeRun manifest) + 07 (test_run_audit_integrity.py passes) |